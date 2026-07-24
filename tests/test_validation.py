from __future__ import annotations

import copy

import pytest

from mir import (
    Availability,
    ConstantDistribution,
    Factory,
    FactoryMeta,
    Machine,
    MaterialFlow,
    Operation,
    Provenance,
    ProvenanceKind,
    Signal,
    SignalDataType,
    SignalSemantic,
)
from mir.passes import Severity, validate_factory


def clean_factory() -> Factory:
    return Factory(
        meta=FactoryMeta(
            id="clean-line",
            name="Clean Line",
            provenance=Provenance(kind=ProvenanceKind.SYNTHETIC),
        ),
        machines=[
            Machine(
                id="machine-01",
                name="Machine 01",
                machine_class="processor",
                capabilities=["process"],
            )
        ],
        operations=[
            Operation(
                id="process-01",
                name="Process 01",
                kind="process",
                machines=["machine-01"],
                cycle_time=ConstantDistribution(value_s=10),
            )
        ],
        flows=[
            MaterialFlow(id="raw-in", material="part", to_op="process-01"),
            MaterialFlow(id="part-out", material="part", from_op="process-01"),
        ],
        signals=[
            Signal(
                id="state",
                tag="M01_STATE",
                machine="machine-01",
                dtype=SignalDataType.ENUM,
                semantic=SignalSemantic.MACHINE_STATE,
                enum_states={"idle": 0, "run": 1},
            ),
            Signal(
                id="count",
                tag="M01_COUNT",
                machine="machine-01",
                dtype=SignalDataType.INT,
                semantic=SignalSemantic.CYCLE_COUNT,
            ),
        ],
    )


def codes(factory: Factory, severity: Severity | None = None) -> list[str]:
    return [
        item.code
        for item in validate_factory(factory).diagnostics
        if severity is None or item.severity is severity
    ]


def test_clean_factory_has_no_diagnostics() -> None:
    assert validate_factory(clean_factory()).diagnostics == ()


def test_mir001_duplicate_id() -> None:
    factory = clean_factory()
    factory.machines.append(copy.deepcopy(factory.machines[0]))
    assert "MIR001" in codes(factory)


def test_mir002_unknown_operation_machine() -> None:
    factory = clean_factory()
    factory.operations[0].machines = ["missing"]
    assert "MIR002" in codes(factory)


def test_mir003_unknown_flow_operation() -> None:
    factory = clean_factory()
    factory.flows[0].to_op = "missing"
    assert "MIR003" in codes(factory)


def test_mir004_endpointless_flow() -> None:
    factory = clean_factory()
    factory.flows[0].to_op = None
    assert "MIR004" in codes(factory)


def test_mir005_operation_without_machine() -> None:
    factory = clean_factory()
    factory.operations[0].machines = []
    assert "MIR005" in codes(factory)


def test_mir006_unknown_signal_machine() -> None:
    factory = clean_factory()
    factory.signals[0].machine = "missing"
    assert "MIR006" in codes(factory)


def test_mir007_duplicate_signal_tag() -> None:
    factory = clean_factory()
    factory.signals.append(
        Signal(
            id="second-state",
            tag="M01_STATE",
            machine="machine-01",
            dtype=SignalDataType.ENUM,
            semantic=SignalSemantic.MACHINE_STATE,
            enum_states={"idle": 0},
        )
    )
    assert "MIR007" in codes(factory)


def test_mir010_orphan_operation() -> None:
    factory = clean_factory()
    factory.flows = []
    assert "MIR010" in codes(factory)


def test_mir011_unreachable_operation() -> None:
    factory = clean_factory()
    factory.flows = [MaterialFlow(id="out", material="part", from_op="process-01")]
    assert "MIR011" in codes(factory)


def test_mir012_unbuffered_cycle_is_error() -> None:
    factory = clean_factory()
    factory.flows.append(
        MaterialFlow(
            id="rework",
            material="part",
            from_op="process-01",
            to_op="process-01",
            buffer_capacity=0,
        )
    )
    assert "MIR012" in codes(factory, Severity.ERROR)


def test_mir012_buffered_cycle_is_info() -> None:
    factory = clean_factory()
    factory.flows.append(
        MaterialFlow(
            id="rework",
            material="part",
            from_op="process-01",
            to_op="process-01",
            buffer_capacity=1,
        )
    )
    assert "MIR012" in codes(factory, Severity.INFO)


def test_mir020_machine_capability_mismatch() -> None:
    factory = clean_factory()
    factory.machines[0].capabilities = ["weld"]
    assert "MIR020" in codes(factory)


def test_mir021_unassigned_machine() -> None:
    factory = clean_factory()
    factory.machines.append(
        Machine(id="spare", name="Spare", machine_class="processor", capabilities=["process"])
    )
    assert "MIR021" in codes(factory)


def test_mir022_missing_machine_states() -> None:
    factory = clean_factory()
    factory.signals[0].enum_states = None
    assert "MIR022" in codes(factory)


def test_mir023_count_signal_non_integer() -> None:
    factory = clean_factory()
    factory.signals[1].dtype = SignalDataType.FLOAT
    assert "MIR023" in codes(factory)


def test_mir024_unknown_measurement_unit() -> None:
    factory = clean_factory()
    factory.signals.append(
        Signal(
            id="measurement",
            tag="M01_X",
            machine="machine-01",
            dtype=SignalDataType.FLOAT,
            semantic=SignalSemantic.MEASUREMENT,
            unit="furlong/fortnight",
        )
    )
    assert "MIR024" in codes(factory)


@pytest.mark.parametrize(("mtbf", "mttr"), [(0, 10), (10, -1)])
def test_mir025_invalid_availability(mtbf: float, mttr: float) -> None:
    factory = clean_factory()
    factory.machines[0].availability = Availability(mtbf_s=mtbf, mttr_s=mttr)
    assert "MIR025" in codes(factory)


def test_mir026_unmatched_boundary_material() -> None:
    factory = clean_factory()
    factory.flows[0].material = "unmatched"
    assert "MIR026" in codes(factory)
