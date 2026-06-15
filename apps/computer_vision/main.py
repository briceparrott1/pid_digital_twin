from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, HTTPException

from core.config import sop_path_for
from core.logging_config import configure_logging
from db.loader import write_job
from db.queries import get_graph, get_job_status, get_violations, neo4j_is_connected
from models.graph import GraphResponse, to_cytoscape
from models.job import HealthResponse, JobResponse
from models.report import ReportResponse, Violation
from pipeline import run_pipeline

configure_logging()
app = FastAPI()


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok", neo4j_connected=neo4j_is_connected(), sop_loaded=True
    )


@app.post("/start-job", response_model=JobResponse)
async def start_job(background_tasks: BackgroundTasks, sop_index: int = 0):
    try:
        sop_path_for(sop_index)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    job_id = write_job()
    background_tasks.add_task(run_pipeline, job_id, sop_index)
    return JobResponse(job_id=job_id, status="pending", message="job started")


@app.get("/graph/{job_id}", response_model=GraphResponse)
async def get_job_graph(job_id: str, page: int | None = None) -> GraphResponse:
    job = get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    graph_data = get_graph(job_id, page)
    elements = to_cytoscape(graph_data["nodes"], graph_data["edges"])

    return GraphResponse(
        job_id=job_id,
        elements=elements,
        summary={
            "total_nodes": len(graph_data["nodes"]),
            "total_edges": len(graph_data["edges"]),
        },
    )


@app.get("/report/{job_id}", response_model=ReportResponse)
async def get_job_report(job_id: str) -> ReportResponse:
    job = get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    violations = get_violations(job_id)
    return ReportResponse(
        job_id=job_id,
        status=job["status"],
        generated_at=datetime.now(timezone.utc),
        summary={"total_violations": len(violations)},
        violations=[Violation(**v) for v in violations],
    )
