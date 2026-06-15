import type { ReportResponse } from '../types'

interface ReportProps {
  report: ReportResponse | null
}

export default function Report({ report }: ReportProps) {
  if (!report || report.status !== 'complete') return null

  const handleSave = () => {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `report-${report.job_id}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section className="rounded bg-white p-4 shadow">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-800">Violation Log</h2>
        <button
          type="button"
          onClick={handleSave}
          className="rounded bg-slate-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
        >
          Save Report
        </button>
      </div>
      {report.violations.length === 0 ? (
        <div className="rounded bg-green-100 p-3 text-sm font-medium text-green-700">
          No violations found
        </div>
      ) : (
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-slate-500">
              <th className="py-2 pr-4 font-medium">Component</th>
              <th className="py-2 font-medium">Violation Description</th>
            </tr>
          </thead>
          <tbody>
            {report.violations.map((violation) => (
              <tr key={violation.component_id} className="border-b border-slate-100">
                <td className="py-2 pr-4 font-mono text-xs text-slate-700">
                  {violation.component_name}
                </td>
                <td className="py-2 text-slate-700">{violation.violation}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
