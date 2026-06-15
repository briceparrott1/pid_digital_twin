import { useEffect, useRef } from 'react'
import CytoscapeComponent from 'react-cytoscapejs'
import type {
  Core,
  ElementDefinition,
  EventObject,
  LayoutOptions,
  StylesheetCSS,
  StylesheetStyle,
} from 'cytoscape'
import type { GraphResponse, GraphNode, CytoscapeElement as CyElement } from '../types'

interface GraphProps {
  graph: GraphResponse | null
  onNodeClick: (node: GraphNode) => void
}

type Stylesheet = StylesheetStyle | StylesheetCSS

const layout: LayoutOptions = { name: 'cose' }

const stylesheet: Stylesheet[] = [
  {
    selector: 'node',
    style: {
      label: 'data(component_name)',
      'font-size': 10,
      'text-valign': 'center',
      'text-halign': 'center',
      width: 80,
      height: 40,
      shape: 'rectangle',
      'background-color': '#94a3b8',
      color: '#fff',
    },
  },
  {
    selector: 'node[level = "equipment"]',
    style: { width: 140, height: 60, 'background-color': '#3b82f6' },
  },
  {
    selector: 'node[level = "instrument"]',
    style: { shape: 'ellipse', width: 40, height: 40, 'background-color': '#8b5cf6' },
  },
  {
    selector: 'node[level = "valve"]',
    style: { shape: 'diamond', width: 30, height: 30, 'background-color': '#64748b' },
  },
  {
    selector: 'node[level = "connector"]',
    style: { shape: 'ellipse', width: 15, height: 15, 'background-color': '#cbd5e1', label: '' },
  },
  {
    selector: 'node[level = "offpage"]',
    style: {
      'background-color': '#e2e8f0',
      color: '#64748b',
      'border-style': 'dashed',
      'border-width': 2,
      'border-color': '#94a3b8',
    },
  },
  {
    selector: 'node[?sop_violation]',
    style: { 'border-color': '#ef4444', 'border-width': 3, 'background-color': '#fca5a5' },
  },
  {
    selector: 'node[confidence = "low"]',
    style: { 'border-style': 'dashed', 'border-color': '#f97316', 'border-width': 2 },
  },
  {
    selector: 'edge',
    style: {
      width: 2,
      'line-color': '#94a3b8',
      'target-arrow-color': '#94a3b8',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
    },
  },
  {
    selector: 'edge[line_type = "major_process"]',
    style: { width: 3, 'line-color': '#475569' },
  },
  {
    selector: 'edge[line_type = "signal"]',
    style: { 'line-style': 'dashed', 'line-color': '#94a3b8' },
  },
]

function toElement(el: CyElement): ElementDefinition {
  const data = { ...el.data }
  if (data.level === undefined) data.level = 'offpage'
  return { data }
}

export default function Graph({ graph, onNodeClick }: GraphProps) {
  const elements = graph ? graph.elements.map(toElement) : []
  const cyRef = useRef<Core | null>(null)

  // react-cytoscapejs doesn't re-run the layout when elements arrive after mount, so trigger it manually.
  useEffect(() => {
    if (graph) cyRef.current?.layout(layout).run()
  }, [graph])

  return (
    <div className="min-w-0 flex-1 rounded bg-slate-900" style={{ height: '600px' }}>
      <CytoscapeComponent
        elements={elements}
        stylesheet={stylesheet}
        layout={layout}
        style={{ width: '100%', height: '100%' }}
        cy={(cy: Core) => {
          cyRef.current = cy
          cy.removeAllListeners()
          cy.on('tap', 'node', (evt: EventObject) => onNodeClick(evt.target.data() as GraphNode))
        }}
      />
    </div>
  )
}
