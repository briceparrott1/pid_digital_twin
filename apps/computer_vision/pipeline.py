import asyncio
import logging
from pathlib import Path

from agent.graph import run_agent
from core.config import sop_path_for
from db.loader import update_job_status
from engine.evaluate import _next_run_dir, evaluate_run
from services.extractions import build_pid_graph, build_sop_requirements

logger = logging.getLogger(__name__)

_RESULTS_DIR = Path("results/production")
_TRUTH_SET_PATH = Path("data/truth_set.json")


async def run_pipeline(job_id: str, sop_index: int = 0):
    try:
        extraction_meta, sop_requirements = await asyncio.gather(
            build_graph(job_id), build_sop(sop_index)
        )
        _run_eval(job_id, extraction_meta)
        violations_log = await run_agent(job_id, sop_requirements)
        logger.info(
            "job=%s violations_found=%d violations=%s",
            job_id,
            len(violations_log),
            violations_log,
        )
        update_job_status(job_id, "complete")
        logger.info("job=%s status=complete", job_id)
    except Exception:
        update_job_status(job_id, "failed")
        logger.exception("job=%s status=failed", job_id)
        raise


def _run_eval(job_id: str, extraction_meta: dict) -> None:
    """Saves output + scores this run against the truth set. Non-fatal on error."""
    if not _TRUTH_SET_PATH.exists():
        logger.warning("truth_set.json not found at %s — skipping eval", _TRUTH_SET_PATH)
        return
    try:
        graph = {
            "nodes": extraction_meta["nodes"],
            "edges": extraction_meta["edges"],
        }
        run_dir = _next_run_dir(_RESULTS_DIR)
        scores = evaluate_run(
            graph=graph,
            run_dir=run_dir,
            truth_path=_TRUTH_SET_PATH,
            results_dir=_RESULTS_DIR,
            elapsed_seconds=extraction_meta.get("elapsed_seconds"),
            token_usage=extraction_meta.get("token_usage"),
        )
        logger.info(
            "job=%s eval run_dir=%s node_f1=%.3f connection_f1=%.3f",
            job_id,
            run_dir.name,
            scores["node_f1"]["f1"],
            scores["connection_f1"]["f1"],
        )
    except Exception:
        logger.exception("job=%s eval failed (non-fatal)", job_id)


async def build_graph(job_id: str) -> dict:
    return await build_pid_graph(job_id)


async def build_sop(sop_index: int) -> list:
    return await build_sop_requirements(sop_path_for(sop_index))
