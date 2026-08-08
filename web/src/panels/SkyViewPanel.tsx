import { useEffect, useState } from 'react'
import type { PassesResponse, VisiblePass } from '../types'
import { fetchPasses } from '../lib/api'
import SkyChart from '../viz/SkyChart'
import Explainer from '../components/Explainer'

/**
 * "Tonight's Sky" (Phase 5.3) — the public face of OrbitWarden.
 *
 * Pick a location (preset cities, browser geolocation, or coordinates) and see
 * which famous satellites pass overhead tonight: times, compass directions,
 * brightness, and a plain-language "look northwest at 9:42 PM" instruction,
 * drawn on a polar sky chart. Every technical term carries an explainer; the
 * panel is honest about data provenance (LIVE vs SAMPLE chips, engine notes
 * surfaced verbatim, and the engine's own "no passes tonight" empty state).
 */
const PRESETS = [
  { name: 'Bengaluru', lat: 12.97, lon: 77.59 },
  { name: 'Delhi', lat: 28.61, lon: 77.21 },
  { name: 'Mumbai', lat: 19.08, lon: 72.88 },
  { name: 'New York', lat: 40.71, lon: -74.01 },
  { name: 'London', lat: 51.51, lon: -0.13 },
  { name: 'Tokyo', lat: 35.68, lon: 139.69 },
]

const fmtLocal = (iso: string): string => {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

const round3 = (v: number): number => Math.round(v * 1000) / 1000

export default function SkyViewPanel() {
  const [lat, setLat] = useState(PRESETS[0].lat)
  const [lon, setLon] = useState(PRESETS[0].lon)
  const [data, setData] = useState<PassesResponse | null>(null)
  const [live, setLive] = useState(false)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(0)
  const [retry, setRetry] = useState(0)
  const [geoBusy, setGeoBusy] = useState(false)
  const [geoErr, setGeoErr] = useState('')
  const [manualLat, setManualLat] = useState(String(PRESETS[0].lat))
  const [manualLon, setManualLon] = useState(String(PRESETS[0].lon))

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchPasses(lat, lon).then(({ data: d, live: isLive }) => {
      if (cancelled) return
      setData(d)
      setLive(isLive)
      setSelected(0)
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [lat, lon, retry])

  const useMyLocation = () => {
    if (!('geolocation' in navigator)) {
      setGeoErr("Geolocation isn't supported here — pick a city or enter coordinates.")
      return
    }
    setGeoBusy(true)
    setGeoErr('')
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLat(round3(pos.coords.latitude))
        setLon(round3(pos.coords.longitude))
        setGeoBusy(false)
      },
      (err) => {
        setGeoErr(`Could not get your location (${err.message}) — pick a city or enter coordinates.`)
        setGeoBusy(false)
      },
      { timeout: 10000 },
    )
  }

  const applyManual = () => {
    const a = parseFloat(manualLat)
    const b = parseFloat(manualLon)
    if (Number.isFinite(a) && a >= -90 && a <= 90 && Number.isFinite(b) && b >= -180 && b <= 180) {
      setLat(round3(a))
      setLon(round3(b))
      setGeoErr('')
    } else {
      setGeoErr('Latitude must be between −90 and 90; longitude between −180 and 180.')
    }
  }

  const passes: VisiblePass[] = data?.passes ?? []
  const best = passes.reduce<VisiblePass | null>(
    (acc, p) => (acc === null || p.magnitude < acc.magnitude ? p : acc),
    null,
  )
  const hasISS = passes.some((p) => p.name.toUpperCase().includes('ISS'))

  return (
    <div className="sky">
      <section className="panel sky-panel">
        <div className="sky-head">
          <span className="eyebrow">
            tonight's sky · <Explainer termId="pass">what's passing over me?</Explainer>
          </span>
          <span className={`chip ${live ? 'good' : 'warn'}`}>
            <span className="dot" style={{ background: live ? 'var(--good)' : 'var(--warn)' }} />
            {live ? 'LIVE · fresh orbital elements' : 'SAMPLE'}
          </span>
        </div>

        {/* ---------- location ---------- */}
        <div className="sky-loc">
          <span className="sky-loc-label">Where are you?</span>
          <div className="sky-presets">
            {PRESETS.map((p) => (
              <button
                key={p.name}
                type="button"
                className={`sky-preset ${lat === p.lat && lon === p.lon ? 'active' : ''}`}
                onClick={() => {
                  setLat(p.lat)
                  setLon(p.lon)
                }}
              >
                {p.name}
              </button>
            ))}
          </div>
          <button type="button" className="sky-geo" onClick={useMyLocation} disabled={geoBusy}>
            {geoBusy ? 'locating…' : 'use my location'}
          </button>
          <div className="sky-manual">
            <input
              type="number"
              step="any"
              aria-label="latitude"
              placeholder="lat"
              value={manualLat}
              onChange={(e) => setManualLat(e.target.value)}
            />
            <input
              type="number"
              step="any"
              aria-label="longitude"
              placeholder="lon"
              value={manualLon}
              onChange={(e) => setManualLon(e.target.value)}
            />
            <button type="button" className="btn btn-primary" onClick={applyManual}>
              check the sky
            </button>
          </div>
        </div>
        {geoErr && <div className="sky-geo-err">{geoErr}</div>}

        {loading ? (
          <div className="panel-loading" role="status">computing tonight's passes…</div>
        ) : !data ? (
          <div className="panel-empty">No pass data.</div>
        ) : !data.available ? (
          /* A reachable engine said no (fresh elements unreachable / date outside
             the reliable window) — show its own words, never a fake prediction. */
          <div className="sky-error" role="alert">
            <div className="sky-error-title">The sky forecast is unavailable right now</div>
            <p>{data.note}</p>
            <button type="button" className="btn" onClick={() => setRetry((n) => n + 1)}>
              try again
            </button>
          </div>
        ) : passes.length === 0 ? (
          <div className="sky-empty">
            <div className="sky-empty-title">The sky is quiet tonight</div>
            <p>
              No famous satellites pass high enough in darkness from here tonight. Try a darker
              location, check back tomorrow, or look at dawn — early-morning passes are often
              the brightest.
            </p>
          </div>
        ) : (
          <>
            {/* ---------- tonight at a glance ---------- */}
            {best && (
              <div className="sky-summary">
                <span className="sky-summary-n">{passes.length}</span> visible{' '}
                {passes.length === 1 ? 'pass' : 'passes'} tonight
                {data.night_start && data.night_end && (
                  <span className="mono">
                    {' '}
                    · dark {fmtLocal(data.night_start)} → {fmtLocal(data.night_end)}
                  </span>
                )}
                {hasISS && (
                  <span className="sky-summary-iss"> · the ISS is one of them — watch for it</span>
                )}
                <p>
                  The brightest is <strong>{best.name.split('(')[0].trim()}</strong> at{' '}
                  <strong>{fmtLocal(best.start)}</strong> — {best.brightness_label.toLowerCase()}.{' '}
                  {best.look_instruction}
                </p>
              </div>
            )}

            <div className="sky-grid">
              {/* ---------- pass list ---------- */}
              <div className="sky-list" role="list" aria-label="tonight's satellite passes">
                {passes.map((p, i) => {
                  const isBest = best !== null && p.magnitude === best.magnitude
                  const short = p.name.split('(')[0].trim()
                  return (
                    <button
                      key={`${p.norad_id}-${p.start}`}
                      type="button"
                      role="listitem"
                      className={`sky-pass ${i === selected ? 'active' : ''} ${isBest ? 'best' : ''}`}
                      onClick={() => setSelected(i)}
                      aria-pressed={i === selected}
                    >
                      <div className="sky-pass-time mono">{fmtLocal(p.start)}</div>
                      <div className="sky-pass-body">
                        <div className="sky-pass-name">
                          {short}
                          {isBest && <span className="chip good">brightest</span>}
                          {!isBest && p.magnitude < 0 && (
                            <span className="chip">very bright</span>
                          )}
                        </div>
                        <div className="sky-pass-dir mono">
                          <Explainer termId="azimuth">look {p.direction_from}</Explainer> · moving{' '}
                          {p.direction_from}→{p.direction_to} · {p.max_elevation_deg.toFixed(0)}°{' '}
                          <Explainer termId="elevation">up</Explainer>
                        </div>
                        <div className="sky-pass-bright">
                          <Explainer termId="magnitude">brightness</Explainer>: {p.brightness_label}
                        </div>
                        <div className="sky-pass-look">{p.look_instruction}</div>
                        {p.object_blurb && <div className="sky-pass-blurb">{p.object_blurb}</div>}
                      </div>
                    </button>
                  )
                })}
              </div>

              {/* ---------- sky chart ---------- */}
              <div className="sky-chart-col">
                <div className="sky-chart-card">
                  <SkyChart pass={passes[selected] ?? null} />
                  {passes[selected] && (
                    <div className="sky-chart-cap mono">
                      {passes[selected].name.split('(')[0].trim()} ·{' '}
                      {fmtLocal(passes[selected].start)} → {fmtLocal(passes[selected].end)} · apex{' '}
                      {fmtLocal(passes[selected].max_elevation_time)} — you are at the centre,
                      looking up
                    </div>
                  )}
                </div>
                <p className="sky-note">{data.note}</p>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
