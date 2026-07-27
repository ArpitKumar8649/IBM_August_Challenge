import { useEffect, useState } from 'react'
import type { SystemHealth } from '../types'
import { fetchSystemHealth } from '../lib/api'

/** Operational health — database + every external data source. */
export default function SystemHealthPanel() {
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = () => {
    setLoading(true)
    fetchSystemHealth().then((h) => {
      setHealth(h)
      setLoading(false)
    })
  }

  useEffect(() => {
    refresh()
  }, [])

  if (loading) return <div className="panel-loading">Checking system health…</div>
  if (!health) return <div className="panel-empty">Health endpoint unavailable (backend offline).</div>

  const statusTone = (s: string) => (s === 'ok' ? 'good' : s === 'stale' ? 'warn' : '')

  return (
    <div className="health-wrap">
      <section className="panel health-summary">
        <div className="health-head">
          <span className="eyebrow">platform health</span>
          <button className="btn btn-ghost btn-sm" onClick={refresh}>Refresh</button>
        </div>
        <div className="health-overall">
          <span className={`health-badge ${health.status === 'ok' ? 'good' : 'warn'}`}>
            {health.status === 'ok' ? '● OPERATIONAL' : '◐ DEGRADED'}
          </span>
          <span className="health-time mono">checked {health.checked_at.slice(11, 19)} UTC</span>
        </div>

        <div className="health-db">
          <span className="signal-l">Screening database</span>
          <span className="signal-v mono">
            {health.database.status === 'ok'
              ? `${health.database.candidates?.toLocaleString()} candidates · last run ${health.database.last_run?.slice(0, 10)}`
              : health.database.status}
          </span>
        </div>

        <div className="health-counts mono">
          <span className="good-text">{health.sources_ok} ok</span>
          <span className="warn-text">{health.sources_stale} stale</span>
          <span>{health.sources_unknown} unknown</span>
          <span>/ {health.sources_total} sources</span>
        </div>
      </section>

      <section className="panel">
        <span className="eyebrow">data sources</span>
        <div className="source-grid">
          {health.sources.map((s) => (
            <div key={s.source} className="source-row">
              <span className={`source-dot ${statusTone(s.status)}`} />
              <span className="source-name">{s.name}</span>
              <span className="source-detail mono">{s.detail}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
