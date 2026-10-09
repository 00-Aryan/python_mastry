"""Pure prerequisite DAG validation; edges point prerequisite → dependent."""

from collections import deque
from collections.abc import Mapping, Sequence
from uuid import UUID

from mastery_backend.domain.content import ContentError


def validate_acyclic_graph(codes: Mapping[UUID, str], edges: Sequence[tuple[UUID, UUID]]) -> None:
    adjacency: dict[UUID, list[UUID]] = {identifier: [] for identifier in codes}
    incoming = dict.fromkeys(codes, 0)
    if len(set(edges)) != len(edges):
        raise ContentError("DUPLICATE_EDGE", "Each prerequisite edge must appear only once.")
    for prerequisite, dependent in edges:
        if prerequisite not in codes or dependent not in codes:
            raise ContentError("INVALID_SKILL", "Every edge must reference an existing skill.")
        if prerequisite == dependent:
            raise ContentError("SELF_PREREQUISITE", "A skill cannot be its own prerequisite.")
        adjacency[prerequisite].append(dependent)
        incoming[dependent] += 1
    ready = deque(identifier for identifier, count in incoming.items() if count == 0)
    visited = 0
    while ready:
        identifier = ready.popleft()
        visited += 1
        for dependent in adjacency[identifier]:
            incoming[dependent] -= 1
            if incoming[dependent] == 0:
                ready.append(dependent)
    if visited == len(codes):
        return
    # Iterative DFS produces an actual cycle path without Python recursion limits.
    finished: set[UUID] = set()
    for root in codes:
        if root in finished:
            continue
        path = [root]
        positions = {root: 0}
        stack = [iter(adjacency[root])]
        while stack:
            child = next(stack[-1], None)
            if child is None:
                finished.add(path[-1])
                positions.pop(path.pop())
                stack.pop()
            elif child in positions:
                cycle = path[positions[child] :] + [child]
                raise ContentError(
                    "GRAPH_CYCLE",
                    "Prerequisite cycle: " + " → ".join(codes[node] for node in cycle),
                )
            elif child not in finished:
                positions[child] = len(path)
                path.append(child)
                stack.append(iter(adjacency[child]))
