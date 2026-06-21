# Unit tests for load_pair (fixed-filename PDF discovery, dimension check,
# alignment diagnostic) and build_root_segment.
from __future__ import annotations

import logging

import fitz
import numpy as np
import pytest

from engine.config import RenderConfig
from engine.preprocess.pipeline import build_root_segment, load_pair

_CONFIG = RenderConfig(dpi=72)


def _make_pdf(path, width: float, height: float) -> None:
    doc = fitz.open()
    doc.new_page(width=width, height=height)
    doc.save(str(path))
    doc.close()


def test_load_pair_returns_both_images_at_matching_dimensions(tmp_path):
    _make_pdf(tmp_path / "colored.pdf", 200, 100)
    _make_pdf(tmp_path / "uncolored.pdf", 200, 100)
    image_colored, image_uncolored = load_pair(str(tmp_path), _CONFIG)
    assert image_colored.shape[:2] == (100, 200)
    assert image_uncolored.shape[:2] == (100, 200)


def test_load_pair_ignores_unrelated_pdf_in_data_dir(tmp_path):
    _make_pdf(tmp_path / "colored.pdf", 200, 100)
    _make_pdf(tmp_path / "uncolored.pdf", 200, 100)
    _make_pdf(tmp_path / "other.pdf", 50, 50)
    image_colored, image_uncolored = load_pair(str(tmp_path), _CONFIG)
    assert image_colored.shape[:2] == (100, 200)


def test_load_pair_raises_naming_missing_colored_file(tmp_path):
    _make_pdf(tmp_path / "uncolored.pdf", 200, 100)
    with pytest.raises(FileNotFoundError, match="colored.pdf"):
        load_pair(str(tmp_path), _CONFIG)


def test_load_pair_raises_naming_missing_uncolored_file(tmp_path):
    _make_pdf(tmp_path / "colored.pdf", 200, 100)
    with pytest.raises(FileNotFoundError, match="uncolored.pdf"):
        load_pair(str(tmp_path), _CONFIG)


def test_load_pair_raises_on_dimension_mismatch(tmp_path):
    _make_pdf(tmp_path / "colored.pdf", 200, 100)
    _make_pdf(tmp_path / "uncolored.pdf", 150, 100)
    with pytest.raises(ValueError):
        load_pair(str(tmp_path), _CONFIG)


def test_load_pair_logs_alignment_diagnostic_without_raising(tmp_path, caplog):
    _make_pdf(tmp_path / "colored.pdf", 200, 100)
    _make_pdf(tmp_path / "uncolored.pdf", 200, 100)
    with caplog.at_level(logging.INFO, logger="engine.preprocess.pipeline"):
        load_pair(str(tmp_path), _CONFIG)
    assert any("edge-diff" in record.message for record in caplog.records)


def test_build_root_segment_has_full_page_box_and_no_cut_sides():
    image_uncolored = np.zeros((100, 200, 3), dtype=np.uint8)
    image_colored = np.zeros((100, 200, 3), dtype=np.uint8)
    segment = build_root_segment(image_colored, image_uncolored)
    assert segment.id == "root"
    assert segment.bbox.x == 0 and segment.bbox.y == 0
    assert segment.bbox.w == 200 and segment.bbox.h == 100
    assert segment.cut_sides == {
        "top": False,
        "bottom": False,
        "left": False,
        "right": False,
    }
