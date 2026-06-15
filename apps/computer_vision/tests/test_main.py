from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_graph_not_found_returns_404():
    with patch("main.get_job_status", return_value=None):
        response = client.get("/graph/missing-job")
    assert response.status_code == 404


def test_graph_returns_cytoscape_elements():
    fake_graph = {
        "nodes": [{"id": "n1", "component_name": "Pump-1", "level": "equipment"}],
        "edges": [{"id": "e1", "source": "n1", "target": "n1", "pipeline": "P-1"}],
    }
    with (
        patch("main.get_job_status", return_value={"status": "complete"}),
        patch("main.get_graph", return_value=fake_graph),
    ):
        response = client.get("/graph/job-1")

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "job-1"
    assert body["summary"] == {"total_nodes": 1, "total_edges": 1}
    assert len(body["elements"]) == 2


def test_graph_passes_page_filter_through():
    fake_graph = {"nodes": [], "edges": []}
    with (
        patch("main.get_job_status", return_value={"status": "complete"}),
        patch("main.get_graph", return_value=fake_graph) as mock_get_graph,
    ):
        response = client.get("/graph/job-1?page=2")

    assert response.status_code == 200
    mock_get_graph.assert_called_once_with("job-1", 2)


def test_report_includes_violations():
    fake_violations = [{"component_id": "n1", "violation": "Pressure exceeds max"}]
    with (
        patch("main.get_job_status", return_value={"status": "complete"}),
        patch("main.get_violations", return_value=fake_violations),
    ):
        response = client.get("/report/job-1")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["violations"] == fake_violations


def test_report_not_found_returns_404():
    with patch("main.get_job_status", return_value=None):
        response = client.get("/report/missing-job")
    assert response.status_code == 404
