from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from mir.sim.scenario import Scenario


@dataclass(frozen=True, slots=True)
class BufferMetrics:
    mean_occupancy: float
    max_occupancy: int
    ending_occupancy: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "mean_occupancy": self.mean_occupancy,
            "max_occupancy": self.max_occupancy,
            "ending_occupancy": self.ending_occupancy,
        }


@dataclass(frozen=True, slots=True)
class MachineMetrics:
    state_fractions: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {"state_fractions": dict(self.state_fractions)}


@dataclass(frozen=True, slots=True)
class ReplicationMetrics:
    seed: int
    measurement_s: float
    throughput_by_outlet: dict[str, float]
    throughput_units_per_hour: float
    machine_metrics: dict[str, MachineMetrics]
    scrap_by_operation: dict[str, int]
    cycles_by_operation: dict[str, int]
    buffers: dict[str, BufferMetrics]
    input_units: int
    output_units: int
    starting_wip: int
    ending_wip: int
    conservation_error: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "measurement_s": self.measurement_s,
            "throughput_by_outlet": dict(self.throughput_by_outlet),
            "throughput_units_per_hour": self.throughput_units_per_hour,
            "machine_metrics": {
                key: value.to_dict() for key, value in self.machine_metrics.items()
            },
            "scrap_by_operation": dict(self.scrap_by_operation),
            "cycles_by_operation": dict(self.cycles_by_operation),
            "buffers": {key: value.to_dict() for key, value in self.buffers.items()},
            "input_units": self.input_units,
            "output_units": self.output_units,
            "starting_wip": self.starting_wip,
            "ending_wip": self.ending_wip,
            "conservation_error": self.conservation_error,
        }


@dataclass(frozen=True, slots=True)
class SimulationSummary:
    throughput_units_per_hour_mean: float
    throughput_units_per_hour_stdev: float
    throughput_by_outlet_mean: dict[str, float]
    machine_state_fractions_mean: dict[str, dict[str, float]]
    scrap_by_operation_mean: dict[str, float]
    ending_wip_mean: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "throughput_units_per_hour_mean": self.throughput_units_per_hour_mean,
            "throughput_units_per_hour_stdev": self.throughput_units_per_hour_stdev,
            "throughput_by_outlet_mean": dict(self.throughput_by_outlet_mean),
            "machine_state_fractions_mean": {
                key: dict(value)
                for key, value in self.machine_state_fractions_mean.items()
            },
            "scrap_by_operation_mean": dict(self.scrap_by_operation_mean),
            "ending_wip_mean": self.ending_wip_mean,
        }


@dataclass(frozen=True, slots=True)
class SimulationResult:
    scenario: Scenario
    replications: tuple[ReplicationMetrics, ...]
    summary: SimulationSummary

    def to_dict(self, include_replications: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "scenario": self.scenario.model_dump(mode="json"),
            "summary": self.summary.to_dict(),
        }
        if include_replications:
            result["replications"] = [item.to_dict() for item in self.replications]
        return result


def _mean_mapping(mappings: list[dict[str, float]]) -> dict[str, float]:
    keys = sorted({key for mapping in mappings for key in mapping})
    return {
        key: statistics.fmean(mapping.get(key, 0.0) for mapping in mappings)
        for key in keys
    }


def summarize_metrics(replications: list[ReplicationMetrics]) -> SimulationSummary:
    if not replications:
        raise ValueError("at least one replication is required")
    throughput = [item.throughput_units_per_hour for item in replications]
    machine_ids = sorted(
        {
            machine_id
            for item in replications
            for machine_id in item.machine_metrics
        }
    )
    states = sorted(
        {
            state
            for item in replications
            for metrics in item.machine_metrics.values()
            for state in metrics.state_fractions
        }
    )
    machine_means = {
        machine_id: {
            state: statistics.fmean(
                item.machine_metrics.get(machine_id, MachineMetrics({})).state_fractions.get(
                    state, 0.0
                )
                for item in replications
            )
            for state in states
        }
        for machine_id in machine_ids
    }
    return SimulationSummary(
        throughput_units_per_hour_mean=statistics.fmean(throughput),
        throughput_units_per_hour_stdev=(
            statistics.stdev(throughput) if len(throughput) > 1 else 0.0
        ),
        throughput_by_outlet_mean=_mean_mapping(
            [item.throughput_by_outlet for item in replications]
        ),
        machine_state_fractions_mean=machine_means,
        scrap_by_operation_mean=_mean_mapping(
            [
                {key: float(value) for key, value in item.scrap_by_operation.items()}
                for item in replications
            ]
        ),
        ending_wip_mean=statistics.fmean(item.ending_wip for item in replications),
    )
