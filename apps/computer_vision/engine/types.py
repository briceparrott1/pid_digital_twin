# Sealed data contracts for the engine-v2 deterministic spine: segments, leaf I/O,
# in-flight subgraphs, and the final page graph. Field names/types are exact; do not
# add or rename fields.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

CutAxis = Literal["horizontal", "vertical"]
Side = Literal["top", "bottom", "left", "right"]


@dataclass
class Box:
    """Absolute page-pixel rectangle: (x, y) is the top-left corner, row=y/col=x,
    so a segment's image is `page[y : y + h, x : x + w]`."""

    x: int
    y: int
    w: int
    h: int


@dataclass
class Segment:
    """One region of the recursion tree: its pixels (an uncolored crop for
    cutting decisions, a colored crop for the leaf VLM), absolute bbox, which
    of its four sides are seams (cuts) vs page edges, and its L/R/T/B path id."""

    image_uncolored: np.ndarray
    image_colored: np.ndarray
    bbox: Box
    cut_sides: dict[str, bool]
    id: str


@dataclass
class Node:
    """A resolved graph node: an equipment/instrument tag or a printed junction label."""

    id: str
    type: str
    metadata: dict = field(default_factory=dict)


@dataclass
class Edge:
    """An undirected edge between two node ids: {a, b} == {b, a}."""

    a: str
    b: str


@dataclass
class Diagnostics:
    """Correctness/quality signals computed once the page graph is assembled.
    `leftover_splits` is obligations still open at the root (expected for a
    genuine page-edge truncation); `seam_pairing_failures` is obligations that
    faced a real internal seam and found no partner there -- a true matching
    failure, geometrically unable to ever resolve at any later seam."""

    leftover_splits: list = field(default_factory=list)
    untagged_count: int = 0
    seam_collisions: int = 0
    equipment_merges: int = 0
    seam_pairing_failures: list = field(default_factory=list)


@dataclass
class PageGraph:
    """Final output of the pipeline: the whole page's nodes, edges, and diagnostics."""

    nodes: list[Node]
    edges: list[Edge]
    diagnostics: Diagnostics


@dataclass
class LeafNode:
    """A node read by the leaf reader, fully contained within its segment."""

    id: str
    type: str
    metadata: dict = field(default_factory=dict)


@dataclass
class LeafEdge:
    """An edge read by the leaf reader; both ends are inside the same segment."""

    a: str
    b: str


@dataclass
class SplitConnection:
    """A line obligation: one end attaches to `node` in this segment, the rest
    crosses `side`. Join key for resolution is (color, label)."""

    node: str
    color: str
    label: str
    side: Side


@dataclass
class PassThroughConnection:
    """A line that enters this crop on `side_in` and exits on `side_out`, with
    no node endpoint visible on either side inside this crop. At each merge
    whichever face touches the seam is converted into a SplitConnection (node=""
    carrying that face's label) so it can pair with the adjacent segment's
    matching SplitConnection; the remaining face propagates as a SplitConnection
    toward the next ancestor seam."""

    color: str
    label_in: str
    side_in: Side
    label_out: str
    side_out: Side


@dataclass
class SplitNode:
    """An equipment/junction fragment obligation: still open on every side in
    `sides`; `edges` accumulates as fragments fuse across seams. An entry in
    `edges` may use `SELF_REF` in place of this node's own (not yet known)
    id -- resolved to the real id once the fragment is whole."""

    id: str | None
    type: str
    metadata: dict = field(default_factory=dict)
    sides: list[str] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


SELF_REF = "\0self"
"""Sentinel `Edge` endpoint meaning "this SplitNode itself" -- used when a
connection to an untagged split fragment is recorded before the fragment has
a resolved id. Never a legal node id, so it can't collide with a real tag."""


@dataclass
class LeafResult:
    """Everything one VLM call returns for a single leaf segment."""

    nodes: list[LeafNode]
    edges: list[LeafEdge]
    split_connections: list[SplitConnection]
    split_nodes: list[SplitNode]
    uncertainty: str = ""
    pass_through_connections: list[PassThroughConnection] = field(
        default_factory=list
    )


@dataclass
class Subgraph:
    """In-flight graph for a segment: resolved nodes/edges plus obligations still
    open on this segment's own boundary, free-text uncertainties accumulated
    from descendant leaf reads, obligations permanently retired because they
    faced a real seam and found no partner (`failed_splits`), and lines still
    in transit through this region with no visible endpoint on either face
    (`pass_through_connections`)."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    open_connections: list[SplitConnection] = field(default_factory=list)
    open_nodes: list[SplitNode] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    failed_splits: list = field(default_factory=list)
    pass_through_connections: list[PassThroughConnection] = field(
        default_factory=list
    )
