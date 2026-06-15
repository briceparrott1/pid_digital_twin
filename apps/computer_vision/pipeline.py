import asyncio
import logging

from agent.graph import run_agent
from core.config import sop_path_for
from db.loader import update_job_status
from services.extractions import build_pid_graph, build_sop_requirements

logger = logging.getLogger(__name__)


async def run_pipeline(job_id: str, sop_index: int = 0):
    try:
        # call services in parallel
        _, sop_requirements = await asyncio.gather(
            build_graph(job_id), build_sop(sop_index)
        )
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


async def build_graph(job_id: str):
    return await build_pid_graph(job_id)


async def build_sop(sop_index: int):
    return await build_sop_requirements(sop_path_for(sop_index))
