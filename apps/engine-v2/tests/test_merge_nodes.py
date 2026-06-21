# Unit tests for SplitNode fusion: single-seam fuse to whole, multi-seam fuse
# across two recursion levels, edge unioning, and equipment_merges counting.
from __future__ import annotations

from engine.instrument.counters import Counters
from engine.merge.merge import merge
from engine.merge.nodes import to_node
from engine.types import SELF_REF, Edge, Node, SplitNode, Subgraph


def test_single_side_split_node_fuses_to_whole_and_inherits_id():
    sub_a = Subgraph(
        open_nodes=[
            SplitNode(
                id=None, type="vessel", sides=["right"], edges=[Edge(a="A", b="B")]
            )
        ]
    )
    sub_b = Subgraph(
        open_nodes=[
            SplitNode(
                id="V1", type="vessel", sides=["left"], edges=[Edge(a="C", b="D")]
            )
        ]
    )
    counters = Counters()
    result = merge(sub_a, sub_b, "vertical", counters)
    assert result.open_nodes == []
    assert result.nodes == [Node(id="V1", type="vessel", metadata={})]
    assert set((e.a, e.b) for e in result.edges) == {("A", "B"), ("C", "D")}
    assert counters.equipment_merges == 1


def test_split_node_cut_on_two_sides_resolves_across_two_levels():
    counters = Counters()

    # Level 1: an inner horizontal cut resolves the "bottom"/"top" seam, but the
    # fragment is still open on "right" (a seam this level didn't make).
    sub_top = Subgraph(
        open_nodes=[
            SplitNode(
                id="V1",
                type="vessel",
                sides=["bottom", "right"],
                edges=[Edge(a="X", b="Y")],
            )
        ]
    )
    sub_bottom = Subgraph(
        open_nodes=[SplitNode(id=None, type="vessel", sides=["top"], edges=[])]
    )
    sub_left = merge(sub_top, sub_bottom, "horizontal", counters)
    assert counters.equipment_merges == 0  # not whole yet
    assert len(sub_left.open_nodes) == 1
    assert sub_left.open_nodes[0].sides == ["right"]

    # Level 2: the outer vertical cut resolves the remaining "right"/"left" seam.
    sub_right = Subgraph(
        open_nodes=[
            SplitNode(
                id=None, type="vessel", sides=["left"], edges=[Edge(a="Y", b="Z")]
            )
        ]
    )
    root_sub = merge(sub_left, sub_right, "vertical", counters)
    assert counters.equipment_merges == 1
    assert root_sub.open_nodes == []
    assert root_sub.nodes == [Node(id="V1", type="vessel", metadata={})]
    assert set((e.a, e.b) for e in root_sub.edges) == {("X", "Y"), ("Y", "Z")}


def test_asymmetric_leftover_split_node_retires_into_failed_splits():
    # Two fragments face this seam on sub_a's side, only one on sub_b's --
    # the unmatched extra is retired (its only open side failed here), not
    # carried forward to risk a false fuse at some later, unrelated seam.
    sub_a = Subgraph(
        open_nodes=[
            SplitNode(id="V1", type="vessel", sides=["right"]),
            SplitNode(id="V2", type="vessel", sides=["right"]),
        ]
    )
    sub_b = Subgraph(open_nodes=[SplitNode(id="V1", type="vessel", sides=["left"])])
    counters = Counters()
    result = merge(sub_a, sub_b, "vertical", counters)
    assert counters.equipment_merges == 1
    assert result.nodes == [Node(id="V1", type="vessel", metadata={})]
    assert result.open_nodes == []
    assert len(result.failed_splits) == 1
    assert result.failed_splits[0].id == "V2"


def test_asymmetric_leftover_split_node_keeps_its_other_open_sides():
    # The unmatched fragment is also open on "top" (an unrelated direction
    # this vertical cut never touches) -- only "right" (the side that failed
    # here) is retired; "top" must remain open for a future seam.
    sub_a = Subgraph(
        open_nodes=[SplitNode(id="V2", type="vessel", sides=["right", "top"])]
    )
    sub_b = Subgraph()
    counters = Counters()
    result = merge(sub_a, sub_b, "vertical", counters)
    assert result.failed_splits == []
    assert len(result.open_nodes) == 1
    assert result.open_nodes[0].sides == ["top"]


def test_to_node_substitutes_resolved_id_for_self_ref():
    node = SplitNode(
        id="V1", type="vessel", sides=[], edges=[Edge(a="MV-1", b=SELF_REF)]
    )
    resolved, edges = to_node(node)
    assert resolved == Node(id="V1", type="vessel", metadata={})
    assert edges == [Edge(a="MV-1", b="V1")]


def test_to_node_substitutes_empty_string_for_self_ref_when_untagged():
    node = SplitNode(
        id=None, type="vessel", sides=[], edges=[Edge(a="MV-1", b=SELF_REF)]
    )
    resolved, edges = to_node(node)
    assert resolved == Node(id="", type="vessel", metadata={})
    assert edges == [Edge(a="MV-1", b="")]
