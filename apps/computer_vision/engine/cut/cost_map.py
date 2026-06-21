# Builds the dilated binary ink map for a segment and scores candidate cut bands
# against it; this is the only place pixel intensities are inspected for cutting.
from __future__ import annotations

import cv2
import numpy as np

from engine.types import CutAxis


def binarize(image: np.ndarray) -> np.ndarray:
    """Thresholds `image` (grayscale or BGR) to a 0/1 ink mask; 1 = dark/ink pixel."""
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    _, mask = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return mask.astype(np.uint8)


def ink_density(image: np.ndarray) -> float:
    """Fraction of ink pixels in `image` (same Otsu threshold as `binarize`).
    A content-density signal for the stop decision -- not used by the cut
    search itself."""
    return float(binarize(image).mean())


def dilate_ink(binary: np.ndarray, radius: int) -> np.ndarray:
    """Grows `binary` ink regions by `radius` so a nearby symbol and its tag fuse
    into one blob, closing the gap a cut could otherwise slip through."""
    if radius <= 0:
        return binary
    kernel_size = 2 * radius + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    return cv2.dilate(binary, kernel)


def band_sum(dilated: np.ndarray, axis: CutAxis, position: int, band_width: int) -> int:
    """Sums dilated-ink pixels in the band of width `band_width` around `position`
    on `axis`, clipped to image bounds; the raw "stuff crossed" cost term."""
    half = band_width // 2
    if axis == "vertical":
        dim = dilated.shape[1]
        lo, hi = max(0, position - half), min(dim, position + half + 1)
        return int(dilated[:, lo:hi].sum())
    dim = dilated.shape[0]
    lo, hi = max(0, position - half), min(dim, position + half + 1)
    return int(dilated[lo:hi, :].sum())
