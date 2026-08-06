import { useEffect, useState } from 'react'
import { fetchKnowledge } from '../lib/api'
import type { KnowledgeChunk } from '../types'

const MODULES = [
  {
    id: 'ca',
    title: 'What is a conjunction?',
    query: 'conjunction assessment thresholds',
    icon: '🛰️'
  },
  {
    id: 'pc',
    title: 'Understanding Collision Probability',
    query: 'collision probability Pc Alfriend Foster realism',
    icon: '🎲'
  },
  {
    id: 'man',
    title: 'How to avoid a collision',
    query: 'avoidance maneuver fuel optimal planning',
    icon: '🚀'
  },
  {
    id: 'weather',
    title: 'Why does space weather matter?',
    query: 'atmospheric drag space weather TLE stale',
    icon: '🌦️'
  },
  {
    id: 'sus',
    title: 'Kessler Syndrome & Sustainability',
    query: 'Kessler syndrome sustainability democratizing',
    icon: '🌍'
  }
]

export default function LearnPanel() {
  const [activeModule, setActiveModule] = useState(MODULES[0].id)
  const [chunks, setChunks] = useState<KnowledgeChunk[]>([])
  const [loading, setLoading] = useState(true)

  const mod = MODULES.find(m => m.id === activeModule)!

  useEffect(() => {
    let mounted = true
    setLoading(true)
    fetchKnowledge(mod.query, 3).then((res) => {
      if (mounted) {
        setChunks(res || [])
        setLoading(false)
      }
    })
    return () => { mounted = false }
  }, [mod.query])

  return (
    <div className="panel learn-panel" style={{ height: 'calc(100vh - 120px)', display: 'flex', gap: '24px', flexDirection: 'row' }}>
      
      {/* Sidebar navigation */}
      <aside style={{ width: '280px', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <h2 className="eyebrow" style={{ marginBottom: '16px' }}>Education Modules</h2>
        
        {MODULES.map(m => (
          <button
            key={m.id}
            onClick={() => setActiveModule(m.id)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              padding: '12px 16px',
              background: activeModule === m.id ? 'var(--bg-surface-2)' : 'transparent',
              border: '1px solid',
              borderColor: activeModule === m.id ? 'var(--border)' : 'transparent',
              borderRadius: '8px',
              color: activeModule === m.id ? 'var(--fg)' : 'var(--fg-dim)',
              textAlign: 'left',
              cursor: 'pointer',
              transition: 'all 0.2s',
              fontWeight: activeModule === m.id ? 500 : 400
            }}
          >
            <span style={{ fontSize: '1.2rem' }}>{m.icon}</span>
            {m.title}
          </button>
        ))}
        
        <div style={{ marginTop: 'auto', padding: '16px', background: 'var(--bg-surface-2)', borderRadius: '8px', border: '1px dashed var(--border)' }}>
          <h3 className="eyebrow">Educator Resources</h3>
          <p style={{ fontSize: '0.85rem', color: 'var(--fg-dim)', margin: '8px 0', lineHeight: 1.4 }}>
            Teaching orbital mechanics? Download the OrbitWarden Educator Guide.
          </p>
          <a href="/EDUCATOR_GUIDE.md" target="_blank" className="btn" style={{ width: '100%', justifyContent: 'center' }}>
            View Guide (PDF/MD)
          </a>
        </div>
      </aside>

      {/* Main content area */}
      <main style={{ flex: 1, borderLeft: '1px solid var(--border)', paddingLeft: '32px', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '24px' }}>
          <span style={{ fontSize: '2rem' }}>{mod.icon}</span>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 600, color: 'var(--fg)' }}>{mod.title}</h2>
        </div>
        
        <p style={{ color: 'var(--fg-dim)', marginBottom: '32px', fontSize: '0.95rem', maxWidth: '600px', lineHeight: 1.6 }}>
          These explanations are pulled directly from the OrbitWarden AI analyst's knowledge base. 
          When you ask the analyst a question, it uses these exact chunks of domain knowledge to answer.
        </p>

        {loading ? (
          <div className="mono" style={{ color: 'var(--fg-dim)' }}>Loading knowledge base chunks...</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', maxWidth: '800px' }}>
            {chunks.map(chunk => (
              <div key={chunk.chunk_id} style={{ 
                background: 'var(--bg)', 
                border: '1px solid var(--border)', 
                borderRadius: '8px',
                padding: '24px'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
                  <h3 style={{ fontSize: '1.1rem', color: 'var(--accent)', margin: 0 }}>{chunk.title}</h3>
                  <span className="chip" style={{ opacity: 0.7 }}>{chunk.topic}</span>
                </div>
                <div className="chunk-body" style={{ 
                  color: 'var(--fg)', 
                  lineHeight: 1.6, 
                  fontSize: '0.95rem'
                }}>
                  {chunk.body}
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
