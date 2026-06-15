import json
import logging

import anthropic

from core.config import get_settings
from engine.orchestrator import run_algo

client = anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key)
logger = logging.getLogger(__name__)


def _parse_response(response) -> dict | list:
    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            "Claude response was truncated (stop_reason=max_tokens); "
            "increase max_tokens to capture the full extraction"
        )

    text = response.content[0].text
    text = (
        text.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )
    return json.loads(text)


async def extract_pid(image: bytes, prompt: str, page: int) -> dict:
    result = await run_algo(image)
    resolved = result["resolved"]
    for node in resolved["nodes"]:
        node["page"] = page
    for connection in resolved["connections"]:
        connection["page"] = page
    return resolved


async def extract_sop_requirements(prompt: str) -> list:
    logger.info("sending SOP requirements to Anthropic")
    response = await client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    logger.info("received SOP requirements from Anthropic")

    return _parse_response(response)
