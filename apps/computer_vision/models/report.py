from datetime import datetime

from pydantic import BaseModel


class Violation(BaseModel):
    component_id: str
    component_name: str
    violation: str


class ReportResponse(BaseModel):
    job_id: str
    status: str
    generated_at: datetime
    summary: dict
    violations: list[Violation]
