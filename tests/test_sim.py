from __future__ import annotations

import json

import pytest

from mir import Availability
from mir.sim import Scenario, SimulationError, simulate
from mir.synth import CATALOG, FactoryBuilder, rework_loop, serial_line


def test_constant_single_station_has_exact_throughput_and_conservation() -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    metrics = simulate(
        factory,
        Scenario(horizon_s=3600, warmup_s=600, seed=42),
    ).replications[0]
    assert metrics.throughput_units_per_hour == 360
    assert metrics.conservation_error == 0
    assert metrics.machine_metrics["machine-01"].state_fractions["busy"] == 1


def test_same_seed_is_byte_for_byte_reproducible() -> None:
    factory = serial_line(stations=2, cycle_times_s=[7, 11], buffer_capacity=2)
    scenario = Scenario(horizon_s=7200, warmup_s=600, seed=1847, replications=3)
    first = json.dumps(
        simulate(factory, scenario).to_dict(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    second = json.dumps(
        simulate(factory, scenario).to_dict(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert first == second


def test_zero_capacity_flow_performs_synchronous_handoff() -> None:
    factory = serial_line(stations=2, cycle_times_s=[5, 20], buffer_capacity=0)
    metrics = simulate(factory, Scenario(horizon_s=7200, warmup_s=600)).replications[0]
    assert metrics.throughput_units_per_hour == pytest.approx(180, abs=1)
    assert metrics.machine_metrics["machine-01"].state_fractions["blocked"] > 0.7
    assert "buffer-01" not in metrics.buffers
    assert metrics.conservation_error == 0


def test_finite_buffer_causes_upstream_blocking() -> None:
    factory = serial_line(stations=2, cycle_times_s=[5, 20], buffer_capacity=2)
    metrics = simulate(factory, Scenario(horizon_s=7200, warmup_s=600)).replications[0]
    assert metrics.buffers["buffer-01"].max_occupancy == 2
    assert metrics.machine_metrics["machine-01"].state_fractions["blocked"] > 0.6
    assert metrics.conservation_error == 0


def test_scrap_is_accounted_without_breaking_conservation() -> None:
    factory = serial_line(stations=1, cycle_times_s=[2])
    factory.operations[0].yield_fraction = 0.75
    metrics = simulate(factory, Scenario(horizon_s=10_000, seed=9)).replications[0]
    assert metrics.scrap_by_operation["operation-01"] > 0
    assert metrics.output_units + sum(metrics.scrap_by_operation.values()) > 0
    assert metrics.conservation_error == 0


def test_downtime_lowers_throughput_by_availability_fraction() -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    factory.machines[0].availability = Availability(mtbf_s=900, mttr_s=100)
    metrics = simulate(
        factory,
        Scenario(horizon_s=500_000, warmup_s=20_000, seed=7),
    ).replications[0]
    assert metrics.throughput_units_per_hour == pytest.approx(324, rel=0.05)
    assert metrics.machine_metrics["machine-01"].state_fractions["down"] == pytest.approx(
        0.1, abs=0.03
    )
    assert metrics.conservation_error == 0


def test_arrival_rate_can_starve_a_faster_machine() -> None:
    factory = serial_line(stations=1, cycle_times_s=[2])
    metrics = simulate(
        factory,
        Scenario(
            horizon_s=20_000,
            warmup_s=2_000,
            arrival_rates_per_hour={"inlet": 120},
        ),
    ).replications[0]
    assert metrics.throughput_units_per_hour == pytest.approx(120, abs=1)
    assert metrics.machine_metrics["machine-01"].state_fractions["starved"] > 0.9
    assert metrics.conservation_error == 0


def test_transport_time_holds_output_before_transfer() -> None:
    factory = serial_line(stations=1, cycle_times_s=[5])
    factory.flows[-1].transport_time_s = 5
    metrics = simulate(factory, Scenario(horizon_s=3600, warmup_s=600)).replications[0]
    assert metrics.throughput_units_per_hour == 360
    assert metrics.machine_metrics["machine-01"].state_fractions["blocked"] == 0.5


def test_setup_time_is_paid_when_shared_machine_switches_kind() -> None:
    builder = FactoryBuilder("shared", "Shared Machine")
    builder.add_machine(
        "machine",
        "Machine",
        "flexible",
        ["first", "second"],
        setup_time_s=5,
    )
    builder.add_operation("first", "First", "first", "machine", 5)
    builder.add_operation("second", "Second", "second", "machine", 5)
    builder.add_flow("inlet", "part", to_op="first")
    builder.add_flow("middle", "part", from_op="first", to_op="second", buffer_capacity=2)
    builder.add_flow("outlet", "part", from_op="second")
    factory = builder.with_default_signals().build()
    metrics = simulate(factory, Scenario(horizon_s=20_000, warmup_s=2_000)).replications[0]
    assert metrics.machine_metrics["machine"].state_fractions["setup"] > 0.45
    assert metrics.throughput_units_per_hour == pytest.approx(180, abs=1)


def test_weighted_rework_loop_executes_and_conserves_material() -> None:
    factory = rework_loop(p_rework=0.2)
    metrics = simulate(
        factory,
        Scenario(horizon_s=100_000, warmup_s=10_000, seed=1),
    ).replications[0]
    assert metrics.throughput_units_per_hour == pytest.approx(144, rel=0.05)
    assert metrics.cycles_by_operation["process"] > metrics.output_units
    assert metrics.conservation_error == 0


@pytest.mark.parametrize("catalog_name", sorted(CATALOG))
def test_catalog_models_conserve_material(catalog_name: str) -> None:
    metrics = simulate(
        CATALOG[catalog_name](),
        Scenario(horizon_s=20_000, warmup_s=2_000, seed=91),
    ).replications[0]
    assert metrics.conservation_error == 0
    assert set(metrics.conservation_by_flow.values()) == {0}


def test_unknown_arrival_flow_is_rejected() -> None:
    factory = serial_line(stations=1, cycle_times_s=[5])
    with pytest.raises(SimulationError, match="non-inlet"):
        simulate(
            factory,
            Scenario(horizon_s=100, arrival_rates_per_hour={"missing": 1}),
        )


def test_state_fractions_sum_to_one() -> None:
    factory = serial_line(stations=3, cycle_times_s=[5, 10, 7], buffer_capacity=1)
    metrics = simulate(factory, Scenario(horizon_s=5000, warmup_s=500)).replications[0]
    for machine in metrics.machine_metrics.values():
        assert sum(machine.state_fractions.values()) == pytest.approx(1)
