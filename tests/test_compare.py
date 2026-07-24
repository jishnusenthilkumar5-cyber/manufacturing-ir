from __future__ import annotations

import pytest

from mir.compare import compare_factories
from mir.sim import Scenario
from mir.synth import serial_line


def test_identical_factories_have_zero_delta() -> None:
    factory = serial_line(stations=2, cycle_times_s=[10, 20])
    report = compare_factories(
        factory,
        factory.model_copy(deep=True),
        Scenario(horizon_s=20_000, warmup_s=2_000, seed=3, replications=3),
    )
    assert report.delta_percent == 0
    assert report.paired_delta_mean == 0
    assert "no material throughput change" in report.verdict


def test_faster_planted_alternative_moves_bottleneck() -> None:
    baseline = serial_line(stations=3, cycle_times_s=[20, 40, 30])
    variant = baseline.model_copy(deep=True)
    variant.meta.id = "faster-alternative"
    variant.operations[1].cycle_time = variant.operations[1].cycle_time.model_copy(
        update={"value_s": 15}
    )
    report = compare_factories(
        baseline,
        variant,
        Scenario(horizon_s=50_000, warmup_s=5_000, seed=10, replications=4),
    )
    assert report.delta_percent == pytest.approx(100 / 3, rel=0.02)
    assert report.bottleneck_before == "machine-02"
    assert report.bottleneck_after == "machine-03"
    assert "raises line throughput" in report.verdict
    assert "moves the bottleneck from machine-02 to machine-03" in report.verdict
    assert "# Capacity comparison" in report.to_markdown()


def test_slower_alternative_is_not_recommended_as_an_improvement() -> None:
    baseline = serial_line(stations=1, cycle_times_s=[10])
    variant = serial_line(
        stations=1,
        cycle_times_s=[20],
        factory_id="slow",
        name="Slow",
    )
    report = compare_factories(
        baseline,
        variant,
        Scenario(horizon_s=10_000, warmup_s=1_000, replications=2),
    )
    assert report.delta_percent == pytest.approx(-50, abs=0.2)
    assert "lowers line throughput" in report.verdict
