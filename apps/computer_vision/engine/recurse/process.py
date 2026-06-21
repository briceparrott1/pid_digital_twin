# Recursive heart of the engine: cut-or-read each segment, merging children
# back into one Subgraph. No VLM call lives here — the leaf reader is injected.
from __future__ import annotations

from typing import Callable

from engine.config import CutConfig, StopConfig
from engine.cut.best_cut import best_cut
from engine.cut.split import split
from engine.graph import to_page_graph
from engine.instrument.counters import Counters
from engine.merge.merge import merge
from engine.recurse.stop import should_stop_cutting
from engine.types import Edge, LeafResult, Node, PageGraph, Segment, Subgraph

LeafReader = Callable[[Segment], LeafResult]


def subgraph_from_leaf(result: LeafResult) -> Subgraph:
    """Converts a flat `LeafResult` into the degenerate single-segment Subgraph:
    nodes/edges pass through, split obligations become open obligations, and
    pass_through_connections are carried forward for resolution at seams."""
    return Subgraph(
        nodes=[Node(id=n.id, type=n.type, metadata=n.metadata) for n in result.nodes],
        edges=[Edge(a=e.a, b=e.b) for e in result.edges],
        open_connections=list(result.split_connections),
        open_nodes=list(result.split_nodes),
        uncertainties=[result.uncertainty] if result.uncertainty else [],
        pass_through_connections=list(result.pass_through_connections),
    )


def process(
    segment: Segment,
    leaf_reader: LeafReader,
    cut_config: CutConfig,
    stop_config: StopConfig,
    counters: Counters,
) -> Subgraph:
    """Recursively reads or cuts `segment`; returns its Subgraph, including any
    obligations still open on this segment's own boundary sides."""
    if should_stop_cutting(segment, stop_config):
        return subgraph_from_leaf(leaf_reader(segment))
    axis, position = best_cut(segment, cut_config)
    first_child, second_child = split(segment, axis, position)
    sub_a = process(first_child, leaf_reader, cut_config, stop_config, counters)
    sub_b = process(second_child, leaf_reader, cut_config, stop_config, counters)
    return merge(sub_a, sub_b, axis, counters)


def run(
    root: Segment,
    leaf_reader: LeafReader,
    cut_config: CutConfig,
    stop_config: StopConfig,
) -> PageGraph:
    """Top-level entrypoint: recursively processes `root` and collapses the
    resulting Subgraph into the final PageGraph."""
    counters = Counters()
    subgraph = process(root, leaf_reader, cut_config, stop_config, counters)
    return to_page_graph(subgraph, counters)
