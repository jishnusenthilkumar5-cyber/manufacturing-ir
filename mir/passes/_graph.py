from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable

from mir.core.model import Factory, MaterialFlow


def operation_adjacency(
    factory: Factory,
    include_flow: Callable[[MaterialFlow], bool] | None = None,
) -> dict[str, set[str]]:
    operation_ids = {operation.id for operation in factory.operations}
    adjacency = {operation_id: set() for operation_id in operation_ids}
    for flow in factory.flows:
        if (
            flow.from_op in operation_ids
            and flow.to_op in operation_ids
            and (include_flow is None or include_flow(flow))
        ):
            adjacency[flow.from_op].add(flow.to_op)
    return adjacency


def reachable_from_inlets(factory: Factory) -> set[str]:
    operation_ids = {operation.id for operation in factory.operations}
    adjacency = operation_adjacency(factory)
    queue = deque(
        flow.to_op
        for flow in factory.flows
        if flow.from_op is None and flow.to_op in operation_ids
    )
    reached = set(queue)
    while queue:
        current = queue.popleft()
        for target in adjacency[current]:
            if target not in reached:
                reached.add(target)
                queue.append(target)
    return reached


def strongly_connected_components(
    adjacency: dict[str, set[str]],
    nodes: Iterable[str] | None = None,
) -> list[tuple[str, ...]]:
    node_set = set(nodes) if nodes is not None else set(adjacency)
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def connect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for target in sorted(adjacency.get(node, set()) & node_set):
            if target not in indices:
                connect(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])

        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            components.append(tuple(sorted(component)))

    for node in sorted(node_set):
        if node not in indices:
            connect(node)
    return components


def is_cyclic_component(component: tuple[str, ...], adjacency: dict[str, set[str]]) -> bool:
    return len(component) > 1 or bool(component and component[0] in adjacency.get(component[0], set()))


def cyclic_components(adjacency: dict[str, set[str]]) -> list[tuple[str, ...]]:
    return [
        component
        for component in strongly_connected_components(adjacency)
        if is_cyclic_component(component, adjacency)
    ]
