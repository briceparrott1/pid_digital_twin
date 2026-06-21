# Unit tests for call_vlm and call_vlm_async retry policies, using mocked
# clients -- no real API calls.
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import anthropic
from engine.config import VlmConfig
from engine.leaf.vlm_client import call_vlm, call_vlm_async

_CONFIG = VlmConfig(
    model="test-model",
    max_tokens=100,
    max_retries=2,
    backoff_seconds=0.0,
    thinking_effort="",
)


def _success_response(text: str):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _rate_limit_error() -> anthropic.RateLimitError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, request=request)
    return anthropic.RateLimitError("rate limited", response=response, body=None)


def test_successful_call_on_first_attempt_does_not_retry():
    client = MagicMock()
    client.messages.create.return_value = _success_response('{"ok": true}')
    result = call_vlm(_dummy_image(), "prompt", _CONFIG, client)
    assert result == '{"ok": true}'
    assert client.messages.create.call_count == 1


def test_transport_failure_retries_then_succeeds():
    client = MagicMock()
    client.messages.create.side_effect = [
        _rate_limit_error(),
        _rate_limit_error(),
        _success_response("recovered"),
    ]
    result = call_vlm(_dummy_image(), "prompt", _CONFIG, client)
    assert result == "recovered"
    assert client.messages.create.call_count == 3


def test_transport_failure_raises_after_exhausting_retries():
    client = MagicMock()
    client.messages.create.side_effect = _rate_limit_error()
    with pytest.raises(anthropic.RateLimitError):
        call_vlm(_dummy_image(), "prompt", _CONFIG, client)
    assert client.messages.create.call_count == _CONFIG.max_retries + 1


def test_disabled_thinking_omits_thinking_and_output_config_kwargs():
    client = MagicMock()
    client.messages.create.return_value = _success_response('{"ok": true}')
    call_vlm(_dummy_image(), "prompt", _CONFIG, client)
    assert "thinking" not in client.messages.create.call_args.kwargs
    assert "output_config" not in client.messages.create.call_args.kwargs


def test_enabled_thinking_passes_adaptive_type_and_effort_to_the_request():
    config = VlmConfig(
        model="test-model",
        max_tokens=100,
        max_retries=2,
        backoff_seconds=0.0,
        thinking_effort="high",
    )
    client = MagicMock()
    client.messages.create.return_value = _success_response('{"ok": true}')
    call_vlm(_dummy_image(), "prompt", config, client)
    assert client.messages.create.call_args.kwargs["thinking"] == {"type": "adaptive"}
    assert client.messages.create.call_args.kwargs["output_config"] == {
        "effort": "high"
    }


def test_call_vlm_skips_thinking_blocks_and_returns_only_text():
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="reasoning..."),
            SimpleNamespace(type="text", text='{"ok": true}'),
        ]
    )
    result = call_vlm(_dummy_image(), "prompt", _CONFIG, client)
    assert result == '{"ok": true}'


def test_call_vlm_async_returns_text_block():
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_success_response('{"ok": true}'))
    result = asyncio.run(call_vlm_async(_dummy_image(), "prompt", _CONFIG, client))
    assert result == '{"ok": true}'


def test_call_vlm_async_retries_on_transport_failure():
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[_rate_limit_error(), _success_response("ok")]
    )
    result = asyncio.run(call_vlm_async(_dummy_image(), "prompt", _CONFIG, client))
    assert result == "ok"
    assert client.messages.create.call_count == 2


def _dummy_image():
    import numpy as np

    return np.full((10, 10, 3), 255, dtype=np.uint8)
