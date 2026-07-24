from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from mir.core.model import Factory
from mir.sim import Scenario

from mir.decide.space import DesignSpace
from mir.decide.sweep import SweepMetrics, SweepPointResult, _scenario_dict, sweep


class RecommendationError(ValueError):
    pass


class Objective(StrEnum):
    THROUGHPUT = "throughput"
    THROUGHPUT_PER_WIP = "throughput_per_wip"


@dataclass(frozen=True, slots=True)
class Recommendation:
    rank: int
    score: float
    point: SweepPointResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "score": self.score,
            "point": self.point.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RecommendationResult:
    factory_id: str
    scenario: Scenario
    objective: Objective
    baseline_score: float
    baseline: SweepMetrics
    recommendations: tuple[Recommendation, ...]
    verdict: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "factory_id": self.factory_id,
            "scenario": _scenario_dict(self.scenario),
            "objective": self.objective.value,
            "baseline_score": self.baseline_score,
            "baseline": self.baseline.to_dict(),
            "recommendations": [item.to_dict() for item in self.recommendations],
            "verdict": self.verdict,
        }


def recommend(
    factory: Factory,
    space: DesignSpace,
    scenario: Scenario | None = None,
    *,
    objective: Objective | str = Objective.THROUGHPUT,
    top_k: int = 3,
    max_workers: int | None = None,
) -> RecommendationResult:
    selected_objective = _objective(objective)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise RecommendationError("top_k must be a positive integer")
    sweep_result = sweep(
        factory,
        space,
        scenario,
        max_workers=max_workers,
    )
    scored = [
        (_point_score(point, selected_objective), point)
        for point in sweep_result.points
    ]
    scored.sort(
        key=lambda item: (
            -item[0],
            -item[1].throughput_mean,
            item[1].ending_wip,
            item[1].index,
        )
    )
    recommendations = tuple(
        Recommendation(rank=rank, score=score, point=point)
        for rank, (score, point) in enumerate(scored[:top_k], start=1)
    )
    baseline_score = _metrics_score(sweep_result.baseline, selected_objective)
    return RecommendationResult(
        factory_id=sweep_result.factory_id,
        scenario=sweep_result.scenario,
        objective=selected_objective,
        baseline_score=baseline_score,
        baseline=sweep_result.baseline,
        recommendations=recommendations,
        verdict=_verdict(selected_objective, baseline_score, recommendations[0]),
    )


def _objective(value: Objective | str) -> Objective:
    try:
        return Objective(value)
    except (TypeError, ValueError) as exc:
        choices = ", ".join(item.value for item in Objective)
        raise RecommendationError(
            f"unknown objective {value!r}; expected one of: {choices}"
        ) from exc


def _point_score(point: SweepPointResult, objective: Objective) -> float:
    if objective is Objective.THROUGHPUT:
        return point.throughput_mean
    return point.throughput_mean / max(point.ending_wip, 1.0)


def _metrics_score(metrics: SweepMetrics, objective: Objective) -> float:
    if objective is Objective.THROUGHPUT:
        return metrics.throughput_mean
    return metrics.throughput_mean / max(metrics.ending_wip, 1.0)


def _verdict(
    objective: Objective,
    baseline_score: float,
    best: Recommendation,
) -> str:
    point = best.point
    label = objective.value.replace("_", " ")
    delta = best.score - baseline_score
    if math.isclose(delta, 0.0, rel_tol=0.0, abs_tol=1e-12):
        return (
            f"Design point {point.index} matches baseline {label} "
            f"at {best.score:.6g}."
        )
    direction = "improves" if delta > 0 else "trails"
    if baseline_score == 0:
        return (
            f"Design point {point.index} {direction} baseline {label}, "
            f"changing the score from 0 to {best.score:.6g}."
        )
    percent = abs(delta) * 100.0 / abs(baseline_score)
    comparison = "over" if delta > 0 else "below"
    return (
        f"Design point {point.index} {direction} baseline {label} by "
        f"{percent:.2f}% {comparison} baseline."
    )
