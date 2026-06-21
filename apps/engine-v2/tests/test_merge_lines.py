# Unit tests for SplitConnection resolution: pairing by color across a seam,
# propagation of non-facing obligations, seam_collisions counting, and retiring
# an unmatched facing connection into failed_splits (not kept open to risk a
# false match at some later, non-adjacent seam).
from __future__ import annotations

from engine.instrument.counters import Counters
from engine.merge.merge import merge
from engine.types import Edge, SplitConnection, Subgraph


def test_facing_connections_resolve_to_one_edge():
    sub_a = Subgraph(
        open_connections=[
            SplitConnection(node="V1", color="red", label="L1", side="right")
        ]
    )
    sub_b = Subgraph(
        open_connections=[
            SplitConnection(node="V2", color="red", label="L1", side="left")
        ]
    )
    counters = Counters()
    result = merge(sub_a, sub_b, "vertical", counters)
    assert result.edges == [Edge(a="V1", b="V2")]
    assert result.open_connections == []
    assert counters.seam_collisions == 0


def test_non_facing_connection_propagates_not_resolved():
    sub_a = Subgraph(
        open_connections=[
            SplitConnection(node="V1", color="red", label="L1", side="top")
        ]
    )
    sub_b = Subgraph()
    counters = Counters()
    result = merge(sub_a, sub_b, "vertical", counters)
    assert result.edges == []
    assert len(result.open_connections) == 1
    propagated = result.open_connections[0]
    assert propagated.side == "top"
    assert propagated.node == "V1"


def test_seam_collision_counted_once_per_colliding_key():
    sub_a = Subgraph(
        open_connections=[
            SplitConnection(node="V1", color="red", label="L1", side="right"),
            SplitConnection(node="V2", color="red", label="L1", side="right"),
        ]
    )
    sub_b = Subgraph(
        open_connections=[
            SplitConnection(node="V3", color="red", label="L1", side="left"),
        ]
    )
    counters = Counters()
    result = merge(sub_a, sub_b, "vertical", counters)
    assert counters.seam_collisions == 1
    assert len(result.edges) == 1  # best-effort: first pair still resolves
    assert (
        result.open_connections == []
    )  # not kept open -- can't face a real seam again
    assert len(result.failed_splits) == 1  # the extra, unmatched one is retired here
    assert result.failed_splits[0].node == "V2"


def test_unmatched_facing_connection_does_not_collide_at_a_later_unrelated_seam():
    # Three columns A | B | C, cut as (A | BC) then, inside BC, (B | C). A's
    # true partner is B (adjacent). C has an unrelated same-color/empty-label
    # obligation on its own left side -- not adjacent to A at all. Without
    # retiring C's failed obligation immediately at the inner B|C seam, it
    # would still be "open" and falsely collide with B's at the outer A|BC
    # seam (same color+label, same side) purely by coincidence of tree shape.
    sub_b = Subgraph(
        open_connections=[
            SplitConnection(node="B_NODE", color="green", label="", side="left")
        ]
    )
    sub_c = Subgraph(
        open_connections=[
            SplitConnection(node="C_NODE", color="green", label="", side="left")
        ]
    )
    counters = Counters()
    sub_bc = merge(sub_b, sub_c, "vertical", counters)
    assert counters.seam_collisions == 0  # C's facing-but-unmatched, not a collision

    sub_a = Subgraph(
        open_connections=[
            SplitConnection(node="A_NODE", color="green", label="", side="right")
        ]
    )
    root = merge(sub_a, sub_bc, "vertical", counters)
    assert root.edges == [Edge(a="A_NODE", b="B_NODE")]
    assert counters.seam_collisions == 0  # no false collision against C's leftover
    assert root.open_connections == []
    assert [c.node for c in root.failed_splits] == ["C_NODE"]
