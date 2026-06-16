import base64
import json
import logging

import anthropic

from core.config import get_settings

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Raised when Claude's extraction response can't be turned into JSON.

    Carries the raw response text (and stop reason) so callers can persist
    it for debugging instead of losing the API response entirely.
    """

    def __init__(self, message: str, raw_text: str, stop_reason: str | None = None):
        super().__init__(message)
        self.raw_text = raw_text
        self.stop_reason = stop_reason


def _parse_response(response) -> dict:
    raw_text = response.content[0].text

    if response.stop_reason == "max_tokens":
        raise ExtractionError(
            "Claude response was truncated (stop_reason=max_tokens); "
            "increase max_tokens to capture the full extraction",
            raw_text=raw_text,
            stop_reason=response.stop_reason,
        )

    text = (
        raw_text.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ExtractionError(
            f"Could not parse extraction response as JSON: {e}",
            raw_text=raw_text,
            stop_reason=response.stop_reason,
        ) from e


async def extract_page(image: bytes, prompt: str, model: str | None = None) -> dict:
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    image_b64 = base64.standard_b64encode(image).decode("utf-8")
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": image_b64,
            },
        },
        {"type": "text", "text": prompt},
    ]

    logger.info("sending P&ID page to Anthropic (model=%s)", model or settings.model)
    async with client.messages.stream(
        model=model or settings.model,
        max_tokens=64000,
        messages=[{"role": "user", "content": content}],
    ) as stream:
        response = await stream.get_final_message()
    logger.info(
        "received P&ID extraction from Anthropic (input_tokens=%d output_tokens=%d)",
        response.usage.input_tokens,
        response.usage.output_tokens,
    )

    result = _parse_response(response)
    return result
