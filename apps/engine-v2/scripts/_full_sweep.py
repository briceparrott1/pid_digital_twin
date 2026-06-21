"""Full segmentation sweep: generates overlays for every achievable leaf count
in the 1-30 range, with 2-4 configs per count showing diverse cut patterns.
Each overlay is annotated with aggregate cut cost (sum of dilated-ink band pixels
crossed per cut — lower = cuts fell in cleaner whitespace).

Structure:
    results/segmentation_exploration/full_sweep/<count>/
        overlay_<params>.png      (annotated with cost stats)
        stats.md                  (table of all configs at this count)

Run from apps/engine-v2/:
    PYTHONPATH=src ../venv/bin/python3 -m scripts._full_sweep
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np

from engine.config import CutConfig, StopConfig, load_config
from engine.cut.best_cut import best_cut
from engine.cut.cost_map import band_sum, binarize, dilate_ink, ink_density
from engine.cut.split import split
from engine.preprocess.pipeline import build_root_segment, load_pair
from engine.recurse.process import run
from engine.types import Box, LeafResult, Segment

_DATA_DIR = "data"
_CONFIG_PATH = Path("config/defaults.yaml")
_OUT_DIR = Path("results/segmentation_exploration/full_sweep")

# Floor used to pre-compute the full cut tree. min_ink_density=0 so density
# never stops a cut; dense_density_threshold=999 collapses the two-tier floor
# into one uniform floor. This is purely for tree discovery.
_FLOOR_STOP = StopConfig(
    min_dim=250,
    min_area=80_000,
    min_ink_density=0.0,
    dense_density_threshold=999.0,
    dense_min_dim=250,
    dense_min_area=80_000,
)

MAX_CONFIGS_PER_COUNT = 4
JACCARD_SIMILARITY_THRESHOLD = 0.80  # below this = "meaningfully different"


# ---------------------------------------------------------------------------
# Pre-computed cut tree
# ---------------------------------------------------------------------------

@dataclass
class CutNode:
    """One node in the pre-computed cut tree."""
    seg_id: str
    bbox: Box
    density: float
    band_cost: float      # dilated-ink band sum at winning cut; 0 if always-leaf
    first: "CutNode | None" = None
    second: "CutNode | None" = None


def _floor_stop(node: CutNode) -> bool:
    return (
        min(node.bbox.w, node.bbox.h) < _FLOOR_STOP.min_dim
        or node.bbox.w * node.bbox.h < _FLOOR_STOP.min_area
    )


def _build_cut_tree(
    seg: Segment, cut_cfg: CutConfig, seg_id: str
) -> CutNode:
    """Recursively builds the cut tree down to _FLOOR_STOP dimensions."""
    density = ink_density(seg.image_uncolored)
    node = CutNode(seg_id=seg_id, bbox=seg.bbox, density=density, band_cost=0.0)

    if _floor_stop(node):
        return node

    axis, position = best_cut(seg, cut_cfg)

    binary = binarize(seg.image_uncolored)
    dilated = dilate_ink(binary, cut_cfg.dilation_radius)
    h, w = dilated.shape[:2]
    dim = w if axis == "vertical" else h
    node.band_cost = float(band_sum(dilated, axis, position, cut_cfg.band_width))

    first_seg, second_seg = split(seg, axis, position)
    first_suffix = "L" if axis == "vertical" else "T"
    second_suffix = "R" if axis == "vertical" else "B"
    node.first = _build_cut_tree(first_seg, cut_cfg, f"{seg_id}.{first_suffix}")
    node.second = _build_cut_tree(second_seg, cut_cfg, f"{seg_id}.{second_suffix}")
    return node


# ---------------------------------------------------------------------------
# Tree queries against a StopConfig
# ---------------------------------------------------------------------------

def _should_stop(node: CutNode, stop: StopConfig) -> bool:
    """Mirrors should_stop_cutting() in recurse/stop.py but runs on a CutNode."""
    if node.density < stop.min_ink_density:
        return True
    if node.density >= stop.dense_density_threshold:
        min_dim, min_area = stop.dense_min_dim, stop.dense_min_area
    else:
        min_dim, min_area = stop.min_dim, stop.min_area
    return min(node.bbox.w, node.bbox.h) < min_dim or node.bbox.w * node.bbox.h < min_area


def _tree_leaves(node: CutNode, stop: StopConfig) -> frozenset[str]:
    if node.first is None or _should_stop(node, stop):
        return frozenset({node.seg_id})
    return _tree_leaves(node.first, stop) | _tree_leaves(node.second, stop)


def _tree_cost(node: CutNode, stop: StopConfig) -> tuple[float, int]:
    """Returns (total_band_cost, n_cuts)."""
    if node.first is None or _should_stop(node, stop):
        return 0.0, 0
    ca, na = _tree_cost(node.first, stop)
    cb, nb = _tree_cost(node.second, stop)
    return node.band_cost + ca + cb, 1 + na + nb


# ---------------------------------------------------------------------------
# Parameter grid
# ---------------------------------------------------------------------------

def _param_grid(base: StopConfig):
    """Yields StopConfig objects covering a broad parameter space.
    Three phases targeting 1-9, 10-22, and 23-30 leaf counts."""
    seen: set[tuple] = set()

    def _emit(stop: StopConfig):
        key = (
            stop.min_dim, stop.min_area, stop.min_ink_density,
            stop.dense_density_threshold, stop.dense_min_dim, stop.dense_min_area,
        )
        if key not in seen:
            seen.add(key)
            yield stop

    # Phase 1: min_dim + min_area sweep → targets 1-9 (and variants of 21-22)
    # min_area between ~11M-17M stops both root children → 2 leaves
    for min_dim in [250, 300, 400, 500, 600, 700, 800, 900, 1000, 1100,
                    1200, 1250, 1280, 1300, 1400, 1600, 2000, 2500, 3000, 3500, 5000]:
        for min_area in [50_000, 100_000, 200_000, 500_000, 1_000_000,
                          2_000_000, 4_000_000, 6_000_000, 8_000_000,
                          10_000_000, 11_000_000, 12_000_000, 13_000_000,
                          14_000_000, 15_000_000, 17_000_000, 20_000_000]:
            for mid in [0.005, 0.008, 0.01, 0.012, 0.015]:
                stop = replace(base, min_dim=min_dim, min_area=min_area,
                               min_ink_density=mid)
                yield from _emit(stop)

    # Phase 2: dense_* sweep with default min_dim/min_area → targets 10-22
    for ddt in [0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30]:
        for dmd in [300, 350, 400, 450, 500, 550, 600, 700, 800, 900, 1000]:
            for dma in [100_000, 150_000, 200_000, 250_000, 400_000,
                         600_000, 800_000, 1_000_000, 1_500_000, 2_000_000]:
                stop = replace(base, dense_density_threshold=ddt,
                               dense_min_dim=dmd, dense_min_area=dma)
                yield from _emit(stop)

    # Phase 3: sub-800 min_dim + smaller dense floors → targets 23-30
    for min_dim in [250, 300, 350, 400, 450, 500, 600, 700]:
        for min_area in [50_000, 100_000, 150_000, 200_000, 300_000, 500_000, 800_000]:
            for ddt in [0.03, 0.05, 0.10, 0.20, 0.50]:
                for dmd in [150, 200, 250, 300, 350, 400]:
                    for dma in [40_000, 60_000, 80_000, 100_000, 150_000, 200_000]:
                        stop = replace(base, min_dim=min_dim, min_area=min_area,
                                       dense_density_threshold=ddt,
                                       dense_min_dim=dmd, dense_min_area=dma)
                        yield from _emit(stop)


# ---------------------------------------------------------------------------
# Diversity selection
# ---------------------------------------------------------------------------

def _jaccard(a: frozenset, b: frozenset) -> float:
    union = len(a | b)
    return len(a & b) / union if union else 1.0


def _pick_diverse(
    entries: list[tuple[StopConfig, frozenset[str], float, int]],
    max_n: int = MAX_CONFIGS_PER_COUNT,
) -> list[tuple[StopConfig, frozenset[str], float, int]]:
    """Greedy diversity selection: start with cheapest-cut config, keep adding
    the most spatially distinct one until we have max_n or no more candidates
    differ enough (Jaccard < JACCARD_SIMILARITY_THRESHOLD)."""
    if len(entries) <= max_n:
        return entries
    by_cost = sorted(entries, key=lambda e: e[2])  # cheapest first
    selected = [by_cost[0]]
    for entry in by_cost[1:]:
        if len(selected) >= max_n:
            break
        max_sim = max(_jaccard(entry[1], s[1]) for s in selected)
        if max_sim < JACCARD_SIMILARITY_THRESHOLD:
            selected.append(entry)
    return selected


# ---------------------------------------------------------------------------
# Overlay helpers
# ---------------------------------------------------------------------------

def _params_str(stop: StopConfig) -> str:
    return (
        f"md={stop.min_dim} ma={stop.min_area//1000}k "
        f"mid={stop.min_ink_density:.3f} "
        f"ddt={stop.dense_density_threshold:.3f} "
        f"dmd={stop.dense_min_dim} "
        f"dma={stop.dense_min_area//1000}k"
    )


def _overlay_filename(stop: StopConfig) -> str:
    dma_k = stop.dense_min_area // 1000
    ma_k = stop.min_area // 1000
    return (
        f"overlay"
        f"_md{stop.min_dim}"
        f"_ma{ma_k}k"
        f"_mid{stop.min_ink_density:.3f}"
        f"_ddt{stop.dense_density_threshold:.3f}"
        f"_dmd{stop.dense_min_dim}"
        f"_dma{dma_k}k"
        ".png"
    )


def _draw_overlay(
    base: np.ndarray,
    leaves: list[tuple[str, Box]],
    total_cost: float,
    n_cuts: int,
    stop: StopConfig,
) -> np.ndarray:
    overlay = base.copy()
    for seg_id, bbox in leaves:
        cv2.rectangle(overlay, (bbox.x, bbox.y), (bbox.x + bbox.w, bbox.y + bbox.h), (0, 0, 255), 3)
        label = seg_id.removeprefix("root").lstrip(".") or "root"
        cv2.putText(overlay, label, (bbox.x + 5, bbox.y + 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

    per_cut = total_cost / n_cuts if n_cuts > 0 else 0.0
    annotation_lines = [
        f"segs={len(leaves)}  cuts={n_cuts}  agg_cost={total_cost:.0f}  per_cut={per_cut:.0f}",
        _params_str(stop),
    ]
    y = 55
    for line in annotation_lines:
        cv2.putText(overlay, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 5)
        cv2.putText(overlay, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2)
        y += 50
    return overlay


def _get_leaf_bboxes(
    image_colored: np.ndarray,
    image_uncolored: np.ndarray,
    stop: StopConfig,
    cut: CutConfig,
) -> list[tuple[str, Box]]:
    root = build_root_segment(image_colored, image_uncolored)
    leaves: list[tuple[str, Box]] = []

    def stub(seg: Segment) -> LeafResult:
        leaves.append((seg.id, seg.bbox))
        return LeafResult(nodes=[], edges=[], split_connections=[], split_nodes=[])

    run(root, stub, cut, stop)
    return leaves


def _write_stats_md(
    count_dir: Path,
    entries: list[tuple[StopConfig, frozenset[str], float, int]],
) -> None:
    rows = ["| overlay | cuts | agg_cost | per_cut | params |",
            "|---|---|---|---|---|"]
    for stop, _, total_cost, n_cuts in sorted(entries, key=lambda e: e[2]):
        per_cut = total_cost / n_cuts if n_cuts > 0 else 0.0
        fname = _overlay_filename(stop)
        rows.append(
            f"| {fname} | {n_cuts} | {total_cost:.0f} | {per_cut:.0f} | {_params_str(stop)} |"
        )
    (count_dir / "stats.md").write_text("\n".join(rows) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = load_config(_CONFIG_PATH)
    print("loading PDFs...")
    image_colored, image_uncolored = load_pair(_DATA_DIR, cfg.render)
    root_seg = build_root_segment(image_colored, image_uncolored)

    print("pre-computing cut tree (one-time, may take ~30-60s)...")
    cut_tree = _build_cut_tree(root_seg, cfg.cut, "root")
    total_nodes = sum(1 for _ in _iter_nodes(cut_tree))
    print(f"  tree has {total_nodes} nodes")

    base_stop = cfg.stop

    print("sweeping parameter grid...")
    # count → list of (stop, leaf_ids, total_cost, n_cuts)
    by_count: dict[int, list[tuple[StopConfig, frozenset[str], float, int]]] = {}
    seen_layouts: set[frozenset[str]] = set()

    n_configs = 0
    for stop in _param_grid(base_stop):
        n_configs += 1
        leaf_ids = _tree_leaves(cut_tree, stop)
        if leaf_ids in seen_layouts:
            continue
        seen_layouts.add(leaf_ids)
        total_cost, n_cuts = _tree_cost(cut_tree, stop)
        count = len(leaf_ids)
        by_count.setdefault(count, []).append((stop, leaf_ids, total_cost, n_cuts))

    print(f"  evaluated {n_configs} configs → {len(seen_layouts)} unique layouts")
    achievable = sorted(by_count)
    print(f"  achievable counts: {achievable}")

    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    for count in achievable:
        entries = by_count[count]
        selected = _pick_diverse(entries)
        count_dir = _OUT_DIR / str(count)
        count_dir.mkdir(exist_ok=True)

        for stop, leaf_ids, total_cost, n_cuts in selected:
            leaves = _get_leaf_bboxes(image_colored, image_uncolored, stop, cfg.cut)
            overlay = _draw_overlay(image_colored, leaves, total_cost, n_cuts, stop)
            cv2.imwrite(str(count_dir / _overlay_filename(stop)), overlay)

        _write_stats_md(count_dir, selected)
        per_cuts = [e[2] / e[3] if e[3] else 0 for e in selected]
        print(f"  {count:3d} segs → {len(selected)} overlays  "
              f"(cost range: {min(per_cuts):.0f}–{max(per_cuts):.0f} per cut)")

    # Summary: which counts in 1-30 were NOT found
    missing = [n for n in range(1, 31) if n not in by_count]
    if missing:
        print(f"\nnot achievable in 1-30 range: {missing}")
    print("\ndone.")


def _iter_nodes(node: CutNode):
    """Utility: iterate all nodes in the pre-computed tree."""
    yield node
    if node.first:
        yield from _iter_nodes(node.first)
    if node.second:
        yield from _iter_nodes(node.second)


if __name__ == "__main__":
    main()
