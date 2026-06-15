from langchain_core.tools import tool

from db import queries, loader


def make_tools(job_id: str) -> list:
    @tool
    def query_components_by_name(pattern: str) -> list[dict]:
        """Find components whose component_name contains the given pattern.
        Returns a list of nodes. Each node has:
        - 'id': Neo4j elementId — use this as node_id in write_violation
        - level, confidence, and all metadata_* fields for spec comparison
        """
        return queries.query_components_by_name(job_id, pattern)

    @tool
    def query_incompatible_connections(type_a: str, type_b: str) -> list[dict]:
        """Find directed CONNECTED_TO relationships in this job's P&ID graph where
        the source component's name contains type_a and the target's name contains
        type_b. Returns a list of dicts with a_id/a_name/b_id/b_name (a_id/b_id are
        Neo4j elementIds, pass to write_violation as node_id)."""
        return queries.query_incompatible_connections(job_id, type_a, type_b)

    @tool
    def write_violation(node_id: str, violation_text: str) -> str:
        """Record an SOP violation on a component. node_id MUST be the Neo4j
        elementId string returned as 'id'/'a_id'/'b_id' by the query tools --
        not a component_name/tag."""
        loader.write_violation(job_id, node_id, violation_text)
        return "ok"

    return [query_components_by_name, query_incompatible_connections, write_violation]
