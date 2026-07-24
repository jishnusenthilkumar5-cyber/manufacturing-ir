from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from mir.core.model import Factory
from mir.passes import analyze_factory
from mir.sim import ReplicationMetrics, Scenario, run_replication

from mir.decide.space import DesignPoint, ParameterPath, apply_design_point
from mir.decide.sweep import SweepMetrics, _scenario_dict


class SensitivityError(ValueError):
    pass


class SensitivityKind(StrEnum):
    CYCLE_TIME = "cycle_time"
    SETUP_TIME = "setup_time"
    AVAILABILITY_MTBF = "availability_mtbf"
    AVAILABILITY_MTTR = "availability_mttr"
    BUFFER_CAPACITY = "buffer_capacity"


@dataclass(frozen=True, slots=True)
class SensitivityEntry:
    rank: int
    path: str
    kind: SensitivityKind
    machine_ids: tuple[str, ...]
    baseline_value: float | int
    lower_value: float | int
    upper_value: float | int
    lower_throughput_mean: float
    upper_throughput_mean: float
    lower_paired_delta: float
    upper_paired_delta: float
    absolute_impact: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "path": self.path,
            "kind": self.kind.value,
            "machine_ids": list(self.machine_ids),
            "baseline_value": self.baseline_value,
            "lower_value": self.lower_value,
            "upper_value": self.upper_value,
            "lower_throughput_mean": self.lower_throughput_mean,
            "upper_throughput_mean": self.upper_throughput_mean,
            "lower_paired_delta": self.lower_paired_delta,
            "upper_paired_delta": self.upper_paired_delta,
            "absolute_impact": self.absolute_impact,
        }


@dataclass(frozen=True, slots=True)
class SensitivityResult:
    factory_id: str
    scenario: Scenario
    percent: float
    baseline: SweepMetrics
    entries: tuple[SensitivityEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "factory_id": self.factory_id,
            "scenario": _scenario_dict(self.scenario),
            "percent": self.percent,
            "baseline": self.baseline.to_dict(),
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True, slots=True)
class _Candidate:
    path: str
    kind: SensitivityKind
    entity_id: str
    machine_ids: tuple[str, ...]
    baseline_value: float | int
    lower_value: float | int
    upper_value: float | int


def sensitivity(
    factory: Factory,
    scenario: Scenario | None = None,
    *,
    percent: float = 10.0,
) -> SensitivityResult:
    if not isinstance(factory, Factory):
        raise SensitivityError("factory must be a Factory")
    selected = scenario or Scenario(replications=10)
    if not isinstance(selected, Scenario):
        raise SensitivityError("scenario must be a Scenario")
    selected_percent = _percent(percent)
    fraction = selected_percent / 100.0
    baseline_runs = _run_replications(factory, selected)
    baseline_throughput = tuple(
        item.throughput_units_per_hour for item in baseline_runs
    )
    baseline = _baseline_metrics(factory, baseline_runs)
    entries: list[SensitivityEntry] = []
    for candidate in _candidates(factory, fraction):
        lower_throughput = _evaluate_value(
            factory,
            selected,
            candidate,
            candidate.lower_value,
            baseline_throughput,
        )
        if candidate.upper_value == candidate.lower_value:
            upper_throughput = lower_throughput
        else:
            upper_throughput = _evaluate_value(
                factory,
                selected,
                candidate,
                candidate.upper_value,
                baseline_throughput,
            )
        lower_mean = statistics.fmean(lower_throughput)
        upper_mean = statistics.fmean(upper_throughput)
        lower_delta = _paired_delta(baseline_throughput, lower_throughput)
        upper_delta = _paired_delta(baseline_throughput, upper_throughput)
        entries.append(
            SensitivityEntry(
                rank=0,
                path=candidate.path,
                kind=candidate.kind,
                machine_ids=candidate.machine_ids,
                baseline_value=candidate.baseline_value,
                lower_value=candidate.lower_value,
                upper_value=candidate.upper_value,
                lower_throughput_mean=lower_mean,
                upper_throughput_mean=upper_mean,
                lower_paired_delta=lower_delta,
                upper_paired_delta=upper_delta,
                absolute_impact=max(abs(lower_delta), abs(upper_delta)),
            )
        )
    entries.sort(key=lambda item: (-item.absolute_impact, item.path))
    ranked = tuple(replace(entry, rank=index) for index, entry in enumerate(entries, 1))
    return SensitivityResult(
        factory_id=factory.meta.id,
        scenario=selected,
        percent=selected_percent,
        baseline=baseline,
        entries=ranked,
    )


def _candidates(factory: Factory, fraction: float) -> tuple[_Candidate, ...]:
    result: list[_Candidate] = []
    for operation in sorted(factory.operations, key=lambda item: item.id):
        result.append(
            _Candidate(
                path=f"operations.{operation.id}.cycle_time_scale",
                kind=SensitivityKind.CYCLE_TIME,
                entity_id=operation.id,
                machine_ids=tuple(sorted(set(operation.machines))),
                baseline_value=1.0,
                lower_value=1.0 - fraction,
                upper_value=1.0 + fraction,
            )
        )
    for machine in sorted(factory.machines, key=lambda item: item.id):
        setup = machine.setup_time_s
        result.append(
            _Candidate(
                path=f"machines.{machine.id}.setup_time_s",
                kind=SensitivityKind.SETUP_TIME,
                entity_id=machine.id,
                machine_ids=(machine.id,),
                baseline_value=setup,
                lower_value=setup * (1.0 - fraction),
                upper_value=setup * (1.0 + fraction),
            )
        )
        if machine.availability is not None:
            mtbf = machine.availability.mtbf_s
            mttr = machine.availability.mttr_s
            result.extend(
                [
                    _Candidate(
                        path=f"machines.{machine.id}.availability.mtbf_s",
                        kind=SensitivityKind.AVAILABILITY_MTBF,
                        entity_id=machine.id,
                        machine_ids=(machine.id,),
                        baseline_value=mtbf,
                        lower_value=mtbf * (1.0 - fraction),
                        upper_value=mtbf * (1.0 + fraction),
                    ),
                    _Candidate(
                        path=f"machines.{machine.id}.availability.mttr_s",
                        kind=SensitivityKind.AVAILABILITY_MTTR,
                        entity_id=machine.id,
                        machine_ids=(machine.id,),
                        baseline_value=mttr,
                        lower_value=mttr * (1.0 - fraction),
                        upper_value=mttr * (1.0 + fraction),
                    ),
                ]
            )
    for flow in sorted(factory.flows, key=lambda item: item.id):
        capacity = flow.buffer_capacity
        if capacity is None:
            continue
        result.append(
            _Candidate(
                path=f"flows.{flow.id}.buffer_capacity",
                kind=SensitivityKind.BUFFER_CAPACITY,
                entity_id=flow.id,
                machine_ids=_flow_machine_ids(factory, flow.from_op, flow.to_op),
                baseline_value=capacity,
                lower_value=max(0, math.floor(capacity * (1.0 - fraction))),
                upper_value=max(0, math.ceil(capacity * (1.0 + fraction))),
            )
        )
    result.sort(key=lambda item: item.path)
    return tuple(result)


def _flow_machine_ids(
    factory: Factory, from_op: str | None, to_op: str | None
) -> tuple[str, ...]:
    operations = factory.operation_map()
    machine_ids: set[str] = set()
    for operation_id in (from_op, to_op):
        operation = operations.get(operation_id or "")
        if operation is not None:
            machine_ids.update(operation.machines)
    return tuple(sorted(machine_ids))


def _evaluate_value(
    factory: Factory,
    scenario: Scenario,
    candidate: _Candidate,
    value: float | int,
    baseline_throughput: tuple[float, ...],
) -> tuple[float, ...]:
    if value == candidate.baseline_value:
        return baseline_throughput
    variant = _mutate(factory, candidate, value)
    return tuple(
        item.throughput_units_per_hour for item in _run_replications(variant, scenario)
    )


def _mutate(factory: Factory, candidate: _Candidate, value: float | int) -> Factory:
    if candidate.kind is SensitivityKind.SETUP_TIME:
        result = factory.model_copy(deep=True)
        matches = [
            machine for machine in result.machines if machine.id == candidate.entity_id
        ]
        if len(matches) != 1:
            raise SensitivityError(
                f"expected exactly one machine {candidate.entity_id!r}; found {len(matches)}"
            )
        matches[0].setup_time_s = float(value)
        return result
    parameter = ParameterPath.parse(candidate.path)
    normalized = parameter.normalize_value(value)
    point = DesignPoint(index=0, assignments=((parameter, normalized),))
    return apply_design_point(factory, point)


def _run_replications(
    factory: Factory, scenario: Scenario
) -> tuple[ReplicationMetrics, ...]:
    return tuple(
        run_replication(factory, scenario, seed=scenario.seed + index)
        for index in range(scenario.replications)
    )


def _baseline_metrics(
    factory: Factory, replications: tuple[ReplicationMetrics, ...]
) -> SweepMetrics:
    throughput = [item.throughput_units_per_hour for item in replications]
    analysis = analyze_factory(factory).artifacts["capacity"]["analysis"]
    return SweepMetrics(
        throughput_mean=statistics.fmean(throughput),
        throughput_stdev=statistics.stdev(throughput) if len(throughput) > 1 else 0.0,
        ending_wip=statistics.fmean(item.ending_wip for item in replications),
        scrap=statistics.fmean(
            sum(item.scrap_by_operation.values()) for item in replications
        ),
        bottleneck=analysis.bottleneck_machine,
    )


def _paired_delta(
    baseline: tuple[float, ...], variant: tuple[float, ...]
) -> float:
    return statistics.fmean(
        after - before for before, after in zip(baseline, variant, strict=True)
    )


def _percent(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SensitivityError(
            "percent must be a finite number greater than 0 and less than 100"
        )
    result = float(value)
    if not math.isfinite(result) or not 0 < result < 100:
        raise SensitivityError(
            "percent must be a finite number greater than 0 and less than 100"
        )
    return result
