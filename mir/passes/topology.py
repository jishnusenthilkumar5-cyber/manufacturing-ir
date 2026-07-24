from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from mir.core.model import Factory
from mir.passes._graph import cyclic_components, operation_adjacency, reachable_from_inlets
from mir.passes.base import PassContext, PassResult


@dataclass(frozen=True, slots=True)
class TopologyAnalysis:
    adjacency: dict[str, tuple[str, ...]]
    reverse_adjacency: dict[str, tuple[str, ...]]
    inlet_flows: tuple[str, ...]
    outlet_flows: tuple[str, ...]
    topological_order: tuple[str, ...]
    cycles: tuple[tuple[str, ...], ...]
    reachable_operations: tuple[str, ...]
    is_serial_line: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjacency": {key: list(value) for key, value in self.adjacency.items()},
            "reverse_adjacency": {
                key: list(value) for key, value in self.reverse_adjacency.items()
            },
            "inlet_flows": list(self.inlet_flows),
            "outlet_flows": list(self.outlet_flows),
            "topological_order": list(self.topological_order),
            "cycles": [list(cycle) for cycle in self.cycles],
            "reachable_operations": list(self.reachable_operations),
            "is_serial_line": self.is_serial_line,
        }


class TopologyPass:
    name = "topology"
    requires = ("structural",)

    def run(self, factory: Factory, context: PassContext) -> PassResult:
        operation_ids = {operation.id for operation in factory.operations}
        adjacency_sets = operation_adjacency(factory)
        reverse_sets = {operation_id: set() for operation_id in operation_ids}
        for source, targets in adjacency_sets.items():
            for target in targets:
                reverse_sets[target].add(source)

        indegree = {node: len(reverse_sets[node]) for node in operation_ids}
        queue = deque(sorted(node for node, degree in indegree.items() if degree == 0))
        order: list[str] = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for target in sorted(adjacency_sets[node]):
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)

        inlets = tuple(
            sorted(
                flow.id
                for flow in factory.flows
                if flow.from_op is None and flow.to_op in operation_ids
            )
        )
        outlets = tuple(
            sorted(
                flow.id
                for flow in factory.flows
                if flow.to_op is None and flow.from_op in operation_ids
            )
        )
        cycles = tuple(cyclic_components(adjacency_sets))
        reachable = tuple(sorted(reachable_from_inlets(factory)))
        is_serial = (
            not cycles
            and len(inlets) == 1
            and len(outlets) == 1
            and set(reachable) == operation_ids
            and all(len(targets) <= 1 for targets in adjacency_sets.values())
            and all(len(sources) <= 1 for sources in reverse_sets.values())
        )
        analysis = TopologyAnalysis(
            adjacency={
                node: tuple(sorted(adjacency_sets[node])) for node in sorted(operation_ids)
            },
            reverse_adjacency={
                node: tuple(sorted(reverse_sets[node])) for node in sorted(operation_ids)
            },
            inlet_flows=inlets,
            outlet_flows=outlets,
            topological_order=tuple(order),
            cycles=cycles,
            reachable_operations=reachable,
            is_serial_line=is_serial,
        )
        return PassResult(artifacts={"analysis": analysis})
