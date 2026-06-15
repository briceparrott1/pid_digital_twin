import asyncio
import json

from parsers.pid_parser import render_pages
from parsers.sop_parser import parse_sop
from extraction.extractors import extract_pid, extract_sop_requirements
from extraction.prompts import get_pid_prompt, get_sop_prompt
from core.config import get_settings
from db.loader import update_job_status, write_extraction

settings = get_settings()


async def build_pid_extraction() -> dict:
    images = render_pages(settings.pid_path)
    prompt = get_pid_prompt()
    pages = await asyncio.gather(
        *(extract_pid(image, prompt, page=i) for i, image in enumerate(images, start=1))
    )

    extraction = {
        "nodes": [node for page in pages for node in page["nodes"]],
        "connections": [conn for page in pages for conn in page["connections"]],
    }

    equipment_list = [n for n in extraction["nodes"] if n["level"] == "equipment"]

    return {"extraction": extraction, "equipment_list": equipment_list}


async def build_pid_graph(job_id: str) -> dict:
    update_job_status(job_id, "extracting")
    pid_extraction = await build_pid_extraction()
    write_extraction(job_id, pid_extraction["extraction"])
    update_job_status(job_id, "extracted")
    return pid_extraction


# parsed sop text is injected into prompt (why we're not passing sop text to extract_sop_requirements)
async def build_sop_requirements(sop_path: str) -> list:
    sop_text = parse_sop(sop_path)
    print(f"Parsed SOP text ({sop_path}):\n{sop_text}")
    prompt = get_sop_prompt(sop_text)
    requirements = await extract_sop_requirements(prompt)
    print(f"Parsed SOP requirements:\n{json.dumps(requirements, indent=2)}")
    return requirements
