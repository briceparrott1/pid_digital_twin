import re
from typing import Any


def normalize_label(label: str) -> str:
    """Upper-case and collapse whitespace runs to "_".

    Converts off-page-endpoint destination text (e.g. "TO CLOSED DRAIN TANK
    V-005") into the truth set's naming convention
    (e.g. "TO_CLOSED_DRAIN_TANK_V-005").
    """
    return re.sub(r"\s+", "_", label.strip().upper())


def flatten_metadata(data: dict, prefix: str = "metadata") -> dict[str, Any]:
    """Recursively flatten a nested metadata dict into "metadata_..." keys.

    e.g. {"design_specs": {"pressure_psig": 275}} -> {"metadata_design_specs_pressure_psig": 275}

    The same function is applied to both the extraction's and the truth
    set's metadata dicts so that field names line up for comparison.
    """
    flat: dict[str, Any] = {}
    for key, value in data.items():
        flat_key = f"{prefix}_{key}"
        if isinstance(value, dict):
            flat.update(flatten_metadata(value, flat_key))
        else:
            flat[flat_key] = value
    return flat


def resolve(raw: dict) -> dict:
    """Turn raw extraction output into the flat, truth-set-comparable shape.

    The extraction prompt already emits component_name/level directly for
    all five levels (equipment/instrument/valve/junction/out_of_system) and
    start_id/end_id as component_name references, so resolution is mostly a
    pass-through plus metadata flattening.

    - every node's nested "metadata" dict is flattened onto the node as
      "metadata_*" keys.
    - out_of_system component names are normalized (uppercase, whitespace ->
      "_") to match the truth set's naming convention.
    - a metadata-only result (equipment metadata pass) has no nodes or
      connections; its "equipment" dict is passed through unchanged, with
      nested spec dicts (design_specs, MDMT, design_cap) intact.
    """
    resolved_nodes = []
    for node in raw.get("nodes", []):
        level = node.get("level")
        if isinstance(level, str):
            level = level.strip().lower()
        component_name = (node.get("component_name") or "").strip()
        if level == "out_of_system":
            component_name = normalize_label(component_name)
        metadata = node.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        resolved_node = {"component_name": component_name, "level": level}
        if "confidence" in node:
            resolved_node["confidence"] = node["confidence"]
        resolved_node.update(flatten_metadata(metadata))
        resolved_nodes.append(resolved_node)

    resolved_connections = []
    for conn in raw.get("connections", []):
        if "color" in conn:
            # SEGMENT_PROMPT fragment: {color, endpoints, line_type,
            # confidence}. Pass through unchanged for stitch_by_color.
            resolved_connections.append(dict(conn))
        else:
            resolved_connection = {
                "start_id": conn.get("start_id"),
                "end_id": conn.get("end_id"),
                "line_type": conn.get("line_type"),
            }
            if "confidence" in conn:
                resolved_connection["confidence"] = conn["confidence"]
            resolved_connections.append(resolved_connection)

    return {
        "nodes": resolved_nodes,
        "connections": resolved_connections,
        "junctions": raw.get("junctions", []),
        "equipment": raw.get("equipment", {}),
    }
