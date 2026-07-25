from __future__ import annotations

import json

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
    dumps_canonical,
    factory_json_schema,
    loads_factory,
)
from mir.io import IRLoadError, UnsupportedSchemaVersion
from mir.synth import serial_line


def make_factory() -> Factory:
    return Factory(
        meta=FactoryMeta(
            id="line-01",
            name="Line 01",
            provenance=Provenance(kind=ProvenanceKind.SYNTHETIC, source="test"),
        ),
        machines=[
            Machine(id="m-02", name="M2", machine_class="generic", capabilities=["op-02"]),
            Machine(id="m-01", name="M1", machine_class="generic", capabilities=["op-01"]),
        ],
        operations=[
            Operation(
                id="op-02",
                name="Op 2",
                kind="op-02",
                machines=["m-02"],
                cycle_time=ConstantDistribution(value_s=20),
            ),
            Operation(
                id="op-01",
                name="Op 1",
                kind="op-01",
                machines=["m-01"],
                cycle_time=ConstantDistribution(value_s=10),
            ),
        ],
        flows=[
            MaterialFlow(id="out", material="part", from_op="op-02"),
            MaterialFlow(id="middle", material="part", from_op="op-01", to_op="op-02"),
            MaterialFlow(id="in", material="blank", to_op="op-01"),
        ],
    )


def test_canonical_round_trip_is_byte_stable() -> None:
    first = dumps_canonical(make_factory())
    loaded = loads_factory(first)
    second = dumps_canonical(loaded)
    assert second == first
    assert first.endswith("\n")
    payload = json.loads(first)
    assert [item["id"] for item in payload["machines"]] == ["m-01", "m-02"]


def test_current_schema_is_exported() -> None:
    schema = factory_json_schema()
    assert schema["properties"]["schema_version"]["const"] == "0.2.0"


def test_schema_version_gate_is_readable() -> None:
    payload = json.loads(dumps_canonical(make_factory()))
    payload["schema_version"] = "9.9.9"
    with pytest.raises(UnsupportedSchemaVersion, match="9.9.9"):
        loads_factory(json.dumps(payload))


def test_invalid_json_has_location() -> None:
    with pytest.raises(IRLoadError, match="line 1, column"):
        loads_factory("{not-json")


def test_invalid_utf8_is_a_load_error() -> None:
    with pytest.raises(IRLoadError, match="not valid UTF-8"):
        loads_factory(b"\xff")


@st.composite
def factories(draw):
    station_count = draw(st.integers(min_value=1, max_value=6))
    cycle_times = draw(
        st.lists(
            st.floats(
                min_value=0.01,
                max_value=1_000,
                allow_nan=False,
                allow_infinity=False,
            ),
            min_size=station_count,
            max_size=station_count,
        )
    )
    capacity = draw(st.one_of(st.none(), st.integers(min_value=0, max_value=20)))
    return serial_line(
        stations=station_count,
        cycle_times_s=cycle_times,
        buffer_capacity=capacity,
    )


@given(factories())
@settings(max_examples=50, deadline=None)
def test_generated_factories_round_trip(factory: Factory) -> None:
    canonical = dumps_canonical(factory)
    assert loads_factory(canonical) == factory
    assert dumps_canonical(loads_factory(canonical)) == canonical


@given(factories())
@settings(max_examples=30, deadline=None)
def test_entity_input_order_does_not_change_canonical_bytes(factory: Factory) -> None:
    shuffled = factory.model_copy(deep=True)
    shuffled.machines.reverse()
    shuffled.operations.reverse()
    shuffled.flows.reverse()
    shuffled.signals.reverse()
    assert dumps_canonical(shuffled) == dumps_canonical(factory)
