import type { GraphNode } from '../types'

interface NodeDetailProps {
  node: GraphNode | null
  onClose: () => void
}

function parseMetadataValue(value: unknown): Record<string, unknown> | null {
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      if (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>
      }
    } catch {
      // not JSON
    }
  }
  return null
}

export default function NodeDetail({ node, onClose }: NodeDetailProps) {
  if (!node) return null

  const metadataEntries = Object.entries(node).filter(([key]) => key.startsWith('metadata_'))

  return (
    <div className="w-full max-w-sm rounded bg-white p-4 shadow md:w-80">
      <div className="mb-2 flex items-start justify-between">
        <h2 className="text-lg font-semibold text-slate-800">{node.component_name}</h2>
        <button
          type="button"
          onClick={onClose}
          className="text-sm text-slate-400 hover:text-slate-600"
        >
          Close
        </button>
      </div>

      <div className="mb-3 flex flex-wrap gap-2">
        {node.level && (
          <span className="rounded bg-blue-100 px-2 py-1 text-xs font-medium text-blue-700">
            {node.level}
          </span>
        )}
        {node.confidence != null && (
          <span className="rounded bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700">
            confidence: {node.confidence}
          </span>
        )}
        {node.sop_violation && (
          <span className="rounded bg-red-100 px-2 py-1 text-xs font-medium text-red-700">
            VIOLATION
          </span>
        )}
      </div>

      {node.sop_violation && node.violation && (
        <p className="mb-3 rounded bg-red-50 p-2 text-sm text-red-700">{node.violation}</p>
      )}

      {metadataEntries.length > 0 && (
        <dl className="space-y-1 text-sm">
          {metadataEntries.map(([key, value]) => {
            const label = key.replace('metadata_', '')
            const nested = parseMetadataValue(value)
            if (nested) {
              return (
                <div key={key}>
                  <dt className="text-slate-500">{label}</dt>
                  <dd className="ml-3 space-y-0.5">
                    {Object.entries(nested).map(([subKey, subVal]) => (
                      <div key={subKey} className="flex justify-between gap-2">
                        <span className="text-slate-400">{subKey}</span>
                        <span className="text-right text-slate-800">{String(subVal)}</span>
                      </div>
                    ))}
                  </dd>
                </div>
              )
            }
            return (
              <div key={key} className="flex justify-between gap-2">
                <dt className="text-slate-500">{label}</dt>
                <dd className="text-right text-slate-800">{String(value)}</dd>
              </div>
            )
          })}
        </dl>
      )}
    </div>
  )
}
