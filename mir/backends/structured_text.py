from __future__ import annotations

import json
import re
from collections.abc import Iterable

from mir.core.model import Factory, Machine, Operation, Signal, SignalDataType, SignalSemantic


SAFETY_NOTICE = (
    "Vendor-neutral IEC 61131-3 Structured Text skeleton; requires safety review; "
    "not deployable control logic."
)

_DEFAULT_MACHINE_STATES = (
    ("idle", 0),
    ("running", 1),
    ("blocked", 2),
    ("starved", 3),
    ("setup", 4),
    ("down", 5),
)

_ST_KEYWORDS = frozenset(
    {
        "ACTION",
        "AND",
        "ARRAY",
        "AT",
        "BOOL",
        "BY",
        "BYTE",
        "CASE",
        "CONFIGURATION",
        "CONSTANT",
        "DATE",
        "DATE_AND_TIME",
        "DINT",
        "DO",
        "DT",
        "DWORD",
        "ELSE",
        "ELSIF",
        "END_ACTION",
        "END_CASE",
        "END_CONFIGURATION",
        "END_FOR",
        "END_FUNCTION",
        "END_FUNCTION_BLOCK",
        "END_IF",
        "END_PROGRAM",
        "END_REPEAT",
        "END_RESOURCE",
        "END_STEP",
        "END_STRUCT",
        "END_TRANSITION",
        "END_TYPE",
        "END_VAR",
        "END_WHILE",
        "EXIT",
        "FALSE",
        "F_EDGE",
        "FOR",
        "FROM",
        "FUNCTION",
        "FUNCTION_BLOCK",
        "IF",
        "INITIAL_STEP",
        "INT",
        "INTERVAL",
        "LINT",
        "LREAL",
        "LWORD",
        "MOD",
        "NON_RETAIN",
        "NOT",
        "OF",
        "ON",
        "OR",
        "PRIORITY",
        "PROGRAM",
        "R_EDGE",
        "READ_ONLY",
        "READ_WRITE",
        "REAL",
        "REPEAT",
        "RESOURCE",
        "RETAIN",
        "RETURN",
        "SINT",
        "STEP",
        "STRING",
        "STRUCT",
        "TASK",
        "THEN",
        "TIME",
        "TIME_OF_DAY",
        "TO",
        "TOD",
        "TRANSITION",
        "TRUE",
        "TYPE",
        "UDINT",
        "UINT",
        "ULINT",
        "UNTIL",
        "USINT",
        "VAR",
        "VAR_ACCESS",
        "VAR_CONFIG",
        "VAR_EXTERNAL",
        "VAR_GLOBAL",
        "VAR_IN_OUT",
        "VAR_INPUT",
        "VAR_OUTPUT",
        "VAR_TEMP",
        "WHILE",
        "WITH",
        "WORD",
        "WSTRING",
        "XOR",
    }
)

_SIGNAL_TYPES = {
    SignalDataType.BOOL: "BOOL",
    SignalDataType.INT: "DINT",
    SignalDataType.FLOAT: "LREAL",
    SignalDataType.ENUM: "INT",
}


def _sanitize_fragment(value: str) -> str:
    fragment = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()
    return fragment or "X"


def _sanitize_identifier(value: str) -> str:
    identifier = _sanitize_fragment(value)
    if identifier[0].isdigit() or identifier in _ST_KEYWORDS:
        identifier = f"ID_{identifier}"
    return identifier


def _generated_identifier(prefix: str, *parts: str) -> str:
    fragments = [_sanitize_fragment(prefix), *(_sanitize_fragment(part) for part in parts)]
    return "_".join(fragments)


def _assert_no_collisions(context: str, names: Iterable[tuple[str, str]]) -> None:
    generated: dict[str, list[tuple[str, str]]] = {}
    for source, identifier in names:
        generated.setdefault(identifier.casefold(), []).append((source, identifier))
    collisions = [entries for entries in generated.values() if len(entries) > 1]
    if not collisions:
        return
    entries = min(collisions, key=lambda group: tuple(sorted(source for source, _ in group)))
    sources = sorted(source for source, _ in entries)
    identifier = entries[0][1]
    rendered = ", ".join(repr(source) for source in sources)
    raise ValueError(f"{context} collide after sanitation as {identifier!r}: {rendered}")


def _machine_path(machine: Machine) -> str:
    return f"{_sanitize_fragment(machine.id).lower()}.st"


def _machine_state_type(machine: Machine) -> str:
    return _generated_identifier("T", machine.id, "STATE")


def _signal_identifier(signal: Signal) -> str:
    return _sanitize_identifier(signal.tag)


def _operation_identifier(machine: Machine, operation: Operation) -> str:
    return _generated_identifier("FB", machine.id, operation.id)


def _state_identifier(state: str) -> str:
    return _generated_identifier("STATE", state)


def _machine_signals(factory: Factory, machine: Machine) -> list[Signal]:
    return sorted(
        (signal for signal in factory.signals if signal.machine == machine.id),
        key=lambda signal: signal.id,
    )


def _machine_operations(factory: Factory, machine: Machine) -> list[Operation]:
    return sorted(
        (operation for operation in factory.operations if machine.id in operation.machines),
        key=lambda operation: operation.id,
    )


def _machine_states(signals: list[Signal], machine: Machine) -> tuple[tuple[str, int], ...]:
    state_signals = [
        signal for signal in signals if signal.semantic is SignalSemantic.MACHINE_STATE
    ]
    if len(state_signals) > 1:
        signal_ids = ", ".join(repr(signal.id) for signal in state_signals)
        raise ValueError(f"machine {machine.id!r} has multiple machine_state signals: {signal_ids}")
    if state_signals and state_signals[0].enum_states:
        states = tuple(
            sorted(state_signals[0].enum_states.items(), key=lambda item: (item[1], item[0]))
        )
    else:
        states = _DEFAULT_MACHINE_STATES
    _assert_no_collisions(
        f"machine {machine.id!r} state identifiers",
        ((state, _state_identifier(state)) for state, _ in states),
    )
    return states


def _signal_type(signal: Signal, state_signal: Signal | None, state_type: str) -> str:
    if signal is state_signal and signal.dtype is SignalDataType.ENUM:
        return state_type
    return _SIGNAL_TYPES[signal.dtype]


def _render_machine(
    machine: Machine,
    signals: list[Signal],
    operations: list[Operation],
    states: tuple[tuple[str, int], ...],
) -> str:
    state_type = _machine_state_type(machine)
    state_signal = next(
        (signal for signal in signals if signal.semantic is SignalSemantic.MACHINE_STATE),
        None,
    )
    lines = [
        "(*",
        "    Generated by Manufacturing IR.",
        "    Vendor-neutral IEC 61131-3 Structured Text skeleton.",
        "    Requires safety review; not deployable control logic.",
        "*)",
        "",
        "TYPE",
        f"    {state_type} : (",
    ]
    for index, (state, value) in enumerate(states):
        suffix = "," if index < len(states) - 1 else ""
        lines.append(f"        {_state_identifier(state)} := {value}{suffix}")
    lines.extend(["    );", "END_TYPE", ""])

    if signals:
        lines.append("VAR_GLOBAL")
        for signal in signals:
            lines.append(
                f"    {_signal_identifier(signal)} : "
                f"{_signal_type(signal, state_signal, state_type)};"
            )
        lines.extend(["END_VAR", ""])

    for operation in operations:
        lines.extend(
            [
                f"FUNCTION_BLOCK {_operation_identifier(machine, operation)}",
                "VAR_INPUT",
                "    Execute : BOOL;",
                "END_VAR",
                "VAR_OUTPUT",
                "    Done : BOOL;",
                "    Error : BOOL;",
                "END_VAR",
                "",
                "(*",
                f"    TODO: Implement operation {operation.id!r} after hardware and safety review.",
                "    This vendor-neutral skeleton is not deployable control logic.",
                "*)",
                "END_FUNCTION_BLOCK",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


class StructuredTextBackend:
    name = "st"
    target = "IEC 61131-3 Structured Text (vendor-neutral skeleton)"

    def emit(self, factory: Factory) -> dict[str, str]:
        machines = sorted(factory.machines, key=lambda machine: machine.id)
        machine_paths = [(machine.id, _machine_path(machine)) for machine in machines]
        _assert_no_collisions("machine output paths", machine_paths)

        rendered: list[tuple[str, str]] = []
        manifest_machines: list[dict[str, object]] = []
        for machine in machines:
            signals = _machine_signals(factory, machine)
            operations = _machine_operations(factory, machine)
            states = _machine_states(signals, machine)
            _assert_no_collisions(
                f"machine {machine.id!r} signal identifiers",
                ((signal.id, _signal_identifier(signal)) for signal in signals),
            )
            _assert_no_collisions(
                f"machine {machine.id!r} operation identifiers",
                (
                    (operation.id, _operation_identifier(machine, operation))
                    for operation in operations
                ),
            )

            path = _machine_path(machine)
            state_type = _machine_state_type(machine)
            rendered.append((path, _render_machine(machine, signals, operations, states)))
            manifest_machines.append(
                {
                    "machine_id": machine.id,
                    "operations": [operation.id for operation in operations],
                    "path": path,
                    "signals": [signal.id for signal in signals],
                    "state_type": state_type,
                }
            )

        manifest = {
            "backend": self.name,
            "factory": {
                "id": factory.meta.id,
                "schema_version": factory.schema_version,
            },
            "machines": manifest_machines,
            "safety_notice": SAFETY_NOTICE,
            "target": self.target,
        }
        files = {path: text for path, text in rendered}
        files["manifest.json"] = (
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        )
        return files
