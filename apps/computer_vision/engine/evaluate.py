"""Scores a pipeline run's graph against data/truth_set.json.

Node F1: component identity (junctions excluded entirely).
Connection F1: start/end identity with junction endpoints collapsed to a
generic category — only "did it pick up a connection involving a junction"
matters, never which specific junction.

Ported from apps/engine-v2/scripts/evaluate.py; adapted for the production
results layout under results/production/ and extended to record token usage.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

_RESULTS_DIR = Path("results/production")
_TRUTH_SET_PATH = Path("data/truth_set.json")
_JUNCTION = "JUNCTION"


def _prf1(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def _normalize_id(raw_id: str) -> str:
    return re.sub(r"[\s_]+", " ", raw_id.strip()).upper()


def _node_f1(predicted_nodes: list[dict], truth_nodes: list[dict]) -> dict:
    predicted_ids = {
        _normalize_id(n["id"]) for n in predicted_nodes if n["type"] != "junction"
    }
    truth_ids = {
        _normalize_id(n["component_name"])
        for n in truth_nodes
        if n["level"] != "junction"
    }
    tp = len(predicted_ids & truth_ids)
    fp = len(predicted_ids - truth_ids)
    fn = len(truth_ids - predicted_ids)
    return _prf1(tp, fp, fn)


def _is_junction_id(node_id: str, id_to_category: dict[str, str]) -> bool:
    category = id_to_category.get(node_id)
    if category is not None:
        return category == "junction"
    return bool(re.fullmatch(r"J\d+", node_id))


def _normalize_edge(
    a: str, b: str, id_to_category: dict[str, str]
) -> tuple[str, str]:
    norm_a = _JUNCTION if _is_junction_id(a, id_to_category) else a
    norm_b = _JUNCTION if _is_junction_id(b, id_to_category) else b
    return tuple(sorted((norm_a, norm_b)))


def _connection_f1(
    predicted_edges: list[dict],
    predicted_nodes: list[dict],
    truth_connections: list[dict],
    truth_nodes: list[dict],
) -> dict:
    pred_id_to_type = {_normalize_id(n["id"]): n["type"] for n in predicted_nodes}
    truth_id_to_level = {
        _normalize_id(n["component_name"]): n["level"] for n in truth_nodes
    }
    predicted = Counter(
        _normalize_edge(_normalize_id(e["a"]), _normalize_id(e["b"]), pred_id_to_type)
        for e in predicted_edges
    )
    truth = Counter(
        _normalize_edge(
            _normalize_id(c["start"]), _normalize_id(c["end"]), truth_id_to_level
        )
        for c in truth_connections
    )
    tp = sum(min(predicted[k], truth[k]) for k in predicted)
    fp = sum(max(predicted[k] - truth.get(k, 0), 0) for k in predicted)
    fn = sum(max(truth[k] - predicted.get(k, 0), 0) for k in truth)
    return _prf1(tp, fp, fn)


def evaluate(graph: dict, truth: dict) -> dict:
    """Scores one run's graph against the truth set.

    Returns {"node_f1": {...}, "connection_f1": {...}}.
    """
    return {
        "node_f1": _node_f1(graph["nodes"], truth["nodes"]),
        "connection_f1": _connection_f1(
            graph["edges"], graph["nodes"], truth["connections"], truth["nodes"]
        ),
    }


def _format_block(run_label: str, scores: dict) -> str:
    node, conn = scores["node_f1"], scores["connection_f1"]
    elapsed = scores.get("elapsed_seconds")
    elapsed_str = f" — {elapsed:.0f}s" if elapsed is not None else ""
    token_usage = scores.get("token_usage", {})
    token_str = ""
    if token_usage:
        inp = token_usage.get("input_tokens", 0)
        out = token_usage.get("output_tokens", 0)
        token_str = f" — {inp:,} in / {out:,} out tokens"
    return (
        f"\n## Evaluation ({run_label}{elapsed_str}{token_str})\n\n"
        f"- Node F1 (junctions excluded): {node['f1']:.3f} "
        f"(precision {node['precision']:.3f}, recall {node['recall']:.3f}, "
        f"tp={node['tp']} fp={node['fp']} fn={node['fn']})\n"
        f"- Connection F1 (junction endpoints collapsed to category): {conn['f1']:.3f} "
        f"(precision {conn['precision']:.3f}, recall {conn['recall']:.3f}, "
        f"tp={conn['tp']} fp={conn['fp']} fn={conn['fn']})\n"
    )


def _run_number(run_dir: Path) -> int:
    return int(run_dir.name.removeprefix("run_"))


def _next_run_dir(results_dir: Path) -> Path:
    """Returns the next results/production/run_<n> path (does not create it)."""
    if not results_dir.exists():
        return results_dir / "run_1"
    candidates = [
        p
        for p in results_dir.iterdir()
        if p.is_dir() and p.name.removeprefix("run_").isdigit()
    ]
    next_n = max((int(p.name.removeprefix("run_")) for p in candidates), default=0) + 1
    return results_dir / f"run_{next_n}"


def _write_summary(results_dir: Path) -> None:
    """Rewrites results/production/summary.md from every eval.json present."""
    if not results_dir.exists():
        return
    run_dirs = sorted(
        (
            p
            for p in results_dir.iterdir()
            if p.is_dir() and p.name.removeprefix("run_").isdigit()
        ),
        key=_run_number,
    )
    rows = []
    for run_dir in run_dirs:
        eval_path = run_dir / "eval.json"
        if not eval_path.exists():
            continue
        scores = json.loads(eval_path.read_text())
        node, conn = scores["node_f1"], scores["connection_f1"]
        elapsed = scores.get("elapsed_seconds")
        elapsed_str = f"{elapsed:.0f}s" if elapsed is not None else "—"
        token_usage = scores.get("token_usage", {})
        inp = token_usage.get("input_tokens", 0)
        out = token_usage.get("output_tokens", 0)
        token_str = f"{inp:,}/{out:,}" if token_usage else "—"
        rows.append(
            f"| {run_dir.name} | {node['f1']:.3f} | {conn['f1']:.3f}"
            f" | {elapsed_str} | {token_str} |"
        )
    lines = [
        "| run | node F1 | connection F1 | time | tokens (in/out) |",
        "|---|---|---|---|---|",
        *rows,
    ]
    (results_dir / "summary.md").write_text("\n".join(lines) + "\n")


def evaluate_run(
    graph: dict,
    run_dir: Path,
    truth_path: Path = _TRUTH_SET_PATH,
    results_dir: Path = _RESULTS_DIR,
    elapsed_seconds: float | None = None,
    token_usage: dict | None = None,
) -> dict:
    """Evaluates a graph dict, writes run_dir/output.json, run_dir/eval.json,
    appends to run_dir/notes.md, and rewrites results_dir/summary.md."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "output.json").write_text(json.dumps({"graph": graph}, indent=2))

    truth = json.loads(truth_path.read_text())
    scores = evaluate(graph, truth)
    if elapsed_seconds is not None:
        scores["elapsed_seconds"] = elapsed_seconds
    if token_usage:
        scores["token_usage"] = token_usage
    (run_dir / "eval.json").write_text(json.dumps(scores, indent=2))

    with (run_dir / "notes.md").open("a") as f:
        f.write(_format_block(run_dir.name, scores))

    _write_summary(results_dir)
    return scores
