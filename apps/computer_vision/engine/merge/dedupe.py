# Deduplicates Node lists by id (tag-based identity) — two segments reading the
# same printed junction/tag collapse to one node.
from __future__ import annotations

from engine.types import Node


def dedupe_nodes(nodes: list[Node]) -> list[Node]:
    """Collapses nodes sharing an `id` into one, merging metadata and keeping
    the first-seen `type`, preserving first-seen order."""
    by_id: dict[str, Node] = {}
    order: list[str] = []
    for node in nodes:
        if node.id not in by_id:
            by_id[node.id] = Node(
                id=node.id, type=node.type, metadata=dict(node.metadata)
            )
            order.append(node.id)
        else:
            by_id[node.id].metadata.update(node.metadata)
    return [by_id[node_id] for node_id in order]
