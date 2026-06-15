from services.extractions import build_pid_graph, build_sop_requirements
from core.config import sop_path_for
from db.loader import update_job_status
from agent.graph import run_agent
import asyncio


async def run_pipeline(job_id: str, sop_index: int = 0):
    try:
        # call services in parellel
        _, sop_requirements = await asyncio.gather(
            build_graph(job_id), build_sop(sop_index)
        )
        violations_log = await run_agent(job_id, sop_requirements)
        print(f"Violations Log: {violations_log}")
        update_job_status(job_id, "complete")
        print(f"Job {job_id} finished")
    except Exception:
        update_job_status(job_id, "failed")
        raise


async def build_graph(job_id: str):
    return await build_pid_graph(job_id)


async def build_sop(sop_index: int):
    return await build_sop_requirements(sop_path_for(sop_index))
