# Integration tests for run_pipeline: wires load_pair -> build_root_segment ->
# run -> diagnostics dict, with a fake leaf reader. Also covers the -r/--record
# and --no-vlm helpers (stub reader, run dir numbering, segment dir mapping,
# recording wrapper), and the two-pass parallel VLM flow (_collect_leaves,
# _parallel_leaf_read). No real API call, no real PDFs from /data.
from __future__ import annotations

import asyncio
import json

import cv2
import fitz
import numpy as np
import pytest

from engine.config import CutConfig, EngineConfig, RenderConfig, StopConfig, VlmConfig
from engine.leaf.leaf_read import LeafParseError
from engine.preprocess.pipeline import build_root_segment
from engine.types import Box, LeafEdge, LeafNode, LeafResult, Segment, SplitNode
from scripts.run import (
    _collect_leaves,
    _draw_segment_overlay,
    _next_run_dir,
    _parallel_leaf_read,
    _recording_leaf_reader,
    _segment_dir,
    _stub_leaf_reader,
    run_pipeline,
)

_WIDTH, _HEIGHT = 80, 80


def _make_pdf(path, width: float, height: float) -> None:
    doc = fitz.open()
    doc.new_page(width=width, height=height)
    doc.save(str(path))
    doc.close()


def _make_pair(data_dir) -> None:
    _make_pdf(data_dir / "colored.pdf", _WIDTH, _HEIGHT)
    _make_pdf(data_dir / "uncolored.pdf", _WIDTH, _HEIGHT)


def _config() -> EngineConfig:
    # min_dim/min_area comfortably above the rendered page size, so the root
    # segment stops immediately and is read as a single leaf -- the cut/merge
    # path is already covered by test_recurse.py; this exercises the wiring.
    return EngineConfig(
        stop=StopConfig(
            min_dim=1000,
            min_area=1_000_000,
            min_ink_density=0.0,
            dense_density_threshold=2.0,
            dense_min_dim=1000,
            dense_min_area=1_000_000,
        ),
        cut=CutConfig(
            dilation_radius=1,
            band_width=3,
            midpoint_lambda=0.01,
            candidate_step_px=1,
            edge_margin_px=5,
            min_split_fraction=0.35,
        ),
        render=RenderConfig(dpi=72),
        vlm=VlmConfig(
            model="fake",
            max_tokens=1,
            max_retries=1,
            backoff_seconds=0.0,
            thinking_effort="",
        ),
    )


def _fake_leaf_reader(segment):
    return LeafResult(
        nodes=[LeafNode(id="V1", type="valve", metadata={})],
        edges=[],
        split_connections=[],
        split_nodes=[],
    )


def test_run_pipeline_returns_graph_and_diagnostics_keys(tmp_path):
    _make_pair(tmp_path)
    output = run_pipeline(str(tmp_path), _config(), _fake_leaf_reader)
    assert "graph" in output
    assert "diagnostics" in output


def test_run_pipeline_diagnostics_values_are_ints(tmp_path):
    _make_pair(tmp_path)
    output = run_pipeline(str(tmp_path), _config(), _fake_leaf_reader)
    diagnostics = output["diagnostics"]
    for key in (
        "untagged_count",
        "seam_collisions",
        "equipment_fragment_merges",
        "leftover_splits_at_root",
        "seam_pairing_failures",
    ):
        assert isinstance(diagnostics[key], int)


def test_run_pipeline_output_is_valid_json(tmp_path):
    _make_pair(tmp_path)
    output = run_pipeline(str(tmp_path), _config(), _fake_leaf_reader)
    assert json.loads(json.dumps(output)) == json.loads(json.dumps(output))


def test_run_pipeline_propagates_missing_file_error(tmp_path):
    # Only uncolored.pdf is created -- colored.pdf is missing.
    _make_pdf(tmp_path / "uncolored.pdf", _WIDTH, _HEIGHT)
    with pytest.raises(FileNotFoundError, match="colored.pdf"):
        run_pipeline(str(tmp_path), _config(), _fake_leaf_reader)


def test_stub_leaf_reader_returns_empty_result():
    segment = Segment(
        image_uncolored=np.zeros((10, 10, 3), dtype=np.uint8),
        image_colored=np.zeros((10, 10, 3), dtype=np.uint8),
        bbox=Box(x=0, y=0, w=10, h=10),
        cut_sides={"top": False, "bottom": False, "left": False, "right": False},
        id="root",
    )
    result = _stub_leaf_reader(segment)
    assert result.nodes == []
    assert result.edges == []
    assert result.split_connections == []
    assert result.split_nodes == []
    assert result.uncertainty == ""


def test_next_run_dir_starts_at_one_for_empty_results_dir(tmp_path):
    results_dir = tmp_path / "results"
    assert _next_run_dir(results_dir) == results_dir / "run_1"


def test_next_run_dir_increments_past_existing_runs_and_ignores_others(tmp_path):
    results_dir = tmp_path / "results"
    for name in ("run_1", "run_2", "run_3", "not_a_run", "run_x"):
        (results_dir / name).mkdir(parents=True)
    assert _next_run_dir(results_dir) == results_dir / "run_4"


def test_segment_dir_maps_dotted_id_to_nested_path(tmp_path):
    segments_root = tmp_path / "segments"
    segment_dir = _segment_dir(segments_root, "root.L.R")
    assert segment_dir == segments_root / "root" / "L" / "R"
    assert segment_dir.is_dir()


def test_recording_leaf_reader_saves_crops_and_passes_through_inner_result(tmp_path):
    segment = Segment(
        image_uncolored=np.full((10, 10, 3), 255, dtype=np.uint8),
        image_colored=np.zeros((10, 10, 3), dtype=np.uint8),
        bbox=Box(x=0, y=0, w=10, h=10),
        cut_sides={"top": False, "bottom": False, "left": False, "right": False},
        id="root.L",
    )
    inner_result = LeafResult(
        nodes=[LeafNode(id="V1", type="valve", metadata={})],
        edges=[LeafEdge(a="V1", b="V2")],
        split_connections=[],
        split_nodes=[SplitNode(id="V2", type="valve", sides=["right"])],
    )
    recorded: list = []
    reader = _recording_leaf_reader(
        lambda seg: inner_result, tmp_path / "segments", recorded
    )
    result = reader(segment)
    assert result is inner_result
    segment_dir = tmp_path / "segments" / "root" / "L"
    colored = cv2.imread(str(segment_dir / "colored.png"))
    uncolored = cv2.imread(str(segment_dir / "uncolored.png"))
    assert np.array_equal(colored, segment.image_colored)
    assert np.array_equal(uncolored, segment.image_uncolored)
    assert recorded == [("root.L", segment.bbox)]


def test_recording_leaf_reader_captures_parse_error_before_reraising(tmp_path):
    segment = Segment(
        image_uncolored=np.full((10, 10, 3), 255, dtype=np.uint8),
        image_colored=np.zeros((10, 10, 3), dtype=np.uint8),
        bbox=Box(x=0, y=0, w=10, h=10),
        cut_sides={"top": False, "bottom": False, "left": False, "right": False},
        id="root.L",
    )

    def failing_inner(seg):
        raise LeafParseError("missing field 'a'", raw_response='{"edges": [{}]}')

    recorded: list = []
    reader = _recording_leaf_reader(failing_inner, tmp_path / "segments", recorded)
    with pytest.raises(LeafParseError):
        reader(segment)

    error_path = tmp_path / "segments" / "root" / "L" / "parse_error.json"
    assert error_path.exists()
    captured = json.loads(error_path.read_text())
    assert captured["raw_response"] == '{"edges": [{}]}'
    assert "missing field 'a'" in captured["message"]


def test_collect_leaves_returns_all_leaf_segments_without_vlm_calls():
    image = np.full((200, 200, 3), 255, dtype=np.uint8)
    root = build_root_segment(image, image)
    config = _config()
    leaves = _collect_leaves(root, config)
    assert "root" in leaves
    assert isinstance(leaves["root"], Segment)


def test_parallel_leaf_read_calls_async_leaf_read_for_every_segment(monkeypatch):
    import engine.leaf.leaf_read as lr_mod

    called: list[str] = []
    expected_result = LeafResult(
        nodes=[LeafNode(id="V1", type="valve", metadata={})],
        edges=[],
        split_connections=[],
        split_nodes=[],
    )

    async def fake_async_leaf_read(segment, config, client):
        called.append(segment.id)
        return expected_result

    monkeypatch.setattr(lr_mod, "async_leaf_read", fake_async_leaf_read)
    import scripts.run as run_mod

    monkeypatch.setattr(run_mod, "async_leaf_read", fake_async_leaf_read)

    image = np.full((200, 200, 3), 255, dtype=np.uint8)
    root = build_root_segment(image, image)
    leaves = {"root": root, "root.L": root}
    results = asyncio.run(_parallel_leaf_read(leaves, _config()))
    assert set(results.keys()) == {"root", "root.L"}
    assert len(called) == 2


def test_draw_segment_overlay_draws_rectangle_border_without_filling_interior():
    base = np.full((100, 100, 3), 255, dtype=np.uint8)
    bbox = Box(x=10, y=10, w=40, h=40)
    overlay = _draw_segment_overlay(base, [("root.L", bbox)])
    assert overlay.shape == base.shape
    assert tuple(overlay[10, 10]) == (0, 0, 255)  # top-left border drawn red
    assert tuple(overlay[30, 30]) == (255, 255, 255)  # interior left untouched
    assert tuple(base[10, 10]) == (255, 255, 255)  # base image not mutated
