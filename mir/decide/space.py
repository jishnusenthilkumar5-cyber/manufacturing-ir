from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import product
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from mir.core.distributions import (
    ConstantDistribution,
    ExponentialDistribution,
    NormalDistribution,
    UniformDistribution,
)
from mir.core.ids import ID_PATTERN
from mir.core.model import Availability, Factory

MAX_DESIGN_POINTS = 500


class DesignSpaceError(ValueError):
    pass


class DesignSpaceParseError(DesignSpaceError):
    pass


class DesignSpaceLimitError(DesignSpaceError):
    pass


class ParameterPathError(DesignSpaceError):
    pass


class ParameterValueError(DesignSpaceError):
    pass


class ParameterKind(StrEnum):
    FLOW_BUFFER_CAPACITY = "flow_buffer_capacity"
    MACHINE_NUM_STATIONS = "machine_num_stations"
    OPERATION_CYCLE_TIME_SCALE = "operation_cycle_time_scale"
    MACHINE_AVAILABILITY = "machine_availability"
    MACHINE_AVAILABILITY_MTBF = "machine_availability_mtbf"
    MACHINE_AVAILABILITY_MTTR = "machine_availability_mttr"


@dataclass(frozen=True, slots=True)
class _AvailabilityValue:
    mtbf_s: float
    mttr_s: float

    def to_dict(self) -> dict[str, float]:
        return {"mtbf_s": self.mtbf_s, "mttr_s": self.mttr_s}


ParameterValue = int | float | None | _AvailabilityValue


@dataclass(frozen=True, slots=True)
class ParameterPath:
    path: str
    kind: ParameterKind
    entity_id: str

    @classmethod
    def parse(cls, path: str) -> ParameterPath:
        if not isinstance(path, str) or not path:
            raise ParameterPathError("parameter path must be a non-empty string")
        parts = path.split(".")
        parsed: tuple[ParameterKind, str] | None = None
        if len(parts) == 3 and parts[0] == "flows" and parts[2] == "buffer_capacity":
            parsed = (ParameterKind.FLOW_BUFFER_CAPACITY, parts[1])
        elif len(parts) == 3 and parts[0] == "machines" and parts[2] == "num_stations":
            parsed = (ParameterKind.MACHINE_NUM_STATIONS, parts[1])
        elif (
            len(parts) == 3
            and parts[0] == "operations"
            and parts[2] == "cycle_time_scale"
        ):
            parsed = (ParameterKind.OPERATION_CYCLE_TIME_SCALE, parts[1])
        elif len(parts) == 3 and parts[0] == "machines" and parts[2] == "availability":
            parsed = (ParameterKind.MACHINE_AVAILABILITY, parts[1])
        elif (
            len(parts) == 4
            and parts[0] == "machines"
            and parts[2] == "availability"
            and parts[3] == "mtbf_s"
        ):
            parsed = (ParameterKind.MACHINE_AVAILABILITY_MTBF, parts[1])
        elif (
            len(parts) == 4
            and parts[0] == "machines"
            and parts[2] == "availability"
            and parts[3] == "mttr_s"
        ):
            parsed = (ParameterKind.MACHINE_AVAILABILITY_MTTR, parts[1])
        if parsed is None or not parsed[1]:
            raise ParameterPathError(f"unsupported parameter path {path!r}")
        if re.fullmatch(ID_PATTERN, parsed[1]) is None:
            raise ParameterPathError(
                f"invalid entity id {parsed[1]!r} in parameter path {path!r}"
            )
        return cls(path=path, kind=parsed[0], entity_id=parsed[1])

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "kind": self.kind.value,
            "entity_id": self.entity_id,
        }

    def normalize_value(self, value: Any) -> ParameterValue:
        try:
            if self.kind is ParameterKind.FLOW_BUFFER_CAPACITY:
                if value is None:
                    return None
                return _integer_value(value, minimum=0, path=self.path)
            if self.kind is ParameterKind.MACHINE_NUM_STATIONS:
                return _integer_value(value, minimum=1, path=self.path)
            if self.kind is ParameterKind.OPERATION_CYCLE_TIME_SCALE:
                return _positive_number(value, path=self.path)
            if self.kind is ParameterKind.MACHINE_AVAILABILITY:
                if value is None:
                    return None
                if not isinstance(value, Mapping):
                    raise ParameterValueError(
                        f"{self.path!r} must be null or a complete availability object"
                    )
                if set(value) != {"mtbf_s", "mttr_s"}:
                    raise ParameterValueError(
                        f"{self.path!r} availability object must contain exactly mtbf_s and mttr_s"
                    )
                mtbf_s = _positive_number(value["mtbf_s"], path=f"{self.path}.mtbf_s")
                mttr_s = _positive_number(value["mttr_s"], path=f"{self.path}.mttr_s")
                model = Availability.model_validate({"mtbf_s": mtbf_s, "mttr_s": mttr_s})
                return _AvailabilityValue(model.mtbf_s, model.mttr_s)
            if self.kind in {
                ParameterKind.MACHINE_AVAILABILITY_MTBF,
                ParameterKind.MACHINE_AVAILABILITY_MTTR,
            }:
                return _positive_number(value, path=self.path)
        except ValidationError as exc:
            raise ParameterValueError(f"invalid value for {self.path!r}: {exc}") from exc
        raise ParameterPathError(f"unsupported parameter path {self.path!r}")

    def serialize_value(self, value: ParameterValue) -> Any:
        if isinstance(value, _AvailabilityValue):
            return value.to_dict()
        return value

    def validate_target(self, factory: Factory) -> None:
        if self.kind is ParameterKind.FLOW_BUFFER_CAPACITY:
            _find_one(factory.flows, self.entity_id, self.path, "flow")
            return
        if self.kind is ParameterKind.OPERATION_CYCLE_TIME_SCALE:
            _find_one(factory.operations, self.entity_id, self.path, "operation")
            return
        machine = _find_one(factory.machines, self.entity_id, self.path, "machine")
        if self.kind in {
            ParameterKind.MACHINE_AVAILABILITY_MTBF,
            ParameterKind.MACHINE_AVAILABILITY_MTTR,
        } and machine.availability is None:
            raise ParameterPathError(
                f"{self.path!r} requires non-null availability on machine {self.entity_id!r}; "
                f"set 'machines.{self.entity_id}.availability' first"
            )


@dataclass(frozen=True, slots=True)
class _Dimension:
    parameter: ParameterPath
    values: tuple[ParameterValue, ...]


@dataclass(frozen=True, slots=True)
class DesignPoint:
    index: int
    assignments: tuple[tuple[ParameterPath, ParameterValue], ...]

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            parameter.path: parameter.serialize_value(value)
            for parameter, value in self.assignments
        }

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "parameters": self.parameters}


@dataclass(frozen=True, slots=True)
class DesignSpace:
    _dimensions: tuple[_Dimension, ...]
    point_count: int

    @classmethod
    def from_dict(cls, payload: Mapping[str, Sequence[Any]]) -> DesignSpace:
        if not isinstance(payload, Mapping):
            raise DesignSpaceParseError("design space root must be an object")
        if not payload:
            raise DesignSpaceParseError("design space must define at least one parameter path")
        dimensions: list[_Dimension] = []
        for raw_path, raw_values in payload.items():
            parameter = ParameterPath.parse(raw_path)
            if isinstance(raw_values, str | bytes) or not isinstance(raw_values, Sequence):
                raise DesignSpaceParseError(
                    f"values for {parameter.path!r} must be a non-empty list"
                )
            if not raw_values:
                raise DesignSpaceParseError(
                    f"values for {parameter.path!r} must be a non-empty list"
                )
            values: list[ParameterValue] = []
            for index, raw_value in enumerate(raw_values):
                try:
                    values.append(parameter.normalize_value(raw_value))
                except ParameterValueError as exc:
                    raise ParameterValueError(
                        f"invalid value at index {index} for {parameter.path!r}: {exc}"
                    ) from exc
            dimensions.append(_Dimension(parameter, tuple(values)))
        dimensions.sort(key=lambda item: item.parameter.path)
        _validate_availability_conflicts(dimensions)
        point_count = math.prod(len(dimension.values) for dimension in dimensions)
        if point_count > MAX_DESIGN_POINTS:
            raise DesignSpaceLimitError(
                f"design space has {point_count} points; maximum is {MAX_DESIGN_POINTS}"
            )
        return cls(tuple(dimensions), point_count)

    @classmethod
    def from_json(cls, source: str | bytes | Path) -> DesignSpace:
        raw = _read_json_source(source)
        try:
            payload = json.loads(raw, object_pairs_hook=_object_without_duplicates)
        except _DuplicateKeyError as exc:
            raise DesignSpaceParseError(f"duplicate JSON key {exc.key!r}") from exc
        except json.JSONDecodeError as exc:
            raise DesignSpaceParseError(
                f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
            ) from exc
        if not isinstance(payload, dict):
            raise DesignSpaceParseError("design space root must be a JSON object")
        return cls.from_dict(payload)

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(dimension.parameter.path for dimension in self._dimensions)

    def iter_points(self) -> Iterator[DesignPoint]:
        value_sets = (dimension.values for dimension in self._dimensions)
        for index, values in enumerate(product(*value_sets)):
            assignments = tuple(
                (dimension.parameter, value)
                for dimension, value in zip(self._dimensions, values, strict=True)
            )
            yield DesignPoint(index=index, assignments=assignments)

    def points(self) -> tuple[DesignPoint, ...]:
        return tuple(self.iter_points())

    def __iter__(self) -> Iterator[DesignPoint]:
        return self.iter_points()

    def __len__(self) -> int:
        return self.point_count

    def validate_against(self, factory: Factory) -> None:
        for dimension in self._dimensions:
            dimension.parameter.validate_target(factory)

    def apply(self, factory: Factory, point: DesignPoint) -> Factory:
        self.validate_against(factory)
        if not isinstance(point, DesignPoint):
            raise DesignSpaceError("point must be a DesignPoint")
        if (
            isinstance(point.index, bool)
            or not isinstance(point.index, int)
            or not 0 <= point.index < self.point_count
        ):
            raise DesignSpaceError("design point does not belong to this design space")
        expected = next(
            candidate
            for candidate in self.iter_points()
            if candidate.index == point.index
        )
        if point != expected:
            raise DesignSpaceError("design point does not belong to this design space")
        return apply_design_point(factory, point)

    def to_dict(self) -> dict[str, list[Any]]:
        return {
            dimension.parameter.path: [
                dimension.parameter.serialize_value(value) for value in dimension.values
            ]
            for dimension in self._dimensions
        }


def apply_design_point(factory: Factory, point: DesignPoint) -> Factory:
    if not isinstance(factory, Factory):
        raise DesignSpaceError("factory must be a Factory")
    if not isinstance(point, DesignPoint):
        raise DesignSpaceError("point must be a DesignPoint")
    parsed: list[tuple[ParameterPath, Any]] = []
    for parameter, value in point.assignments:
        if not isinstance(parameter, ParameterPath):
            raise ParameterPathError("design point assignments require ParameterPath values")
        canonical = ParameterPath.parse(parameter.path)
        if parameter != canonical:
            raise ParameterPathError(
                f"parameter metadata does not match path {parameter.path!r}"
            )
        parsed.append((canonical, value))
    _validate_assignment_conflicts(parsed)
    normalized: list[tuple[ParameterPath, ParameterValue]] = []
    for canonical, value in parsed:
        canonical.validate_target(factory)
        if isinstance(value, _AvailabilityValue):
            value = canonical.normalize_value(value.to_dict())
        else:
            value = canonical.normalize_value(value)
        normalized.append((canonical, value))
    result = factory.model_copy(deep=True)
    for parameter, value in normalized:
        _apply_value(result, parameter, value)
    return result


def _apply_value(factory: Factory, parameter: ParameterPath, value: ParameterValue) -> None:
    if parameter.kind is ParameterKind.FLOW_BUFFER_CAPACITY:
        flow = _find_one(factory.flows, parameter.entity_id, parameter.path, "flow")
        flow.buffer_capacity = value
        return
    if parameter.kind is ParameterKind.MACHINE_NUM_STATIONS:
        machine = _find_one(factory.machines, parameter.entity_id, parameter.path, "machine")
        machine.num_stations = value
        return
    if parameter.kind is ParameterKind.OPERATION_CYCLE_TIME_SCALE:
        operation = _find_one(
            factory.operations, parameter.entity_id, parameter.path, "operation"
        )
        operation.cycle_time = _scale_cycle_time(operation.cycle_time, float(value))
        return
    machine = _find_one(factory.machines, parameter.entity_id, parameter.path, "machine")
    if parameter.kind is ParameterKind.MACHINE_AVAILABILITY:
        if value is None:
            machine.availability = None
        elif isinstance(value, _AvailabilityValue):
            machine.availability = Availability.model_validate(value.to_dict())
        else:
            raise ParameterValueError(f"invalid normalized value for {parameter.path!r}")
        return
    if machine.availability is None:
        raise ParameterPathError(
            f"{parameter.path!r} requires non-null availability on machine {parameter.entity_id!r}; "
            f"set 'machines.{parameter.entity_id}.availability' first"
        )
    if parameter.kind is ParameterKind.MACHINE_AVAILABILITY_MTBF:
        machine.availability.mtbf_s = value
        return
    if parameter.kind is ParameterKind.MACHINE_AVAILABILITY_MTTR:
        machine.availability.mttr_s = value
        return
    raise ParameterPathError(f"unsupported parameter path {parameter.path!r}")


def _scale_cycle_time(distribution: Any, scale: float) -> Any:
    if isinstance(distribution, ConstantDistribution):
        payload = {"kind": "constant", "value_s": distribution.value_s * scale}
    elif isinstance(distribution, UniformDistribution):
        payload = {
            "kind": "uniform",
            "low_s": distribution.low_s * scale,
            "high_s": distribution.high_s * scale,
        }
    elif isinstance(distribution, NormalDistribution):
        payload = {
            "kind": "normal",
            "mean_s": distribution.mean_s * scale,
            "std_s": distribution.std_s * scale,
        }
    elif isinstance(distribution, ExponentialDistribution):
        payload = {"kind": "exponential", "mean_s": distribution.mean_s * scale}
    else:
        raise ParameterValueError(
            f"unsupported cycle-time distribution {type(distribution).__name__!r}"
        )
    try:
        return type(distribution).model_validate(payload)
    except ValidationError as exc:
        raise ParameterValueError(
            f"cycle-time scaling produced an invalid distribution: {exc}"
        ) from exc


def _find_one(items: Sequence[Any], entity_id: str, path: str, entity_type: str) -> Any:
    matches = [item for item in items if item.id == entity_id]
    if len(matches) != 1:
        raise ParameterPathError(
            f"{path!r} expected exactly one {entity_type} {entity_id!r}; found {len(matches)}"
        )
    return matches[0]


def _integer_value(value: Any, *, minimum: int, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ParameterValueError(f"{path!r} must be an integer >= {minimum}")
    return value


def _positive_number(value: Any, *, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ParameterValueError(f"{path!r} must be a finite positive number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ParameterValueError(
            f"{path!r} must be a finite positive number"
        ) from exc
    if not math.isfinite(result) or result <= 0:
        raise ParameterValueError(f"{path!r} must be a finite positive number")
    return result


def _validate_assignment_conflicts(
    assignments: Sequence[tuple[ParameterPath, Any]],
) -> None:
    paths = [parameter.path for parameter, _ in assignments]
    if len(paths) != len(set(paths)):
        raise DesignSpaceError("design point contains duplicate parameter paths")
    parents = {
        parameter.entity_id
        for parameter, _ in assignments
        if parameter.kind is ParameterKind.MACHINE_AVAILABILITY
    }
    leaves = {
        parameter.entity_id
        for parameter, _ in assignments
        if parameter.kind
        in {
            ParameterKind.MACHINE_AVAILABILITY_MTBF,
            ParameterKind.MACHINE_AVAILABILITY_MTTR,
        }
    }
    conflicts = sorted(parents & leaves)
    if conflicts:
        raise DesignSpaceError(
            f"availability parent and leaf paths conflict for machine {conflicts[0]!r}"
        )


def _validate_availability_conflicts(dimensions: Sequence[_Dimension]) -> None:
    parents = {
        item.parameter.entity_id
        for item in dimensions
        if item.parameter.kind is ParameterKind.MACHINE_AVAILABILITY
    }
    leaves = {
        item.parameter.entity_id
        for item in dimensions
        if item.parameter.kind
        in {
            ParameterKind.MACHINE_AVAILABILITY_MTBF,
            ParameterKind.MACHINE_AVAILABILITY_MTTR,
        }
    }
    conflicts = sorted(parents & leaves)
    if conflicts:
        machine_id = conflicts[0]
        raise DesignSpaceParseError(
            f"availability parent and leaf paths conflict for machine {machine_id!r}"
        )


class _DuplicateKeyError(ValueError):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(key)


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(key)
        result[key] = value
    return result


def _read_json_source(source: str | bytes | Path) -> str:
    if isinstance(source, bytes):
        try:
            return source.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DesignSpaceParseError(
                f"design space JSON is not valid UTF-8: {exc}"
            ) from exc
    if isinstance(source, Path):
        return _read_json_path(source)
    if not isinstance(source, str):
        raise DesignSpaceParseError("JSON source must be text, bytes, or a path")
    if source.lstrip().startswith(("{", "[")):
        return source
    try:
        path = Path(source)
        if path.is_file():
            return _read_json_path(path)
    except OSError:
        pass
    return source


def _read_json_path(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise DesignSpaceParseError(
            f"design space JSON at {path} is not valid UTF-8: {exc}"
        ) from exc
    except OSError as exc:
        raise DesignSpaceParseError(f"cannot read design space {path}: {exc}") from exc
