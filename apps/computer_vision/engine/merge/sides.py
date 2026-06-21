# Maps obligation boundary sides between a cut's two children and the parent's
# frame: which side is the seam this cut produced, and how a non-seam side
# propagates upward unchanged.
from __future__ import annotations

from typing import Literal

from engine.types import CutAxis

WhichChild = Literal["first", "second"]

_FACING_SIDE = {
    ("vertical", "first"): "right",
    ("vertical", "second"): "left",
    ("horizontal", "first"): "bottom",
    ("horizontal", "second"): "top",
}


def facing_side(axis: CutAxis, which_child: WhichChild) -> str:
    """Returns the side name, in the child's own frame, that this cut produced."""
    return _FACING_SIDE[(axis, which_child)]


def is_facing(axis: CutAxis, which_child: WhichChild, side: str) -> bool:
    """True if `side` (reported in the child's own frame) is the seam this cut
    just made, i.e. should be resolved here rather than propagated upward."""
    return side == facing_side(axis, which_child)


def retranslate(side: str) -> str:
    """Propagates a non-facing side into the parent's frame. A cut never relabels
    the two sides parallel to its own axis, so this is the identity map; kept as
    a named function as a seam for any future geometric retranslation need."""
    return side
