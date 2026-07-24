from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from mir.dsl.lexer import DSLParseError, Token, TokenKind, tokenize


@dataclass(frozen=True, slots=True)
class LocatedValue:
    value: Any
    token: Token


@dataclass(frozen=True, slots=True)
class DistributionNode:
    kind: str
    arguments: tuple[LocatedValue, ...]
    token: Token


@dataclass(frozen=True, slots=True)
class AvailabilityNode:
    fields: dict[str, LocatedValue]
    token: Token


@dataclass(frozen=True, slots=True)
class EntityNode:
    kind: str
    entity_id: str
    id_token: Token
    fields: dict[str, LocatedValue]


@dataclass(frozen=True, slots=True)
class FactoryNode:
    factory_id: str
    id_token: Token
    fields: dict[str, LocatedValue]
    entities: tuple[EntityNode, ...]
    text: str
    source_name: str

    def error(self, message: str, token: Token) -> DSLParseError:
        lines = self.text.splitlines()
        if not lines or self.text.endswith(("\n", "\r")):
            lines.append("")
        offending_line = lines[token.line - 1] if token.line <= len(lines) else ""
        return DSLParseError(
            message,
            source=self.source_name,
            line=token.line,
            column=token.column,
            offending_line=offending_line,
        )


_FACTORY_FIELDS = {
    "name": "name",
    "description": "description",
    "provenance": "provenance",
    "source": "source",
    "schema": "schema_version",
    "schema_version": "schema_version",
    "version": "schema_version",
}
_MACHINE_FIELDS = {
    "name": "name",
    "class": "machine_class",
    "machine_class": "machine_class",
    "capabilities": "capabilities",
    "stations": "num_stations",
    "num_stations": "num_stations",
    "setup": "setup_time_s",
    "setup_time_s": "setup_time_s",
    "availability": "availability",
    "attrs": "attrs",
}
_OPERATION_FIELDS = {
    "name": "name",
    "kind": "kind",
    "on": "machines",
    "machines": "machines",
    "cycle": "cycle_time",
    "cycle_time": "cycle_time",
    "yield": "yield_fraction",
    "yield_fraction": "yield_fraction",
    "batch": "batch_size",
    "batch_size": "batch_size",
    "attrs": "attrs",
}
_FLOW_FIELDS = {
    "port": "input_port",
    "input_port": "input_port",
    "weight": "routing_weight",
    "routing_weight": "routing_weight",
    "cap": "buffer_capacity",
    "buffer_capacity": "buffer_capacity",
    "transport": "transport_time_s",
    "transport_time_s": "transport_time_s",
}
_SIGNAL_FIELDS = {
    "tag": "tag",
    "machine": "machine",
    "dtype": "dtype",
    "semantic": "semantic",
    "states": "enum_states",
    "enum_states": "enum_states",
    "unit": "unit",
}
_ENTITY_KINDS = frozenset(("machine", "operation", "flow", "signal"))
_DURATION_MULTIPLIERS = {"s": 1.0, "min": 60.0, "h": 3600.0}
_DISTRIBUTION_ARITY = {
    "constant": 1,
    "uniform": 2,
    "normal": 2,
    "exponential": 1,
}


class Parser:
    def __init__(self, text: str, source_name: str = "<string>") -> None:
        self.text = text
        self.source_name = source_name
        self.tokens = tokenize(text, source_name)
        self.index = 0
        self._lines = text.splitlines()
        if not self._lines or text.endswith(("\n", "\r")):
            self._lines.append("")

    def parse(self) -> FactoryNode:
        self._expect_keyword("factory")
        factory_id = self._parse_id("factory id")
        fields: dict[str, LocatedValue] = {}
        while not self._check(TokenKind.LBRACE):
            if self._check(TokenKind.EOF):
                self._raise("expected '{' to open factory body")
            key_token = self._expect(TokenKind.IDENTIFIER, "factory metadata field")
            canonical = _FACTORY_FIELDS.get(key_token.value)
            if canonical is None:
                self._raise(f"unknown factory field {key_token.value!r}", key_token)
            self._match(TokenKind.EQUALS)
            value = self._parse_factory_field(canonical)
            self._store(fields, canonical, value, key_token)
        self._advance()

        entities: list[EntityNode] = []
        while not self._check(TokenKind.RBRACE):
            if self._check(TokenKind.EOF):
                self._raise("expected '}' to close factory body")
            if self._match(TokenKind.COMMA):
                continue
            if self._current.kind is TokenKind.IDENTIFIER and self._current.value in _ENTITY_KINDS:
                kind = self._advance().value
                entities.append(self._parse_entity(kind))
                continue
            key_token = self._expect(TokenKind.IDENTIFIER, "factory field or entity declaration")
            canonical = _FACTORY_FIELDS.get(key_token.value)
            if canonical is None:
                self._raise(f"unknown factory field or entity {key_token.value!r}", key_token)
            self._expect(TokenKind.EQUALS, "'=' after factory field")
            value = self._parse_factory_field(canonical)
            self._store(fields, canonical, value, key_token)
        self._advance()
        self._expect(TokenKind.EOF, "end of input")
        return FactoryNode(
            factory_id=factory_id.value,
            id_token=factory_id.token,
            fields=fields,
            entities=tuple(entities),
            text=self.text,
            source_name=self.source_name,
        )

    @property
    def _current(self) -> Token:
        return self.tokens[self.index]

    def _peek(self, distance: int = 1) -> Token:
        return self.tokens[min(self.index + distance, len(self.tokens) - 1)]

    def _advance(self) -> Token:
        token = self._current
        if token.kind is not TokenKind.EOF:
            self.index += 1
        return token

    def _check(self, kind: TokenKind) -> bool:
        return self._current.kind is kind

    def _match(self, kind: TokenKind) -> Token | None:
        if not self._check(kind):
            return None
        return self._advance()

    def _expect(self, kind: TokenKind, description: str) -> Token:
        if self._check(kind):
            return self._advance()
        self._raise(f"expected {description}, found {self._describe(self._current)}")

    def _expect_keyword(self, keyword: str) -> Token:
        token = self._expect(TokenKind.IDENTIFIER, repr(keyword))
        if token.value != keyword:
            self._raise(f"expected {keyword!r}, found {token.value!r}", token)
        return token

    def _parse_entity(self, kind: str) -> EntityNode:
        entity_id = self._parse_id(f"{kind} id")
        self._expect(TokenKind.LBRACE, "'{' after entity id")
        if kind == "machine":
            fields = self._parse_machine_fields()
        elif kind == "operation":
            fields = self._parse_operation_fields()
        elif kind == "flow":
            fields = self._parse_flow_fields()
        else:
            fields = self._parse_signal_fields()
        self._expect(TokenKind.RBRACE, "'}' after entity body")
        return EntityNode(kind, entity_id.value, entity_id.token, fields)

    def _parse_machine_fields(self) -> dict[str, LocatedValue]:
        fields: dict[str, LocatedValue] = {}
        while not self._check(TokenKind.RBRACE):
            self._ensure_entity_body_open("machine")
            if self._match(TokenKind.COMMA):
                continue
            key_token, canonical = self._field_key(_MACHINE_FIELDS, "machine")
            if canonical == "availability" and self._check(TokenKind.LPAREN):
                value = self._parse_availability()
            else:
                self._expect(TokenKind.EQUALS, "'=' after machine field")
                if canonical in {"name", "machine_class"}:
                    value = self._parse_text(canonical)
                elif canonical == "capabilities":
                    value = self._parse_atom_list("capability")
                elif canonical == "num_stations":
                    value = self._parse_integer(canonical)
                elif canonical == "setup_time_s":
                    value = self._parse_duration(canonical)
                elif canonical == "availability":
                    value = self._parse_nullable_availability()
                else:
                    value = self._parse_json_object("attrs")
            self._store(fields, canonical, value, key_token)
        return fields

    def _parse_operation_fields(self) -> dict[str, LocatedValue]:
        fields: dict[str, LocatedValue] = {}
        while not self._check(TokenKind.RBRACE):
            self._ensure_entity_body_open("operation")
            if self._match(TokenKind.COMMA):
                continue
            key_token, canonical = self._field_key(_OPERATION_FIELDS, "operation")
            self._expect(TokenKind.EQUALS, "'=' after operation field")
            if canonical in {"name", "kind"}:
                value = self._parse_text(canonical)
            elif canonical == "machines":
                value = self._parse_atom_list("machine id")
            elif canonical == "cycle_time":
                value = self._parse_distribution()
            elif canonical == "yield_fraction":
                value = self._parse_number(canonical)
            elif canonical == "batch_size":
                value = self._parse_integer(canonical)
            else:
                value = self._parse_json_object("attrs")
            self._store(fields, canonical, value, key_token)
        return fields

    def _parse_flow_fields(self) -> dict[str, LocatedValue]:
        fields: dict[str, LocatedValue] = {}
        if self._check(TokenKind.RBRACE):
            self._raise("flow body must begin with a material path")
        material = self._parse_text("flow material")
        if self._match(TokenKind.ARROW):
            arrow = self.tokens[self.index - 1]
            from_op = LocatedValue(None, arrow)
        else:
            from_op = self._parse_id("source operation id")
            arrow = self._expect(TokenKind.ARROW, "'->' in flow path")
        if self._flow_target_is_omitted():
            to_op = LocatedValue(None, arrow)
        else:
            to_op = self._parse_id("destination operation id")
        fields["material"] = material
        fields["from_op"] = from_op
        fields["to_op"] = to_op

        while not self._check(TokenKind.RBRACE):
            self._ensure_entity_body_open("flow")
            if self._match(TokenKind.COMMA):
                continue
            key_token, canonical = self._field_key(_FLOW_FIELDS, "flow")
            self._expect(TokenKind.EQUALS, "'=' after flow field")
            if canonical == "input_port":
                value = self._parse_nullable_text(canonical)
            elif canonical == "routing_weight":
                value = self._parse_number(canonical)
            elif canonical == "buffer_capacity":
                value = self._parse_nullable_integer(canonical)
            else:
                value = self._parse_duration(canonical)
            self._store(fields, canonical, value, key_token)
        return fields

    def _parse_signal_fields(self) -> dict[str, LocatedValue]:
        fields: dict[str, LocatedValue] = {}
        while not self._check(TokenKind.RBRACE):
            self._ensure_entity_body_open("signal")
            if self._match(TokenKind.COMMA):
                continue
            key_token, canonical = self._field_key(_SIGNAL_FIELDS, "signal")
            self._expect(TokenKind.EQUALS, "'=' after signal field")
            if canonical in {"tag", "machine", "dtype", "semantic"}:
                value = self._parse_text(canonical)
            elif canonical == "enum_states":
                value = self._parse_nullable_json_object(canonical)
            else:
                value = self._parse_nullable_text(canonical)
            self._store(fields, canonical, value, key_token)
        return fields

    def _parse_factory_field(self, field: str) -> LocatedValue:
        if field in {"name", "description", "source", "schema_version", "provenance"}:
            return self._parse_text(field)
        self._raise(f"unsupported factory field {field!r}")

    def _parse_availability(self) -> LocatedValue:
        start = self._expect(TokenKind.LPAREN, "'(' after availability")
        fields: dict[str, LocatedValue] = {}
        aliases = {"mtbf": "mtbf_s", "mtbf_s": "mtbf_s", "mttr": "mttr_s", "mttr_s": "mttr_s"}
        while not self._check(TokenKind.RPAREN):
            if self._check(TokenKind.EOF) or self._check(TokenKind.RBRACE):
                self._raise("expected ')' after availability")
            if self._match(TokenKind.COMMA):
                continue
            key_token, canonical = self._field_key(aliases, "availability")
            self._expect(TokenKind.EQUALS, "'=' after availability field")
            value = self._parse_duration(canonical)
            self._store(fields, canonical, value, key_token)
        self._advance()
        return LocatedValue(AvailabilityNode(fields, start), start)

    def _parse_nullable_availability(self) -> LocatedValue:
        if self._is_null():
            token = self._advance()
            return LocatedValue(None, token)
        return self._parse_availability()

    def _parse_distribution(self) -> LocatedValue:
        if self._check(TokenKind.DURATION):
            duration = self._parse_duration("constant cycle time")
            distribution = DistributionNode("constant", (duration,), duration.token)
            return LocatedValue(distribution, duration.token)
        kind_token = self._expect(TokenKind.IDENTIFIER, "distribution name")
        arity = _DISTRIBUTION_ARITY.get(kind_token.value)
        if arity is None:
            self._raise(f"unknown distribution {kind_token.value!r}", kind_token)
        self._expect(TokenKind.LPAREN, "'(' after distribution name")
        arguments: list[LocatedValue] = []
        for index in range(arity):
            if index:
                self._expect(TokenKind.COMMA, "',' between distribution arguments")
            arguments.append(self._parse_duration(f"{kind_token.value} argument"))
        self._expect(TokenKind.RPAREN, "')' after distribution arguments")
        distribution = DistributionNode(kind_token.value, tuple(arguments), kind_token)
        return LocatedValue(distribution, kind_token)

    def _parse_duration(self, description: str) -> LocatedValue:
        token = self._expect(TokenKind.DURATION, f"duration for {description}")
        unit = next(unit for unit in ("min", "s", "h") if token.value.endswith(unit))
        numeric_text = token.value[: -len(unit)]
        value = float(numeric_text) * _DURATION_MULTIPLIERS[unit]
        if not math.isfinite(value):
            self._raise("duration must be finite", token)
        return LocatedValue(value, token)

    def _parse_text(self, description: str) -> LocatedValue:
        token = self._current
        if token.kind in {TokenKind.STRING, TokenKind.IDENTIFIER, TokenKind.DURATION}:
            self._advance()
            return LocatedValue(token.value, token)
        if token.kind is TokenKind.NUMBER:
            self._advance()
            return LocatedValue(token.value, token)
        self._raise(f"expected text for {description}, found {self._describe(token)}", token)

    def _parse_nullable_text(self, description: str) -> LocatedValue:
        if self._is_null():
            token = self._advance()
            return LocatedValue(None, token)
        return self._parse_text(description)

    def _parse_id(self, description: str) -> LocatedValue:
        return self._parse_text(description)

    def _parse_atom_list(self, description: str) -> LocatedValue:
        start = self._expect(TokenKind.LBRACKET, "'['")
        values: list[str] = []
        if not self._check(TokenKind.RBRACKET):
            while True:
                values.append(self._parse_text(description).value)
                if not self._match(TokenKind.COMMA):
                    break
                if self._check(TokenKind.RBRACKET):
                    self._raise("trailing comma is not allowed in lists")
        self._expect(TokenKind.RBRACKET, "']'")
        return LocatedValue(values, start)

    def _parse_number(self, description: str) -> LocatedValue:
        token = self._expect(TokenKind.NUMBER, f"number for {description}")
        value: int | float
        if any(marker in token.value for marker in ".eE"):
            value = float(token.value)
            if not math.isfinite(value):
                self._raise(f"{description} must be finite", token)
        else:
            value = int(token.value)
        return LocatedValue(value, token)

    def _parse_integer(self, description: str) -> LocatedValue:
        value = self._parse_number(description)
        if not isinstance(value.value, int):
            self._raise(f"{description} must be an integer", value.token)
        return value

    def _parse_nullable_integer(self, description: str) -> LocatedValue:
        if self._is_null():
            token = self._advance()
            return LocatedValue(None, token)
        return self._parse_integer(description)

    def _parse_json_object(self, description: str) -> LocatedValue:
        value = self._parse_json_value()
        if not isinstance(value.value, dict):
            self._raise(f"{description} must be a JSON object", value.token)
        return value

    def _parse_nullable_json_object(self, description: str) -> LocatedValue:
        if self._is_null():
            token = self._advance()
            return LocatedValue(None, token)
        return self._parse_json_object(description)

    def _parse_json_value(self) -> LocatedValue:
        token = self._current
        if token.kind is TokenKind.STRING:
            self._advance()
            return LocatedValue(token.value, token)
        if token.kind is TokenKind.NUMBER:
            return self._parse_number("JSON value")
        if token.kind is TokenKind.IDENTIFIER:
            literals = {"true": True, "false": False, "null": None}
            if token.value in literals:
                self._advance()
                return LocatedValue(literals[token.value], token)
            self._raise("JSON values must quote strings", token)
        if token.kind is TokenKind.LBRACKET:
            self._advance()
            values: list[Any] = []
            if not self._check(TokenKind.RBRACKET):
                while True:
                    values.append(self._parse_json_value().value)
                    if not self._match(TokenKind.COMMA):
                        break
                    if self._check(TokenKind.RBRACKET):
                        self._raise("trailing comma is not allowed in JSON arrays")
            self._expect(TokenKind.RBRACKET, "']' after JSON array")
            return LocatedValue(values, token)
        if token.kind is TokenKind.LBRACE:
            self._advance()
            values: dict[str, Any] = {}
            if not self._check(TokenKind.RBRACE):
                while True:
                    key = self._expect(TokenKind.STRING, "quoted JSON object key")
                    if key.value in values:
                        self._raise(f"duplicate JSON object key {key.value!r}", key)
                    self._expect(TokenKind.COLON, "':' after JSON object key")
                    values[key.value] = self._parse_json_value().value
                    if not self._match(TokenKind.COMMA):
                        break
                    if self._check(TokenKind.RBRACE):
                        self._raise("trailing comma is not allowed in JSON objects")
            self._expect(TokenKind.RBRACE, "'}' after JSON object")
            return LocatedValue(values, token)
        self._raise(f"expected JSON value, found {self._describe(token)}", token)

    def _field_key(self, aliases: dict[str, str], owner: str) -> tuple[Token, str]:
        token = self._expect(TokenKind.IDENTIFIER, f"{owner} field")
        canonical = aliases.get(token.value)
        if canonical is None:
            self._raise(f"unknown {owner} field {token.value!r}", token)
        return token, canonical

    def _store(
        self,
        fields: dict[str, LocatedValue],
        canonical: str,
        value: LocatedValue,
        key_token: Token,
    ) -> None:
        if canonical in fields:
            self._raise(f"duplicate field {canonical!r}", key_token)
        fields[canonical] = value

    def _flow_target_is_omitted(self) -> bool:
        if self._check(TokenKind.RBRACE) or self._check(TokenKind.COMMA):
            return True
        return (
            self._current.kind is TokenKind.IDENTIFIER
            and self._current.value in _FLOW_FIELDS
            and self._peek().kind is TokenKind.EQUALS
        )

    def _ensure_entity_body_open(self, kind: str) -> None:
        if self._check(TokenKind.EOF):
            self._raise(f"expected '}}' to close {kind} body")

    def _is_null(self) -> bool:
        return self._current.kind is TokenKind.IDENTIFIER and self._current.value == "null"

    @staticmethod
    def _describe(token: Token) -> str:
        if token.kind is TokenKind.EOF:
            return "end of input"
        return repr(token.text)

    def _raise(self, message: str, token: Token | None = None) -> None:
        target = token or self._current
        offending_line = self._lines[target.line - 1] if target.line <= len(self._lines) else ""
        raise DSLParseError(
            message,
            source=self.source_name,
            line=target.line,
            column=target.column,
            offending_line=offending_line,
        )


def parse(text: str, source_name: str = "<string>") -> FactoryNode:
    return Parser(text, source_name).parse()
