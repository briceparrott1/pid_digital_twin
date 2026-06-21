# The single Anthropic SDK boundary: sends one segment crop + prompt to the
# VLM and returns its raw text. Retries only on transport/API failures --
# never on a bad parse, which is leaf_read.py's concern, not this file's.
# Both a synchronous and an async variant are provided; the async one is used
# by the parallel batch runner in scripts/run.py.
# Non-streaming is used because each call is a single bounded crop+JSON
# request that finishes well within the limit.
from __future__ import annotations

import asyncio
import base64
import time

import anthropic
import cv2
import numpy as np

from engine.config import VlmConfig

# Failures worth retrying: nothing was learned, ask again. Client errors
# (bad request, auth, permission, not-found, too-large) are not included --
# retrying an identical malformed request never succeeds.
_RETRYABLE_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.OverloadedError,
)


def _encode_png_base64(image: np.ndarray) -> str:
    """Encodes a BGR ndarray as base64 PNG bytes for the Messages API image block."""
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("failed to encode image as PNG")
    return base64.standard_b64encode(buffer.tobytes()).decode("utf-8")


def _build_extra_kwargs(config: VlmConfig) -> dict:
    """Builds the thinking/output_config kwargs from the VlmConfig.

    When thinking_budget_tokens > 0, uses the enabled+budget_tokens form so the
    model cannot consume more than that many tokens on thinking, leaving the rest
    of max_tokens for the JSON answer. Falls back to adaptive+effort otherwise.
    The two forms are mutually exclusive in the API.
    """
    if config.thinking_budget_tokens > 0:
        return {
            "thinking": {
                "type": "enabled",
                "budget_tokens": config.thinking_budget_tokens,
            }
        }
    if not config.thinking_effort:
        return {}
    return {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": config.thinking_effort},
    }


def _messages_payload(image_b64: str, prompt: str) -> list:
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_b64,
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }
    ]


def call_vlm(
    image: np.ndarray, prompt: str, config: VlmConfig, client: anthropic.Anthropic
) -> str:
    """Sends `image` + `prompt` as one vision request via the non-streaming
    Messages API; returns the response's raw text content. Retries up to
    `config.max_retries` times with exponential backoff on transport/API
    failures only."""
    image_b64 = _encode_png_base64(image)
    extra_kwargs = _build_extra_kwargs(config)
    last_error: Exception | None = None
    for attempt in range(config.max_retries + 1):
        try:
            msg = client.messages.create(
                model=config.model,
                max_tokens=config.max_tokens,
                messages=_messages_payload(image_b64, prompt),
                timeout=3600.0,
                **extra_kwargs,
            )
        except _RETRYABLE_ERRORS as error:
            last_error = error
            if attempt < config.max_retries:
                time.sleep(config.backoff_seconds * (2**attempt))
                continue
            raise
        if msg.stop_reason == "max_tokens":
            raise RuntimeError(
                "VLM response truncated (stop_reason=max_tokens); "
                "increase max_tokens or reduce input"
            )
        return next((b.text for b in msg.content if b.type == "text"), "")
    raise last_error  # pragma: no cover


async def call_vlm_async(
    image: np.ndarray,
    prompt: str,
    config: VlmConfig,
    client: anthropic.AsyncAnthropic,
) -> str:
    """Async variant of `call_vlm`: identical contract but uses AsyncAnthropic
    so many calls can be awaited concurrently. The synchronous encoding step
    runs in a thread pool to avoid blocking the event loop."""
    image_b64 = await asyncio.get_event_loop().run_in_executor(
        None, _encode_png_base64, image
    )
    extra_kwargs = _build_extra_kwargs(config)
    last_error: Exception | None = None
    for attempt in range(config.max_retries + 1):
        try:
            msg = await client.messages.create(
                model=config.model,
                max_tokens=config.max_tokens,
                messages=_messages_payload(image_b64, prompt),
                timeout=3600.0,
                **extra_kwargs,
            )
        except _RETRYABLE_ERRORS as error:
            last_error = error
            if attempt < config.max_retries:
                await asyncio.sleep(config.backoff_seconds * (2**attempt))
                continue
            raise
        if msg.stop_reason == "max_tokens":
            raise RuntimeError(
                "VLM response truncated (stop_reason=max_tokens); "
                "increase max_tokens or reduce input"
            )
        return next((b.text for b in msg.content if b.type == "text"), "")
    raise last_error  # pragma: no cover
