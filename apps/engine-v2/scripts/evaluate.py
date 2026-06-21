# Scores a recorded run's graph against data/truth_set.json: node F1
# (component identity, junctions excluded entirely) and connection F1
# (start/end identity, with junction endpoints collapsed to a generic
# category since only "did it pick up a connection involving a junction"
# matters, never which specific junction). Metadata is never compared.
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

_RESULTS_DIR = Path("results")
_TRUTH_SET_PATH = Path("data/truth_set.json")
_JUNCTION = "JUNCTION"


def _prf1(tp: int, fp: int, fn: int) -> dict:
    """Computes precision/recall/F1 from true/false positive/negative counts."""
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
    """Canonicalizes an id for comparison: collapses underscores/whitespace
    to single spaces and uppercases. Makes truth's slugged convention (e.g.
    "TO_SURGE_DRUM_V-720") compare equal to the model's verbatim transcription
    (e.g. "TO SURGE DRUM V-720"); a no-op for ordinary dash-only tags."""
    return re.sub(r"[\s_]+", " ", raw_id.strip()).upper()


def _node_f1(predicted_nodes: list[dict], truth_nodes: list[dict]) -> dict:
    """Set-based F1 over node identity (id/component_name), excluding
    junctions entirely from both sides -- junctions are scored only as part
    of connection F1, never individually."""
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
    """True if `node_id` is a junction, by its recorded level/type (truth
    uses "level", predicted uses "type" -- callers pass the right lookup for
    their side, already keyed by normalized id). Falls back to the
    "J<digits>" naming convention if an id is ever missing from the lookup,
    as a defensive guard against a connection referencing a node absent from
    its own "nodes"/"connections" list."""
    category = id_to_category.get(node_id)
    if category is not None:
        return category == "junction"
    return bool(re.fullmatch(r"J\d+", node_id))


def _normalize_edge(a: str, b: str, id_to_category: dict[str, str]) -> tuple[str, str]:
    """Collapses any junction endpoint to a generic category, then returns an
    order-independent pair -- a junction-involving connection only needs to
    match by category (junction-junction vs node-junction), never by which
    specific junction was involved."""
    norm_a = _JUNCTION if _is_junction_id(a, id_to_category) else a
    norm_b = _JUNCTION if _is_junction_id(b, id_to_category) else b
    return tuple(sorted((norm_a, norm_b)))


def _connection_f1(
    predicted_edges: list[dict],
    predicted_nodes: list[dict],
    truth_connections: list[dict],
    truth_nodes: list[dict],
) -> dict:
    """Multiset F1 over normalized (a, b) pairs: counted with multiplicity
    (not a plain set) so multiple distinct junction-involving connections
    each still count individually, even though they collapse to the same
    normalized category."""
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
    """Scores one run's graph (the "graph" object from output.json) against
    the truth set. Returns {"node_f1": {...}, "connection_f1": {...}}."""
    return {
        "node_f1": _node_f1(graph["nodes"], truth["nodes"]),
        "connection_f1": _connection_f1(
            graph["edges"], graph["nodes"], truth["connections"], truth["nodes"]
        ),
    }


def _format_block(run_label: str, scores: dict) -> str:
    """Renders one run's scores as a human-readable Markdown block for notes.md."""
    node, conn = scores["node_f1"], scores["connection_f1"]
    elapsed = scores.get("elapsed_seconds")
    elapsed_str = f" — {elapsed:.0f}s" if elapsed is not None else ""
    return (
        f"\n## Evaluation ({run_label}{elapsed_str})\n\n"
        f"- Node F1 (junctions excluded): {node['f1']:.3f} "
        f"(precision {node['precision']:.3f}, recall {node['recall']:.3f}, "
        f"tp={node['tp']} fp={node['fp']} fn={node['fn']})\n"
        f"- Connection F1 (junction endpoints collapsed to category): {conn['f1']:.3f} "
        f"(precision {conn['precision']:.3f}, recall {conn['recall']:.3f}, "
        f"tp={conn['tp']} fp={conn['fp']} fn={conn['fn']})\n"
    )


def _run_number(run_dir: Path) -> int:
    """Extracts the numeric suffix from a results/run_<n> directory name."""
    return int(run_dir.name.removeprefix("run_"))


def _latest_run_dir(results_dir: Path) -> Path:
    """Finds the highest-numbered results/run_<n> directory."""
    candidates = [
        path
        for path in results_dir.iterdir()
        if path.is_dir() and path.name.removeprefix("run_").isdigit()
    ]
    if not candidates:
        raise FileNotFoundError(f"no run_<n> directories found under {results_dir}")
    return max(candidates, key=_run_number)


def _write_summary(results_dir: Path) -> None:
    """Rewrites results/summary.md from every run_<n>/eval.json found, in run
    order. Regenerated from scratch each call, not appended, so it always
    reflects exactly the eval.json files present on disk."""
    run_dirs = sorted(
        (
            path
            for path in results_dir.iterdir()
            if path.is_dir() and path.name.removeprefix("run_").isdigit()
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
        rows.append(
            f"| {run_dir.name} | {node['f1']:.3f} | {conn['f1']:.3f} | {elapsed_str} |"
        )
    lines = ["| run | node F1 | connection F1 | time |", "|---|---|---|---|", *rows]
    (results_dir / "summary.md").write_text("\n".join(lines) + "\n")


def evaluate_run(
    run_dir: Path,
    truth_path: Path = _TRUTH_SET_PATH,
    results_dir: Path = _RESULTS_DIR,
    elapsed_seconds: float | None = None,
) -> dict:
    """Evaluates `run_dir/output.json` against `truth_path`, writes
    `run_dir/eval.json` (including `elapsed_seconds` when provided), appends a
    formatted block to `run_dir/notes.md`, and rewrites
    `results_dir/summary.md` across every evaluated run so far."""
    graph = json.loads((run_dir / "output.json").read_text())["graph"]
    truth = json.loads(truth_path.read_text())
    scores = evaluate(graph, truth)
    if elapsed_seconds is not None:
        scores["elapsed_seconds"] = elapsed_seconds
    (run_dir / "eval.json").write_text(json.dumps(scores, indent=2))
    with (run_dir / "notes.md").open("a") as notes_file:
        notes_file.write(_format_block(run_dir.name, scores))
    _write_summary(results_dir)
    return scores


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses an optional run_dir positional arg, defaulting to the most
    recent results/run_<n> directory."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "run_dir",
        nargs="?",
        default=None,
        help="results/run_<n> directory to evaluate (default: the most recent run)",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    target_dir = Path(args.run_dir) if args.run_dir else _latest_run_dir(_RESULTS_DIR)
    result = evaluate_run(target_dir)
    print(
        f"{target_dir.name}: node F1={result['node_f1']['f1']:.3f}, "
        f"connection F1={result['connection_f1']['f1']:.3f}"
    )
