import argparse
import asyncio
import json
import re
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from core.config import app_path, get_settings
from orchestrator import run_algo
from tools.resolve import flatten_metadata
from visual.view_graph import build_graph, draw_graph

NODE_LEVELS = ["equipment", "instrument", "valve"]
EXCLUDED_NODE_LEVELS = {"junction", "out_of_system"}
JUNCTION_NAME_RE = re.compile(r"^j\d+$")


def precision_recall_f1(tp: int, fp: int, fn: int) -> dict:
    if tp + fp == 0:
        precision = 1.0 if tp + fn == 0 else 0.0
    else:
        precision = tp / (tp + fp)

    if tp + fn == 0:
        recall = 1.0 if tp + fp == 0 else 0.0
    else:
        recall = tp / (tp + fn)

    f1 = (
        0.0
        if precision + recall == 0
        else 2 * precision * recall / (precision + recall)
    )
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def node_names_by_level(nodes: list[dict]) -> dict[str, set[str]]:
    by_level: dict[str, set[str]] = defaultdict(set)
    for node in nodes:
        level = node.get("level")
        if level in EXCLUDED_NODE_LEVELS:
            continue
        by_level[level].add(node["component_name"])
    return by_level


def node_detection_metrics(truth_nodes: list[dict], ext_nodes: list[dict]) -> dict:
    """Per-level (equipment/instrument/valve) and overall precision/recall/F1,
    matching nodes by component_name. junction and out_of_system nodes are
    excluded entirely."""
    truth_by_level = node_names_by_level(truth_nodes)
    ext_by_level = node_names_by_level(ext_nodes)

    results = {}
    total_tp = total_fp = total_fn = 0
    for level in NODE_LEVELS:
        truth_set = truth_by_level.get(level, set())
        ext_set = ext_by_level.get(level, set())
        tp = truth_set & ext_set
        fp = ext_set - truth_set
        fn = truth_set - ext_set

        metrics = precision_recall_f1(len(tp), len(fp), len(fn))
        metrics["hallucinated"] = sorted(fp)
        metrics["missed"] = sorted(fn)
        results[level] = metrics

        total_tp += len(tp)
        total_fp += len(fp)
        total_fn += len(fn)

    results["overall"] = precision_recall_f1(total_tp, total_fp, total_fn)
    return results


def values_match(truth_value, ext_value) -> bool:
    if isinstance(truth_value, (int, float)) and isinstance(ext_value, (int, float)):
        return abs(float(truth_value) - float(ext_value)) < 1e-6
    if isinstance(truth_value, str) and isinstance(ext_value, str):
        return truth_value.strip().lower() == ext_value.strip().lower()
    return truth_value == ext_value


def metadata_accuracy_metrics(truth_nodes: list[dict], ext_nodes: list[dict]) -> dict:
    """For equipment nodes detected in both truth and extraction, compare
    flattened metadata fields. Truth's nested "metadata" dict is flattened
    with the same scheme used to produce the extraction's "metadata_*" keys
    (see tools.resolve.flatten_metadata), so field names line up."""
    truth_equipment = {
        n["component_name"]: n for n in truth_nodes if n.get("level") == "equipment"
    }
    ext_equipment = {
        n["component_name"]: n for n in ext_nodes if n.get("level") == "equipment"
    }

    matched = sorted(set(truth_equipment) & set(ext_equipment))

    per_node = {}
    total_correct = total_fields = 0
    for name in matched:
        truth_flat = flatten_metadata(truth_equipment[name].get("metadata") or {})
        ext_flat = {
            k: v for k, v in ext_equipment[name].items() if k.startswith("metadata_")
        }

        wrong_fields = []
        correct = 0
        for field, truth_value in truth_flat.items():
            ext_value = ext_flat.get(field)
            if values_match(truth_value, ext_value):
                correct += 1
            else:
                wrong_fields.append(
                    {"field": field, "truth": truth_value, "extracted": ext_value}
                )

        total = len(truth_flat)
        per_node[name] = {
            "accuracy": correct / total if total else 1.0,
            "correct_fields": correct,
            "total_fields": total,
            "wrong_fields": wrong_fields,
        }
        total_correct += correct
        total_fields += total

    return {
        "matched_equipment": matched,
        "overall_accuracy": total_correct / total_fields if total_fields else 1.0,
        "total_correct_fields": total_correct,
        "total_fields": total_fields,
        "per_node": per_node,
    }


def junction_names(nodes: list[dict]) -> set[str]:
    return {n["component_name"] for n in nodes if n.get("level") == "junction"}


def _match_connections(
    truth_items: list[tuple[tuple, dict]], ext_items: list[tuple[tuple, dict]]
) -> dict:
    """Multiset match of (key, original) pairs. Returns precision/recall/F1
    plus human-readable missed/hallucinated connection lists."""
    truth_by_key: dict[tuple, list[dict]] = defaultdict(list)
    for key, original in truth_items:
        truth_by_key[key].append(original)
    ext_by_key: dict[tuple, list[dict]] = defaultdict(list)
    for key, original in ext_items:
        ext_by_key[key].append(original)

    tp = fp = fn = 0
    missed, hallucinated = [], []
    for key in set(truth_by_key) | set(ext_by_key):
        truth_list = truth_by_key.get(key, [])
        ext_list = ext_by_key.get(key, [])
        matched = min(len(truth_list), len(ext_list))
        tp += matched
        fn += len(truth_list) - matched
        fp += len(ext_list) - matched
        missed.extend(truth_list[matched:])
        hallucinated.extend(ext_list[matched:])

    metrics = precision_recall_f1(tp, fp, fn)
    metrics["missed"] = missed
    metrics["hallucinated"] = hallucinated
    return metrics


def collapse_junctions(connections: list[dict], is_junction) -> set[frozenset]:
    """Collapse paths through junction nodes into direct edges between the
    non-junction components on either side.

    Junction labels are arbitrary and assigned independently by the truth
    set and the model, so a chain like A--j1--j2--B and a direct edge A--B
    represent the same topology. Returns the set of frozenset({compA, compB})
    edges between non-junction components, walking through zero or more
    junction nodes.
    """
    adjacency: dict[str, set[str]] = defaultdict(set)
    for c in connections:
        start = c["start"] if "start" in c else c["start_id"]
        end = c["end"] if "end" in c else c["end_id"]
        adjacency[start].add(end)
        adjacency[end].add(start)

    edges: set[frozenset] = set()
    for source in adjacency:
        if is_junction(source):
            continue
        visited = {source}
        queue = deque(adjacency[source])
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            if is_junction(node):
                queue.extend(adjacency[node])
            else:
                edges.add(frozenset({source, node}))

    return edges


def _format_edge(edge: frozenset) -> str:
    a, b = sorted(edge)
    return f"{a} -- {b}"


def _check_collapse_junctions() -> None:
    conns = [
        {"start": "A", "end": "j1"},
        {"start": "j1", "end": "j2"},
        {"start": "j2", "end": "B"},
        {"start": "j1", "end": "C"},
    ]
    edges = collapse_junctions(conns, lambda n: bool(re.match(r"^j\d+$", n)))
    assert edges == {
        frozenset({"A", "B"}),
        frozenset({"A", "C"}),
        frozenset({"B", "C"}),
    }


_check_collapse_junctions()


def connection_metrics(truth: dict, resolved: dict) -> dict:
    """Topology match (junctions collapsed, so arbitrary junction labels
    don't matter — primary metric), plus the legacy exact/fuzzy matches
    (junction-label-sensitive) for comparison. Endpoint pairs are treated as
    undirected."""
    truth_junctions = junction_names(truth["nodes"])
    ext_junctions = junction_names(resolved["nodes"])

    def is_truth_junction(name: str) -> bool:
        return name in truth_junctions or bool(JUNCTION_NAME_RE.match(name))

    def is_ext_junction(name: str) -> bool:
        return name in ext_junctions or bool(JUNCTION_NAME_RE.match(name))

    truth_edges = collapse_junctions(truth["connections"], is_truth_junction)
    ext_edges = collapse_junctions(resolved["connections"], is_ext_junction)

    tp_edges = truth_edges & ext_edges
    fp_edges = ext_edges - truth_edges
    fn_edges = truth_edges - ext_edges
    topology = precision_recall_f1(len(tp_edges), len(fp_edges), len(fn_edges))
    topology["missed"] = sorted(_format_edge(e) for e in fn_edges)
    topology["hallucinated"] = sorted(_format_edge(e) for e in fp_edges)

    def item(start, end, line_type) -> dict:
        return {"start": start, "end": end, "line_type": line_type}

    # Exact match: normalize any junction endpoint to "JUNCTION".
    truth_exact, ext_exact = [], []
    for c in truth["connections"]:
        start, end = c["start"], c["end"]
        norm_start = "JUNCTION" if start in truth_junctions else start
        norm_end = "JUNCTION" if end in truth_junctions else end
        key = tuple(sorted((norm_start, norm_end)))
        truth_exact.append((key, item(start, end, c.get("line_type"))))

    for c in resolved["connections"]:
        start, end = c["start_id"], c["end_id"]
        norm_start = "JUNCTION" if start in ext_junctions else start
        norm_end = "JUNCTION" if end in ext_junctions else end
        key = tuple(sorted((norm_start, norm_end)))
        ext_exact.append((key, item(start, end, c.get("line_type"))))

    exact = _match_connections(truth_exact, ext_exact)

    # Fuzzy match: drop any connection touching a junction, then exact-match the rest.
    truth_fuzzy, ext_fuzzy = [], []
    for c in truth["connections"]:
        start, end = c["start"], c["end"]
        if start in truth_junctions or end in truth_junctions:
            continue
        key = tuple(sorted((start, end)))
        truth_fuzzy.append((key, item(start, end, c.get("line_type"))))

    for c in resolved["connections"]:
        start, end = c["start_id"], c["end_id"]
        if start in ext_junctions or end in ext_junctions:
            continue
        key = tuple(sorted((start, end)))
        ext_fuzzy.append((key, item(start, end, c.get("line_type"))))

    fuzzy = _match_connections(truth_fuzzy, ext_fuzzy)

    return {"topology": topology, "exact": exact, "fuzzy": fuzzy}


def summary_line(metrics: dict) -> str:
    nodes_f1 = metrics["node_detection"]["overall"]["f1"]
    meta_acc = metrics["metadata_accuracy"]["overall_accuracy"]
    topology_f1 = metrics["connections"]["topology"]["f1"]
    exact_f1 = metrics["connections"]["exact"]["f1"]
    fuzzy_f1 = metrics["connections"]["fuzzy"]["f1"]
    return (
        f"SUMMARY: nodes F1={nodes_f1:.2f} | metadata acc={meta_acc:.2f} | "
        f"connections topology F1={topology_f1:.2f} "
        f"(exact F1={exact_f1:.2f} fuzzy F1={fuzzy_f1:.2f})"
    )


def compute_metrics(truth: dict, resolved: dict) -> dict:
    metrics = {
        "node_detection": node_detection_metrics(truth["nodes"], resolved["nodes"]),
        "metadata_accuracy": metadata_accuracy_metrics(
            truth["nodes"], resolved["nodes"]
        ),
        "connections": connection_metrics(truth, resolved),
    }
    return {"summary": summary_line(metrics), **metrics}


def print_summary(metrics: dict) -> None:
    print(metrics["summary"])

    print("\n=== Node Detection ===")
    for level, m in metrics["node_detection"].items():
        print(
            f"  {level:10s} P={m['precision']:.2f} R={m['recall']:.2f} F1={m['f1']:.2f} "
            f"(tp={m['tp']} fp={m['fp']} fn={m['fn']})"
        )

    meta_acc = metrics["metadata_accuracy"]
    print("\n=== Metadata Accuracy (equipment) ===")
    print(
        f"  overall: {meta_acc['overall_accuracy']:.2f} "
        f"({meta_acc['total_correct_fields']}/{meta_acc['total_fields']} fields)"
    )

    topology = metrics["connections"]["topology"]
    print("\n=== Connections (topology, primary) ===")
    print(
        f"  P={topology['precision']:.2f} R={topology['recall']:.2f} "
        f"F1={topology['f1']:.2f} "
        f"(tp={topology['tp']} fp={topology['fp']} fn={topology['fn']})"
    )
    if topology["missed"]:
        print("  missed:")
        for edge in topology["missed"]:
            print(f"    {edge}")
    if topology["hallucinated"]:
        print("  hallucinated:")
        for edge in topology["hallucinated"]:
            print(f"    {edge}")

    print("\n=== Connections (exact/fuzzy, for comparison) ===")
    for kind in ("exact", "fuzzy"):
        m = metrics["connections"][kind]
        print(
            f"  {kind:6s} P={m['precision']:.2f} R={m['recall']:.2f} F1={m['f1']:.2f} "
            f"(tp={m['tp']} fp={m['fp']} fn={m['fn']})"
        )


def slugify(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip()) or "run"


def save_colorized_image(run_dir: Path, image_bytes: bytes) -> None:
    """Write the line-colorized diagram for this run alongside its results."""
    (run_dir / "colorized.png").write_bytes(image_bytes)


def save_segmented_images(run_dir: Path, segments: list[bytes]) -> None:
    """Write each pass-1 segment image for this run to segmented_images/."""
    seg_dir = run_dir / "segmented_images"
    seg_dir.mkdir(parents=True, exist_ok=True)
    for i, segment_bytes in enumerate(segments):
        (seg_dir / f"segment_{i}.png").write_bytes(segment_bytes)


def write_summary_md(results_root: Path) -> None:
    """Rebuild results/summary.md: one row per run for quick comparison."""
    header = (
        "| Run | Description | Model | Nodes F1 | Metadata Acc | "
        "Conn Topology F1 | Conn Exact F1 | Conn Fuzzy F1 | Timestamp |"
    )
    divider = "|---|---|---|---|---|---|---|---|---|"
    rows = []

    for run_dir in sorted(results_root.glob("run_*")):
        meta_path, metrics_path, error_path = (
            run_dir / "meta.json",
            run_dir / "metrics.json",
            run_dir / "error.json",
        )
        if meta_path.exists() and metrics_path.exists():
            meta = json.loads(meta_path.read_text())
            metrics = json.loads(metrics_path.read_text())
            nodes_f1 = metrics["node_detection"]["overall"]["f1"]
            meta_acc = metrics["metadata_accuracy"]["overall_accuracy"]
            topology_f1 = metrics["connections"].get("topology", {}).get("f1")
            exact_f1 = metrics["connections"]["exact"]["f1"]
            fuzzy_f1 = metrics["connections"]["fuzzy"]["f1"]
            topology_str = f"{topology_f1:.2f}" if topology_f1 is not None else "-"
            rows.append(
                f"| {run_dir.name} | {meta.get('description', '')} | "
                f"{meta.get('model', '')} | {nodes_f1:.2f} | {meta_acc:.2f} | "
                f"{topology_str} | {exact_f1:.2f} | {fuzzy_f1:.2f} | "
                f"{meta.get('timestamp', '')} |"
            )
        elif error_path.exists():
            error = json.loads(error_path.read_text())
            rows.append(
                f"| {run_dir.name} | {error.get('description', '')} | - | "
                f"FAILED: {error.get('error_type', 'Error')} | - | - | - | - | "
                f"{error.get('timestamp', '')} |"
            )

    (results_root / "summary.md").write_text(
        "\n".join(["# Eval Run Summary", "", header, divider, *rows]) + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate the P&ID extraction algorithm"
    )
    parser.add_argument(
        "--description",
        default="run",
        help="Short tag for this run, used in the results directory name",
    )
    parser.add_argument(
        "--truth",
        default=None,
        help="Path to the truth set JSON (defaults to settings.truth_set_path)",
    )
    args = parser.parse_args()

    settings = get_settings()
    truth_path = Path(args.truth) if args.truth else app_path(settings.truth_set_path)
    truth = json.loads(truth_path.read_text())

    results_root = app_path(settings.results_dir)
    results_root.mkdir(parents=True, exist_ok=True)
    n = len(list(results_root.glob("run_*"))) + 1
    run_dir = results_root / f"run_{n}_{slugify(args.description)}"
    run_dir.mkdir(parents=True)

    try:
        result = asyncio.run(run_algo(args.description))
    except Exception as e:
        (run_dir / "error.json").write_text(
            json.dumps(
                {
                    "description": args.description,
                    "run_number": n,
                    "error_type": type(e).__name__,
                    "error": str(e),
                    "stop_reason": getattr(e, "stop_reason", None),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
        )
        if raw_text := getattr(e, "raw_text", None):
            (run_dir / "raw_response.txt").write_text(raw_text)
        write_summary_md(results_root)
        print(f"\nRun failed ({type(e).__name__}): {e}")
        print(f"Wrote error details to {run_dir}")
        raise

    resolved = result["resolved"]
    metrics = compute_metrics(truth, resolved)
    print_summary(metrics)

    (run_dir / "raw_extraction.json").write_text(json.dumps(result["raw"], indent=2))
    (run_dir / "extraction.json").write_text(json.dumps(resolved, indent=2))
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    save_colorized_image(run_dir, result["colorized_image"])
    save_segmented_images(run_dir, result["segments"])
    draw_graph(
        build_graph(resolved), title=run_dir.name, output_path=run_dir / "graph.png", show=False
    )
    (run_dir / "meta.json").write_text(
        json.dumps({**result["meta"], "run_number": n}, indent=2)
    )
    write_summary_md(results_root)

    print(f"\nWrote results to {run_dir}")


if __name__ == "__main__":
    main()
