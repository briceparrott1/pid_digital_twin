from db.neo4j_client import get_driver

driver = get_driver()


def get_job_status(job_id: str) -> dict | None:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (j:Job {id: $job_id})
            return j
        """,
            job_id=job_id,
        )
        record = result.single()
        return dict(record["j"]) if record else None


def neo4j_is_connected() -> bool:
    try:
        with driver.session() as session:
            session.run("RETURN 1")
        return True
    except Exception:
        return False


def query_components_by_name(job_id: str, pattern: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (n {job_id: $job_id})
            WHERE n.component_name CONTAINS $pattern
            RETURN elementId(n) AS id, n AS node
        """,
            job_id=job_id,
            pattern=pattern,
        )
        return [{"id": r["id"], **dict(r["node"])} for r in result]


def query_incompatible_connections(job_id: str, type_a: str, type_b: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (a)-[:CONNECTED_TO {job_id: $job_id}]->(b)
            WHERE a.component_name CONTAINS $type_a AND b.component_name CONTAINS $type_b
            RETURN elementId(a) AS a_id, a.component_name AS a_name,
                   elementId(b) AS b_id, b.component_name AS b_name
        """,
            job_id=job_id,
            type_a=type_a,
            type_b=type_b,
        )
        return [dict(r) for r in result]


def get_graph(job_id: str, page: int | None = None) -> dict:
    with driver.session() as session:
        nodes_result = session.run(
            """
            MATCH (n {job_id: $job_id})
            WHERE NOT n:Job AND ($page IS NULL OR n.page = $page)
            RETURN elementId(n) AS id, n AS node
        """,
            job_id=job_id,
            page=page,
        )

        nodes = [{"id": r["id"], **dict(r["node"])} for r in nodes_result]

        edges_result = session.run(
            """
            MATCH (a)-[r:CONNECTED_TO {job_id: $job_id}]->(b)
            WHERE $page IS NULL OR r.page = $page
            RETURN elementId(r) AS id,
                   elementId(a) AS source,
                   elementId(b) AS target,
                   r AS edge
        """,
            job_id=job_id,
            page=page,
        )

        edges = [
            {
                "id": r["id"],
                "source": r["source"],
                "target": r["target"],
                **dict(r["edge"]),
            }
            for r in edges_result
        ]

        return {"nodes": nodes, "edges": edges}


def get_violations(job_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (n {job_id: $job_id})
            WHERE n.sop_violation = true
            RETURN elementId(n) AS component_id, n.component_name AS component_name,
                   n.violation AS violation
            """,
            job_id=job_id,
        )
        return [dict(r) for r in result]
