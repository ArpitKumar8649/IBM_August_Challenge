import { useEffect, useState } from 'react'
import { fetchKnowledge } from '../lib/api'
import type { KnowledgeChunk } from '../types'

const MODULES = [
  {
    id: 'ca',
    title: 'What is a conjunction?',
    query: 'conjunction assessment thresholds screening geometry',
    icon: '🛰️',
  },
  {
    id: 'pc',
    title: 'Understanding collision probability',
    query: 'collision probability Pc covariance realism dilution',
    icon: '🎲',
  },
  {
    id: 'man',
    title: 'How to avoid a collision',
    query: 'avoidance maneuver planning propellant rocket equation',
    icon: '🚀',
  },
  {
    id: 'weather',
    title: 'Why does space weather matter?',
    query: 'atmospheric drag space weather storm stale TLE',
    icon: '🌦️',
  },
  {
    id: 'sus',
    title: 'Kessler syndrome & sustainability',
    query: 'Kessler syndrome debris sustainability democratizing',
    icon: '🌍',
  },
] as const

export default function LearnPanel() {
  const [activeModule, setActiveModule] = useState<string>(MODULES[0].id)
  const [chunks, setChunks] = useState<KnowledgeChunk[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const mod = MODULES.find((m) => m.id === activeModule)!

  useEffect(() => {
    let mounted = true
    setLoading(true)
    setExpanded(new Set())
    fetchKnowledge(mod.query, 3, mod.id).then((res) => {
      if (mounted) {
        setChunks(res ?? [])
        setLoading(false)
      }
    })
    return () => {
      mounted = false
    }
  }, [mod.query, mod.id])

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  return (
    <div className="panel learn-panel">
      {/* Sidebar navigation */}
      <aside className="learn-side">
        <h2 className="eyebrow" style={{ marginBottom: 16 }}>
          Education modules
        </h2>

        {MODULES.map((m) => (
          <button
            key={m.id}
            onClick={() => setActiveModule(m.id)}
            className={`learn-nav ${m.id === activeModule ? 'active' : ''}`}
          >
            <span style={{ fontSize: '1.2rem' }}>{m.icon}</span>
            {m.title}
          </button>
        ))}

        <div className="learn-edu">
          <h3 className="eyebrow">Educator resources</h3>
          <p>
            Teaching orbital mechanics? The Educator Guide has classroom activities and a glossary —
            no space background required.
          </p>
          <a
            href="https://github.com/ranbeerrathore56-art/IBM_August_Challenge/blob/main/docs/EDUCATOR_GUIDE.md"
            target="_blank"
            rel="noreferrer"
            className="btn"
          >
            View Educator Guide
          </a>
        </div>
      </aside>

      {/* Main content area */}
      <main className="learn-main">
        <div className="learn-head">
          <span style={{ fontSize: '2rem' }}>{mod.icon}</span>
          <h2>{mod.title}</h2>
        </div>

        <p className="learn-note">
          Plain language first — the full technical detail is one click away. Every explanation comes
          from the same knowledge base the AI analyst cites when it answers your questions, so what
          you read here is exactly what the analyst knows.
        </p>

        {loading ? (
          <div className="mono" style={{ color: 'var(--fg-dim)' }}>
            Loading knowledge base…
          </div>
        ) : (
          <div className="learn-cards">
            {chunks.map((chunk) => (
              <article key={chunk.chunk_id} className="learn-card">
                <div className="learn-card-head">
                  <h3 className="learn-card-title">{chunk.title}</h3>
                  <span className="chip" style={{ opacity: 0.7 }}>
                    {chunk.topic}
                  </span>
                </div>
                <p className="learn-plain">{chunk.plain || chunk.body}</p>
                {chunk.plain && (
                  <>
                    <button className="learn-deeper" onClick={() => toggle(chunk.chunk_id)}>
                      {expanded.has(chunk.chunk_id) ? 'Hide technical detail ▴' : 'Go deeper (technical) ▾'}
                    </button>
                    {expanded.has(chunk.chunk_id) && <div className="learn-body">{chunk.body}</div>}
                  </>
                )}
              </article>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
