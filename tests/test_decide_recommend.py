from __future__ import annotations

import json

import pytest

from mir import dumps_canonical
from mir.decide import DesignSpace, Objective, RecommendationError, recommend
from mir.sim import Scenario
from mir.synth import serial_line, unbalanced_line


def test_recommendation_finds_planted_alternative_and_is_deterministic() -> None:
    factory = unbalanced_line()
    before = dumps_canonical(factory)
    space = DesignSpace.from_dict(
        {"operations.operation-02.cycle_time_scale": [1.0, 0.75, 0.4]}
    )
    scenario = Scenario(horizon_s=20_000, warmup_s=2_000, seed=11, replications=2)

    first = recommend(
        factory,
        space,
        scenario,
        objective=Objective.THROUGHPUT,
        top_k=2,
        max_workers=1,
    )
    second = recommend(
        factory,
        space,
        scenario,
        objective="throughput",
        top_k=2,
        max_workers=1,
    )

    assert first.to_dict() == second.to_dict()
    assert dumps_canonical(factory) == before
    assert [item.rank for item in first.recommendations] == [1, 2]
    assert first.recommendations[0].point.parameters == {
        "operations.operation-02.cycle_time_scale": 0.4
    }
    assert first.recommendations[0].score > first.baseline_score
    assert "improves baseline throughput" in first.verdict
    json.dumps(first.to_dict(), allow_nan=False)


def test_throughput_per_wip_uses_guarded_denominator_and_top_k() -> None:
    factory = serial_line(stations=2, cycle_times_s=[5, 10], buffer_capacity=1)
    space = DesignSpace.from_dict({"flows.buffer-01.buffer_capacity": [1, 4]})
    result = recommend(
        factory,
        space,
        Scenario(horizon_s=5_000, warmup_s=500, replications=1),
        objective="throughput_per_wip",
        top_k=10,
        max_workers=1,
    )

    assert result.objective is Objective.THROUGHPUT_PER_WIP
    assert len(result.recommendations) == 2
    assert result.baseline_score == result.baseline.throughput_mean / max(
        result.baseline.ending_wip, 1.0
    )
    for item in result.recommendations:
        assert item.score == item.point.throughput_mean / max(item.point.ending_wip, 1.0)


def test_recommendation_ties_follow_original_point_order() -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    space = DesignSpace.from_dict(
        {"operations.operation-01.cycle_time_scale": [1.0, 1.0, 1.0]}
    )
    result = recommend(
        factory,
        space,
        Scenario(horizon_s=3_600, warmup_s=600, replications=1),
        top_k=3,
        max_workers=1,
    )

    assert [item.point.index for item in result.recommendations] == [0, 1, 2]
    assert "matches baseline throughput" in result.verdict


@pytest.mark.parametrize("objective", ["unknown", "THROUGHPUT", 1, None])
def test_recommendation_rejects_invalid_objectives(objective) -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    space = DesignSpace.from_dict(
        {"operations.operation-01.cycle_time_scale": [1.0]}
    )
    with pytest.raises(RecommendationError, match="unknown objective"):
        recommend(factory, space, objective=objective, max_workers=1)


@pytest.mark.parametrize("top_k", [0, -1, True, 1.5])
def test_recommendation_rejects_invalid_top_k(top_k) -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    space = DesignSpace.from_dict(
        {"operations.operation-01.cycle_time_scale": [1.0]}
    )
    with pytest.raises(RecommendationError, match="top_k"):
        recommend(factory, space, top_k=top_k, max_workers=1)
