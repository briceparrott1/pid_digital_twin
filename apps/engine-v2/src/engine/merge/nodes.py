# Fuses SplitNode fragments across a seam, unioning their edges and closing the
# side the seam resolved; tracks when a fragment becomes whole.
from __future__ import annotations

from engine.instrument.counters import Counters
from engine.types import SELF_REF, Edge, Node, SplitNode


def fuse(
    node_a: SplitNode,
    side_a: str,
    node_b: SplitNode,
    side_b: str,
    counters: Counters,
) -> SplitNode:
    """Merges two fragments meeting across a seam, where `side_a`/`side_b` are
    the (generally different) facing side names in each fragment's own frame.
    Unions remaining open sides, concatenates accumulated edges, inherits
    id/type/metadata. Resolves this one seam; the result may still be open on
    other sides."""
    sides_a = [s for s in node_a.sides if s != side_a]
    sides_b = [s for s in node_b.sides if s != side_b]
    merged_sides = list(dict.fromkeys(sides_a + sides_b))

    if node_a.id and node_b.id:
        if node_a.id != node_b.id:
            counters.seam_collisions += 1
        fused_id = node_a.id
    else:
        fused_id = node_a.id or node_b.id

    return SplitNode(
        id=fused_id,
        type=node_a.type,
        metadata={**node_a.metadata, **node_b.metadata},
        sides=merged_sides,
        edges=node_a.edges + node_b.edges,
    )


def is_whole(node: SplitNode) -> bool:
    """True once a fused fragment has no remaining open sides."""
    return not node.sides


def to_node(node: SplitNode) -> tuple[Node, list[Edge]]:
    """Promotes a whole `SplitNode` into a final `Node`, coercing an unreadable
    id (None) to "" so it is later counted by `untagged_count`. Substitutes
    the resolved id for any `SELF_REF` placeholder in the accumulated edges
    (recorded when a connection to this fragment was read before it had a
    known id), then returns the node plus those edges for the caller to fold
    in."""
    resolved_id = node.id or ""
    edges = [
        Edge(
            a=resolved_id if edge.a == SELF_REF else edge.a,
            b=resolved_id if edge.b == SELF_REF else edge.b,
        )
        for edge in node.edges
    ]
    return Node(id=resolved_id, type=node.type, metadata=node.metadata), edges
