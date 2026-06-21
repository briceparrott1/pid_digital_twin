# Applies a chosen cut to a segment, producing two non-overlapping child segments
# that exactly tile the parent's image and bbox.
from __future__ import annotations

from engine.types import Box, CutAxis, Segment


def split(segment: Segment, axis: CutAxis, position: int) -> tuple[Segment, Segment]:
    """Slices `segment` at `position` along `axis`; returns `(first_child,
    second_child)` = (L, R) for a vertical cut or (T, B) for a horizontal cut,
    with tiled bboxes, seam-marked cut_sides, and id suffixes appended."""
    bbox = segment.bbox
    if axis == "vertical":
        first_slice = (slice(None), slice(None, position))
        second_slice = (slice(None), slice(position, None))
        first_bbox = Box(x=bbox.x, y=bbox.y, w=position, h=bbox.h)
        second_bbox = Box(x=bbox.x + position, y=bbox.y, w=bbox.w - position, h=bbox.h)
        first_sides = {**segment.cut_sides, "right": True}
        second_sides = {**segment.cut_sides, "left": True}
        first_suffix, second_suffix = "L", "R"
    else:
        first_slice = (slice(None, position), slice(None))
        second_slice = (slice(position, None), slice(None))
        first_bbox = Box(x=bbox.x, y=bbox.y, w=bbox.w, h=position)
        second_bbox = Box(x=bbox.x, y=bbox.y + position, w=bbox.w, h=bbox.h - position)
        first_sides = {**segment.cut_sides, "bottom": True}
        second_sides = {**segment.cut_sides, "top": True}
        first_suffix, second_suffix = "T", "B"

    # The same crop rectangle is applied to both images identically, since
    # alignment between them is a contract guarantee, not something cut/split
    # establishes.
    first_child = Segment(
        image_uncolored=segment.image_uncolored[first_slice],
        image_colored=segment.image_colored[first_slice],
        bbox=first_bbox,
        cut_sides=first_sides,
        id=f"{segment.id}.{first_suffix}",
    )
    second_child = Segment(
        image_uncolored=segment.image_uncolored[second_slice],
        image_colored=segment.image_colored[second_slice],
        bbox=second_bbox,
        cut_sides=second_sides,
        id=f"{segment.id}.{second_suffix}",
    )
    return first_child, second_child
