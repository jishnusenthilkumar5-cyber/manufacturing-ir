from __future__ import annotations

from pathlib import Path

import pytest

from mir import (
    Availability,
    ConstantDistribution,
    ExponentialDistribution,
    Factory,
    FactoryMeta,
    Machine,
    MaterialFlow,
    NormalDistribution,
    Operation,
    Provenance,
    ProvenanceKind,
    Signal,
    SignalDataType,
    SignalSemantic,
    UniformDistribution,
)
from mir.dsl import dumps_mir, loads_mir, read_mir, write_mir
from mir.synth import CATALOG


def rich_factory() -> Factory:
    machines = [
        Machine(
            id="m-constant",
            name="Découpe #1",
            machine_class="laser cutter",
            capabilities=["constant"],
            num_stations=2,
            setup_time_s=7.5,
            availability=Availability(mtbf_s=5_400.0, mttr_s=180.0),
            attrs={
                "active": True,
                "limits": [None, -2, 3.5, {"note": "温度 # nominal"}],
            },
        ),
        Machine(
            id="m-exponential",
            name="Exponential",
            machine_class="processor",
            capabilities=["exponential"],
        ),
        Machine(
            id="m-normal",
            name="Normal",
            machine_class="processor",
            capabilities=["normal"],
        ),
        Machine(
            id="m-uniform",
            name="Uniform",
            machine_class="processor",
            capabilities=["uniform"],
        ),
    ]
    operations = [
        Operation(
            id="op-constant",
            name="Découper",
            kind="constant",
            machines=["m-constant"],
            cycle_time=ConstantDistribution(value_s=12.5),
            yield_fraction=0.975,
            batch_size=3,
            attrs={"recipe": {"passes": 2, "label": "α"}},
        ),
        Operation(
            id="op-exponential",
            name="Exponential",
            kind="exponential",
            machines=["m-exponential"],
            cycle_time=ExponentialDistribution(mean_s=9.25),
        ),
        Operation(
            id="op-normal",
            name="Normal",
            kind="normal",
            machines=["m-normal"],
            cycle_time=NormalDistribution(mean_s=20.0, std_s=1.75),
        ),
        Operation(
            id="op-uniform",
            name="Uniform",
            kind="uniform",
            machines=["m-uniform"],
            cycle_time=UniformDistribution(low_s=4.0, high_s=8.0),
        ),
    ]
    flows: list[MaterialFlow] = []
    for operation in operations:
        suffix = operation.id.removeprefix("op-")
        flows.extend(
            [
                MaterialFlow(
                    id=f"in-{suffix}",
                    material=f"part-{suffix}",
                    to_op=operation.id,
                    input_port="feed" if suffix == "constant" else None,
                    buffer_capacity=0 if suffix == "constant" else None,
                    transport_time_s=2.25 if suffix == "constant" else 0.0,
                ),
                MaterialFlow(
                    id=f"out-{suffix}",
                    material=f"part-{suffix}",
                    from_op=operation.id,
                    routing_weight=0.25 if suffix == "constant" else 1.0,
                ),
            ]
        )
    signals = [
        Signal(
            id="state",
            tag="ÉTAT_MACHINE",
            machine="m-constant",
            dtype=SignalDataType.ENUM,
            semantic=SignalSemantic.MACHINE_STATE,
            enum_states={"arrêt": 0, "marche": 1},
        ),
        Signal(
            id="temperature",
            tag="TEMP_温度",
            machine="m-constant",
            dtype=SignalDataType.FLOAT,
            semantic=SignalSemantic.MEASUREMENT,
            unit="degC",
        ),
    ]
    return Factory(
        meta=FactoryMeta(
            id="rich-line",
            name="Línea de producción 東京",
            description="Every v0.1 field; # remains text.",
            provenance=Provenance(
                kind=ProvenanceKind.RECONSTRUCTED,
                source="測定/line-a",
            ),
        ),
        machines=machines,
        operations=operations,
        flows=sorted(flows, key=lambda item: item.id),
        signals=signals,
    )


@pytest.mark.parametrize("catalog_name", sorted(CATALOG))
def test_catalog_models_round_trip(catalog_name: str) -> None:
    factory = CATALOG[catalog_name]()
    rendered = dumps_mir(factory)
    loaded = loads_mir(rendered, source_name=f"{catalog_name}.mir")
    assert loaded == factory
    assert dumps_mir(loaded) == rendered
    assert rendered.endswith("\n")


def test_every_v01_field_and_distribution_round_trips() -> None:
    factory = rich_factory()
    rendered = dumps_mir(factory)
    loaded = loads_mir(rendered)
    assert loaded == factory
    assert "cycle = constant(12.5s)" in rendered
    assert "cycle = uniform(4.0s, 8.0s)" in rendered
    assert "cycle = normal(20.0s, 1.75s)" in rendered
    assert "cycle = exponential(9.25s)" in rendered
    assert "availability(mtbf=5400.0s, mttr=180.0s)" in rendered
    assert '"温度 # nominal"' in rendered


def test_entity_input_order_does_not_change_canonical_output() -> None:
    factory = rich_factory()
    reversed_factory = factory.model_copy(deep=True)
    reversed_factory.machines.reverse()
    reversed_factory.operations.reverse()
    reversed_factory.flows.reverse()
    reversed_factory.signals.reverse()
    assert dumps_mir(reversed_factory) == dumps_mir(factory)


def test_compact_m3_syntax_comments_and_duration_units() -> None:
    text = '''# authored source
factory "line-01" name "Line # 01" {
  machine m1 { class=cnc capabilities=[mill] stations=2 setup=0.5min availability(mtbf=1h mttr=2min) }
  operation op1 { kind=mill on=[m1] cycle=normal(0.5min, 2s) yield=0.98 }
  flow inlet  { part -> op1 cap=10 } # inline comment
  flow outlet { part op1 -> transport=1min }
}
'''
    factory = loads_mir(text)
    assert factory.meta.name == "Line # 01"
    assert factory.machines[0].name == "m1"
    assert factory.machines[0].setup_time_s == 30.0
    assert factory.machines[0].availability == Availability(
        mtbf_s=3_600.0,
        mttr_s=120.0,
    )
    assert factory.operations[0].cycle_time == NormalDistribution(mean_s=30.0, std_s=2.0)
    assert factory.flows[1].transport_time_s == 60.0
    assert loads_mir(dumps_mir(factory)) == factory


def test_flow_arrow_does_not_require_surrounding_whitespace() -> None:
    text = '''factory line name "Line" {
  machine m1 { class=processor capabilities=[process] }
  operation op1 { kind=process on=[m1] cycle=10s }
  flow input { part->op1 }
  flow output { part op1-> }
}
'''
    factory = loads_mir(text)
    assert factory.flows[0] == MaterialFlow(id="input", material="part", to_op="op1")
    assert factory.flows[1] == MaterialFlow(id="output", material="part", from_op="op1")


def test_utf8_file_helpers(tmp_path: Path) -> None:
    factory = rich_factory()
    path = tmp_path / "línea.mir"
    assert write_mir(factory, path) == path
    assert path.read_text(encoding="utf-8") == dumps_mir(factory)
    assert read_mir(path) == factory
