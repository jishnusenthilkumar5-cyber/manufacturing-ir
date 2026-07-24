from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable, Protocol

from mir.core.model import Factory


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    severity: Severity
    message: str
    entities: tuple[str, ...] = ()
    hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "entities": list(self.entities),
            "hint": self.hint,
        }


@dataclass(slots=True)
class PassResult:
    diagnostics: list[Diagnostic] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PassContext:
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def require(self, pass_name: str, artifact: str) -> Any:
        try:
            return self.artifacts[pass_name][artifact]
        except KeyError as exc:
            raise KeyError(f"required artifact {pass_name}.{artifact} is unavailable") from exc


class Pass(Protocol):
    name: str
    requires: tuple[str, ...]

    def run(self, factory: Factory, context: PassContext) -> PassResult: ...


@dataclass(frozen=True, slots=True)
class PipelineResult:
    diagnostics: tuple[Diagnostic, ...]
    artifacts: dict[str, dict[str, Any]]
    executed: tuple[str, ...]

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)


class PassManager:
    def __init__(self, passes: Iterable[Pass] = ()) -> None:
        self._passes: dict[str, Pass] = {}
        for item in passes:
            self.register(item)

    def register(self, item: Pass) -> None:
        if item.name in self._passes:
            raise ValueError(f"pass {item.name!r} is already registered")
        self._passes[item.name] = item

    def _execution_order(self, targets: Iterable[str] | None) -> list[str]:
        requested = list(targets) if targets is not None else list(self._passes)
        order: list[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in visiting:
                raise ValueError(f"cyclic pass dependency involving {name!r}")
            try:
                item = self._passes[name]
            except KeyError as exc:
                raise KeyError(f"unknown pass {name!r}") from exc
            visiting.add(name)
            for dependency in item.requires:
                visit(dependency)
            visiting.remove(name)
            visited.add(name)
            order.append(name)

        for name in requested:
            visit(name)
        return order

    def run(self, factory: Factory, targets: Iterable[str] | None = None) -> PipelineResult:
        context = PassContext()
        diagnostics: list[Diagnostic] = []
        order = self._execution_order(targets)
        for name in order:
            result = self._passes[name].run(factory, context)
            context.artifacts[name] = result.artifacts
            diagnostics.extend(result.diagnostics)
        severity_order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
        diagnostics.sort(
            key=lambda item: (
                severity_order[item.severity],
                item.code,
                item.entities,
                item.message,
            )
        )
        return PipelineResult(tuple(diagnostics), dict(context.artifacts), tuple(order))
