from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings, strategies as st

from mir import (
    ConstantDistribution,
    Factory,
    FactoryMeta,
    Machine,
    MaterialFlow,
    Operation,
    Provenance,
    ProvenanceKind,
)
from mir.dsl import DSLParseError, dumps_mir, loads_mir


unicode_text = st.text(st.characters(blacklist_categories=("Cs",)), max_size=24)
nonempty_unicode_text = st.text(
    st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=24,
)
finite_numbers = st.one_of(
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(
        min_value=-1e12,
        max_value=1e12,
        allow_nan=False,
        allow_infinity=False,
        width=64,
    ),
)
json_scalars = st.one_of(st.none(), st.booleans(), finite_numbers, unicode_text)
json_values = st.recursive(
    json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(unicode_text, children, max_size=4),
    ),
    max_leaves=12,
)
json_objects = st.dictionaries(unicode_text, json_values, max_size=6)
valid_ids = st.from_regex(r"[a-z0-9][a-z0-9_-]{0,20}", fullmatch=True)


def attributed_factory(
    name: str,
    machine_attrs: dict[str, Any],
    operation_attrs: dict[str, Any],
    *,
    factory_id: str = "property-line",
    machine_id: str = "machine",
    operation_id: str = "operation",
) -> Factory:
    return Factory(
        meta=FactoryMeta(
            id=factory_id,
            name=name,
            provenance=Provenance(kind=ProvenanceKind.AUTHORED),
        ),
        machines=[
            Machine(
                id=machine_id,
                name=name,
                machine_class="processor",
                capabilities=["process"],
                attrs=machine_attrs,
            )
        ],
        operations=[
            Operation(
                id=operation_id,
                name=name,
                kind="process",
                machines=[machine_id],
                cycle_time=ConstantDistribution(value_s=1.0),
                attrs=operation_attrs,
            )
        ],
        flows=[
            MaterialFlow(id="input", material="part", to_op=operation_id),
            MaterialFlow(id="output", material="part", from_op=operation_id),
        ],
    )


@given(nonempty_unicode_text, json_objects, json_objects)
@settings(max_examples=60, deadline=None)
def test_unicode_and_json_values_round_trip(
    name: str,
    machine_attrs: dict[str, Any],
    operation_attrs: dict[str, Any],
) -> None:
    factory = attributed_factory(name, machine_attrs, operation_attrs)
    canonical = dumps_mir(factory)
    loaded = loads_mir(canonical)
    assert loaded == factory
    assert dumps_mir(loaded) == canonical


@given(valid_ids, valid_ids, valid_ids)
@settings(max_examples=60, deadline=None)
def test_valid_identifier_tokens_round_trip(
    factory_id: str,
    machine_id: str,
    operation_id: str,
) -> None:
    factory = attributed_factory(
        "Identifiers",
        {},
        {},
        factory_id=factory_id,
        machine_id=machine_id,
        operation_id=operation_id,
    )
    canonical = dumps_mir(factory)
    assert loads_mir(canonical) == factory
    assert dumps_mir(loads_mir(canonical)) == canonical


def test_overflow_shaped_identifier_round_trips() -> None:
    factory = attributed_factory(
        "Numeric identifier",
        {},
        {},
        factory_id="1e999",
        machine_id="2e999",
        operation_id="3e999",
    )
    assert loads_mir(dumps_mir(factory)) == factory


def test_nonfinite_json_number_is_rejected() -> None:
    text = '''factory line name "Line" {
  machine machine { class=processor capabilities=[process] attrs={"bad": 1e999} }
}
'''
    with pytest.raises(DSLParseError, match="must be finite"):
        loads_mir(text)


@given(
    st.floats(
        min_value=0.001,
        max_value=100_000,
        allow_nan=False,
        allow_infinity=False,
        width=64,
    ),
    st.sampled_from((("s", 1.0), ("min", 60.0), ("h", 3_600.0))),
)
@settings(max_examples=60, deadline=None)
def test_duration_tokens_convert_to_seconds(
    value: float,
    unit_and_multiplier: tuple[str, float],
) -> None:
    unit, multiplier = unit_and_multiplier
    text = f'''factory duration-line name "Duration" {{
  machine machine {{ class=processor capabilities=[process] setup={value!r}{unit} }}
  operation operation {{ kind=process on=[machine] cycle=constant({value!r}{unit}) }}
  flow input {{ part -> operation }}
  flow output {{ part operation -> }}
}}
'''
    factory = loads_mir(text)
    expected = float(repr(value)) * multiplier
    assert factory.machines[0].setup_time_s == expected
    assert factory.operations[0].cycle_time.value_s == expected
    assert loads_mir(dumps_mir(factory)) == factory
