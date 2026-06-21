import asyncio
import dataclasses
import logging
from pathlib import Path

import anthropic

from engine.config import CutConfig, EngineConfig, RenderConfig, StopConfig, VlmConfig
from engine.leaf.leaf_read import LeafParseError, async_leaf_read
from engine.preprocess.pipeline import build_root_segment, load_pair
from engine.recurse.process import run
from engine.types import LeafResult, Segment

logger = logging.getLogger(__name__)

# Best config from engine-v2 run_35 (node F1=0.976, connection F1=0.873).
# Three stop thresholds differ from defaults to tighten the dense-segment
# floor and prevent oversized leaves in busy regions.
_ENGINE_CONFIG = EngineConfig(
    stop=StopConfig(
        min_dim=800,
        min_area=1_000_000,
        min_ink_density=0.01,
        dense_density_threshold=0.01,
        dense_min_dim=600,
        dense_min_area=1_500_000,
    ),
    cut=CutConfig(
        dilation_radius=3,
        band_width=5,
        midpoint_lambda=0.01,
        candidate_step_px=2,
        edge_margin_px=8,
        min_split_fraction=0.35,
    ),
    render=RenderConfig(dpi=300),
    vlm=VlmConfig(
        model="claude-opus-4-8",
        max_tokens=32_000,
        thinking_budget_tokens=0,
        max_retries=3,
        backoff_seconds=1.0,
        thinking_effort="medium",
    ),
)


def _collect_leaves(root: Segment, config: EngineConfig) -> dict[str, Segment]:
    """Pass 1: dry run with a stub reader to enumerate all leaf segments."""
    leaves: dict[str, Segment] = {}

    def _stub(segment: Segment) -> LeafResult:
        leaves[segment.id] = segment
        return LeafResult(nodes=[], edges=[], split_connections=[], split_nodes=[])

    run(root, _stub, config.cut, config.stop)
    return leaves


async def _parallel_leaf_read(
    leaves: dict[str, Segment], config: EngineConfig
) -> dict[str, LeafResult]:
    """Pass 2: fires every leaf VLM call concurrently."""
    async with anthropic.AsyncAnthropic() as client:
        tasks = {
            seg_id: asyncio.create_task(async_leaf_read(segment, config.vlm, client))
            for seg_id, segment in leaves.items()
        }
        results: dict[str, LeafResult] = {}
        for seg_id, task in tasks.items():
            try:
                results[seg_id] = await task
            except LeafParseError as exc:
                logger.warning("leaf %s parse failed, skipping: %s", seg_id, exc)
                results[seg_id] = LeafResult(
                    nodes=[], edges=[], split_connections=[], split_nodes=[]
                )
        return results


async def run_algo(pid_path: str) -> tuple[dict, None]:
    """Runs the engine-v2 recursive-bisection pipeline on one P&ID page.

    Expects colored.pdf and uncolored.pdf in the same directory as `pid_path`.
    Returns ({"nodes": [...], "edges": [...]}, None). Token usage is not
    tracked by engine-v2 (each leaf is an independent VLM call).
    """
    config = _ENGINE_CONFIG
    data_dir = str(Path(pid_path).parent)
    logger.info("loading PDF pair from %s", data_dir)
    image_colored, image_uncolored = load_pair(data_dir, config.render)
    root = build_root_segment(image_colored, image_uncolored)

    logger.info("collecting leaf segments (pass 1/2)")
    leaves = _collect_leaves(root, config)

    logger.info("firing %d VLM leaf calls in parallel (pass 2/2)", len(leaves))
    results = await _parallel_leaf_read(leaves, config)

    logger.info("merging results")
    page_graph = run(root, lambda seg: results[seg.id], config.cut, config.stop)

    nodes = [dataclasses.asdict(n) for n in page_graph.nodes]
    edges = [dataclasses.asdict(e) for e in page_graph.edges]
    logger.info("extraction complete nodes=%d edges=%d", len(nodes), len(edges))
    return {"nodes": nodes, "edges": edges}, None
