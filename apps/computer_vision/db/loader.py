import json
import logging
from datetime import datetime
from uuid import uuid4

from db.neo4j_client import get_driver

logger = logging.getLogger(__name__)

driver = get_driver()


def write_job(status: str = "pending") -> str:
    job_id = str(uuid4())
    with driver.session() as session:
        session.run(
            """
            CREATE (j:Job {
                id: $job_id,
                status: $status,
                created_at: $created_at
            })
        """,
            job_id=job_id,
            status=status,
            created_at=datetime.utcnow().isoformat(),
        )
    return job_id


def update_job_status(job_id: str, status: str):
    with driver.session() as session:
        session.run(
            """
            MATCH (j:Job {id: $job_id})
            SET j.status = $status
            """,
            job_id=job_id,
            status=status,
        )


def write_extraction(job_id: str, extraction: dict):
    """Write nodes and edges from a VLM extraction to Neo4j.

    Node schema: {id, type, metadata}.
    Edge schema: {a, b}.

    id -> component_name, type -> level so the graph queries and frontend
    continue to work without changes.
    """
    with driver.session() as session:
        id_map: dict[str, str] = {}

        for node in extraction.get("nodes", []):
            node_id = node.get("id", "")
            properties = {
                "component_name": node_id,
                "level": node.get("type", ""),
                **_flatten_metadata(node.get("metadata") or {}),
            }
            result = session.run(
                """
                CREATE (n)
                SET n += $properties
                SET n.job_id = $job_id,
                    n.sop_violation = false,
                    n.violation = null
                WITH n
                MATCH (j:Job {id: $job_id})
                CREATE (j)-[:CONTAINS]->(n)
                RETURN elementId(n) AS element_id
            """,
                job_id=job_id,
                properties=properties,
            )
            id_map[node_id] = result.single()["element_id"]

        for edge in extraction.get("edges", []):
            from_id = id_map.get(edge.get("a", ""))
            to_id = id_map.get(edge.get("b", ""))
            if from_id is None or to_id is None:
                continue

            session.run(
                """
                MATCH (a) WHERE elementId(a) = $from_id
                MATCH (b) WHERE elementId(b) = $to_id
                CREATE (a)-[r:CONNECTED_TO]->(b)
                SET r.job_id = $job_id
            """,
                from_id=from_id,
                to_id=to_id,
                job_id=job_id,
            )


def write_violation(job_id: str, component_id: str, violation_text: str):
    with driver.session() as session:
        session.run(
            """
            MATCH (n)
            WHERE elementId(n) = $component_id AND n.job_id = $job_id
            SET n.sop_violation = true,
                n.violation = CASE
                    WHEN n.violation IS NULL THEN $violation_text
                    ELSE n.violation + ' | ' + $violation_text
                END
        """,
            component_id=component_id,
            job_id=job_id,
            violation_text=violation_text,
        )


def _flatten_metadata(metadata: dict) -> dict:
    return {f"metadata_{k}": _sanitize_value(v) for k, v in metadata.items()}


def _sanitize_value(value):
    if isinstance(value, dict):
        return json.dumps(value)
    if isinstance(value, list) and not all(
        isinstance(v, (str, int, float, bool)) or v is None for v in value
    ):
        return json.dumps(value)
    return value
