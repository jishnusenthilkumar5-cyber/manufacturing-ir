from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from mir.core.calendar import shift_fraction
from mir.core.model import Factory, Machine
from mir.passes.base import Diagnostic, PassContext, PassResult, Severity
from mir.passes.topology import TopologyAnalysis


@dataclass(frozen=True, slots=True)
class MachineCapacity:
    machine_id: str
    busy_seconds_per_unit: float
    effective_seconds_per_unit: float
    availability_fraction: float
    calendar_fraction: float
    capacity_units_per_hour: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "busy_seconds_per_unit": self.busy_seconds_per_unit,
            "effective_seconds_per_unit": self.effective_seconds_per_unit,
            "availability_fraction": self.availability_fraction,
            "calendar_fraction": self.calendar_fraction,
            "capacity_units_per_hour": self.capacity_units_per_hour,
        }


@dataclass(frozen=True, slots=True)
class CapacityAnalysis:
    exact: bool
    throughput_upper_bound_units_per_hour: float | None
    bottleneck_machine: str | None
    operation_cycles_per_unit: dict[str, float]
    flow_units_per_output: dict[str, float]
    machine_capacities: dict[str, MachineCapacity]

    def to_dict(self) -> dict[str, Any]:
        return {
            "exact": self.exact,
            "throughput_upper_bound_units_per_hour": self.throughput_upper_bound_units_per_hour,
            "bottleneck_machine": self.bottleneck_machine,
            "operation_cycles_per_unit": dict(self.operation_cycles_per_unit),
            "flow_units_per_output": dict(self.flow_units_per_output),
            "machine_capacities": {
                key: value.to_dict() for key, value in self.machine_capacities.items()
            },
        }


def availability_fraction(machine: Machine) -> float:
    availability = machine.availability
    if availability is None:
        return 1.0
    if availability.mtbf_s <= 0 or availability.mttr_s <= 0:
        return 0.0
    return availability.mtbf_s / (availability.mtbf_s + availability.mttr_s)


class CapacityPass:
    name = "capacity"
    requires = ("topology",)

    def run(self, factory: Factory, context: PassContext) -> PassResult:
        topology: TopologyAnalysis = context.require("topology", "analysis")
        diagnostics: list[Diagnostic] = []
        output_groups: defaultdict[tuple[str, str], int] = defaultdict(int)
        input_groups: defaultdict[tuple[str, str], int] = defaultdict(int)
        for flow in factory.flows:
            if flow.from_op is not None:
                output_groups[(flow.from_op, flow.material)] += 1
            if flow.to_op is not None and flow.input_port is not None:
                input_groups[(flow.to_op, flow.input_port)] += 1
        has_alternative_routing = any(count > 1 for count in output_groups.values())
        has_alternative_inputs = any(count > 1 for count in input_groups.values())
        exact = (
            len(topology.outlet_flows) == 1
            and not topology.cycles
            and not has_alternative_routing
            and not has_alternative_inputs
        )
        if not exact:
            diagnostics.append(
                Diagnostic(
                    "MIR100",
                    Severity.WARNING,
                    "capacity result is approximate for cyclic, multi-outlet, or alternative-routing topology",
                    tuple(sorted(topology.outlet_flows)),
                    "Use simulation for a calibrated throughput estimate.",
                )
            )

        operations = factory.operation_map()
        required_flow_units: defaultdict[str, float] = defaultdict(float)
        cycles: dict[str, float] = {}

        if exact:
            required_flow_units[topology.outlet_flows[0]] = 1.0
            for operation_id in reversed(topology.topological_order):
                operation = operations[operation_id]
                successful_cycles = [
                    required_flow_units[flow.id]
                    / (operation.batch_size * flow.units_per_batch)
                    for flow in factory.flows
                    if flow.from_op == operation_id
                    and required_flow_units[flow.id] > 0
                ]
                if not successful_cycles:
                    continue
                cycle_count = max(successful_cycles) / operation.yield_fraction
                cycles[operation_id] = cycle_count
                for flow in factory.flows:
                    if flow.to_op == operation_id:
                        required_flow_units[flow.id] = (
                            cycle_count
                            * operation.batch_size
                            * flow.units_per_batch
                        )
        else:
            cycles = {
                operation.id: 1.0
                / (
                    operation.batch_size
                    * max(
                        (
                            flow.units_per_batch
                            for flow in factory.flows
                            if flow.from_op == operation.id
                        ),
                        default=1,
                    )
                    * operation.yield_fraction
                )
                for operation in factory.operations
            }

        machines = factory.machine_map()
        busy_seconds: defaultdict[str, float] = defaultdict(float)
        for operation_id, cycle_count in cycles.items():
            operation = operations[operation_id]
            eligible = [machines[item] for item in operation.machines if item in machines]
            if not eligible:
                continue
            weights = {
                machine.id: (
                    machine.num_stations
                    * availability_fraction(machine)
                    * shift_fraction(machine)
                )
                for machine in eligible
            }
            total_weight = sum(weights.values())
            if total_weight <= 0:
                share = 1.0 / len(eligible)
                allocations = {machine.id: share for machine in eligible}
            else:
                allocations = {
                    machine.id: weights[machine.id] / total_weight for machine in eligible
                }
            duration = cycle_count * operation.cycle_time.mean_seconds()
            for machine_id, allocation in allocations.items():
                busy_seconds[machine_id] += duration * allocation

        machine_capacities: dict[str, MachineCapacity] = {}
        for machine_id in sorted(machines):
            machine = machines[machine_id]
            fraction = availability_fraction(machine)
            calendar = shift_fraction(machine)
            busy = busy_seconds[machine_id]
            denominator = machine.num_stations * fraction * calendar
            effective = busy / denominator if denominator > 0 else float("inf")
            capacity = 3600.0 / effective if 0 < effective < float("inf") else None
            machine_capacities[machine_id] = MachineCapacity(
                machine_id=machine_id,
                busy_seconds_per_unit=busy,
                effective_seconds_per_unit=effective,
                availability_fraction=fraction,
                calendar_fraction=calendar,
                capacity_units_per_hour=capacity,
            )

        active = [item for item in machine_capacities.values() if item.busy_seconds_per_unit > 0]
        bottleneck = (
            max(active, key=lambda item: (item.effective_seconds_per_unit, item.machine_id))
            if active
            else None
        )
        throughput = (
            3600.0 / bottleneck.effective_seconds_per_unit
            if bottleneck is not None
            and 0 < bottleneck.effective_seconds_per_unit < float("inf")
            else None
        )
        analysis = CapacityAnalysis(
            exact=exact,
            throughput_upper_bound_units_per_hour=throughput,
            bottleneck_machine=bottleneck.machine_id if bottleneck else None,
            operation_cycles_per_unit=dict(sorted(cycles.items())),
            flow_units_per_output={
                key: required_flow_units[key] for key in sorted(required_flow_units)
            },
            machine_capacities=machine_capacities,
        )
        return PassResult(diagnostics=diagnostics, artifacts={"analysis": analysis})
