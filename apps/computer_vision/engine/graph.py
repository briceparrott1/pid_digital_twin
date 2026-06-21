# Subgraph-to-PageGraph collapse: final node/edge dedup, untagged_count pass,
# and folding any remaining open obligations into Diagnostics.leftover_splits.
from __future__ import annotations

from engine.instrument.counters import Counters, to_diagnostics
from engine.merge.dedupe import dedupe_nodes
from engine.types import Edge, PageGraph, Subgraph


def _dedupe_edges(edges: list[Edge]) -> list[Edge]:
    """Drops exact duplicate undirected edges ({a,b} == {b,a}), keeping first-seen order."""
    seen: set[frozenset[str]] = set()
    deduped: list[Edge] = []
    for edge in edges:
        key = frozenset((edge.a, edge.b))
        if key not in seen:
            seen.add(key)
            deduped.append(edge)
    return deduped


def to_page_graph(subgraph: Subgraph, counters: Counters) -> PageGraph:
    """Collapses the root's Subgraph into the final PageGraph: obligations
    still open here (genuine page-edge truncations) surface as
    `leftover_splits`; obligations that hit a real seam and never found a
    partner (a true matching failure) surface separately as
    `seam_pairing_failures`."""
    nodes = dedupe_nodes(subgraph.nodes)
    edges = _dedupe_edges(subgraph.edges)
    untagged_count = sum(1 for node in nodes if node.id == "")
    leftover_splits = [*subgraph.open_connections, *subgraph.open_nodes]
    diagnostics = to_diagnostics(
        counters, leftover_splits, untagged_count, subgraph.failed_splits
    )
    return PageGraph(nodes=nodes, edges=edges, diagnostics=diagnostics)
