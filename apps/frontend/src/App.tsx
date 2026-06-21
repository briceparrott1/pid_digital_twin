import { useEffect, useMemo, useState } from 'react'
import StatusBar from './components/StatusBar'
import Graph from './components/Graph'
import NodeDetail from './components/NodeDetail'
import Report from './components/Report'
import { getGraph, getReport } from './api/client'
import type { GraphNode, GraphResponse, ReportResponse } from './types'

const POLL_INTERVAL_MS = 3000

function getPages(graph: GraphResponse | null): number[] {
  if (!graph) return []
  const pages = new Set<number>()
  for (const el of graph.elements) {
    if (typeof el.data.page === 'number') pages.add(el.data.page)
  }
  return [...pages].sort((a, b) => a - b)
}

export default function App() {
  const [jobId, setJobId] = useState<string | null>(null)
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [graph, setGraph] = useState<GraphResponse | null>(null)
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [selectedPage, setSelectedPage] = useState<number | null>(null)
  const [sopIndex, setSopIndex] = useState<number | null>(null)

  useEffect(() => {
    if (!jobId) return
    let cancelled = false

    const tick = async () => {
      const result = await getReport(jobId)
      if (cancelled) return
      setReport(result)

      if (result.status === 'complete' || result.status === 'failed') {
        clearInterval(interval)
        if (result.status === 'complete') {
          const graphResult = await getGraph(jobId)
          if (!cancelled) setGraph(graphResult)
        }
      }
    }

    tick()
    const interval = setInterval(tick, POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [jobId])

  useEffect(() => {
    setSelectedPage(getPages(graph)[0] ?? null)
  }, [graph])

  const pages = useMemo(() => getPages(graph), [graph])

  const pageElements = useMemo(() => {
    if (!graph) return []
    const elements =
      pages.length === 0
        ? graph.elements
        : graph.elements.filter(
            (el) => el.data.page === selectedPage || el.data.page === undefined,
          )

    // Cytoscape throws if an edge references a node that isn't in `elements`
    // (e.g. a connection whose endpoint resolved to a node on another page).
    const nodeIds = new Set(
      elements.filter((el) => el.data.source === undefined).map((el) => el.data.id),
    )
    return elements.filter(
      (el) =>
        el.data.source === undefined ||
        (nodeIds.has(String(el.data.source)) && nodeIds.has(String(el.data.target))),
    )
  }, [graph, pages, selectedPage])

  const equipmentNames = useMemo(
    () =>
      pageElements
        .filter((el) => el.data.level === 'equipment')
        .map((el) => String(el.data.component_name)),
    [pageElements],
  )

  const pageGraph = useMemo<GraphResponse | null>(
    () => (graph ? { ...graph, elements: pageElements } : null),
    [graph, pageElements],
  )

  const handleJobStarted = (newJobId: string, newSopIndex: number) => {
    setReport(null)
    setGraph(null)
    setSelectedNode(null)
    setSopIndex(newSopIndex)
    setJobId(newJobId)
  }

  return (
    <div className="min-h-screen bg-slate-100">
      <StatusBar
        status={report?.status ?? null}
        sopIndex={sopIndex}
        onJobStarted={handleJobStarted}
      />
      <main className="flex flex-col gap-4 p-6">
        {pages.length > 0 && (
          <div className="flex flex-col gap-2">
            {pages.length > 1 && (
              <div className="flex gap-2">
                {pages.map((page) => (
                  <button
                    key={page}
                    type="button"
                    onClick={() => setSelectedPage(page)}
                    className={`rounded px-3 py-1 text-sm font-medium ${
                      page === selectedPage
                        ? 'bg-blue-600 text-white'
                        : 'bg-white text-slate-600 hover:bg-slate-200'
                    }`}
                  >
                    Page {page}
                  </button>
                ))}
              </div>
            )}
            <div className="text-sm text-slate-600">
              <span className="font-medium">Page {selectedPage} equipment:</span>{' '}
              {equipmentNames.length > 0 ? equipmentNames.join(', ') : 'none'}
            </div>
          </div>
        )}
        <div className="flex flex-col gap-4 md:flex-row">
          <Graph graph={pageGraph} onNodeClick={setSelectedNode} />
          <NodeDetail node={selectedNode} onClose={() => setSelectedNode(null)} />
        </div>
        <Report report={report} />
      </main>
    </div>
  )
}
