from pydantic import BaseModel

class CytoscapeElement(BaseModel):
    data: dict

class GraphResponse(BaseModel):
    job_id: str
    elements: list[CytoscapeElement]
    summary: dict

def to_cytoscape(nodes: list[dict], edges: list[dict]) -> list[CytoscapeElement]:
    elements = []

    for node in nodes:
        elements.append(CytoscapeElement(data=node))

    for edge in edges:
        elements.append(CytoscapeElement(data=edge))

    return elements