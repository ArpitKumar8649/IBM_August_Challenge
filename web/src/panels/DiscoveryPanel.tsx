import { useEffect, useState } from 'react'
import type { Transient, ExoplanetStats, Star } from '../types'
import { fetchTransients, fetchExoplanets, fetchStars } from '../lib/api'

/** Phase E — astronomy & discovery: transients, exoplanets, Gaia stars. */
export default function DiscoveryPanel() {
  const [transients, setTransients] = useState<Transient[] | null>(null)
  const [exoplanets, setExoplanets] = useState<ExoplanetStats | null>(null)
  const [stars, setStars] = useState<Star[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Gaia cone search near the Galactic center as a representative field.
    Promise.all([fetchTransients(8), fetchExoplanets(2020), fetchStars(266.4, -28.9, 6)]).then(
      ([t, e, s]) => {
        setTransients(t)
        setExoplanets(e)
        setStars(s)
        setLoading(false)
      },
    )
  }, [])

  if (loading) return <div className="panel-loading">Loading discovery data…</div>

  return (
    <div className="disco-grid">
      {/* Transients */}
      <section className="panel">
        <span className="eyebrow">tonight's sky · ZTF transients</span>
        {transients && transients.length > 0 ? (
          <div className="transient-list">
            {transients.map((t) => (
              <div key={t.oid} className="transient-row">
                <span className="transient-oid mono">{t.oid}</span>
                <span className="transient-class">{t.classification}</span>
                <span className="transient-meta mono">
                  {t.ra.toFixed(1)}, {t.dec.toFixed(1)} · {t.last_observed}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="panel-empty">Transient data unavailable (ALeRCE slow/offline).</div>
        )}
      </section>

      {/* Exoplanets */}
      <section className="panel stat-panel">
        <span className="eyebrow">exoplanets</span>
        {exoplanets?.available ? (
          <>
            <div className="big-score">
              <span className="risk-big good">{exoplanets.count.toLocaleString()}</span>
              <span className="risk-l">confirmed since {exoplanets.confirmed_since}</span>
            </div>
            <div className="method-tags">
              {Object.entries(exoplanets.methods_in_sample).map(([m, n]) => (
                <span key={m} className="chip">{m}: {n}</span>
              ))}
            </div>
            <div className="recent-exos">
              {exoplanets.recent.slice(0, 4).map((e) => (
                <div key={e.name} className="exo-row mono">
                  {e.name} · {e.year} · {e.discovery_method}
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="panel-empty">Exoplanet data unavailable.</div>
        )}
      </section>

      {/* Gaia stars */}
      <section className="panel">
        <span className="eyebrow">Gaia DR3 · field near Galactic center</span>
        {stars && stars.length > 0 ? (
          <div className="star-list">
            {stars.map((s) => (
              <div key={s.source_id} className="star-row mono">
                <span className="star-id">{s.source_id}</span>
                <span className="star-mag">G {s.g_mag.toFixed(2)}</span>
                <span className="star-pos">{s.ra.toFixed(3)}, {s.dec.toFixed(3)}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="panel-empty">Gaia field unavailable (rate-limited).</div>
        )}
      </section>
    </div>
  )
}
