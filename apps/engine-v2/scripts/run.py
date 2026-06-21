# End-to-end entrypoint: loads the colored/uncolored PDF pair from data/, runs
# the full recursive engine with the real VLM leaf reader, and writes the
# resulting page graph plus diagnostics to data/output.json. Fixed paths, one
# job. Two flags exist for inspecting the pipeline before/without spending on
# VLM calls: --no-vlm stubs the leaf reader, -r/--record saves this run's
# notes, leaf segment crops, a full-page overlay of segment boundaries, and
# an evaluation against data/truth_set.json under results/run_<n>/. Invoke as
# `python -m scripts.run` (not `python scripts/run.py`) so the sibling
# `scripts.evaluate` import resolves the same way it does under pytest.
#
# VLM calls are fully parallel: segmentation (cut/split/stop) is deterministic
# and VLM-independent, so a first pass with a stub reader collects all leaf
# segments, asyncio.gather fires every VLM call simultaneously, and a second
# pass drives the merge from the pre-built results dict.
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import time
from pathlib import Path
from typing import Callable

import anthropic
import cv2
import numpy as np

from engine.config import EngineConfig, load_config
from engine.leaf.leaf_read import LeafParseError, async_leaf_read, leaf_read
from engine.preprocess.pipeline import build_root_segment, load_pair
from engine.recurse.process import LeafReader, run
from engine.types import Box, LeafResult, PageGraph, Segment
from scripts.evaluate import evaluate_run

_DATA_DIR = "data"
_RESULTS_DIR = Path("results")
_CONFIG_PATH = Path("config/defaults.yaml")
_OUTPUT_PATH = Path(_DATA_DIR) / "output.json"


def _diagnostics_dict(page_graph: PageGraph) -> dict:
    """Renames/derives the top-level diagnostics counters from
    `PageGraph.diagnostics` for the output contract: `equipment_merges`
    becomes `equipment_fragment_merges`, and `leftover_splits`/
    `seam_pairing_failures` (lists) become their counts."""
    diagnostics = page_graph.diagnostics
    return {
        "untagged_count": diagnostics.untagged_count,
        "seam_collisions": diagnostics.seam_collisions,
        "equipment_fragment_merges": diagnostics.equipment_merges,
        "leftover_splits_at_root": len(diagnostics.leftover_splits),
        "seam_pairing_failures": len(diagnostics.seam_pairing_failures),
    }


def run_pipeline(data_dir: str, config: EngineConfig, leaf_reader: LeafReader) -> dict:
    """Runs the full pipeline for one page: loads the PDF pair from
    `data_dir`, builds the root segment, recurses with `leaf_reader`, and
    returns `{"graph": ..., "diagnostics": ...}` ready for JSON serialization."""
    image_colored, image_uncolored = load_pair(data_dir, config.render)
    root: Segment = build_root_segment(image_colored, image_uncolored)
    page_graph = run(root, leaf_reader, config.cut, config.stop)
    return {
        "graph": dataclasses.asdict(page_graph),
        "diagnostics": _diagnostics_dict(page_graph),
    }


def _real_leaf_reader(config: EngineConfig) -> Callable[[Segment], LeafResult]:
    """Builds the real Segment -> LeafResult reader: an Anthropic client bound
    to `config.vlm`, matching the LeafReader signature `run()` expects."""
    client = anthropic.Anthropic()
    return lambda segment: leaf_read(segment, config.vlm, client)


def _collect_leaves(root: Segment, config: EngineConfig) -> dict[str, Segment]:
    """First pass: runs the full recursion with a stub reader to discover every
    leaf segment without making any VLM calls. Returns a mapping of segment id
    to Segment so the second pass can look up results by id."""
    leaves: dict[str, Segment] = {}

    def _stub(segment: Segment) -> LeafResult:
        leaves[segment.id] = segment
        return LeafResult(nodes=[], edges=[], split_connections=[], split_nodes=[])

    run(root, _stub, config.cut, config.stop)
    return leaves


async def _parallel_leaf_read(
    leaves: dict[str, Segment], config: EngineConfig
) -> dict[str, LeafResult]:
    """Fires every VLM call concurrently using AsyncAnthropic. All N calls are
    in-flight simultaneously; the event loop handles scheduling."""
    async with anthropic.AsyncAnthropic() as client:
        tasks = {
            seg_id: asyncio.create_task(async_leaf_read(segment, config.vlm, client))
            for seg_id, segment in leaves.items()
        }
        results: dict[str, LeafResult] = {}
        for seg_id, task in tasks.items():
            results[seg_id] = await task
    return results


def _stub_leaf_reader(segment: Segment) -> LeafResult:
    """Empty LeafResult for --no-vlm runs: lets recursion complete and leaf
    segments get visited (and recorded, if -r is also set) with no API call."""
    return LeafResult(nodes=[], edges=[], split_connections=[], split_nodes=[])


def _next_run_dir(results_dir: Path) -> Path:
    """Finds the next results/run_<n> dir: n is one more than the highest
    existing run_<n> under `results_dir` (0 if none exist)."""
    results_dir.mkdir(parents=True, exist_ok=True)
    existing = [
        int(path.name.removeprefix("run_"))
        for path in results_dir.iterdir()
        if path.is_dir() and path.name.removeprefix("run_").isdigit()
    ]
    return results_dir / f"run_{max(existing, default=0) + 1}"


def _segment_dir(segments_root: Path, segment_id: str) -> Path:
    """Maps a segment's dot-separated recursion id (e.g. "root.L.R") to a
    nested directory under `segments_root`, creating it."""
    path = segments_root.joinpath(*segment_id.split("."))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _recording_leaf_reader(
    inner: LeafReader, segments_root: Path, recorded: list[tuple[str, Box]]
) -> LeafReader:
    """Wraps `inner` to first save each visited leaf segment's colored and
    uncolored crops under `segments_root` (nested by recursion id) and append
    its (id, bbox) to `recorded` for the overlay, then delegate to `inner`.
    If `inner` raises `LeafParseError`, writes the raw response to
    `parse_error.json` in that segment's dir before re-raising, so a crash is
    self-diagnosing without a separate diagnostic rerun."""

    def reader(segment: Segment) -> LeafResult:
        segment_dir = _segment_dir(segments_root, segment.id)
        cv2.imwrite(str(segment_dir / "colored.png"), segment.image_colored)
        cv2.imwrite(str(segment_dir / "uncolored.png"), segment.image_uncolored)
        recorded.append((segment.id, segment.bbox))
        try:
            return inner(segment)
        except LeafParseError as error:
            (segment_dir / "parse_error.json").write_text(
                json.dumps(
                    {"message": str(error), "raw_response": error.raw_response},
                    indent=2,
                )
            )
            raise

    return reader


def _draw_segment_overlay(
    base_image: np.ndarray, segments: list[tuple[str, Box]]
) -> np.ndarray:
    """Draws each segment's bbox as a labeled red rectangle over a copy of
    `base_image`, so every leaf segment's boundary can be eyeballed at once
    against the full page."""
    overlay = base_image.copy()
    for segment_id, bbox in segments:
        top_left = (bbox.x, bbox.y)
        bottom_right = (bbox.x + bbox.w, bbox.y + bbox.h)
        cv2.rectangle(overlay, top_left, bottom_right, (0, 0, 255), 3)
        label = segment_id.removeprefix("root").lstrip(".") or "root"
        cv2.putText(
            overlay,
            label,
            (bbox.x + 5, bbox.y + 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2,
        )
    return overlay


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses --no-vlm (skip the real VLM call) and -r/--record NOTE (save
    this run's notes and leaf segment crops to results/run_<n>/)."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-r",
        "--record",
        metavar="NOTE",
        help="save this run to results/run_<n>/ with NOTE written to notes.md",
    )
    parser.add_argument(
        "--no-vlm",
        action="store_true",
        help="skip the real VLM leaf call; use an empty stub LeafResult instead",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    _start = time.monotonic()
    args = _parse_args()
    config = load_config(_CONFIG_PATH)
    print("loading and rendering colored/uncolored PDF pair...")
    image_colored, image_uncolored = load_pair(_DATA_DIR, config.render)
    root: Segment = build_root_segment(image_colored, image_uncolored)

    run_dir: Path | None = None
    recorded_segments: list[tuple[str, Box]] = []
    if args.record is not None:
        run_dir = _next_run_dir(_RESULTS_DIR)
        run_dir.mkdir(parents=True)
        (run_dir / "notes.md").write_text(args.record + "\n")
        print(f"recording this run to {run_dir}...")

    if args.no_vlm:
        leaf_reader: LeafReader = _stub_leaf_reader
        if run_dir is not None:
            leaf_reader = _recording_leaf_reader(
                leaf_reader, run_dir / "segments", recorded_segments
            )
        print("processing page (cut/merge/leaf-read recursion, --no-vlm)...")
        output = run_pipeline(_DATA_DIR, config, leaf_reader)
    else:
        print("collecting leaf segments (pass 1 of 2)...")
        leaves = _collect_leaves(root, config)
        if run_dir is not None:
            segments_root = run_dir / "segments"
            for seg_id, segment in leaves.items():
                seg_dir = _segment_dir(segments_root, seg_id)
                cv2.imwrite(str(seg_dir / "colored.png"), segment.image_colored)
                cv2.imwrite(str(seg_dir / "uncolored.png"), segment.image_uncolored)
                recorded_segments.append((seg_id, segment.bbox))
        print(f"firing {len(leaves)} VLM calls in parallel (pass 2 of 2)...")
        results = asyncio.run(_parallel_leaf_read(leaves, config))
        print("merging results...")
        leaf_reader = lambda seg: results[seg.id]  # noqa: E731
        output = run_pipeline(_DATA_DIR, config, leaf_reader)

    if run_dir is not None:
        overlay = _draw_segment_overlay(image_colored, recorded_segments)
        cv2.imwrite(str(run_dir / "overlay.png"), overlay)
        print(f"wrote segment overlay to {run_dir / 'overlay.png'}...")
    print(f"writing output to {_OUTPUT_PATH}...")
    _OUTPUT_PATH.write_text(json.dumps(output, indent=2))
    if run_dir is not None:
        elapsed = time.monotonic() - _start
        (run_dir / "output.json").write_text(json.dumps(output, indent=2))
        scores = evaluate_run(run_dir, elapsed_seconds=elapsed)
        print(
            f"evaluated against truth set: node F1={scores['node_f1']['f1']:.3f}, "
            f"connection F1={scores['connection_f1']['f1']:.3f} ({elapsed:.0f}s)"
        )
    print("done.")
