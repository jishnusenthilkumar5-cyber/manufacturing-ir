from __future__ import annotations

import statistics
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any

from mir.core.model import Factory
from mir.passes import analyze_factory
from mir.sim import ReplicationMetrics, Scenario, run_replication

from mir.decide.space import DesignPoint, DesignSpace


class SweepError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SweepMetrics:
    throughput_mean: float
    throughput_stdev: float
    ending_wip: float
    scrap: float
    bottleneck: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "throughput_mean": self.throughput_mean,
            "throughput_stdev": self.throughput_stdev,
            "ending_wip": self.ending_wip,
            "scrap": self.scrap,
            "bottleneck": self.bottleneck,
        }


@dataclass(frozen=True, slots=True)
class SweepPointResult:
    index: int
    parameters: dict[str, Any]
    throughput_mean: float
    throughput_stdev: float
    paired_delta_mean: float
    paired_delta_stdev: float
    delta_percent: float | None
    ending_wip: float
    scrap: float
    bottleneck: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "parameters": dict(self.parameters),
            "throughput_mean": self.throughput_mean,
            "throughput_stdev": self.throughput_stdev,
            "paired_delta_mean": self.paired_delta_mean,
            "paired_delta_stdev": self.paired_delta_stdev,
            "delta_percent": self.delta_percent,
            "ending_wip": self.ending_wip,
            "scrap": self.scrap,
            "bottleneck": self.bottleneck,
        }


@dataclass(frozen=True, slots=True)
class SweepResult:
    factory_id: str
    scenario: Scenario
    baseline: SweepMetrics
    points: tuple[SweepPointResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "factory_id": self.factory_id,
            "scenario": _scenario_dict(self.scenario),
            "baseline": self.baseline.to_dict(),
            "points": [point.to_dict() for point in self.points],
        }


@dataclass(frozen=True, slots=True)
class _SweepTask:
    factory: Factory
    point: DesignPoint
    scenario: Scenario


@dataclass(frozen=True, slots=True)
class _PointEvaluation:
    point: DesignPoint
    throughput: tuple[float, ...]
    ending_wip: float
    scrap: float
    bottleneck: str | None


def sweep(
    factory: Factory,
    space: DesignSpace,
    scenario: Scenario | None = None,
    *,
    max_workers: int | None = None,
) -> SweepResult:
    if not isinstance(factory, Factory):
        raise SweepError("factory must be a Factory")
    if not isinstance(space, DesignSpace):
        raise SweepError("space must be a DesignSpace")
    _validate_max_workers(max_workers)
    selected = scenario or Scenario(replications=10)
    if not isinstance(selected, Scenario):
        raise SweepError("scenario must be a Scenario")
    space.validate_against(factory)

    baseline_runs = _run_replications(factory, selected)
    baseline_throughput = tuple(
        replication.throughput_units_per_hour for replication in baseline_runs
    )
    baseline = _metrics(factory, baseline_runs)
    tasks = (
        _SweepTask(space.apply(factory, point), point, selected)
        for point in space.iter_points()
    )
    if max_workers == 1:
        evaluations = tuple(_evaluate_point(task) for task in tasks)
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            evaluations = tuple(executor.map(_evaluate_point, tasks))
    points = tuple(
        _point_result(evaluation, baseline_throughput, baseline.throughput_mean)
        for evaluation in evaluations
    )
    return SweepResult(
        factory_id=factory.meta.id,
        scenario=selected,
        baseline=baseline,
        points=points,
    )


def _evaluate_point(task: _SweepTask) -> _PointEvaluation:
    replications = _run_replications(task.factory, task.scenario)
    return _PointEvaluation(
        point=task.point,
        throughput=tuple(item.throughput_units_per_hour for item in replications),
        ending_wip=statistics.fmean(item.ending_wip for item in replications),
        scrap=statistics.fmean(
            sum(item.scrap_by_operation.values()) for item in replications
        ),
        bottleneck=_analytic_bottleneck(task.factory),
    )


def _run_replications(
    factory: Factory, scenario: Scenario
) -> tuple[ReplicationMetrics, ...]:
    return tuple(
        run_replication(factory, scenario, seed=scenario.seed + index)
        for index in range(scenario.replications)
    )


def _metrics(
    factory: Factory, replications: tuple[ReplicationMetrics, ...]
) -> SweepMetrics:
    throughput = [item.throughput_units_per_hour for item in replications]
    return SweepMetrics(
        throughput_mean=statistics.fmean(throughput),
        throughput_stdev=_stdev(throughput),
        ending_wip=statistics.fmean(item.ending_wip for item in replications),
        scrap=statistics.fmean(
            sum(item.scrap_by_operation.values()) for item in replications
        ),
        bottleneck=_analytic_bottleneck(factory),
    )


def _point_result(
    evaluation: _PointEvaluation,
    baseline_throughput: tuple[float, ...],
    baseline_mean: float,
) -> SweepPointResult:
    throughput = list(evaluation.throughput)
    paired_deltas = [
        after - before
        for before, after in zip(baseline_throughput, throughput, strict=True)
    ]
    throughput_mean = statistics.fmean(throughput)
    return SweepPointResult(
        index=evaluation.point.index,
        parameters=evaluation.point.parameters,
        throughput_mean=throughput_mean,
        throughput_stdev=_stdev(throughput),
        paired_delta_mean=statistics.fmean(paired_deltas),
        paired_delta_stdev=_stdev(paired_deltas),
        delta_percent=(
            (throughput_mean - baseline_mean) * 100.0 / baseline_mean
            if baseline_mean != 0
            else None
        ),
        ending_wip=evaluation.ending_wip,
        scrap=evaluation.scrap,
        bottleneck=evaluation.bottleneck,
    )


def _analytic_bottleneck(factory: Factory) -> str | None:
    analysis = analyze_factory(factory).artifacts["capacity"]["analysis"]
    return analysis.bottleneck_machine


def _stdev(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def _scenario_dict(scenario: Scenario) -> dict[str, Any]:
    result = scenario.model_dump(mode="json")
    result["arrival_rates_per_hour"] = dict(
        sorted(result["arrival_rates_per_hour"].items())
    )
    return result


def _validate_max_workers(max_workers: int | None) -> None:
    if max_workers is None:
        return
    if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
        raise SweepError("max_workers must be a positive integer or None")
