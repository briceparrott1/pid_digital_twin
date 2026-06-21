"""One-off segmentation exploration sweep: generates overlays for t12–t18.

Run from apps/engine-v2/:
    PYTHONPATH=src ../venv/bin/python3 -m scripts._seg_explore
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from engine.config import load_config
from engine.cut.cost_map import ink_density
from engine.preprocess.pipeline import load_pair, build_root_segment
from engine.recurse.process import run
from engine.types import Box, LeafResult, Segment

_DATA_DIR = "data"
_CONFIG_PATH = Path("config/defaults.yaml")
_OUT_DIR = Path("results/segmentation_exploration")

# (label, overrides as kwargs to replace(cfg.stop, ...))
# All keep min_dim=800, min_area=1_000_000, min_ink_density=0.01 at defaults.
# Only dense_* params are varied — this is the lever that moves us from 22
# down into the 12-18 range without the cliff that raising min_dim causes.
CONFIGS: list[tuple[str, dict]] = [
    # --- 12 leaves ---
    # Raise dense_min_area 4x from 250k → 1M; ddt/dmd unchanged
    ("t12_raise_dma", dict(dense_density_threshold=0.03, dense_min_dim=400, dense_min_area=1_000_000)),
    # Raise ddt+dmd; dma moderate
    ("t12_raise_ddt_dmd", dict(dense_density_threshold=0.04, dense_min_dim=600, dense_min_area=600_000)),
    # --- 13 leaves ---
    # Raise dmd only (400→500), dma moderate
    ("t13_raise_dmd", dict(dense_density_threshold=0.03, dense_min_dim=500, dense_min_area=600_000)),
    # Lower ddt (treats fewer segments as dense), raise dmd
    ("t13_low_ddt", dict(dense_density_threshold=0.02, dense_min_dim=600, dense_min_area=400_000)),
    # --- 14 leaves ---
    # Moderate raise on all three
    ("t14_balanced", dict(dense_density_threshold=0.04, dense_min_dim=500, dense_min_area=400_000)),
    # Very low ddt (almost nothing qualifies as dense) + large dmd
    ("t14_low_ddt", dict(dense_density_threshold=0.01, dense_min_dim=600, dense_min_area=800_000)),
    # --- 15 leaves ---
    # Raise dmd, keep dma moderate
    ("t15_raise_dmd", dict(dense_density_threshold=0.03, dense_min_dim=500, dense_min_area=400_000)),
    # Very low ddt, dma at 1M
    ("t15_low_ddt", dict(dense_density_threshold=0.01, dense_min_dim=400, dense_min_area=1_000_000)),
    # --- 16 leaves ---
    # Low ddt, large dmd, large dma
    ("t16_low_ddt", dict(dense_density_threshold=0.01, dense_min_dim=500, dense_min_area=800_000)),
    # Slightly higher ddt, modest raise on dma
    ("t16_mid", dict(dense_density_threshold=0.05, dense_min_dim=400, dense_min_area=400_000)),
    # --- 17 leaves ---
    # Single point in this count; moderate raise across the board
    ("t17_mid", dict(dense_density_threshold=0.04, dense_min_dim=400, dense_min_area=400_000)),
    # --- 18 leaves ---
    # Low ddt, dmd=400 (same as current), raise dma 3x
    ("t18_raise_dma", dict(dense_density_threshold=0.01, dense_min_dim=400, dense_min_area=800_000)),
    # Low ddt, larger dmd, moderate dma
    ("t18_raise_dmd", dict(dense_density_threshold=0.01, dense_min_dim=600, dense_min_area=400_000)),
]


def _collect_leaves(root: Segment, cfg, stop) -> list[Segment]:
    leaves: list[Segment] = []

    def stub(s: Segment) -> LeafResult:
        leaves.append(s)
        return LeafResult(nodes=[], edges=[], split_connections=[], split_nodes=[])

    run(root, stub, cfg.cut, stop)
    return leaves


def _overlay(base: "np.ndarray", segments: list[Segment]) -> "np.ndarray":
    import numpy as np

    overlay = base.copy()
    for seg in segments:
        b = seg.bbox
        cv2.rectangle(overlay, (b.x, b.y), (b.x + b.w, b.y + b.h), (0, 0, 255), 3)
        label = seg.id.removeprefix("root").lstrip(".") or "root"
        cv2.putText(
            overlay, label, (b.x + 5, b.y + 25),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2,
        )
    return overlay


def _config_md(label: str, leaf_count: int, overrides: dict, leaves: list[Segment], base_stop) -> str:
    lines = [
        f"# {label}  (leaves={leaf_count})\n",
        "## Stop config",
        f"- min_dim: {base_stop.min_dim}",
        f"- min_area: {base_stop.min_area:,}",
        f"- min_ink_density: {base_stop.min_ink_density}",
        f"- dense_density_threshold: {overrides.get('dense_density_threshold', base_stop.dense_density_threshold)}",
        f"- dense_min_dim: {overrides.get('dense_min_dim', base_stop.dense_min_dim)}",
        f"- dense_min_area: {overrides.get('dense_min_area', base_stop.dense_min_area):,}",
        "",
        "## Leaf segments",
    ]
    for seg in leaves:
        d = ink_density(seg.image_uncolored)
        stop_reason = "density" if d < base_stop.min_ink_density else "size"
        lines.append(f"- {seg.id}: {seg.bbox.w}x{seg.bbox.h}  density={d:.4f}  stopped_by={stop_reason}")
    return "\n".join(lines) + "\n"


def main() -> None:
    cfg = load_config(_CONFIG_PATH)
    print("loading PDFs...")
    image_colored, image_uncolored = load_pair(_DATA_DIR, cfg.render)
    root = build_root_segment(image_colored, image_uncolored)
    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    for label, overrides in CONFIGS:
        stop = replace(cfg.stop, **overrides)
        leaves = _collect_leaves(root, cfg, stop)
        n = len(leaves)
        print(f"  {label}: {n} leaves")

        out_dir = _OUT_DIR / label
        out_dir.mkdir(exist_ok=True)

        overlay_img = _overlay(image_colored, leaves)
        cv2.imwrite(str(out_dir / "overlay.png"), overlay_img)

        notes = _config_md(label, n, overrides, leaves, stop)
        (out_dir / "config.md").write_text(notes)

    print(f"done — overlays written to {_OUT_DIR}/")


if __name__ == "__main__":
    main()
