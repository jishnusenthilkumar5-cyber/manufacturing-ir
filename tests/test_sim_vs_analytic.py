from __future__ import annotations

import pytest

from mir import Availability
from mir.passes import analyze_factory
from mir.sim import Scenario, simulate
from mir.synth import serial_line


@pytest.mark.parametrize(
    ("cycle_times", "expected_bottleneck"),
    [
        ([10, 20, 15], "machine-02"),
        ([30, 10, 20], "machine-01"),
        ([10, 15, 25, 12], "machine-03"),
    ],
)
def test_simulation_agrees_with_analytic_bound(
    cycle_times: list[float], expected_bottleneck: str
) -> None:
    factory = serial_line(
        stations=len(cycle_times),
        cycle_times_s=cycle_times,
        buffer_capacity=100,
    )
    analytic = analyze_factory(factory).artifacts["capacity"]["analysis"]
    simulated = simulate(
        factory,
        Scenario(horizon_s=100_000, warmup_s=10_000, seed=1),
    ).replications[0]
    utilization_bottleneck = max(
        simulated.machine_metrics,
        key=lambda machine_id: simulated.machine_metrics[machine_id].state_fractions[
            "busy"
        ],
    )
    assert analytic.bottleneck_machine == expected_bottleneck
    assert utilization_bottleneck == expected_bottleneck
    assert simulated.throughput_units_per_hour == pytest.approx(
        analytic.throughput_upper_bound_units_per_hour,
        rel=0.05,
    )


def test_stochastic_downtime_tracks_analytic_availability_bound() -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    factory.machines[0].availability = Availability(mtbf_s=900, mttr_s=100)
    analytic = analyze_factory(factory).artifacts["capacity"]["analysis"]
    simulated = simulate(
        factory,
        Scenario(horizon_s=1_000_000, warmup_s=20_000, seed=77),
    ).replications[0]
    assert simulated.throughput_units_per_hour == pytest.approx(
        analytic.throughput_upper_bound_units_per_hour,
        rel=0.05,
    )
