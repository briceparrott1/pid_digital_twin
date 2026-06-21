# End-to-end tests: real recursion + merge over a hand-built two-leaf page,
# driven by an injected fake leaf reader (zero model calls).
from __future__ import annotations

import numpy as np

from engine.config import CutConfig, StopConfig
from engine.recurse.process import run
from engine.types import (
    Box,
    Edge,
    LeafEdge,
    LeafNode,
    LeafResult,
    Node,
    Segment,
    SplitConnection,
)

# A clear whitespace corridor centered at x=40 in an 80x80 page: full-height ink
# blocks on each side make the vertical cut win decisively, and the midpoint
# bias makes x=40 the unique minimum-cost position.
_WIDTH, _HEIGHT = 80, 80


def _page_image() -> np.ndarray:
    image = np.full((_HEIGHT, _WIDTH), 255, dtype=np.uint8)
    image[:, :30] = 0
    image[:, 50:] = 0
    return image


def _root_segment() -> Segment:
    # The colored image plays no role in cutting decisions; any same-shape
    # filler array is fine here since no leaf reader exists yet to consume it.
    uncolored = _page_image()
    colored = np.zeros_like(uncolored)
    return Segment(
        image_uncolored=uncolored,
        image_colored=colored,
        bbox=Box(x=0, y=0, w=_WIDTH, h=_HEIGHT),
        cut_sides={"top": False, "bottom": False, "left": False, "right": False},
        id="root",
    )


_CUT_CONFIG = CutConfig(
    dilation_radius=1,
    band_width=3,
    midpoint_lambda=0.01,
    candidate_step_px=1,
    edge_margin_px=5,
    min_split_fraction=0.0,
)
_STOP_CONFIG = StopConfig(
    min_dim=50,
    min_area=1,
    min_ink_density=0.0,
    dense_density_threshold=2.0,  # unreachable (density is a 0-1 fraction)
    dense_min_dim=50,
    dense_min_area=1,
)


def _well_formed_fixtures() -> dict[str, LeafResult]:
    return {
        "root.L": LeafResult(
            nodes=[LeafNode(id="V1", type="valve", metadata={})],
            edges=[],
            split_connections=[
                SplitConnection(node="V1", color="red", label="L1", side="right")
            ],
            split_nodes=[],
        ),
        "root.R": LeafResult(
            nodes=[LeafNode(id="V2", type="valve", metadata={})],
            edges=[],
            split_connections=[
                SplitConnection(node="V2", color="red", label="L1", side="left")
            ],
            split_nodes=[],
        ),
    }


def test_end_to_end_matches_known_answer_graph():
    fixtures = _well_formed_fixtures()
    page = run(_root_segment(), lambda seg: fixtures[seg.id], _CUT_CONFIG, _STOP_CONFIG)
    assert sorted(page.nodes, key=lambda n: n.id) == [
        Node(id="V1", type="valve", metadata={}),
        Node(id="V2", type="valve", metadata={}),
    ]
    assert {frozenset((e.a, e.b)) for e in page.edges} == {frozenset(("V1", "V2"))}


def test_well_formed_fixture_yields_zero_leftover_splits():
    fixtures = _well_formed_fixtures()
    page = run(_root_segment(), lambda seg: fixtures[seg.id], _CUT_CONFIG, _STOP_CONFIG)
    assert page.diagnostics.leftover_splits == []


def test_malformed_fixture_with_dangling_obligation_flags_leftover_splits():
    fixtures = _well_formed_fixtures()
    # root.L reports an extra connection facing "top", a true page edge (never a
    # seam in this tree) -- no cut anywhere can ever resolve it; a real bug. The
    # original V1/V2 pairing is left intact so this is the only leftover.
    fixtures["root.L"] = LeafResult(
        nodes=[LeafNode(id="V1", type="valve", metadata={})],
        edges=[],
        split_connections=[
            SplitConnection(node="V1", color="red", label="L1", side="right"),
            SplitConnection(node="V3", color="blue", label="L2", side="top"),
        ],
        split_nodes=[],
    )
    page = run(_root_segment(), lambda seg: fixtures[seg.id], _CUT_CONFIG, _STOP_CONFIG)
    assert len(page.diagnostics.leftover_splits) == 1
    leftover = page.diagnostics.leftover_splits[0]
    assert isinstance(leftover, SplitConnection)
    assert leftover.side == "top"
    assert leftover.node == "V3"


def test_leaf_edges_pass_through_within_a_single_leaf():
    fixtures = _well_formed_fixtures()
    fixtures["root.L"] = LeafResult(
        nodes=[
            LeafNode(id="V1", type="valve", metadata={}),
            LeafNode(id="J1", type="junction", metadata={}),
        ],
        edges=[LeafEdge(a="V1", b="J1")],
        split_connections=[
            SplitConnection(node="J1", color="red", label="L1", side="right")
        ],
        split_nodes=[],
    )
    page = run(_root_segment(), lambda seg: fixtures[seg.id], _CUT_CONFIG, _STOP_CONFIG)
    assert Edge(a="V1", b="J1") in page.edges
