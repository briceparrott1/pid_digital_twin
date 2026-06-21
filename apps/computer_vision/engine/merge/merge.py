# Orchestrates one cut's merge: resolves obligations facing the seam this cut
# just made, retranslates and propagates the rest toward the next ancestor.
# An obligation that faces this seam and finds no partner is retired into
# `failed_splits` rather than propagated -- recursive bisection only ever
# enlarges a merged region, so a failed-to-pair facing obligation is now
# permanently interior and can never face a real boundary again. Letting it
# keep propagating would just create false collisions against unrelated
# obligations at later, non-adjacent seams.
from __future__ import annotations

from dataclasses import replace

from engine.instrument.counters import Counters
from engine.merge.dedupe import dedupe_nodes
from engine.merge.lines import resolve_connections
from engine.merge.nodes import fuse, is_whole, to_node
from engine.merge.sides import facing_side, is_facing, retranslate
from engine.types import CutAxis, Edge, Node, SplitConnection, SplitNode, Subgraph


def _retranslated(conn: SplitConnection) -> SplitConnection:
    """Returns a copy of `conn` with its side moved into the parent's frame."""
    return replace(conn, side=retranslate(conn.side))


def _retranslated_node(node: SplitNode) -> SplitNode:
    """Returns a copy of `node` with every open side moved into the parent's frame."""
    return replace(node, sides=[retranslate(s) for s in node.sides])


def _retire_failed_side(node: SplitNode, failed_side: str) -> SplitNode:
    """Removes `failed_side` from `node`'s open sides: this fragment faced a
    real seam on that side and found no partner there, so it can never face a
    real boundary on that side again. Any other still-open sides are
    unaffected and may still resolve at a future seam."""
    return replace(node, sides=[s for s in node.sides if s != failed_side])


def merge(
    sub_a: Subgraph, sub_b: Subgraph, axis: CutAxis, counters: Counters
) -> Subgraph:
    """Merges the two child Subgraphs of one cut: pairs facing SplitConnections
    into Edges, fuses facing SplitNodes (closing this seam's side), dedupes
    nodes by id, and retranslates+propagates every obligation that does not
    face this seam upward unchanged."""
    side_a, side_b = facing_side(axis, "first"), facing_side(axis, "second")

    facing_conns_a = [
        c for c in sub_a.open_connections if is_facing(axis, "first", c.side)
    ]
    facing_conns_b = [
        c for c in sub_b.open_connections if is_facing(axis, "second", c.side)
    ]
    propagate_conns = [
        _retranslated(c)
        for c in sub_a.open_connections
        if not is_facing(axis, "first", c.side)
    ] + [
        _retranslated(c)
        for c in sub_b.open_connections
        if not is_facing(axis, "second", c.side)
    ]

    new_edges, unmatched_conns = resolve_connections(
        facing_conns_a, facing_conns_b, counters
    )

    facing_nodes_a = [n for n in sub_a.open_nodes if side_a in n.sides]
    facing_nodes_b = [n for n in sub_b.open_nodes if side_b in n.sides]
    propagate_nodes = [
        _retranslated_node(n) for n in sub_a.open_nodes if side_a not in n.sides
    ] + [_retranslated_node(n) for n in sub_b.open_nodes if side_b not in n.sides]

    resolved_nodes: list[Node] = []
    resolved_node_edges: list[Edge] = []
    still_open_nodes: list[SplitNode] = []
    paired = min(len(facing_nodes_a), len(facing_nodes_b))
    for i in range(paired):
        fused = fuse(facing_nodes_a[i], side_a, facing_nodes_b[i], side_b, counters)
        if is_whole(fused):
            node, edges = to_node(fused)
            resolved_nodes.append(node)
            resolved_node_edges.extend(edges)
            counters.equipment_merges += 1
        else:
            still_open_nodes.append(_retranslated_node(fused))
    # Asymmetric leftovers (shouldn't occur for a true 1:1 equipment split, but
    # never silently dropped): each faced this seam and found no partner, so
    # retire just the failed side -- any other open side may still resolve.
    failed_nodes: list[SplitNode] = []
    for node, failed_side in [
        *((n, side_a) for n in facing_nodes_a[paired:]),
        *((n, side_b) for n in facing_nodes_b[paired:]),
    ]:
        retired = _retire_failed_side(node, failed_side)
        (still_open_nodes if retired.sides else failed_nodes).append(retired)

    nodes = dedupe_nodes(sub_a.nodes + sub_b.nodes + resolved_nodes)
    edges = sub_a.edges + sub_b.edges + new_edges + resolved_node_edges

    return Subgraph(
        nodes=nodes,
        edges=edges,
        open_connections=propagate_conns,
        open_nodes=propagate_nodes + still_open_nodes,
        uncertainties=sub_a.uncertainties + sub_b.uncertainties,
        failed_splits=sub_a.failed_splits
        + sub_b.failed_splits
        + unmatched_conns
        + failed_nodes,
    )
