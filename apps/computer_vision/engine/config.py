# Loads and validates engine config from YAML into typed config dataclasses; logic
# modules take these as explicit parameters and never read config globally.
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class StopConfig:
    """Size floor below which a segment becomes a leaf instead of being cut
    further, plus two density-driven adjustments: a segment sparser than
    `min_ink_density` stops immediately regardless of size (not worth a
    call), while one at or above `dense_density_threshold` gets the lower
    `dense_min_dim`/`dense_min_area` floor instead, so packed regions get
    one more cut before becoming a leaf."""

    min_dim: int
    min_area: int
    min_ink_density: float
    dense_density_threshold: float
    dense_min_dim: int
    dense_min_area: int


@dataclass(frozen=True)
class CutConfig:
    """Parameters for the dilated-ink band-sum cost used by `best_cut`."""

    dilation_radius: int
    band_width: int
    midpoint_lambda: float
    candidate_step_px: int
    edge_margin_px: int
    min_split_fraction: float


@dataclass(frozen=True)
class RenderConfig:
    """DPI used to render both PDFs; shared so colored/uncolored dimensions match."""

    dpi: int


@dataclass(frozen=True)
class VlmConfig:
    """Call parameters for the leaf VLM and its transport-failure retry
    policy. `thinking_effort` enables adaptive extended thinking when
    non-empty. `max_tokens` is the total cap across thinking + answer.
    `thinking_budget_tokens` explicitly caps the thinking portion so the
    remainder is always available for the JSON answer; 0 means no explicit
    cap (adaptive mode, model decides)."""

    model: str
    max_tokens: int
    thinking_budget_tokens: int
    max_retries: int
    backoff_seconds: float
    thinking_effort: str


@dataclass(frozen=True)
class EngineConfig:
    """Bundled config for one engine run."""

    stop: StopConfig
    cut: CutConfig
    render: RenderConfig
    vlm: VlmConfig


def load_config(path: Path) -> EngineConfig:
    """Parses `path` (e.g. config/defaults.yaml) into an `EngineConfig`."""
    raw = yaml.safe_load(Path(path).read_text())
    return EngineConfig(
        stop=StopConfig(**raw["stop"]),
        cut=CutConfig(**raw["cut"]),
        render=RenderConfig(**raw["render"]),
        vlm=VlmConfig(**raw["vlm"]),
    )
