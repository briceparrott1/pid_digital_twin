import type { JobResponse, GraphResponse, ReportResponse } from '../types'

const BASE = '/api'

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init)
  if (!response.ok) {
    throw new Error(`Request to ${path} failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function startJob(sopIndex: number): Promise<JobResponse> {
  return fetchJson<JobResponse>(`/start-job?sop_index=${sopIndex}`, { method: 'POST' })
}

export function getReport(jobId: string): Promise<ReportResponse> {
  return fetchJson<ReportResponse>(`/report/${jobId}`)
}

export function getGraph(jobId: string): Promise<GraphResponse> {
  return fetchJson<GraphResponse>(`/graph/${jobId}`)
}
