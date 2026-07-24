from __future__ import annotations

import math

import pytest

from mir.dsl import DSLParseError, DSLValidationError, dumps_mir, loads_mir
from tests.test_dsl import rich_factory


def test_malformed_token_has_source_line_column_and_caret() -> None:
    text = '''factory line name "Line" {
  machine m1 { class=@ capabilities=[process] }
}
'''
    with pytest.raises(DSLParseError) as raised:
        loads_mir(text, source_name="broken.mir")
    error = raised.value
    assert error.source == "broken.mir"
    assert error.line == 2
    assert error.column == 22
    assert error.offending_line == "  machine m1 { class=@ capabilities=[process] }"
    assert str(error) == (
        "broken.mir:2:22: unexpected character '@'\n"
        "  machine m1 { class=@ capabilities=[process] }\n"
        "                     ^"
    )


def test_unterminated_string_points_to_opening_quote() -> None:
    text = 'factory line name "Unclosed {\n'
    with pytest.raises(DSLParseError, match="unterminated string literal") as raised:
        loads_mir(text, source_name="quote.mir")
    assert (raised.value.line, raised.value.column) == (1, 19)
    assert raised.value.caret.endswith("^")


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            '''factory line name "Line" {
  machine m1 { class=processor mystery=1 capabilities=[process] }
}
''',
            "unknown machine field 'mystery'",
        ),
        (
            '''factory line name "Line" {
  machine m1 { class=processor machine_class=other capabilities=[process] }
}
''',
            "duplicate field 'machine_class'",
        ),
        (
            '''factory line name "Line" {
  description = "first"
  description = "second"
}
''',
            "duplicate field 'description'",
        ),
        (
            '''factory line name "Line" {
  operation op1 { kind=process on=[] cycle=constant(10s) surprise=true }
}
''',
            "unknown operation field 'surprise'",
        ),
    ],
)
def test_unknown_and_duplicate_fields_are_parse_errors(body: str, message: str) -> None:
    with pytest.raises(DSLParseError, match=message):
        loads_mir(body)


def test_duplicate_json_keys_are_rejected() -> None:
    text = '''factory line name "Line" {
  machine m1 { class=processor capabilities=[process] attrs={"a": 1, "a": 2} }
}
'''
    with pytest.raises(DSLParseError, match="duplicate JSON object key 'a'"):
        loads_mir(text)


@pytest.mark.parametrize(
    "cycle",
    ["constant(1ms)", "normal(1s 2s)", "uniform(2s, 1s", "mystery(1s)"],
)
def test_malformed_distribution_is_rejected(cycle: str) -> None:
    text = f'''factory line name "Line" {{
  operation op1 {{ kind=process on=[] cycle={cycle} }}
}}
'''
    with pytest.raises(DSLParseError):
        loads_mir(text)


def test_invalid_schema_value_is_source_local() -> None:
    text = '''factory line name "Line" {
  schema_version = "9.9.9"
}
'''
    with pytest.raises(DSLParseError, match="invalid schema_version") as raised:
        loads_mir(text, source_name="version.mir")
    assert raised.value.source == "version.mir"
    assert (raised.value.line, raised.value.column) == (2, 20)
    assert raised.value.offending_line == '  schema_version = "9.9.9"'


@pytest.mark.parametrize(
    ("entity", "expected_code"),
    [
        (
            "  operation op1 { kind=process on=[missing] cycle=constant(10s) }\n",
            "MIR002",
        ),
        (
            "  flow bad-flow { part -> missing }\n",
            "MIR003",
        ),
        (
            "  signal bad-signal { tag=BAD machine=missing dtype=int semantic=cycle_count }\n",
            "MIR006",
        ),
    ],
)
def test_cross_reference_diagnostics_are_structured(entity: str, expected_code: str) -> None:
    text = f'''factory line name "Line" {{
  machine m1 {{ class=process capabilities=[process] }}
{entity}}}
'''
    with pytest.raises(DSLValidationError) as raised:
        loads_mir(text, source_name="refs.mir")
    error = raised.value
    assert error.source == "refs.mir"
    assert expected_code in [item.code for item in error.diagnostics]
    assert f"error: {expected_code}:" in str(error)


def test_validation_error_contains_all_ordered_diagnostics() -> None:
    text = '''factory line name "Line" {
  machine m1 { class=process capabilities=[process] }
  operation op1 { kind=process on=[missing] cycle=constant(10s) }
  flow endpointless { part -> }
}
'''
    with pytest.raises(DSLValidationError) as raised:
        loads_mir(text)
    diagnostics = raised.value.diagnostics
    assert [item.code for item in diagnostics if item.severity.value == "error"] == [
        "MIR002",
        "MIR004",
    ]


def test_parse_errors_are_not_hidden_by_validation() -> None:
    text = '''factory line name "Line" {
  operation op1 { kind=process on=[missing] cycle=constant(10s) bogus=1 }
}
'''
    with pytest.raises(DSLParseError, match="unknown operation field 'bogus'"):
        loads_mir(text)


def test_missing_required_field_uses_entity_source_location() -> None:
    text = '''factory line name "Line" {
  machine m1 { capabilities=[process] }
}
'''
    with pytest.raises(
        DSLParseError,
        match="missing required machine field 'machine_class'",
    ) as raised:
        loads_mir(text, source_name="required.mir")
    assert raised.value.source == "required.mir"
    assert raised.value.offending_line == "  machine m1 { capabilities=[process] }"


def test_printer_rejects_non_json_attrs() -> None:
    factory = rich_factory()
    factory.machines[0].attrs = {"not-json": {1, 2}}
    with pytest.raises(TypeError, match="cannot contain set"):
        dumps_mir(factory)


def test_printer_rejects_nonfinite_attrs() -> None:
    factory = rich_factory()
    factory.machines[0].attrs = {"bad": math.nan}
    with pytest.raises(ValueError, match="non-finite"):
        dumps_mir(factory)


def test_printer_rejects_non_string_object_keys() -> None:
    factory = rich_factory()
    factory.machines[0].attrs[1] = "bad"
    with pytest.raises(TypeError, match="keys must be strings"):
        dumps_mir(factory)


def test_duplicate_entity_ids_surface_mir001() -> None:
    text = '''factory line name "Line" {
  machine duplicate { class=processor capabilities=[process] }
  machine duplicate { class=processor capabilities=[process] }
}
'''
    with pytest.raises(DSLValidationError) as raised:
        loads_mir(text)
    assert "MIR001" in [item.code for item in raised.value.diagnostics]


def test_invalid_flow_arrow_is_parse_error() -> None:
    text = '''factory line name "Line" {
  flow broken { part op1 op2 }
}
'''
    with pytest.raises(DSLParseError, match="expected '->' in flow path"):
        loads_mir(text)
