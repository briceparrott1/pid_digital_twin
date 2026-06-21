# Unit tests for the evaluator's scoring functions (pure, no files) and
# file-level helpers (eval.json / notes.md / summary.md, via tmp_path).
from __future__ import annotations

import json

from scripts.evaluate import (
    _is_junction_id,
    _latest_run_dir,
    _normalize_edge,
    _normalize_id,
    _write_summary,
    evaluate,
    evaluate_run,
)

_TRUTH = {
    "nodes": [
        {"component_name": "F-715A", "level": "equipment"},
        {"component_name": "MV-715-01", "level": "valve"},
        {"component_name": "j1", "level": "junction"},
        {"component_name": "j2", "level": "junction"},
    ],
    "connections": [
        {"start": "F-715A", "end": "j1"},
        {"start": "j1", "end": "j2"},
        {"start": "j2", "end": "MV-715-01"},
    ],
}


def _graph(nodes, edges):
    return {"nodes": nodes, "edges": edges}


def test_node_f1_excludes_junctions_and_matches_exact_ids():
    graph = _graph(
        nodes=[
            {"id": "F-715A", "type": "equipment", "metadata": {}},
            {"id": "MV-715-01", "type": "valve", "metadata": {}},
            {"id": "11", "type": "junction", "metadata": {}},  # predicted junction id
        ],
        edges=[],
    )
    scores = evaluate(graph, _TRUTH)
    # Perfect match on the two non-junction nodes; junction ids never compared.
    assert scores["node_f1"] == {
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
        "tp": 2,
        "fp": 0,
        "fn": 0,
    }


def test_node_f1_penalizes_missing_and_extra_nodes():
    graph = _graph(
        nodes=[
            {"id": "F-715A", "type": "equipment", "metadata": {}},
            {"id": "BOGUS-1", "type": "equipment", "metadata": {}},
        ],
        edges=[],
    )
    scores = evaluate(graph, _TRUTH)["node_f1"]
    assert scores["tp"] == 1  # F-715A
    assert scores["fp"] == 1  # BOGUS-1
    assert scores["fn"] == 1  # MV-715-01 missing


def test_node_f1_matches_out_of_system_text_despite_underscore_vs_space():
    truth = {
        "nodes": [{"component_name": "TO_SURGE_DRUM_V-720", "level": "out_of_system"}],
        "connections": [],
    }
    graph = _graph(
        nodes=[{"id": "TO SURGE DRUM V-720", "type": "out_of_system", "metadata": {}}],
        edges=[],
    )
    scores = evaluate(graph, truth)["node_f1"]
    assert scores == {
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
        "tp": 1,
        "fp": 0,
        "fn": 0,
    }


def test_connection_f1_matches_junction_to_junction_regardless_of_specific_id():
    graph = _graph(
        nodes=[
            {"id": "F-715A", "type": "equipment", "metadata": {}},
            {"id": "MV-715-01", "type": "valve", "metadata": {}},
            {"id": "11", "type": "junction", "metadata": {}},
            {"id": "12", "type": "junction", "metadata": {}},
        ],
        edges=[
            {"a": "F-715A", "b": "11"},
            {"a": "11", "b": "12"},  # predicted ids differ from truth's j1/j2
            {"a": "12", "b": "MV-715-01"},
        ],
    )
    scores = evaluate(graph, _TRUTH)["connection_f1"]
    assert scores == {
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
        "tp": 3,
        "fp": 0,
        "fn": 0,
    }


def test_connection_f1_is_a_multiset_not_a_plain_set():
    # Truth has exactly one junction-junction connection (j1-j2); predicting
    # two separate junction-junction connections should count one as a false
    # positive, not be treated as an automatic match via category collapse.
    graph = _graph(
        nodes=[
            {"id": "11", "type": "junction", "metadata": {}},
            {"id": "12", "type": "junction", "metadata": {}},
            {"id": "13", "type": "junction", "metadata": {}},
        ],
        edges=[{"a": "11", "b": "12"}, {"a": "12", "b": "13"}],
    )
    truth = {
        "nodes": [
            {"component_name": "j1", "level": "junction"},
            {"component_name": "j2", "level": "junction"},
        ],
        "connections": [{"start": "j1", "end": "j2"}],
    }
    scores = evaluate(graph, truth)["connection_f1"]
    assert scores["tp"] == 1
    assert scores["fp"] == 1


def test_is_junction_id_falls_back_to_naming_convention_when_missing_from_lookup():
    # Real callers always pass already-_normalize_id'd (uppercased) ids.
    assert _is_junction_id("J60", {}) is True
    assert _is_junction_id("MV-715-01", {}) is False
    assert _is_junction_id("MV-715-01", {"MV-715-01": "valve"}) is False
    assert _is_junction_id("j1", {"j1": "junction"}) is True


def test_normalize_id_collapses_underscores_and_whitespace_and_uppercases():
    assert _normalize_id("TO_SURGE_DRUM_V-720") == "TO SURGE DRUM V-720"
    assert _normalize_id("to surge drum v-720") == "TO SURGE DRUM V-720"
    assert _normalize_id("MV-715-01") == "MV-715-01"


def test_normalize_edge_is_order_independent():
    id_to_category = {"j1": "junction", "F-715A": "equipment"}
    assert _normalize_edge("j1", "F-715A", id_to_category) == _normalize_edge(
        "F-715A", "j1", id_to_category
    )


def test_evaluate_run_writes_eval_json_appends_notes_and_writes_summary(tmp_path):
    results_dir = tmp_path / "results"
    run_dir = results_dir / "run_1"
    run_dir.mkdir(parents=True)
    (run_dir / "notes.md").write_text("initial note\n")
    (run_dir / "output.json").write_text(
        json.dumps(
            {
                "graph": _graph(
                    nodes=[{"id": "F-715A", "type": "equipment", "metadata": {}}],
                    edges=[],
                )
            }
        )
    )
    truth_path = tmp_path / "truth_set.json"
    truth_path.write_text(json.dumps(_TRUTH))

    scores = evaluate_run(run_dir, truth_path=truth_path, results_dir=results_dir)

    assert (run_dir / "eval.json").exists()
    assert json.loads((run_dir / "eval.json").read_text()) == scores
    notes = (run_dir / "notes.md").read_text()
    assert notes.startswith("initial note\n")
    assert "Evaluation (run_1)" in notes
    summary = (results_dir / "summary.md").read_text()
    assert "run_1" in summary
    assert "time" in summary  # header column present


def test_evaluate_run_writes_elapsed_to_eval_json_and_summary(tmp_path):
    results_dir = tmp_path / "results"
    run_dir = results_dir / "run_1"
    run_dir.mkdir(parents=True)
    (run_dir / "notes.md").write_text("note\n")
    (run_dir / "output.json").write_text(
        json.dumps({"graph": _graph(nodes=[], edges=[])})
    )
    truth_path = tmp_path / "truth_set.json"
    truth_path.write_text(json.dumps(_TRUTH))

    scores = evaluate_run(
        run_dir, truth_path=truth_path, results_dir=results_dir, elapsed_seconds=42.7
    )

    assert scores["elapsed_seconds"] == 42.7
    eval_data = json.loads((run_dir / "eval.json").read_text())
    assert eval_data["elapsed_seconds"] == 42.7
    notes = (run_dir / "notes.md").read_text()
    assert "43s" in notes  # formatted as integer seconds
    summary = (results_dir / "summary.md").read_text()
    assert "43s" in summary


def test_latest_run_dir_picks_highest_numbered(tmp_path):
    for name in ("run_1", "run_2", "run_10", "not_a_run"):
        (tmp_path / name).mkdir()
    assert _latest_run_dir(tmp_path).name == "run_10"


def test_write_summary_skips_runs_without_eval_json(tmp_path):
    (tmp_path / "run_1").mkdir()
    (tmp_path / "run_1" / "eval.json").write_text(
        json.dumps(
            {
                "node_f1": {
                    "precision": 1,
                    "recall": 1,
                    "f1": 1,
                    "tp": 1,
                    "fp": 0,
                    "fn": 0,
                },
                "connection_f1": {
                    "precision": 1,
                    "recall": 1,
                    "f1": 1,
                    "tp": 1,
                    "fp": 0,
                    "fn": 0,
                },
            }
        )
    )
    (tmp_path / "run_2").mkdir()  # no eval.json -- never evaluated
    _write_summary(tmp_path)
    summary = (tmp_path / "summary.md").read_text()
    assert "run_1" in summary
    assert "run_2" not in summary
