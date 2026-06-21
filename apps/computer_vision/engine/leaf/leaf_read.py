# The real Segment -> LeafResult implementation: calls the VLM, parses its
# JSON into the sealed LeafResult contract. A parse failure raises
# immediately -- no retry, no degraded result, no fallback. Retrying an
# identical call against a non-deterministic model risks a different kind of
# bad output, not a better one; surfacing the raw response lets a human
# decide whether it's a prompt problem or a one-off.
from __future__ import annotations

import json

import anthropic

from engine.config import VlmConfig
from engine.leaf.prompt import build_leaf_prompt
from engine.leaf.vlm_client import call_vlm, call_vlm_async
from engine.types import (
    SELF_REF,
    Edge,
    LeafEdge,
    LeafNode,
    LeafResult,
    PassThroughConnection,
    Segment,
    SplitConnection,
    SplitNode,
)


class LeafParseError(ValueError):
    """Raised when the VLM's output does not match the LeafResult contract.
    Carries the raw response so a human can inspect exactly what came back."""

    def __init__(self, message: str, raw_response: str):
        super().__init__(message)
        self.raw_response = raw_response


def parse_leaf_result(raw_text: str) -> LeafResult:
    """Parses `raw_text` (the VLM's raw JSON response) into a `LeafResult`.
    Raises `LeafParseError` immediately on unparseable JSON or a missing
    required field within a list entry; unrecognized extra fields are
    silently ignored. A top-level list key ("nodes"/"edges"/
    "split_connections"/"split_nodes") missing entirely is treated the same
    as an explicit empty list -- the model occasionally omits an empty array
    key rather than writing it out, and a missing key carries the exact same
    information as an explicit [] (nothing to report), so defaulting it
    loses nothing. Required fields *within* a present entry stay strict."""
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise LeafParseError(
            f"VLM output was not valid JSON: {error}", raw_response=raw_text
        ) from error

    try:
        nodes = [
            LeafNode(id=n["id"], type=n["type"], metadata=n.get("metadata", {}))
            for n in data.get("nodes", [])
        ]
        edges = [LeafEdge(a=e["a"], b=e["b"]) for e in data.get("edges", [])]
        split_connections = [
            SplitConnection(
                node=c["node"], color=c["color"], label=c["label"], side=c["side"]
            )
            for c in data.get("split_connections", [])
        ]
        split_nodes = [
            SplitNode(
                id=n.get("id"),
                type=n["type"],
                metadata=n.get("metadata", {}),
                sides=n["sides"],
                edges=[
                    Edge(a=other_id, b=SELF_REF)
                    for other_id in n.get("connects_to", [])
                ],
            )
            for n in data.get("split_nodes", [])
        ]
        pass_through_connections = [
            PassThroughConnection(
                color=p["color"],
                label_in=p["label_in"],
                side_in=p["side_in"],
                label_out=p["label_out"],
                side_out=p["side_out"],
            )
            for p in data.get("pass_through_connections", [])
        ]
        uncertainty = data.get("uncertainty", "")
    except (KeyError, TypeError) as error:
        raise LeafParseError(
            f"VLM output missing a required field: {error}", raw_response=raw_text
        ) from error

    return LeafResult(
        nodes=nodes,
        edges=edges,
        split_connections=split_connections,
        split_nodes=split_nodes,
        uncertainty=uncertainty,
        pass_through_connections=pass_through_connections,
    )


def leaf_read(
    segment: Segment, config: VlmConfig, client: anthropic.Anthropic
) -> LeafResult:
    """Reads one leaf segment via the VLM and parses its response."""
    raw_text = call_vlm(segment.image_colored, build_leaf_prompt(), config, client)
    return parse_leaf_result(raw_text)


async def async_leaf_read(
    segment: Segment, config: VlmConfig, client: anthropic.AsyncAnthropic
) -> LeafResult:
    """Async variant of `leaf_read`: same contract, uses `AsyncAnthropic` so
    many leaf segments can be read concurrently."""
    raw_text = await call_vlm_async(
        segment.image_colored, build_leaf_prompt(), config, client
    )
    return parse_leaf_result(raw_text)
