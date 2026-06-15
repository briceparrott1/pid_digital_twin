from pydantic import BaseModel

class JobResponse(BaseModel):
    job_id: str
    status: str
    message: str

class HealthResponse(BaseModel):
    status: str
    neo4j_connected: bool
    sop_loaded: bool