"""One-off sweep runner: runs the full engine-v2 pipeline (real VLM) for each
segmentation config, recording results to results/run_<n>/.

Run from apps/engine-v2/:
    PYTHONPATH=src ../venv/bin/python3 -m scripts._run_sweep
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path

import cv2

from engine.config import load_config
from engine.leaf.leaf_read import LeafParseError, async_leaf_read
from engine.preprocess.pipeline import build_root_segment, load_pair
from engine.recurse.process import run
from engine.types import Box, LeafResult, Segment
from scripts.evaluate import evaluate_run
from scripts.run import (
    _collect_leaves,
    _draw_segment_overlay,
    _next_run_dir,
    _segment_dir,
    run_pipeline,
)

import anthropic

_DATA_DIR = "data"
_CONFIG_PATH = Path("config/defaults.yaml")
_RESULTS_DIR = Path("results")
_OUTPUT_PATH = Path(_DATA_DIR) / "output.json"

# Best-agg-cost config per segment count 7-25 (lowest total band cost from full_sweep).
# Each dict overrides the FULL set of stop params so _note can embed them without
# reading base_cfg.stop defaults.
CONFIGS: list[tuple[str, dict]] = [
    # Re-run only: segs12/18/23 had parse errors (thinking-only response) in prior sweep.
    # All other configs have clean runs already recorded.
    ("segs12_best", dict(min_dim=800, min_area=1_000_000, min_ink_density=0.010,
                         dense_density_threshold=0.010, dense_min_dim=300,  dense_min_area=1_500_000)),
    ("segs18_best", dict(min_dim=800, min_area=1_000_000, min_ink_density=0.010,
                         dense_density_threshold=0.010, dense_min_dim=500,  dense_min_area=600_000)),
    ("segs23_best", dict(min_dim=400, min_area=800_000,   min_ink_density=0.010,
                         dense_density_threshold=0.050, dense_min_dim=300,  dense_min_area=200_000)),
]

START_FROM = 0


async def _parallel_leaf_read_tolerant(
    leaves: dict[str, Segment], cfg, run_dir: Path
) -> dict[str, LeafResult]:
    """Like scripts.run._parallel_leaf_read but catches LeafParseError per task:
    saves parse_error_<id>.json and substitutes an empty LeafResult so one bad
    leaf doesn't kill the whole gather."""
    async with anthropic.AsyncAnthropic() as client:
        tasks = {
            seg_id: asyncio.create_task(async_leaf_read(segment, cfg.vlm, client))
            for seg_id, segment in leaves.items()
        }
        results: dict[str, LeafResult] = {}
        for seg_id, task in tasks.items():
            try:
                results[seg_id] = await task
            except LeafParseError as err:
                safe_id = seg_id.replace(".", "_")
                (run_dir / f"parse_error_{safe_id}.json").write_text(
                    json.dumps({"message": str(err), "raw_response": err.raw_response}, indent=2)
                )
                print(f"     ⚠ parse error on leaf {seg_id} — saved, using empty result")
                results[seg_id] = LeafResult(nodes=[], edges=[], split_connections=[], split_nodes=[])
    return results


def _note(label: str, overrides: dict) -> str:
    """Builds the -r note string: config label + all six stop param values."""
    return (
        f"{label} | "
        f"min_dim={overrides['min_dim']} "
        f"min_area={overrides['min_area']} "
        f"min_ink_density={overrides['min_ink_density']} "
        f"dense_density_threshold={overrides['dense_density_threshold']} "
        f"dense_min_dim={overrides['dense_min_dim']} "
        f"dense_min_area={overrides['dense_min_area']}"
    )


def _run_one(
    label: str,
    overrides: dict,
    base_cfg,
    image_colored,
    image_uncolored,
) -> dict:
    """Runs the full two-pass pipeline for one config and writes results."""
    cfg = replace(base_cfg, stop=replace(base_cfg.stop, **overrides))
    note = _note(label, overrides)

    run_dir = _next_run_dir(_RESULTS_DIR)
    run_dir.mkdir(parents=True)
    (run_dir / "notes.md").write_text(note + "\n")
    print(f"  → {run_dir.name}  ({label})")

    root = build_root_segment(image_colored, image_uncolored)

    # Pass 1: collect leaf segments (no VLM)
    leaves = _collect_leaves(root, cfg)
    print(f"     {len(leaves)} leaves — firing VLM calls in parallel...")

    # Save leaf crops
    segments_root = run_dir / "segments"
    recorded: list[tuple[str, Box]] = []
    for seg_id, segment in leaves.items():
        seg_dir = _segment_dir(segments_root, seg_id)
        cv2.imwrite(str(seg_dir / "colored.png"), segment.image_colored)
        cv2.imwrite(str(seg_dir / "uncolored.png"), segment.image_uncolored)
        recorded.append((seg_id, segment.bbox))

    # Pass 2: fire all VLM calls concurrently (tolerant: parse errors saved, not raised)
    start = time.monotonic()
    results = asyncio.run(_parallel_leaf_read_tolerant(leaves, cfg, run_dir))
    elapsed = time.monotonic() - start

    # Pass 3: merge using pre-built results
    leaf_reader = lambda seg: results[seg.id]  # noqa: E731
    output = run_pipeline(_DATA_DIR, cfg, leaf_reader)

    # Write output
    _OUTPUT_PATH.write_text(json.dumps(output, indent=2))
    (run_dir / "output.json").write_text(json.dumps(output, indent=2))

    # Overlay
    overlay = _draw_segment_overlay(image_colored, recorded)
    cv2.imwrite(str(run_dir / "overlay.png"), overlay)

    # Evaluate
    scores = evaluate_run(run_dir, elapsed_seconds=elapsed)
    node_f1 = scores["node_f1"]["f1"]
    conn_f1 = scores["connection_f1"]["f1"]
    print(f"     node F1={node_f1:.3f}  conn F1={conn_f1:.3f}  ({elapsed:.0f}s)")
    return {
        "run": run_dir.name, "label": label,
        "node_f1": node_f1, "conn_f1": conn_f1,
        "elapsed": elapsed, "leaves": len(leaves),
    }


def main() -> None:
    base_cfg = load_config(_CONFIG_PATH)
    print("loading PDFs once...")
    image_colored, image_uncolored = load_pair(_DATA_DIR, base_cfg.render)

    remaining = CONFIGS[START_FROM:]
    print(f"running {len(remaining)} configs sequentially (VLM parallel within each):\n")
    summary = []
    for label, overrides in remaining:
        result = _run_one(label, overrides, base_cfg, image_colored, image_uncolored)
        summary.append(result)
        print()

    print("\n=== SUMMARY ===")
    print(f"{'run':<10} {'label':<22} {'leaves':>6} {'node F1':>8} {'conn F1':>8} {'time':>6}")
    print("-" * 66)
    for r in summary:
        print(f"{r['run']:<10} {r['label']:<22} {r['leaves']:>6} {r['node_f1']:>8.3f} {r['conn_f1']:>8.3f} {r['elapsed']:>5.0f}s")


if __name__ == "__main__":
    main()
