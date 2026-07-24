from __future__ import annotations

from collections import Counter

from mir.core.model import Factory
from mir.passes._graph import cyclic_components, operation_adjacency, reachable_from_inlets
from mir.passes.base import Diagnostic, PassContext, PassResult, Severity


class StructuralValidationPass:
    name = "structural"
    requires: tuple[str, ...] = ()

    def run(self, factory: Factory, context: PassContext) -> PassResult:
        diagnostics: list[Diagnostic] = []
        collections = {
            "machine": factory.machines,
            "operation": factory.operations,
            "flow": factory.flows,
            "signal": factory.signals,
        }
        for kind, items in collections.items():
            counts = Counter(item.id for item in items)
            for entity_id, count in sorted(counts.items()):
                if count > 1:
                    diagnostics.append(
                        Diagnostic(
                            "MIR001",
                            Severity.ERROR,
                            f"duplicate {kind} id {entity_id!r}",
                            (entity_id,),
                            "Rename entities so every id is unique within its collection.",
                        )
                    )

        machine_ids = {machine.id for machine in factory.machines}
        operation_ids = {operation.id for operation in factory.operations}

        for operation in factory.operations:
            if not operation.machines:
                diagnostics.append(
                    Diagnostic(
                        "MIR005",
                        Severity.ERROR,
                        f"operation {operation.id!r} has no eligible machines",
                        (operation.id,),
                        "Assign at least one machine to the operation.",
                    )
                )
            for machine_id in operation.machines:
                if machine_id not in machine_ids:
                    diagnostics.append(
                        Diagnostic(
                            "MIR002",
                            Severity.ERROR,
                            f"operation {operation.id!r} references unknown machine {machine_id!r}",
                            (operation.id, machine_id),
                            "Create the machine or correct the reference.",
                        )
                    )

        for flow in factory.flows:
            missing = sorted(
                endpoint
                for endpoint in (flow.from_op, flow.to_op)
                if endpoint is not None and endpoint not in operation_ids
            )
            for endpoint in missing:
                diagnostics.append(
                    Diagnostic(
                        "MIR003",
                        Severity.ERROR,
                        f"flow {flow.id!r} references unknown operation {endpoint!r}",
                        (flow.id, endpoint),
                        "Create the operation or correct the flow endpoint.",
                    )
                )
            if flow.from_op is None and flow.to_op is None:
                diagnostics.append(
                    Diagnostic(
                        "MIR004",
                        Severity.ERROR,
                        f"flow {flow.id!r} has no endpoints",
                        (flow.id,),
                        "Set from_op, to_op, or both.",
                    )
                )

        for signal in factory.signals:
            if signal.machine not in machine_ids:
                diagnostics.append(
                    Diagnostic(
                        "MIR006",
                        Severity.ERROR,
                        f"signal {signal.id!r} references unknown machine {signal.machine!r}",
                        (signal.id, signal.machine),
                        "Create the machine or correct the reference.",
                    )
                )
        signal_keys = Counter((signal.machine, signal.tag) for signal in factory.signals)
        for (machine_id, tag), count in sorted(signal_keys.items()):
            if count > 1:
                signal_ids = tuple(
                    sorted(
                        signal.id
                        for signal in factory.signals
                        if signal.machine == machine_id and signal.tag == tag
                    )
                )
                diagnostics.append(
                    Diagnostic(
                        "MIR007",
                        Severity.ERROR,
                        f"signal tag {tag!r} is duplicated on machine {machine_id!r}",
                        signal_ids,
                        "Signal tags must be unique per machine.",
                    )
                )

        connected: set[str] = set()
        for flow in factory.flows:
            if flow.from_op in operation_ids:
                connected.add(flow.from_op)
            if flow.to_op in operation_ids:
                connected.add(flow.to_op)
        orphaned = operation_ids - connected
        for operation_id in sorted(orphaned):
            diagnostics.append(
                Diagnostic(
                    "MIR010",
                    Severity.WARNING,
                    f"operation {operation_id!r} has no material flows",
                    (operation_id,),
                    "Connect it to an inlet, outlet, or another operation.",
                )
            )

        reachable = reachable_from_inlets(factory)
        for operation_id in sorted(operation_ids - reachable - orphaned):
            diagnostics.append(
                Diagnostic(
                    "MIR011",
                    Severity.WARNING,
                    f"operation {operation_id!r} is unreachable from every inlet",
                    (operation_id,),
                    "Add a material path from a factory inlet.",
                )
            )

        full_adjacency = operation_adjacency(factory)
        zero_buffer_adjacency = operation_adjacency(
            factory, lambda flow: flow.buffer_capacity == 0
        )
        zero_cycles = cyclic_components(zero_buffer_adjacency)
        zero_cycle_nodes = {node for component in zero_cycles for node in component}
        for component in zero_cycles:
            diagnostics.append(
                Diagnostic(
                    "MIR012",
                    Severity.ERROR,
                    "unbuffered cycle is guaranteed to deadlock",
                    component,
                    "Give at least one edge in the cycle a positive or unbounded buffer.",
                )
            )
        for component in cyclic_components(full_adjacency):
            if set(component).isdisjoint(zero_cycle_nodes):
                diagnostics.append(
                    Diagnostic(
                        "MIR012",
                        Severity.INFO,
                        "buffered cycle is treated as a rework loop",
                        component,
                        "Confirm that the cycle is intentional.",
                    )
                )

        return PassResult(diagnostics=diagnostics)
