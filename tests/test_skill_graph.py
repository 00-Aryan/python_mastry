"""Pure graph tests exercise topology and long paths without database coupling."""

from uuid import UUID

import pytest

from mastery_backend.domain.content import ContentError
from mastery_backend.domain.skill_graph import validate_acyclic_graph


@pytest.mark.parametrize(
    "edges", [[], [(1, 2), (2, 3)], [(1, 2), (1, 3)], [(1, 2), (1, 3), (2, 4), (3, 4)]]
)
def test_valid_graphs(edges: list[tuple[int, int]]) -> None:
    validate_acyclic_graph(
        {UUID(int=i): f"SK-{i}" for i in range(1, 6)},
        [(UUID(int=a), UUID(int=b)) for a, b in edges],
    )


@pytest.mark.parametrize(
    "edges,code",
    [
        ([(1, 1)], "SELF_PREREQUISITE"),
        ([(1, 2), (2, 1)], "GRAPH_CYCLE"),
        ([(1, 2), (2, 3), (3, 1)], "GRAPH_CYCLE"),
    ],
)
def test_cycle_paths(edges: list[tuple[int, int]], code: str) -> None:
    with pytest.raises(ContentError) as caught:
        validate_acyclic_graph(
            {UUID(int=i): f"SK-{i}" for i in range(1, 5)},
            [(UUID(int=a), UUID(int=b)) for a, b in edges],
        )
    assert caught.value.code == code
    if code == "GRAPH_CYCLE":
        assert "SK-1" in caught.value.message
        assert "SK-2" in caught.value.message


def test_long_chain_and_cycle_do_not_use_recursive_stack() -> None:
    codes = {UUID(int=i): f"SK-{i}" for i in range(1, 2501)}
    edges = [(UUID(int=i), UUID(int=i + 1)) for i in range(1, 2500)]
    validate_acyclic_graph(codes, edges)
    with pytest.raises(ContentError, match="Prerequisite cycle"):
        validate_acyclic_graph(codes, [*edges, (UUID(int=2500), UUID(int=1))])


def test_duplicate_and_missing_endpoints_are_domain_errors() -> None:
    a, b = UUID(int=1), UUID(int=2)
    with pytest.raises(ContentError) as duplicate:
        validate_acyclic_graph({a: "AA", b: "BB"}, [(a, b), (a, b)])
    assert duplicate.value.code == "DUPLICATE_EDGE"
    with pytest.raises(ContentError) as missing:
        validate_acyclic_graph({a: "AA"}, [(a, b)])
    assert missing.value.code == "INVALID_SKILL"
