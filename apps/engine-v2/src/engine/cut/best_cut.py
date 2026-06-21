# Searches candidate cut positions on both axes against the dilated ink map and
# picks the lowest band_sum + midpoint-bias cost; always returns a cut.
from __future__ import annotations

from engine.config import CutConfig
from engine.cut.cost_map import band_sum, binarize, dilate_ink
from engine.types import CutAxis, Segment


def candidate_positions(dim: int, config: CutConfig) -> list[int]:
    """Enumerates valid candidate cut positions along one axis of length `dim`,
    excluding positions within `margin` of either edge. `margin` is the larger
    of `config.edge_margin_px` and `config.min_split_fraction * dim` -- a
    fixed-pixel margin alone doesn't scale across recursion depths and would
    let a cut land a sliver's width from the edge on a large segment."""
    margin = max(config.edge_margin_px, round(dim * config.min_split_fraction))
    positions = list(range(margin, dim - margin, config.candidate_step_px))
    return positions if positions else [dim // 2]


def cost(dilated, axis: CutAxis, position: int, dim: int, config: CutConfig) -> float:
    """Combined cost for one candidate: dilated-ink band sum plus a weak bias
    toward the segment's midpoint along `axis`."""
    midpoint_term = config.midpoint_lambda * abs(position - dim / 2)
    return band_sum(dilated, axis, position, config.band_width) + midpoint_term


def best_cut(segment: Segment, config: CutConfig) -> tuple[CutAxis, int]:
    """Scores every candidate cut on both axes and returns the global-minimum
    `(axis, position)`; ties between axes are broken in favor of vertical."""
    binary = binarize(segment.image_uncolored)
    dilated = dilate_ink(binary, config.dilation_radius)
    height, width = dilated.shape[:2]

    v_positions = candidate_positions(width, config)
    h_positions = candidate_positions(height, config)

    best_v_pos = min(
        v_positions, key=lambda p: cost(dilated, "vertical", p, width, config)
    )
    best_v_cost = cost(dilated, "vertical", best_v_pos, width, config)

    best_h_pos = min(
        h_positions, key=lambda p: cost(dilated, "horizontal", p, height, config)
    )
    best_h_cost = cost(dilated, "horizontal", best_h_pos, height, config)

    if best_v_cost <= best_h_cost:
        return "vertical", best_v_pos
    return "horizontal", best_h_pos
