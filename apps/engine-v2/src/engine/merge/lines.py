# Resolves SplitConnection obligations facing a seam by pairing them on their
# color join key and emitting one Edge per matched pair. Label is intentionally
# excluded: the VLM inconsistently omits labels, so including it in the key
# causes false split failures when one side reports a label and the other doesn't.
from __future__ import annotations

from collections import defaultdict

from engine.instrument.counters import Counters
from engine.types import Edge, SplitConnection


def resolve_connections(
    facing_a: list[SplitConnection],
    facing_b: list[SplitConnection],
    counters: Counters,
) -> tuple[list[Edge], list[SplitConnection]]:
    """Pairs `facing_a`/`facing_b` connections by color; returns the resolved
    `Edge`s plus any obligations left unmatched (kept open rather than dropped).
    A color with more than one match on either side increments
    `counters.seam_collisions` once; within a collision bucket, pairing is
    positional (first-a with first-b, etc.)."""
    by_key_a: dict[str, list[SplitConnection]] = defaultdict(list)
    by_key_b: dict[str, list[SplitConnection]] = defaultdict(list)
    for conn in facing_a:
        by_key_a[conn.color].append(conn)
    for conn in facing_b:
        by_key_b[conn.color].append(conn)

    edges: list[Edge] = []
    unmatched: list[SplitConnection] = []
    for key in set(by_key_a) | set(by_key_b):  # key is now just color
        a_list = by_key_a.get(key, [])
        b_list = by_key_b.get(key, [])
        if len(a_list) > 1 or len(b_list) > 1:
            counters.seam_collisions += 1
        paired = min(len(a_list), len(b_list))
        for i in range(paired):
            edges.append(Edge(a=a_list[i].node, b=b_list[i].node))
        unmatched.extend(a_list[paired:])
        unmatched.extend(b_list[paired:])

    return edges, unmatched
