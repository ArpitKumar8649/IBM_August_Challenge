import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ScoredConjunction, SatelliteInfo, SpaceWeather, ManeuverOption } from '../types'
import { fetchSatellite, fetchEvents, fetchWeather, fetchManeuvers, streamChat } from '../lib/api'
import { MissionClock, TcaCountdown } from '../components/Clocks'
import '../styles/dashboard.css'

interface ChatMsg {
  role: 'user' | 'bot' | 'tool'
  text: string
}

export default function Dashboard() {
  const [satellite, setSatellite] = useState<SatelliteInfo | null>(null)
  const [weather, setWeather] = useState<SpaceWeather | null>(null)
  const [events, setEvents] = useState<ScoredConjunction[]>([])
  const [live, setLive] = useState(false)
  const [selected, setSelected] = useState<ScoredConjunction | null>(null)
  const [maneuvers, setManeuvers] = useState<ManeuverOption[]>([])
  const [chat, setChat] = useState<ChatMsg[]>([
    { role: 'bot', text: 'OrbitWarden analyst online. Ask me about your conjunctions, or request an avoidance plan.' },
  ])
  const [chatInput, setChatInput] = useState('')
  const [chatBusy, setChatBusy] = useState(false)

  useEffect(() => {
    let mounted = true
    Promise.all([fetchSatellite(), fetchEvents(), fetchWeather()]).then(([s, e, w]) => {
      if (!mounted) return
      setSatellite(s.data)
      setEvents(e.data)
      setWeather(w.data)
      setLive(e.live)
      setSelected(e.data[0] ?? null)
    })
    return () => { mounted = false }
  }, [])

  useEffect(() => {
    if (!selected) return
    fetchManeuvers(selected.event_id).then(({ data }) => setManeuvers(data))
  }, [selected])

  const sendChat = async () => {
    const msg = chatInput.trim()
    if (!msg || chatBusy) return
    setChatInput('')
    setChat((c) => [...c, { role: 'user', text: msg }])
    setChatBusy(true)
    try {
      let botText = ''
      for await (const ev of streamChat(msg)) {
        if (ev.type === 'tool_call' && ev.name) {
          setChat((c) => [...c, { role: 'tool', text: `⚙ ${ev.name}` }])
        } else if (ev.type === 'content' && ev.text) {
          botText = ev.text
        }
      }
      setChat((c) => [...c, { role: 'bot', text: botText || 'Done.' }])
    } catch {
      setChat((c) => [...c, { role: 'bot', text: 'The analyst backend is offline — showing sample data. Start the API with `uvicorn api.main:app` to chat live.' }])
    } finally {
      setChatBusy(false)
    }
  }

  const riskTone = (score: number) => (score >= 60 ? 'danger' : score >= 40 ? 'warn' : 'good')

  return (
    <div className="dash">
      {/* ---------- top bar ---------- */}
      <header className="dash-top">
        <Link to="/" className="brand">
          <span className="script">OrbitWarden</span>
          <span className="tag">mission control</span>
        </Link>
        <div className="dash-status">
          <span className={`chip ${live ? 'good' : 'warn'}`}>
            <span className="dot" style={{ background: live ? 'var(--good)' : 'var(--warn)' }} />
            {live ? 'LIVE API' : 'SAMPLE DATA'}
          </span>
          <span className="chip"><MissionClock /></span>
        </div>
      </header>

      <div className="dash-body">
        {/* ---------- left rail: KPIs + event board ---------- */}
        <aside className="dash-rail">
          <div className="kpi-strip">
            <div className="kpi">
              <span className="kpi-v mono">{satellite?.name ?? '—'}</span>
              <span className="kpi-l">primary · NORAD {satellite?.norad_id}</span>
            </div>
            <div className="kpi-grid">
              <div className="kpi">
                <span className="kpi-v mono">{events.length}</span>
                <span className="kpi-l">conjunctions · 7d</span>
              </div>
              <div className="kpi">
                <span className="kpi-v mono">{satellite ? `${satellite.perigee_alt_km.toFixed(0)}×${satellite.apogee_alt_km.toFixed(0)}` : '—'}</span>
                <span className="kpi-l">orbit · km</span>
              </div>
              <div className="kpi">
                <span className="kpi-v mono">{weather ? weather.max_kp_3day.toFixed(1) : '—'}</span>
                <span className="kpi-l">max Kp · 3d</span>
              </div>
              <div className="kpi">
                <span className="kpi-v mono">{weather?.active_storm ? 'STORM' : 'quiet'}</span>
                <span className="kpi-l">space weather</span>
              </div>
            </div>
          </div>

          <div className="board">
            <div className="board-head">
              <span className="eyebrow" style={{ fontSize: '0.62rem' }}>Conjunction board</span>
              <span className="mono board-count">{events.length} tracked</span>
            </div>
            <div className="board-list">
              {events.map((e) => (
                <button
                  key={e.event_id}
                  className={`event-row ${selected?.event_id === e.event_id ? 'active' : ''}`}
                  onClick={() => setSelected(e)}
                >
                  <div className="event-top">
                    <span className={`risk-chip ${riskTone(e.risk_score)}`}>{e.risk_score.toFixed(0)}</span>
                    <span className="event-name">{e.secondary_name}</span>
                    {e.storm_flag && <span className="storm-flag" title="Storm flag — re-screen near TCA">⚠</span>}
                  </div>
                  <div className="event-meta mono">
                    miss {e.miss_km.toFixed(2)} km · {e.vrel_kms.toFixed(1)} km/s · {e.geometry}
                  </div>
                  <div className="event-tca mono">
                    TCA <TcaCountdown target={e.tca} />
                  </div>
                </button>
              ))}
            </div>
          </div>
        </aside>

        {/* ---------- main: event detail + analyst ---------- */}
        <main className="dash-main">
          {selected && (
            <section className="detail panel">
              <div className="detail-head">
                <div>
                  <div className="detail-name">
                    {selected.secondary_name}
                    <span className="chip" style={{ marginLeft: 12 }}>{selected.secondary_type}</span>
                    {!selected.secondary_maneuverable && (
                      <span className="chip danger" style={{ marginLeft: 8 }}>cannot maneuver</span>
                    )}
                  </div>
                  <div className="detail-sub mono">
                    NORAD {selected.secondary_norad} · event #{selected.event_id}
                  </div>
                </div>
                <div className="detail-risk">
                  <span className={`risk-big ${riskTone(selected.risk_score)}`}>{selected.risk_score.toFixed(1)}</span>
                  <span className="risk-l">risk score</span>
                </div>
              </div>

              <div className="detail-grid">
                <div className="metric">
                  <span className="m-v mono">{selected.miss_km.toFixed(3)}</span>
                  <span className="m-l">miss distance · km</span>
                </div>
                <div className="metric">
                  <span className="m-v mono">{selected.vrel_kms.toFixed(2)}</span>
                  <span className="m-l">rel. velocity · km/s</span>
                </div>
                <div className="metric">
                  <span className="m-v mono">{selected.pc.toExponential(2)}</span>
                  <span className="m-l">collision probability</span>
                </div>
                <div className="metric">
                  <span className="m-v mono"><TcaCountdown target={selected.tca} /></span>
                  <span className="m-l">time to closest approach</span>
                </div>
              </div>

              {selected.miss_rsw_km && (
                <div className="rsw">
                  <span className="eyebrow" style={{ fontSize: '0.6rem' }}>miss geometry · RSW</span>
                  <div className="rsw-bars">
                    {([
                      ['radial', selected.miss_rsw_km.radial, 'var(--danger)'],
                      ['in-track', selected.miss_rsw_km.in_track, 'var(--accent)'],
                      ['cross-track', selected.miss_rsw_km.cross_track, 'var(--warn)'],
                    ] as const).map(([label, val, color]) => {
                      const max = Math.max(
                        Math.abs(selected.miss_rsw_km!.radial),
                        Math.abs(selected.miss_rsw_km!.in_track),
                        Math.abs(selected.miss_rsw_km!.cross_track),
                        1,
                      )
                      return (
                        <div key={label} className="rsw-row">
                          <span className="rsw-label mono">{label}</span>
                          <div className="rsw-track">
                            <div
                              className="rsw-fill"
                              style={{ width: `${(Math.abs(val) / max) * 100}%`, background: color }}
                            />
                          </div>
                          <span className="rsw-val mono">{val.toFixed(2)} km</span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              <div className="maneuvers">
                <span className="eyebrow" style={{ fontSize: '0.6rem' }}>avoidance options</span>
                <div className="man-grid">
                  {maneuvers.map((m) => (
                    <div key={m.kind} className="man-card">
                      <span className={`man-kind ${m.kind}`}>{m.kind}</span>
                      <div className="man-v mono">{m.dv_total_ms.toFixed(0)} <small>m/s</small></div>
                      <div className="man-row mono">→ {m.post_burn_miss_km.toFixed(0)} km miss</div>
                      <div className="man-row mono">{m.propellant_g.toFixed(0)} g propellant</div>
                      <div className="man-row mono">{m.lead_time_min.toFixed(0)} min before TCA</div>
                    </div>
                  ))}
                </div>
                <p className="man-note">
                  Recommendation only — human approval required. Re-screen within 24 h of TCA.
                </p>
              </div>
            </section>
          )}

          {/* ---------- analyst chat ---------- */}
          <section className="analyst panel">
            <div className="analyst-head">
              <span className="chat-dot" /> OrbitWarden Analyst
              <span className="chip good" style={{ marginLeft: 'auto' }}>Granite · validated</span>
            </div>
            <div className="analyst-body">
              {chat.map((m, i) => (
                <div key={i} className={`amsg ${m.role}`}>{m.text}</div>
              ))}
              {chatBusy && <div className="amsg tool">thinking…</div>}
            </div>
            <div className="analyst-input">
              <input
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && sendChat()}
                placeholder="Ask about your conjunctions, or request an avoidance plan…"
                disabled={chatBusy}
              />
              <button className="btn btn-primary" onClick={sendChat} disabled={chatBusy}>
                Send
              </button>
            </div>
          </section>
        </main>
      </div>
    </div>
  )
}
