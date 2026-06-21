# Unit tests for should_stop_cutting's three-way decision: sparse early-stop,
# dense lowered floor, and the default size floor.
from __future__ import annotations

import numpy as np

from engine.config import StopConfig
from engine.recurse.stop import should_stop_cutting
from engine.types import Box, Segment

_CONFIG = StopConfig(
    min_dim=50,
    min_area=2000,
    min_ink_density=0.05,
    dense_density_threshold=0.5,
    dense_min_dim=10,
    dense_min_area=50,
)


def _segment(image: np.ndarray, w: int, h: int) -> Segment:
    return Segment(
        image_uncolored=image,
        image_colored=image,
        bbox=Box(x=0, y=0, w=w, h=h),
        cut_sides={"top": False, "bottom": False, "left": False, "right": False},
        id="root",
    )


def test_sparse_segment_stops_even_when_large():
    image = np.full((200, 200), 255, dtype=np.uint8)  # blank: density 0.0
    segment = _segment(image, 200, 200)
    assert should_stop_cutting(segment, _CONFIG) is True


def test_dense_segment_keeps_cutting_below_default_floor_above_dense_floor():
    image = np.zeros((30, 30), dtype=np.uint8)  # solid ink: density 1.0
    segment = _segment(image, 30, 30)  # below min_dim=50, above dense_min_dim=10
    assert should_stop_cutting(segment, _CONFIG) is False


def test_dense_segment_stops_once_below_dense_floor():
    image = np.zeros((8, 8), dtype=np.uint8)  # solid ink: density 1.0
    segment = _segment(image, 8, 8)  # below dense_min_dim=10
    assert should_stop_cutting(segment, _CONFIG) is True


def test_moderate_density_uses_default_floor_not_dense_floor():
    image = np.full((30, 30), 255, dtype=np.uint8)
    image[:10, :10] = (
        0  # ~11% ink: above min_ink_density, below dense_density_threshold
    )
    segment = _segment(image, 30, 30)  # below default min_dim=50 -> should stop
    assert should_stop_cutting(segment, _CONFIG) is True
