from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from mir.core.distributions import (
    ConstantDistribution,
    ExponentialDistribution,
    NormalDistribution,
    UniformDistribution,
)
from mir.core.model import Factory, Machine, MaterialFlow, Operation, Signal


_INDENT = "  "


def dumps_mir(factory: Factory) -> str:
    lines = [f"factory {_identifier(factory.meta.id)} name {_string(factory.meta.name)} {{"]
    lines.append(f"{_INDENT}schema_version = {_string(factory.schema_version)}")
    if factory.meta.description:
        lines.append(f"{_INDENT}description = {_string(factory.meta.description)}")
    lines.append(f"{_INDENT}provenance = {factory.meta.provenance.kind.value}")
    if factory.meta.provenance.source:
        lines.append(f"{_INDENT}source = {_string(factory.meta.provenance.source)}")

    groups: tuple[tuple[Any, ...], ...] = (
        tuple(sorted(factory.machines, key=lambda item: item.id)),
        tuple(sorted(factory.operations, key=lambda item: item.id)),
        tuple(sorted(factory.flows, key=lambda item: item.id)),
        tuple(sorted(factory.signals, key=lambda item: item.id)),
    )
    for group in groups:
        for entity in group:
            lines.append("")
            if isinstance(entity, Machine):
                lines.extend(_machine_lines(entity))
            elif isinstance(entity, Operation):
                lines.extend(_operation_lines(entity))
            elif isinstance(entity, MaterialFlow):
                lines.extend(_flow_lines(entity))
            else:
                lines.extend(_signal_lines(entity))
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_mir(factory: Factory, path: str | Path) -> Path:
    destination = Path(path)
    destination.write_text(dumps_mir(factory), encoding="utf-8", newline="\n")
    return destination


def _machine_lines(machine: Machine) -> list[str]:
    prefix = _INDENT
    field = _INDENT * 2
    lines = [f"{prefix}machine {_identifier(machine.id)} {{"]
    lines.append(f"{field}name = {_string(machine.name)}")
    lines.append(f"{field}class = {_string(machine.machine_class)}")
    capabilities = ", ".join(_string(item) for item in machine.capabilities)
    lines.append(f"{field}capabilities = [{capabilities}]")
    if machine.num_stations != 1:
        lines.append(f"{field}stations = {machine.num_stations}")
    if machine.setup_time_s != 0.0:
        lines.append(f"{field}setup = {_duration(machine.setup_time_s)}")
    if machine.availability is not None:
        lines.append(
            f"{field}availability(mtbf={_duration(machine.availability.mtbf_s)}, "
            f"mttr={_duration(machine.availability.mttr_s)})"
        )
    if machine.calendar:
        calendar = [window.model_dump(mode="json") for window in machine.calendar]
        lines.append(f"{field}calendar = {_json(calendar)}")
    if machine.attrs:
        lines.append(f"{field}attrs = {_json(machine.attrs)}")
    lines.append(f"{prefix}}}")
    return lines


def _operation_lines(operation: Operation) -> list[str]:
    prefix = _INDENT
    field = _INDENT * 2
    lines = [f"{prefix}operation {_identifier(operation.id)} {{"]
    lines.append(f"{field}name = {_string(operation.name)}")
    lines.append(f"{field}kind = {_string(operation.kind)}")
    machines = ", ".join(_identifier(item) for item in operation.machines)
    lines.append(f"{field}on = [{machines}]")
    lines.append(f"{field}cycle = {_distribution(operation)}")
    if operation.yield_fraction != 1.0:
        lines.append(f"{field}yield = {_number(operation.yield_fraction)}")
    if operation.batch_size != 1:
        lines.append(f"{field}batch = {operation.batch_size}")
    if operation.priority != 0:
        lines.append(f"{field}priority = {operation.priority}")
    if operation.attrs:
        lines.append(f"{field}attrs = {_json(operation.attrs)}")
    lines.append(f"{prefix}}}")
    return lines


def _flow_lines(flow: MaterialFlow) -> list[str]:
    prefix = _INDENT
    field = _INDENT * 2
    lines = [f"{prefix}flow {_identifier(flow.id)} {{"]
    source = f" {_identifier(flow.from_op)}" if flow.from_op is not None else ""
    target = f" {_identifier(flow.to_op)}" if flow.to_op is not None else ""
    lines.append(f"{field}{_string(flow.material)}{source} ->{target}")
    if flow.input_port is not None:
        lines.append(f"{field}port = {_string(flow.input_port)}")
    if flow.routing_weight != 1.0:
        lines.append(f"{field}weight = {_number(flow.routing_weight)}")
    if flow.buffer_capacity is not None:
        lines.append(f"{field}cap = {flow.buffer_capacity}")
    if flow.transport_time_s != 0.0:
        lines.append(f"{field}transport = {_duration(flow.transport_time_s)}")
    if flow.units_per_batch != 1:
        lines.append(f"{field}units = {flow.units_per_batch}")
    lines.append(f"{prefix}}}")
    return lines


def _signal_lines(signal: Signal) -> list[str]:
    prefix = _INDENT
    field = _INDENT * 2
    lines = [f"{prefix}signal {_identifier(signal.id)} {{"]
    lines.append(f"{field}tag = {_string(signal.tag)}")
    lines.append(f"{field}machine = {_identifier(signal.machine)}")
    lines.append(f"{field}dtype = {signal.dtype.value}")
    lines.append(f"{field}semantic = {signal.semantic.value}")
    if signal.enum_states is not None:
        lines.append(f"{field}states = {_json(signal.enum_states)}")
    if signal.unit is not None:
        lines.append(f"{field}unit = {_string(signal.unit)}")
    lines.append(f"{prefix}}}")
    return lines


def _distribution(operation: Operation) -> str:
    distribution = operation.cycle_time
    if isinstance(distribution, ConstantDistribution):
        return f"constant({_duration(distribution.value_s)})"
    if isinstance(distribution, UniformDistribution):
        return f"uniform({_duration(distribution.low_s)}, {_duration(distribution.high_s)})"
    if isinstance(distribution, NormalDistribution):
        return f"normal({_duration(distribution.mean_s)}, {_duration(distribution.std_s)})"
    if isinstance(distribution, ExponentialDistribution):
        return f"exponential({_duration(distribution.mean_s)})"
    raise TypeError(f"unsupported cycle-time distribution {type(distribution).__name__}")


def _identifier(value: str) -> str:
    return value


def _duration(value: float) -> str:
    return f"{_number(value)}s"


def _number(value: int | float) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"expected a number, found {type(value).__name__}")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("MIR DSL cannot represent non-finite numbers")
    return repr(value)


def _string(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"expected a string, found {type(value).__name__}")
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _json(value: Any) -> str:
    _validate_json(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(", ", ": "),
    )


def _validate_json(value: Any) -> None:
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("MIR DSL attrs cannot contain non-finite numbers")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("MIR DSL object keys must be strings")
            _validate_json(item)
        return
    raise TypeError(f"MIR DSL attrs cannot contain {type(value).__name__}")
