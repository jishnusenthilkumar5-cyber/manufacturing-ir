from __future__ import annotations

from mir.core.model import Factory
from mir.passes import Severity, validate_factory
from mir.sim._engine import ReplicationEngine
from mir.sim.metrics import (
    ReplicationMetrics,
    SimulationResult,
    summarize_metrics,
)
from mir.sim.scenario import Scenario


class SimulationError(ValueError):
    pass


def _validate_simulation(factory: Factory, scenario: Scenario) -> None:
    diagnostics = validate_factory(factory).diagnostics
    errors = [item for item in diagnostics if item.severity is Severity.ERROR]
    if errors:
        details = "; ".join(f"{item.code}: {item.message}" for item in errors)
        raise SimulationError(f"factory is not executable: {details}")

    inlet_flows = {
        flow.id: flow
        for flow in factory.flows
        if flow.from_op is None and flow.to_op is not None
    }
    unknown = sorted(set(scenario.arrival_rates_per_hour) - set(inlet_flows))
    if unknown:
        raise SimulationError(
            f"arrival rates reference non-inlet flows: {', '.join(unknown)}"
        )
    synchronous = sorted(
        flow_id
        for flow_id in scenario.arrival_rates_per_hour
        if inlet_flows[flow_id].buffer_capacity == 0
    )
    if synchronous:
        raise SimulationError(
            "scheduled arrivals require a storable inlet buffer: "
            + ", ".join(synchronous)
        )


def run_replication(
    factory: Factory,
    scenario: Scenario,
    *,
    seed: int | None = None,
) -> ReplicationMetrics:
    _validate_simulation(factory, scenario)
    return ReplicationEngine(
        factory.model_copy(deep=True),
        scenario,
        scenario.seed if seed is None else seed,
    ).run()


def simulate(factory: Factory, scenario: Scenario | None = None) -> SimulationResult:
    selected = scenario or Scenario()
    _validate_simulation(factory, selected)
    replications = [
        ReplicationEngine(
            factory.model_copy(deep=True),
            selected,
            selected.seed + index,
        ).run()
        for index in range(selected.replications)
    ]
    return SimulationResult(
        scenario=selected,
        replications=tuple(replications),
        summary=summarize_metrics(replications),
    )
