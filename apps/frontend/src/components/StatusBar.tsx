import { useState } from 'react'
import { startJob } from '../api/client'

interface StatusBarProps {
  status: string | null
  sopIndex: number | null
  onJobStarted: (jobId: string, sopIndex: number) => void
}

const statusColor = (status: string | null) => {
  if (status === null) return 'bg-gray-400'
  if (status === 'complete') return 'bg-green-500'
  if (status === 'failed') return 'bg-red-500'
  return 'bg-yellow-400'
}

export default function StatusBar({ status, sopIndex, onJobStarted }: StatusBarProps) {
  const [starting, setStarting] = useState(false)
  const [selecting, setSelecting] = useState(false)

  const jobInProgress = status !== null && status !== 'complete' && status !== 'failed'
  const disabled = starting || jobInProgress

  const handleSelect = async (sopIndex: number) => {
    setSelecting(false)
    setStarting(true)
    try {
      const job = await startJob(sopIndex)
      onJobStarted(job.job_id, sopIndex)
    } catch (err) {
      console.error('Failed to start job', err)
    } finally {
      setStarting(false)
    }
  }

  return (
    <header className="flex items-center justify-between bg-white px-6 py-4 shadow">
      <h1 className="text-xl font-semibold text-slate-800">P&ID Digital Twin</h1>
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <span className={`inline-block h-3 w-3 rounded-full ${statusColor(status)}`} />
          <span className="text-sm text-slate-600">{status ?? 'idle'}</span>
        </div>
        {sopIndex !== null && (
          <span className="rounded bg-slate-100 px-2 py-1 text-sm font-medium text-slate-600">
            SOP test case: {sopIndex}
          </span>
        )}
        {selecting ? (
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-600">SOP test case:</span>
            {[0, 1, 2, 3].map((sopIndex) => (
              <button
                key={sopIndex}
                type="button"
                onClick={() => handleSelect(sopIndex)}
                disabled={disabled}
                className="rounded bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {sopIndex}
              </button>
            ))}
            <button
              type="button"
              onClick={() => setSelecting(false)}
              className="px-2 text-sm text-slate-500 hover:text-slate-700"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setSelecting(true)}
            disabled={disabled}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            Start Job
          </button>
        )}
      </div>
    </header>
  )
}
