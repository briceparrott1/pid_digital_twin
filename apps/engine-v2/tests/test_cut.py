# Unit tests for cost_map (dilation/band scoring) and best_cut/split selection logic.
from __future__ import annotations

import numpy as np

from engine.config import CutConfig
from engine.cut.best_cut import best_cut, candidate_positions
from engine.cut.cost_map import band_sum, binarize, dilate_ink, ink_density
from engine.cut.split import split
from engine.types import Box, Segment


def _white(h: int, w: int) -> np.ndarray:
    return np.full((h, w), 255, dtype=np.uint8)


def _config(**overrides) -> CutConfig:
    base = dict(
        dilation_radius=2,
        band_width=5,
        midpoint_lambda=0.01,
        candidate_step_px=2,
        edge_margin_px=4,
        min_split_fraction=0.0,
    )
    base.update(overrides)
    return CutConfig(**base)


def test_band_over_whitespace_scores_zero():
    image = _white(40, 40)
    dilated = dilate_ink(binarize(image), radius=2)
    assert band_sum(dilated, "vertical", 20, band_width=5) == 0


def test_band_over_dense_blob_scores_high():
    image = _white(40, 40)
    image[10:30, 10:30] = 0  # dense filled square ("text/symbol blob")
    dilated = dilate_ink(binarize(image), radius=2)
    blob_score = band_sum(dilated, "vertical", 20, band_width=5)
    whitespace_score = band_sum(dilated, "vertical", 2, band_width=5)
    assert blob_score > whitespace_score
    assert blob_score > 0


def test_band_crossing_thin_line_scores_low():
    image = _white(40, 40)
    image[:, 19:20] = 0  # single thin vertical line
    image[5:35, 25:35] = 0  # dense blob, for comparison
    dilated = dilate_ink(binarize(image), radius=1)
    # A horizontal band crossing the thin line perpendicularly picks up far
    # fewer pixels than the same-width band crossing the dense blob.
    line_score = band_sum(dilated, "horizontal", 20, band_width=5)
    blob_score = band_sum(dilated, "vertical", 30, band_width=5)
    assert 0 < line_score < blob_score


def test_ink_density_is_zero_for_blank_image():
    assert ink_density(_white(40, 40)) == 0.0


def test_ink_density_reflects_ink_fraction():
    image = _white(40, 40)
    image[:, :20] = 0  # exactly half the image is ink
    assert ink_density(image) == 0.5


def test_dilation_fuses_symbol_and_nearby_tag():
    image = _white(40, 40)
    image[10:15, 5:10] = 0  # symbol
    image[10:15, 13:18] = 0  # tag, separated by a 3px gap
    binary = binarize(image)
    undilated_gap_sum = int(binary[10:15, 10:13].sum())
    dilated = dilate_ink(binary, radius=3)
    dilated_gap_sum = int(dilated[10:15, 10:13].sum())
    assert undilated_gap_sum == 0
    assert dilated_gap_sum > 0  # gap is now covered by the fused blob


def test_best_cut_picks_clear_whitespace_corridor_near_midpoint():
    image = _white(60, 60)
    image[5:55, 5:15] = 0  # dense blob on the left
    image[5:55, 45:55] = 0  # dense blob on the right
    # whitespace corridor sits between columns ~15 and ~45, centered near 30
    segment = Segment(
        image_uncolored=image,
        image_colored=image.copy(),
        bbox=Box(0, 0, 60, 60),
        cut_sides={},
        id="root",
    )
    config = _config()
    axis, position = best_cut(segment, config)
    assert axis == "vertical"
    assert 20 <= position <= 40


def test_best_cut_never_reads_image_colored():
    image = _white(60, 60)
    image[5:55, 5:15] = 0
    image[5:55, 45:55] = 0
    # A sentinel with no array behavior at all: any access to .ndim, slicing,
    # or cv2 calls on it would raise immediately, proving cost_map/best_cut
    # never touch image_colored.
    segment = Segment(
        image_uncolored=image,
        image_colored="SENTINEL: must never be read by cut logic",
        bbox=Box(0, 0, 60, 60),
        cut_sides={},
        id="root",
    )
    axis, position = best_cut(segment, _config())
    assert axis == "vertical"


def test_candidate_positions_excludes_near_edge_when_fraction_set():
    config = _config(min_split_fraction=0.35, edge_margin_px=2)
    positions = candidate_positions(100, config)
    assert min(positions) >= 35
    assert max(positions) <= 65


def test_candidate_positions_falls_back_to_pixel_margin_when_fraction_is_zero():
    config = _config(min_split_fraction=0.0, edge_margin_px=4)
    positions = candidate_positions(100, config)
    assert min(positions) == 4


def test_best_cut_avoids_sliver_when_cheapest_corridor_is_near_edge():
    # A near-edge whitespace corridor (cols 0-~25) is cheap (zero ink) and,
    # without a balance constraint, wins over the far costlier mid corridor
    # -- producing a sliver. min_split_fraction excludes it from consideration
    # entirely, forcing the chosen cut to leave each side >=35% of the width.
    image = _white(40, 100)
    image[:, 48:52] = 0  # obstruction centered in the segment
    config = _config(min_split_fraction=0.35, edge_margin_px=2, midpoint_lambda=0.0)
    segment = Segment(
        image_uncolored=image,
        image_colored=image.copy(),
        bbox=Box(0, 0, 100, 40),
        cut_sides={},
        id="root",
    )
    axis, position = best_cut(segment, config)
    assert axis == "vertical"
    assert 35 <= position <= 65


def test_split_tiles_parent_exactly_vertical():
    uncolored = _white(30, 50)
    colored = np.full((30, 50), 128, dtype=np.uint8)
    segment = Segment(
        image_uncolored=uncolored,
        image_colored=colored,
        bbox=Box(x=100, y=200, w=50, h=30),
        cut_sides={"top": False, "bottom": False, "left": False, "right": False},
        id="root",
    )
    first, second = split(segment, "vertical", 20)
    assert first.bbox == Box(x=100, y=200, w=20, h=30)
    assert second.bbox == Box(x=120, y=200, w=30, h=30)
    assert first.image_uncolored.shape == (30, 20)
    assert second.image_uncolored.shape == (30, 30)
    # The colored crop is sliced with the identical bounds, so it stays
    # aligned (same shape) with its sibling's uncolored crop at every level.
    assert first.image_colored.shape == first.image_uncolored.shape
    assert second.image_colored.shape == second.image_uncolored.shape
    assert np.array_equal(first.image_colored, colored[:, :20])
    assert np.array_equal(second.image_colored, colored[:, 20:])
    assert first.cut_sides == {
        "top": False,
        "bottom": False,
        "left": False,
        "right": True,
    }
    assert second.cut_sides == {
        "top": False,
        "bottom": False,
        "left": True,
        "right": False,
    }
    assert first.id == "root.L"
    assert second.id == "root.R"


def test_split_tiles_parent_exactly_horizontal():
    uncolored = _white(30, 50)
    colored = np.full((30, 50), 128, dtype=np.uint8)
    segment = Segment(
        image_uncolored=uncolored,
        image_colored=colored,
        bbox=Box(x=0, y=0, w=50, h=30),
        cut_sides={"top": True, "bottom": False, "left": False, "right": False},
        id="root.R",
    )
    first, second = split(segment, "horizontal", 12)
    assert first.bbox == Box(x=0, y=0, w=50, h=12)
    assert second.bbox == Box(x=0, y=12, w=50, h=18)
    assert first.image_colored.shape == first.image_uncolored.shape
    assert second.image_colored.shape == second.image_uncolored.shape
    assert np.array_equal(first.image_colored, colored[:12, :])
    assert np.array_equal(second.image_colored, colored[12:, :])
    assert first.cut_sides == {
        "top": True,
        "bottom": True,
        "left": False,
        "right": False,
    }
    assert second.cut_sides == {
        "top": True,
        "bottom": False,
        "left": False,
        "right": False,
    }
    assert first.id == "root.R.T"
    assert second.id == "root.R.B"
