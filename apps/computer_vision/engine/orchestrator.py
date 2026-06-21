import json
import logging
from pathlib import Path

import anthropic

from core.config import get_settings
from engine.tools.prompts import PID_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)

_RETRYABLE_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.OverloadedError,
)

_BETAS = ["files-api-2025-04-14", "code-execution-2025-08-25"]
_CODE_EXEC_TOOL = {"type": "code_execution_20250825", "name": "code_execution"}


async def run_algo(pdf_path: str) -> dict:
    """Upload P&ID PDF via Files API; let Claude rasterize and tile it via
    code_execution; return parsed dict with keys: nodes, edges, uncertainty."""
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    with open(pdf_path, "rb") as fh:
        uploaded = await client.beta.files.upload(
            file=(Path(pdf_path).name, fh, "application/pdf"),
        )
    file_id = uploaded.id
    logger.info("uploaded PDF to Files API (file_id=%s)", file_id)

    content = [
        {"type": "container_upload", "file_id": file_id},
        {"type": "text", "text": PID_EXTRACTION_PROMPT},
    ]

    try:
        for attempt in range(3):
            try:
                logger.info(
                    "sending P&ID PDF for code-execution extraction (model=%s attempt=%d)",
                    settings.model,
                    attempt,
                )
                async with client.beta.messages.stream(
                    model=settings.model,
                    max_tokens=64000,
                    thinking={"type": "adaptive"},
                    output_config={"effort": "high"},
                    tools=[_CODE_EXEC_TOOL],
                    betas=_BETAS,
                    messages=[{"role": "user", "content": content}],
                ) as stream:
                    msg = await stream.get_final_message()

                if msg.stop_reason == "max_tokens":
                    raise RuntimeError(
                        "Claude response truncated (stop_reason=max_tokens); "
                        "raise max_tokens or reduce page complexity"
                    )

                logger.info(
                    "received P&ID extraction (input_tokens=%d output_tokens=%d)",
                    msg.usage.input_tokens,
                    msg.usage.output_tokens,
                )

                sandbox_error = any(
                    getattr(b, "type", None) == "tool_result"
                    and getattr(b, "is_error", False)
                    for b in msg.content
                )
                if sandbox_error:
                    logger.warning(
                        "sandbox rasterization failed; falling back to local PNG upload"
                    )
                    return await _png_fallback(client, settings, pdf_path)

                text_blocks = [
                    b.text for b in msg.content if getattr(b, "type", None) == "text"
                ]
                text = text_blocks[-1] if text_blocks else ""
                text = (
                    text.strip()
                    .removeprefix("```json")
                    .removeprefix("```")
                    .removesuffix("```")
                    .strip()
                )
                return json.loads(text)

            except _RETRYABLE_ERRORS as exc:
                if attempt < 2:
                    logger.warning("retryable error on attempt %d: %s", attempt, exc)
                    continue
                raise
    finally:
        try:
            await client.beta.files.delete(file_id)
        except Exception as exc:
            logger.warning("failed to delete uploaded file %s: %s", file_id, exc)


async def _png_fallback(
    client: anthropic.AsyncAnthropic,
    settings,
    pdf_path: str,
) -> dict:
    """Rasterize locally with PyMuPDF, upload PNGs via Files API, re-run extraction."""
    import fitz  # noqa: PLC0415

    doc = fitz.open(pdf_path)
    png_ids: list[str] = []
    try:
        for page in doc:
            mat = fitz.Matrix(375 / 72, 375 / 72)
            pix = page.get_pixmap(matrix=mat)
            up = await client.beta.files.upload(
                file=("page.png", pix.tobytes("png"), "image/png"),
            )
            png_ids.append(up.id)

        content = [
            *[{"type": "container_upload", "file_id": fid} for fid in png_ids],
            {"type": "text", "text": PID_EXTRACTION_PROMPT},
        ]
        async with client.beta.messages.stream(
            model=settings.model,
            max_tokens=64000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            tools=[_CODE_EXEC_TOOL],
            betas=_BETAS,
            messages=[{"role": "user", "content": content}],
        ) as stream:
            msg = await stream.get_final_message()

        text_blocks = [
            b.text for b in msg.content if getattr(b, "type", None) == "text"
        ]
        text = text_blocks[-1] if text_blocks else ""
        text = (
            text.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
        return json.loads(text)
    finally:
        for fid in png_ids:
            try:
                await client.beta.files.delete(fid)
            except Exception as exc:
                logger.warning("failed to delete PNG file %s: %s", fid, exc)
