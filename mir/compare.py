from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from mir.core.model import Factory
from mir.passes import analyze_factory
from mir.passes.capacity import CapacityAnalysis
from mir.sim import ReplicationMetrics, Scenario, run_replication


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    baseline_id: str
    variant_id: str
    scenario: Scenario
    baseline_throughput_mean: float
    baseline_throughput_stdev: float
    variant_throughput_mean: float
    variant_throughput_stdev: float
    paired_delta_mean: float
    paired_delta_stdev: float
    delta_percent: float | None
    bottleneck_before: str | None
    bottleneck_after: str | None
    utilization_before: dict[str, float]
    utilization_after: dict[str, float]
    ending_wip_before: float
    ending_wip_after: float
    scrap_before: float
    scrap_after: float
    verdict: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_id": self.baseline_id,
            "variant_id": self.variant_id,
            "scenario": self.scenario.model_dump(mode="json"),
            "throughput": {
                "baseline_mean": self.baseline_throughput_mean,
                "baseline_stdev": self.baseline_throughput_stdev,
                "variant_mean": self.variant_throughput_mean,
                "variant_stdev": self.variant_throughput_stdev,
                "paired_delta_mean": self.paired_delta_mean,
                "paired_delta_stdev": self.paired_delta_stdev,
                "delta_percent": self.delta_percent,
            },
            "bottleneck": {
                "before": self.bottleneck_before,
                "after": self.bottleneck_after,
            },
            "utilization": {
                "before": dict(self.utilization_before),
                "after": dict(self.utilization_after),
            },
            "ending_wip": {
                "before": self.ending_wip_before,
                "after": self.ending_wip_after,
            },
            "scrap": {"before": self.scrap_before, "after": self.scrap_after},
            "verdict": self.verdict,
        }

    def to_markdown(self) -> str:
        delta = "n/a" if self.delta_percent is None else f"{self.delta_percent:+.2f}%"
        machine_ids = sorted(set(self.utilization_before) | set(self.utilization_after))
        rows = [
            "# Capacity comparison",
            "",
            self.verdict,
            "",
            "| Metric | Baseline | Variant | Delta |",
            "|---|---:|---:|---:|",
            (
                "| Throughput (units/h) | "
                f"{self.baseline_throughput_mean:.2f} ± {self.baseline_throughput_stdev:.2f} | "
                f"{self.variant_throughput_mean:.2f} ± {self.variant_throughput_stdev:.2f} | {delta} |"
            ),
            f"| Bottleneck | {self.bottleneck_before or 'n/a'} | {self.bottleneck_after or 'n/a'} | |",
            f"| Ending WIP | {self.ending_wip_before:.2f} | {self.ending_wip_after:.2f} | {self.ending_wip_after - self.ending_wip_before:+.2f} |",
            f"| Scrap | {self.scrap_before:.2f} | {self.scrap_after:.2f} | {self.scrap_after - self.scrap_before:+.2f} |",
            "",
            "## Machine utilization",
            "",
            "| Machine | Baseline | Variant |",
            "|---|---:|---:|",
        ]
        rows.extend(
            f"| {machine_id} | {self.utilization_before.get(machine_id, 0.0):.1%} | {self.utilization_after.get(machine_id, 0.0):.1%} |"
            for machine_id in machine_ids
        )
        return "\n".join(rows) + "\n"


def _stdev(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def _utilization(replications: list[ReplicationMetrics]) -> dict[str, float]:
    machine_ids = sorted(
        {
            machine_id
            for replication in replications
            for machine_id in replication.machine_metrics
        }
    )
    return {
        machine_id: statistics.fmean(
            replication.machine_metrics[machine_id].state_fractions["busy"]
            + replication.machine_metrics[machine_id].state_fractions["setup"]
            for replication in replications
        )
        for machine_id in machine_ids
    }


def _capacity(factory: Factory) -> CapacityAnalysis:
    return analyze_factory(factory).artifacts["capacity"]["analysis"]


def _verdict(
    delta_percent: float | None,
    bottleneck_before: str | None,
    bottleneck_after: str | None,
) -> str:
    if delta_percent is None:
        return "No baseline throughput was observed, so the alternatives cannot be ranked."
    if abs(delta_percent) < 0.1:
        movement = (
            f" The bottleneck remains {bottleneck_after}."
            if bottleneck_after
            else ""
        )
        return f"The variant produces no material throughput change ({delta_percent:+.2f}%).{movement}"
    direction = "raises" if delta_percent > 0 else "lowers"
    movement = ""
    if bottleneck_before and bottleneck_after:
        if bottleneck_before == bottleneck_after:
            movement = f"; the bottleneck remains {bottleneck_after}"
        else:
            movement = (
                f" and moves the bottleneck from {bottleneck_before} "
                f"to {bottleneck_after}"
            )
    return f"The variant {direction} line throughput {abs(delta_percent):.2f}%{movement}."


def compare_factories(
    baseline: Factory,
    variant: Factory,
    scenario: Scenario | None = None,
) -> ComparisonReport:
    selected = scenario or Scenario(replications=10)
    baseline_runs: list[ReplicationMetrics] = []
    variant_runs: list[ReplicationMetrics] = []
    for index in range(selected.replications):
        seed = selected.seed + index
        baseline_runs.append(run_replication(baseline, selected, seed=seed))
        variant_runs.append(run_replication(variant, selected, seed=seed))

    baseline_throughput = [item.throughput_units_per_hour for item in baseline_runs]
    variant_throughput = [item.throughput_units_per_hour for item in variant_runs]
    paired_deltas = [
        after - before
        for before, after in zip(baseline_throughput, variant_throughput, strict=True)
    ]
    baseline_mean = statistics.fmean(baseline_throughput)
    variant_mean = statistics.fmean(variant_throughput)
    delta_percent = (
        (variant_mean - baseline_mean) * 100.0 / baseline_mean
        if baseline_mean != 0
        else None
    )
    before_capacity = _capacity(baseline)
    after_capacity = _capacity(variant)
    return ComparisonReport(
        baseline_id=baseline.meta.id,
        variant_id=variant.meta.id,
        scenario=selected,
        baseline_throughput_mean=baseline_mean,
        baseline_throughput_stdev=_stdev(baseline_throughput),
        variant_throughput_mean=variant_mean,
        variant_throughput_stdev=_stdev(variant_throughput),
        paired_delta_mean=statistics.fmean(paired_deltas),
        paired_delta_stdev=_stdev(paired_deltas),
        delta_percent=delta_percent,
        bottleneck_before=before_capacity.bottleneck_machine,
        bottleneck_after=after_capacity.bottleneck_machine,
        utilization_before=_utilization(baseline_runs),
        utilization_after=_utilization(variant_runs),
        ending_wip_before=statistics.fmean(item.ending_wip for item in baseline_runs),
        ending_wip_after=statistics.fmean(item.ending_wip for item in variant_runs),
        scrap_before=statistics.fmean(
            sum(item.scrap_by_operation.values()) for item in baseline_runs
        ),
        scrap_after=statistics.fmean(
            sum(item.scrap_by_operation.values()) for item in variant_runs
        ),
        verdict=_verdict(
            delta_percent,
            before_capacity.bottleneck_machine,
            after_capacity.bottleneck_machine,
        ),
    )
