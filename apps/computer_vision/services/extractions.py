import json
import logging
import time

from core.config import get_settings
from db.loader import update_job_status, write_extraction
from engine.orchestrator import run_algo
from extraction.extractors import extract_sop_requirements
from extraction.prompts import get_sop_prompt
from parsers.sop_parser import parse_sop

settings = get_settings()
logger = logging.getLogger(__name__)


async def build_pid_graph(job_id: str) -> dict:
    """Runs P&ID extraction and writes results to Neo4j.

    Returns a dict with keys: nodes, edges, token_usage, elapsed_seconds.
    """
    update_job_status(job_id, "extracting")
    t0 = time.monotonic()
    result, token_usage = await run_algo(settings.pid_path)
    elapsed = time.monotonic() - t0
    nodes = result.get("nodes", [])
    edges = result.get("edges", [])
    write_extraction(job_id, {"nodes": nodes, "edges": edges})
    update_job_status(job_id, "extracted")
    logger.info(
        "job=%s extraction complete elapsed=%.1fs nodes=%d edges=%d",
        job_id,
        elapsed,
        len(nodes),
        len(edges),
    )
    return {
        "nodes": nodes,
        "edges": edges,
        "token_usage": token_usage,
        "elapsed_seconds": elapsed,
    }


async def build_sop_requirements(sop_path: str) -> list:
    sop_text = parse_sop(sop_path)
    logger.debug("parsed SOP text from %s:\n%s", sop_path, sop_text)
    prompt = get_sop_prompt(sop_text)
    requirements = await extract_sop_requirements(prompt)
    logger.debug("parsed SOP requirements:\n%s", json.dumps(requirements, indent=2))
    return requirements
