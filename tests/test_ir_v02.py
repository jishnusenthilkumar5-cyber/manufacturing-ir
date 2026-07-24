from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mir import Factory, MaterialFlow, ShiftWindow, dumps_canonical, loads_factory
from mir.passes import Severity, analyze_factory, validate_factory
from mir.sim import DispatchPolicy, Scenario, simulate
from mir.synth import FactoryBuilder, serial_line


def capacity(factory: Factory):
    return analyze_factory(factory).artifacts["capacity"]["analysis"]


def ratio_factory() -> Factory:
    builder = FactoryBuilder("ratio-assembly", "Ratio Assembly")
    builder.add_machine("assembler", "Assembler", "assembly", ["assemble"])
    builder.add_operation("assemble", "Assemble", "assemble", "assembler", 10)
    builder.add_flow("component-a", "part", to_op="assemble", units_per_batch=2)
    builder.add_flow("component-b", "part", to_op="assemble")
    builder.add_flow("outlet", "part", from_op="assemble")
    return builder.with_default_signals().build()


def dispatch_factory() -> Factory:
    builder = FactoryBuilder("dispatch", "Dispatch")
    builder.add_machine("shared", "Shared", "processor", ["fast", "slow"])
    builder.add_operation("fast", "Fast", "fast", "shared", 5, priority=1)
    builder.add_operation("slow", "Slow", "slow", "shared", 10, priority=10)
    builder.add_flow("fast-in", "fast-part", to_op="fast")
    builder.add_flow("slow-in", "slow-part", to_op="slow")
    builder.add_flow("fast-out", "fast-part", from_op="fast")
    builder.add_flow("slow-out", "slow-part", from_op="slow")
    return builder.with_default_signals().build()


def test_v01_fixture_loads_with_v02_defaults_and_writes_v02() -> None:
    source = Path(__file__).parent / "fixtures" / "ir-0.1-serial.json"
    factory = loads_factory(source)
    assert factory.schema_version == "0.2.0"
    assert all(not machine.calendar for machine in factory.machines)
    assert all(operation.priority == 0 for operation in factory.operations)
    assert all(flow.units_per_batch == 1 for flow in factory.flows)
    payload = json.loads(dumps_canonical(factory))
    assert payload["schema_version"] == "0.2.0"
    assert all("calendar" in machine for machine in payload["machines"])
    assert all("priority" in operation for operation in payload["operations"])
    assert all("units_per_batch" in flow for flow in payload["flows"])
    canonical = dumps_canonical(factory)
    assert dumps_canonical(loads_factory(canonical)) == canonical


def test_v01_fixture_retains_pinned_simulation_metrics() -> None:
    source = Path(__file__).parent / "fixtures" / "ir-0.1-serial.json"
    metrics = simulate(
        loads_factory(source),
        Scenario(horizon_s=1000, warmup_s=100, seed=17),
    ).replications[0]
    actual = metrics.to_dict()
    actual.pop("conservation_by_flow")
    for machine in actual["machine_metrics"].values():
        machine["state_fractions"].pop("offshift")
    assert actual == {
        "seed": 17,
        "measurement_s": 900.0,
        "throughput_by_outlet": {"outlet": 180.0},
        "throughput_units_per_hour": 180.0,
        "machine_metrics": {
            "machine-01": {
                "state_fractions": {
                    "busy": 0.5,
                    "idle": 0.0,
                    "blocked": 0.5,
                    "starved": 0.0,
                    "setup": 0.0,
                    "down": 0.0,
                }
            },
            "machine-02": {
                "state_fractions": {
                    "busy": 1.0,
                    "idle": 0.0,
                    "blocked": 0.0,
                    "starved": 0.0,
                    "setup": 0.0,
                    "down": 0.0,
                }
            },
        },
        "scrap_by_operation": {"operation-01": 0, "operation-02": 0},
        "cycles_by_operation": {"operation-01": 45, "operation-02": 45},
        "buffers": {
            "buffer-01": {
                "mean_occupancy": 2.0,
                "max_occupancy": 2,
                "ending_occupancy": 2,
            }
        },
        "input_units": 45,
        "output_units": 45,
        "starting_wip": 4,
        "ending_wip": 4,
        "conservation_error": 0,
    }
    assert set(metrics.conservation_by_flow.values()) == {0}


def test_two_to_one_assembly_uses_physical_quantities_and_conserves() -> None:
    metrics = simulate(
        ratio_factory(),
        Scenario(horizon_s=1000, warmup_s=100, seed=4),
    ).replications[0]
    assert metrics.input_units == 3 * metrics.output_units
    assert metrics.throughput_units_per_hour == 360
    assert metrics.conservation_error == 0
    assert set(metrics.conservation_by_flow.values()) == {0}


def test_capacity_propagates_two_to_one_flow_requirements() -> None:
    analysis = capacity(ratio_factory())
    assert analysis.exact
    assert analysis.operation_cycles_per_unit == {"assemble": 1.0}
    assert analysis.flow_units_per_output == {
        "component-a": 2.0,
        "component-b": 1.0,
        "outlet": 1.0,
    }
    assert analysis.throughput_upper_bound_units_per_hour == 360


def test_units_per_batch_rejects_nonpositive_values() -> None:
    with pytest.raises(ValidationError):
        MaterialFlow(id="flow", material="part", to_op="operation", units_per_batch=0)


def test_dispatch_policies_are_observable_and_deterministic() -> None:
    factory = dispatch_factory()
    results = {}
    for policy in DispatchPolicy:
        scenario = Scenario(horizon_s=100, seed=22, dispatch=policy)
        first = simulate(factory, scenario).replications[0]
        second = simulate(factory, scenario).replications[0]
        assert first.to_dict() == second.to_dict()
        results[policy] = first.cycles_by_operation
    assert results[DispatchPolicy.PRIORITY] == {"fast": 0, "slow": 10}
    assert results[DispatchPolicy.SHORTEST_CYCLE] == {"fast": 20, "slow": 0}
    assert results[DispatchPolicy.FIFO_FAIR]["fast"] > 0
    assert results[DispatchPolicy.FIFO_FAIR]["slow"] > 0


def test_dispatch_defaults_to_fifo_fair_and_rejects_unknown_policy() -> None:
    assert Scenario().dispatch is DispatchPolicy.FIFO_FAIR
    assert Scenario(dispatch="priority").dispatch is DispatchPolicy.PRIORITY
    with pytest.raises(ValidationError):
        Scenario(dispatch="unknown")


def test_half_shift_halves_simulated_and_analytic_throughput() -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    factory.machines[0].calendar = [
        ShiftWindow(day=day, start_s=0, end_s=43_200) for day in range(7)
    ]
    metrics = simulate(factory, Scenario(horizon_s=86_400, seed=1)).replications[0]
    assert metrics.throughput_units_per_hour == 180
    assert metrics.machine_metrics["machine-01"].state_fractions["offshift"] == 0.5
    assert sum(metrics.machine_metrics["machine-01"].state_fractions.values()) == 1
    assert capacity(factory).throughput_upper_bound_units_per_hour == 180


def test_offshift_pauses_and_resumes_in_progress_work() -> None:
    factory = serial_line(stations=1, cycle_times_s=[100])
    factory.machines[0].calendar = [
        ShiftWindow(day=0, start_s=0, end_s=50),
        ShiftWindow(day=0, start_s=100, end_s=150),
    ]
    metrics = simulate(factory, Scenario(horizon_s=160, seed=3)).replications[0]
    assert metrics.output_units == 1
    assert metrics.cycles_by_operation == {"operation-01": 1}
    assert metrics.machine_metrics["machine-01"].state_fractions["busy"] == 0.625
    assert metrics.machine_metrics["machine-01"].state_fractions["offshift"] == 0.375
    assert metrics.conservation_error == 0


def test_mir030_reports_invalid_and_overlapping_calendar_windows() -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    factory.machines[0].calendar = [
        ShiftWindow(day=7, start_s=0, end_s=10),
        ShiftWindow(day=0, start_s=0, end_s=20),
        ShiftWindow(day=0, start_s=10, end_s=30),
    ]
    diagnostics = [
        item
        for item in validate_factory(factory).diagnostics
        if item.code == "MIR030" and item.severity is Severity.ERROR
    ]
    assert len(diagnostics) == 2


def test_mir031_reports_alternative_ratio_and_capacity_conflicts() -> None:
    factory = ratio_factory()
    factory.flows[0].input_port = "component"
    factory.flows[1].input_port = "component"
    factory.flows.append(
        MaterialFlow(
            id="buffered-output",
            material="part",
            from_op="assemble",
            to_op="assemble",
            units_per_batch=2,
            buffer_capacity=1,
        )
    )
    diagnostics = [
        item
        for item in validate_factory(factory).diagnostics
        if item.code == "MIR031" and item.severity is Severity.ERROR
    ]
    assert len(diagnostics) >= 2


@pytest.mark.parametrize(
    "name",
    ["assembly-merge.json", "faster-alternative.json", "unbalanced-line.json"],
)
def test_committed_examples_are_canonical_v02(name: str) -> None:
    source = Path(__file__).parents[1] / "examples" / name
    text = source.read_text(encoding="utf-8")
    assert dumps_canonical(loads_factory(text)) == text
