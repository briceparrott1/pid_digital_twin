# Decides whether a segment is small enough, or sparse enough, to stop
# cutting and become a leaf.
from __future__ import annotations

from engine.config import StopConfig
from engine.cut.cost_map import ink_density
from engine.types import Segment


def should_stop_cutting(segment: Segment, config: StopConfig) -> bool:
    """True if `segment` should be read as a leaf instead of cut further:
    either it's too sparse to be worth a call (`min_ink_density`), or it's
    below the size floor for its density tier -- dense segments
    (>= `dense_density_threshold`) use the lower `dense_min_dim`/
    `dense_min_area` floor instead of `min_dim`/`min_area`."""
    density = ink_density(segment.image_uncolored)
    if density < config.min_ink_density:
        return True
    bbox = segment.bbox
    if density >= config.dense_density_threshold:
        min_dim, min_area = config.dense_min_dim, config.dense_min_area
    else:
        min_dim, min_area = config.min_dim, config.min_area
    return min(bbox.w, bbox.h) < min_dim or bbox.w * bbox.h < min_area
