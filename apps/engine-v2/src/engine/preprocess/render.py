# Renders a single-page PDF to a BGR ndarray via PyMuPDF, at a caller-supplied DPI.
from __future__ import annotations

import cv2
import fitz
import numpy as np


def render_pdf(pdf_path: str, dpi: int) -> np.ndarray:
    """Renders page 0 of `pdf_path` at `dpi` into a BGR `np.ndarray` (OpenCV
    convention, matching what `cut/cost_map.py` expects). Raises if the PDF has
    more than one page — multi-page handling is not in scope here."""
    doc = fitz.open(pdf_path)
    if doc.page_count != 1:
        raise ValueError(
            f"expected a single-page PDF, got {doc.page_count} pages: {pdf_path}"
        )
    page = doc[0]
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pixmap = page.get_pixmap(matrix=matrix)
    rgb = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
