from typing import TypedDict


class AgentState(TypedDict):
    job_id: str
    requirements: list[dict]
    current_index: int
    violations_log: list[dict]
    messages: list
