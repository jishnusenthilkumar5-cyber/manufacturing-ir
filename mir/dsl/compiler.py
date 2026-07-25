from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from mir.core.model import Factory, SCHEMA_VERSION
from mir.dsl.lexer import Token
from mir.dsl.parser import (
    AvailabilityNode,
    DistributionNode,
    EntityNode,
    FactoryNode,
    LocatedValue,
    parse,
)
from mir.passes import Diagnostic, Severity, validate_factory


class DSLValidationError(ValueError):
    def __init__(
        self,
        diagnostics: tuple[Diagnostic, ...],
        *,
        source: str = "<string>",
    ) -> None:
        self.diagnostics = diagnostics
        self.source = source
        rendered = "\n".join(
            f"{item.severity.value}: {item.code}: {item.message}"
            + (f" [{', '.join(item.entities)}]" if item.entities else "")
            for item in diagnostics
        )
        super().__init__(f"{source}: Manufacturing IR validation failed\n{rendered}")


def compile_factory(node: FactoryNode) -> Factory:
    grouped: dict[str, list[EntityNode]] = {
        "machine": [],
        "operation": [],
        "flow": [],
        "signal": [],
    }
    for entity in node.entities:
        grouped[entity.kind].append(entity)

    payload: dict[str, Any] = {
        "schema_version": _field(node.fields, "schema_version", SCHEMA_VERSION),
        "meta": {
            "id": node.factory_id,
            "name": _required_field(node, "name"),
            "description": _field(node.fields, "description", ""),
            "provenance": {
                "kind": _field(node.fields, "provenance", "authored"),
                "source": _field(node.fields, "source", ""),
            },
        },
        "machines": [_machine_payload(node, entity) for entity in grouped["machine"]],
        "operations": [_operation_payload(node, entity) for entity in grouped["operation"]],
        "flows": [_flow_payload(node, entity) for entity in grouped["flow"]],
        "signals": [_signal_payload(node, entity) for entity in grouped["signal"]],
    }

    try:
        factory = Factory.model_validate(payload)
    except ValidationError as exc:
        error = exc.errors(include_url=False)[0]
        token = _token_for_location(node, error.get("loc", ()))
        location = ".".join(str(part) for part in error.get("loc", ()))
        message = str(error.get("msg", "invalid value"))
        prefix = f"invalid {location}: " if location else "invalid factory: "
        raise node.error(prefix + message, token) from exc

    factory.machines.sort(key=lambda item: item.id)
    factory.operations.sort(key=lambda item: item.id)
    factory.flows.sort(key=lambda item: item.id)
    factory.signals.sort(key=lambda item: item.id)

    diagnostics = validate_factory(factory).diagnostics
    if any(item.severity is Severity.ERROR for item in diagnostics):
        raise DSLValidationError(diagnostics, source=node.source_name)
    return factory


def loads_mir(text: str, source_name: str = "<string>") -> Factory:
    return compile_factory(parse(text, source_name))


def read_mir(path: str | Path) -> Factory:
    source = Path(path)
    return loads_mir(source.read_text(encoding="utf-8"), source_name=str(source))


def _machine_payload(node: FactoryNode, entity: EntityNode) -> dict[str, Any]:
    return {
        "id": entity.entity_id,
        "name": _entity_field(entity, "name", entity.entity_id),
        "machine_class": _entity_required(node, entity, "machine_class"),
        "capabilities": _entity_required(node, entity, "capabilities"),
        "num_stations": _entity_field(entity, "num_stations", 1),
        "setup_time_s": _entity_field(entity, "setup_time_s", 0.0),
        "availability": _availability_payload(_entity_field(entity, "availability", None)),
        "calendar": _entity_field(entity, "calendar", []),
        "attrs": _entity_field(entity, "attrs", {}),
    }


def _operation_payload(node: FactoryNode, entity: EntityNode) -> dict[str, Any]:
    return {
        "id": entity.entity_id,
        "name": _entity_field(entity, "name", entity.entity_id),
        "kind": _entity_required(node, entity, "kind"),
        "machines": _entity_required(node, entity, "machines"),
        "cycle_time": _distribution_payload(_entity_required(node, entity, "cycle_time")),
        "yield_fraction": _entity_field(entity, "yield_fraction", 1.0),
        "batch_size": _entity_field(entity, "batch_size", 1),
        "priority": _entity_field(entity, "priority", 0),
        "attrs": _entity_field(entity, "attrs", {}),
    }


def _flow_payload(node: FactoryNode, entity: EntityNode) -> dict[str, Any]:
    return {
        "id": entity.entity_id,
        "material": _entity_required(node, entity, "material"),
        "from_op": _entity_field(entity, "from_op", None),
        "to_op": _entity_field(entity, "to_op", None),
        "input_port": _entity_field(entity, "input_port", None),
        "routing_weight": _entity_field(entity, "routing_weight", 1.0),
        "buffer_capacity": _entity_field(entity, "buffer_capacity", None),
        "transport_time_s": _entity_field(entity, "transport_time_s", 0.0),
        "units_per_batch": _entity_field(entity, "units_per_batch", 1),
    }


def _signal_payload(node: FactoryNode, entity: EntityNode) -> dict[str, Any]:
    return {
        "id": entity.entity_id,
        "tag": _entity_required(node, entity, "tag"),
        "machine": _entity_required(node, entity, "machine"),
        "dtype": _entity_required(node, entity, "dtype"),
        "semantic": _entity_required(node, entity, "semantic"),
        "enum_states": _entity_field(entity, "enum_states", None),
        "unit": _entity_field(entity, "unit", None),
    }


def _availability_payload(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, AvailabilityNode):
        return value
    return {
        "mtbf_s": _located_field(value.fields, "mtbf_s"),
        "mttr_s": _located_field(value.fields, "mttr_s"),
    }


def _distribution_payload(value: Any) -> Any:
    if not isinstance(value, DistributionNode):
        return value
    arguments = [argument.value for argument in value.arguments]
    if value.kind == "constant":
        return {"kind": value.kind, "value_s": arguments[0]}
    if value.kind == "uniform":
        return {"kind": value.kind, "low_s": arguments[0], "high_s": arguments[1]}
    if value.kind == "normal":
        return {"kind": value.kind, "mean_s": arguments[0], "std_s": arguments[1]}
    return {"kind": value.kind, "mean_s": arguments[0]}


def _required_field(node: FactoryNode, name: str) -> Any:
    located = node.fields.get(name)
    if located is None:
        raise node.error(f"missing required factory field {name!r}", node.id_token)
    return located.value


def _field(fields: dict[str, LocatedValue], name: str, default: Any) -> Any:
    located = fields.get(name)
    return default if located is None else located.value


def _entity_required(node: FactoryNode, entity: EntityNode, name: str) -> Any:
    located = entity.fields.get(name)
    if located is None:
        raise node.error(f"missing required {entity.kind} field {name!r}", entity.id_token)
    return located.value


def _entity_field(entity: EntityNode, name: str, default: Any) -> Any:
    located = entity.fields.get(name)
    return default if located is None else located.value


def _located_field(fields: dict[str, LocatedValue], name: str) -> Any:
    located = fields.get(name)
    return None if located is None else located.value


def _token_for_location(node: FactoryNode, location: tuple[Any, ...]) -> Token:
    if not location:
        return node.id_token
    if location[0] == "schema_version":
        return node.fields.get("schema_version", LocatedValue(None, node.id_token)).token
    if location[0] == "meta":
        if len(location) > 1 and location[1] == "id":
            return node.id_token
        if len(location) > 2 and location[1] == "provenance":
            field = "provenance" if location[2] == "kind" else "source"
            return node.fields.get(field, LocatedValue(None, node.id_token)).token
        if len(location) > 1:
            return node.fields.get(str(location[1]), LocatedValue(None, node.id_token)).token
        return node.id_token

    collection_map = {
        "machines": "machine",
        "operations": "operation",
        "flows": "flow",
        "signals": "signal",
    }
    kind = collection_map.get(str(location[0]))
    if kind is None or len(location) < 2 or not isinstance(location[1], int):
        return node.id_token
    entities = [entity for entity in node.entities if entity.kind == kind]
    if location[1] >= len(entities):
        return node.id_token
    entity = entities[location[1]]
    if len(location) < 3 or location[2] == "id":
        return entity.id_token
    field = str(location[2])
    located = entity.fields.get(field)
    if located is None:
        return entity.id_token
    value = located.value
    if isinstance(value, DistributionNode) and len(location) > 3:
        argument_index = {
            "value_s": 0,
            "low_s": 0,
            "high_s": 1,
            "mean_s": 0,
            "std_s": 1,
        }.get(str(location[-1]))
        if argument_index is not None and argument_index < len(value.arguments):
            return value.arguments[argument_index].token
    if isinstance(value, AvailabilityNode) and len(location) > 3:
        nested = value.fields.get(str(location[-1]))
        if nested is not None:
            return nested.token
    return located.token
