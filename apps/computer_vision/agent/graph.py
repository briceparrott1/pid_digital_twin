import json

from langgraph.graph import StateGraph, END
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from core.config import get_settings
from agent.state import AgentState
from agent.tools import make_tools

llm = ChatAnthropic(model="claude-opus-4-5", api_key=get_settings().anthropic_api_key)

SPEC_CHECK_PROMPT = """You are checking one component against an SOP specification.

SOP specs (limits/requirements that must be respected): {specs}

Component properties from the P&ID graph: {component}

If the component's metadata violates any of the SOP specs (e.g. a design/operating
value exceeds a max_* spec), call write_violation with this component's "id" and a
short description of the violation. Otherwise, do not call any tool."""

#node
async def process_requirement(state: AgentState) -> dict:
    job_id = state["job_id"]
    requirement = state["requirements"][state["current_index"]]
    query_components, query_connections, write_violation = make_tools(job_id)
    new_violations = []

    if requirement["rule_type"] == "incompatible_components":
        specs = requirement["specs"]
        pairs = query_connections.invoke(
            {"type_a": specs["type_a"], "type_b": specs["type_b"]}
        )
        for pair in pairs:
            for node_id in (pair["a_id"], pair["b_id"]):
                write_violation.invoke(
                    {"node_id": node_id, "violation_text": requirement["raw_text"]}
                )
                new_violations.append({"requirement": requirement, "node_id": node_id})

    elif requirement["rule_type"] == "component_specifications":
        pattern = requirement["component_description"].split()[0]
        components = query_components.invoke({"pattern": pattern})
        bound_llm = llm.bind_tools([write_violation])
        for component in components:
            prompt = SPEC_CHECK_PROMPT.format(
                specs=json.dumps(requirement["specs"]), component=json.dumps(component)
            )
            response = await bound_llm.ainvoke([HumanMessage(prompt)])
            for call in response.tool_calls:
                write_violation.invoke(call["args"])
                new_violations.append({"requirement": requirement, **call["args"]})

    return {
        "violations_log": state["violations_log"] + new_violations,
        "current_index": state["current_index"] + 1,
    }


def should_continue(state: AgentState) -> str:
    return "process_requirement" if state["current_index"] < len(state["requirements"]) else END


graph = StateGraph(AgentState)
graph.add_node("process_requirement", process_requirement)
graph.set_entry_point("process_requirement")
graph.add_conditional_edges("process_requirement", should_continue)
compiled_graph = graph.compile()


async def run_agent(job_id: str, requirements: list[dict]) -> list[dict]:
    if not requirements:
        return []
    result = await compiled_graph.ainvoke({
        "job_id": job_id,
        "requirements": requirements,
        "current_index": 0,
        "violations_log": [],
        "messages": [],
    })
    return result["violations_log"]
