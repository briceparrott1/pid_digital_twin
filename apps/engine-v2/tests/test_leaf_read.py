# Unit tests for leaf_read/parse_leaf_result: parses well-formed VLM JSON,
# raises immediately (no retry) on any malformed/incomplete output. The VLM
# call itself is monkeypatched -- never hits the real API.
from __future__ import annotations

import json

import numpy as np
import pytest

import engine.leaf.leaf_read as leaf_read_module
from engine.config import VlmConfig
from engine.leaf.leaf_read import LeafParseError, leaf_read, parse_leaf_result
from engine.types import (
    SELF_REF,
    Box,
    Edge,
    LeafEdge,
    LeafNode,
    Segment,
    SplitConnection,
    SplitNode,
)

_CONFIG = VlmConfig(
    model="test-model",
    max_tokens=100,
    max_retries=2,
    backoff_seconds=0.0,
    thinking_effort="",
)

_WELL_FORMED = {
    "nodes": [{"id": "V1", "type": "valve", "metadata": {"foo": "bar"}}],
    "edges": [{"a": "V1", "b": "J1"}],
    "split_connections": [
        {"node": "V1", "color": "red", "label": "L1", "side": "right"}
    ],
    "split_nodes": [{"id": "T1", "type": "vessel", "metadata": {}, "sides": ["left"]}],
    "uncertainty": "not sure about the label",
}


def _segment() -> Segment:
    image = np.full((20, 20, 3), 255, dtype=np.uint8)
    return Segment(
        image_uncolored=image,
        image_colored=image.copy(),
        bbox=Box(0, 0, 20, 20),
        cut_sides={"top": False, "bottom": False, "left": False, "right": False},
        id="root",
    )


def test_well_formed_json_parses_field_for_field():
    result = parse_leaf_result(json.dumps(_WELL_FORMED))
    assert result.nodes == [LeafNode(id="V1", type="valve", metadata={"foo": "bar"})]
    assert result.edges == [LeafEdge(a="V1", b="J1")]
    assert result.split_connections == [
        SplitConnection(node="V1", color="red", label="L1", side="right")
    ]
    assert result.split_nodes == [
        SplitNode(id="T1", type="vessel", metadata={}, sides=["left"], edges=[])
    ]
    assert result.uncertainty == "not sure about the label"


def test_split_node_connects_to_becomes_self_ref_edges():
    with_connects_to = json.loads(json.dumps(_WELL_FORMED))
    with_connects_to["split_nodes"][0]["connects_to"] = ["V1", "V2"]
    result = parse_leaf_result(json.dumps(with_connects_to))
    assert result.split_nodes == [
        SplitNode(
            id="T1",
            type="vessel",
            metadata={},
            sides=["left"],
            edges=[Edge(a="V1", b=SELF_REF), Edge(a="V2", b=SELF_REF)],
        )
    ]


def test_split_node_without_connects_to_has_no_edges():
    result = parse_leaf_result(json.dumps(_WELL_FORMED))
    assert result.split_nodes[0].edges == []


def test_missing_top_level_list_key_defaults_to_empty_not_raise():
    # A missing list key carries the same information as an explicit [] --
    # the model sometimes omits an empty array rather than writing it out.
    missing_key = json.loads(json.dumps(_WELL_FORMED))
    del missing_key["edges"]
    result = parse_leaf_result(json.dumps(missing_key))
    assert result.edges == []
    assert result.nodes == [LeafNode(id="V1", type="valve", metadata={"foo": "bar"})]


def test_missing_required_field_within_an_entry_raises():
    malformed = json.loads(json.dumps(_WELL_FORMED))
    del malformed["nodes"][0]["id"]
    with pytest.raises(LeafParseError):
        parse_leaf_result(json.dumps(malformed))


def test_unparseable_json_raises():
    with pytest.raises(LeafParseError):
        parse_leaf_result("not json at all {{{")


def test_extra_unexpected_field_is_ignored():
    with_extra = json.loads(json.dumps(_WELL_FORMED))
    with_extra["some_extra_field"] = "ignored"
    with_extra["nodes"][0]["unexpected"] = "also ignored"
    result = parse_leaf_result(json.dumps(with_extra))
    assert result.nodes == [LeafNode(id="V1", type="valve", metadata={"foo": "bar"})]


def test_no_retry_on_any_failure_case(monkeypatch):
    call_count = {"n": 0}

    def fake_call_vlm(image, prompt, config, client):
        call_count["n"] += 1
        return "not json {{{"

    monkeypatch.setattr(leaf_read_module, "call_vlm", fake_call_vlm)
    with pytest.raises(LeafParseError):
        leaf_read(_segment(), _CONFIG, client=object())
    assert call_count["n"] == 1


def test_leaf_read_returns_parsed_result_on_well_formed_output(monkeypatch):
    monkeypatch.setattr(
        leaf_read_module,
        "call_vlm",
        lambda image, prompt, config, client: json.dumps(_WELL_FORMED),
    )
    result = leaf_read(_segment(), _CONFIG, client=object())
    assert result.nodes[0].id == "V1"
