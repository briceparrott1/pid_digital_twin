export interface JobResponse {
  job_id: string
  status: string
  message: string
}

export interface GraphNode {
  id: string
  component_name: string
  level?: string
  sop_violation: boolean
  violation?: string
  confidence: string
  page?: number
  [key: string]: unknown
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  pipeline?: string
  line_type?: string
  page?: number
  [key: string]: unknown
}

export interface CytoscapeElement {
  data: GraphNode | GraphEdge
}

export interface GraphResponse {
  job_id: string
  elements: CytoscapeElement[]
  summary: Record<string, number>
}

export interface Violation {
  component_id: string
  component_name: string
  violation: string
}

export interface ReportResponse {
  job_id: string
  status: string
  generated_at: string
  summary: Record<string, unknown>
  violations: Violation[]
}
