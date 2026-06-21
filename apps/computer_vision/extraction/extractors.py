import json
import logging

import anthropic

from core.config import get_settings

logger = logging.getLogger(__name__)


async def extract_sop_requirements(prompt: str) -> list:
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    logger.info("sending SOP requirements to Anthropic")
    response = await client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    logger.info("received SOP requirements from Anthropic")

    raw_text = response.content[0].text
    text = (
        raw_text.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )
    return json.loads(text)
