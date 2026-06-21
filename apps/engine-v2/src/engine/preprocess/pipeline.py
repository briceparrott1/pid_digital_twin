# Loads the colored/uncolored PDF pair for one page, renders both at a shared
# DPI, and builds the root Segment for recursion. Does no line/junction
# detection -- that is baked into the colored PDF before it reaches this repo.
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from engine.config import RenderConfig
from engine.preprocess.render import render_pdf
from engine.types import Box, Segment

logger = logging.getLogger(__name__)


def load_pair(
    data_dir: str, render_config: RenderConfig
) -> tuple[np.ndarray, np.ndarray]:
    """Loads `{data_dir}/colored.pdf` and `{data_dir}/uncolored.pdf` (fixed
    names, no globbing) and renders both at `render_config.dpi`. Raises if
    either file is missing (naming it) or if the renders differ in pixel
    dimensions. Logs a non-gating alignment diagnostic; does not certify
    pixel-level registration. Returns `(image_colored, image_uncolored)`."""
    colored_path = Path(data_dir) / "colored.pdf"
    uncolored_path = Path(data_dir) / "uncolored.pdf"
    if not colored_path.exists():
        raise FileNotFoundError(f"expected {colored_path}, not found")
    if not uncolored_path.exists():
        raise FileNotFoundError(f"expected {uncolored_path}, not found")

    image_colored = render_pdf(str(colored_path), render_config.dpi)
    image_uncolored = render_pdf(str(uncolored_path), render_config.dpi)

    if image_colored.shape[:2] != image_uncolored.shape[:2]:
        raise ValueError(
            "colored/uncolored renders differ in size: "
            f"{image_colored.shape[:2]} vs {image_uncolored.shape[:2]}"
        )

    _log_alignment_signal(image_colored, image_uncolored)
    return image_colored, image_uncolored


def _log_alignment_signal(
    image_colored: np.ndarray, image_uncolored: np.ndarray
) -> None:
    """Logs an edge-map disagreement count between the two renders. This is an
    informational signal only -- equal dimensions plus a low edge-diff count
    does not certify pixel registration; it never raises or gates anything."""
    gray_colored = cv2.cvtColor(image_colored, cv2.COLOR_BGR2GRAY)
    gray_uncolored = cv2.cvtColor(image_uncolored, cv2.COLOR_BGR2GRAY)
    edges_colored = cv2.Canny(gray_colored, 50, 150)
    edges_uncolored = cv2.Canny(gray_uncolored, 50, 150)
    diff_count = int(np.count_nonzero(cv2.bitwise_xor(edges_colored, edges_uncolored)))
    logger.info(
        "alignment edge-diff count=%d (informational only, does not certify alignment)",
        diff_count,
    )


def build_root_segment(
    image_colored: np.ndarray, image_uncolored: np.ndarray
) -> Segment:
    """Builds the root Segment for the full page: no side has been cut yet."""
    height, width = image_uncolored.shape[:2]
    return Segment(
        image_uncolored=image_uncolored,
        image_colored=image_colored,
        bbox=Box(x=0, y=0, w=width, h=height),
        cut_sides={"top": False, "bottom": False, "left": False, "right": False},
        id="root",
    )
