from __future__ import annotations

import json

import pytest

from mir import dumps_canonical
from mir.decide import DesignSpace, SweepError, sweep
from mir.sim import Scenario
from mir.synth import serial_line, unbalanced_line


def _bytes(value) -> bytes:
    return json.dumps(
        value.to_dict(),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def test_sweep_is_paired_deterministic_and_never_mutates_source() -> None:
    factory = unbalanced_line()
    before = dumps_canonical(factory)
    space = DesignSpace.from_dict(
        {"operations.operation-02.cycle_time_scale": [1.0, 0.4]}
    )
    scenario = Scenario(horizon_s=20_000, warmup_s=2_000, seed=17, replications=2)

    first = sweep(factory, space, scenario, max_workers=1)
    second = sweep(factory, space, scenario, max_workers=1)

    assert _bytes(first) == _bytes(second)
    assert dumps_canonical(factory) == before
    assert [point.index for point in first.points] == [0, 1]
    assert first.points[0].paired_delta_mean == 0
    assert first.points[0].paired_delta_stdev == 0
    assert first.points[0].delta_percent == 0
    assert first.points[1].throughput_mean > first.baseline.throughput_mean
    assert first.points[1].paired_delta_mean > 0
    assert first.points[1].delta_percent > 0
    assert first.points[1].bottleneck == "machine-03"


def test_sweep_returns_wip_scrap_stdev_and_analytic_bottleneck() -> None:
    factory = serial_line(stations=2, cycle_times_s=[10, 20], buffer_capacity=1)
    factory.operations[1].yield_fraction = 0.8
    result = sweep(
        factory,
        DesignSpace.from_dict({"flows.buffer-01.buffer_capacity": [0, 3]}),
        Scenario(horizon_s=10_000, warmup_s=1_000, seed=5, replications=3),
        max_workers=1,
    )

    assert result.baseline.throughput_mean > 0
    assert result.baseline.throughput_stdev >= 0
    assert result.baseline.ending_wip >= 0
    assert result.baseline.scrap > 0
    assert result.baseline.bottleneck == "machine-02"
    for point in result.points:
        assert point.ending_wip >= 0
        assert point.scrap > 0
        assert point.throughput_stdev >= 0
        assert point.bottleneck == "machine-02"


def test_sweep_order_and_bytes_match_across_worker_counts() -> None:
    factory = serial_line(stations=2, cycle_times_s=[8, 12], buffer_capacity=1)
    space = DesignSpace.from_dict(
        {
            "flows.buffer-01.buffer_capacity": [0, 2],
            "machines.machine-01.num_stations": [1, 2],
        }
    )
    scenario = Scenario(horizon_s=4_000, warmup_s=400, seed=41, replications=1)

    sequential = sweep(factory, space, scenario, max_workers=1)
    parallel = sweep(factory, space, scenario, max_workers=2)

    assert _bytes(sequential) == _bytes(parallel)
    assert [point.parameters for point in parallel.points] == [
        {
            "flows.buffer-01.buffer_capacity": 0,
            "machines.machine-01.num_stations": 1,
        },
        {
            "flows.buffer-01.buffer_capacity": 0,
            "machines.machine-01.num_stations": 2,
        },
        {
            "flows.buffer-01.buffer_capacity": 2,
            "machines.machine-01.num_stations": 1,
        },
        {
            "flows.buffer-01.buffer_capacity": 2,
            "machines.machine-01.num_stations": 2,
        },
    ]


def test_sweep_validates_context_before_starting_workers() -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    missing = DesignSpace.from_dict({"flows.missing.buffer_capacity": [1]})
    with pytest.raises(ValueError, match="missing"):
        sweep(factory, missing, max_workers=2)


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_sweep_rejects_invalid_worker_counts(value) -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    space = DesignSpace.from_dict(
        {"operations.operation-01.cycle_time_scale": [1.0]}
    )
    with pytest.raises(SweepError, match="max_workers"):
        sweep(factory, space, max_workers=value)
