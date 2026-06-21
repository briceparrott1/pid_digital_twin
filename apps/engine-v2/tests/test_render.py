# Unit tests for render_pdf: single-page rendering at a given DPI, and the
# explicit refusal to silently pick a page out of a multi-page PDF.
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from engine.preprocess.render import render_pdf


def _make_pdf(path: Path, page_sizes: list[tuple[float, float]]) -> None:
    doc = fitz.open()
    for width, height in page_sizes:
        doc.new_page(width=width, height=height)
    doc.save(str(path))
    doc.close()


def test_render_pdf_returns_expected_dimensions(tmp_path):
    pdf_path = tmp_path / "page.pdf"
    _make_pdf(pdf_path, [(200, 100)])
    # dpi=72 means matrix scale is 1.0, so pixel dims equal point dims exactly.
    image = render_pdf(str(pdf_path), dpi=72)
    assert image.shape[:2] == (100, 200)
    assert image.shape[2] == 3


def test_render_pdf_raises_on_multi_page_pdf(tmp_path):
    pdf_path = tmp_path / "multi.pdf"
    _make_pdf(pdf_path, [(200, 100), (200, 100)])
    with pytest.raises(ValueError):
        render_pdf(str(pdf_path), dpi=72)
