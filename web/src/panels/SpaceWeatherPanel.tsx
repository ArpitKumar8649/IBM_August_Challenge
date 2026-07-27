import { useEffect, useState } from 'react'
import type { SpaceWeatherDetailed } from '../types'
import { fetchWeatherDetailed } from '../lib/api'

/** Phase B — multi-signal space-weather panel. */
export default function SpaceWeatherPanel() {
  const [data, setData] = useState<SpaceWeatherDetailed | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchWeatherDetailed().then((d) => {
      setData(d)
      setLoading(false)
    })
  }, [])

  if (loading) return <div className="panel-loading">Loading space weather…</div>
  if (!data) return <div className="panel-empty">Space weather data unavailable (backend offline).</div>

  const levelTone =
    data.composite.level === 'severe' || data.composite.level === 'storm'
      ? 'danger'
      : data.composite.level === 'active' || data.composite.level === 'unsettled'
        ? 'warn'
        : 'good'

  return (
    <div className="panel-grid-2">
      <section className="panel stat-panel">
        <span className="eyebrow">composite storm risk</span>
        <div className="big-score">
          <span className={`risk-big ${levelTone}`}>{data.composite.score.toFixed(0)}</span>
          <span className="risk-l">/ 100 · {data.composite.level}</span>
        </div>
        <div className="drivers">
          {data.composite.drivers.length > 0 ? (
            data.composite.drivers.map((d) => (
              <span key={d} className="chip warn">{d}</span>
            ))
          ) : (
            <span className="chip good">no active drivers</span>
          )}
        </div>
      </section>

      <section className="panel stat-panel">
        <span className="eyebrow">signals</span>
        <div className="signal-list">
          <div className="signal">
            <span className="signal-l">Kp forecast (3d max)</span>
            <span className="signal-v mono">{data.kp_max_3day.toFixed(1)}</span>
          </div>
          <div className="signal">
            <span className="signal-l">IMF Bt</span>
            <span className="signal-v mono">{data.solar_wind.bt_nt.toFixed(1)} nT</span>
          </div>
          <div className="signal">
            <span className="signal-l">IMF Bz (GSM)</span>
            <span className={`signal-v mono ${data.solar_wind.bz_gsm_nt < -5 ? 'danger-text' : ''}`}>
              {data.solar_wind.bz_gsm_nt.toFixed(1)} nT
            </span>
          </div>
          <div className="signal">
            <span className="signal-l">Solar wind speed</span>
            <span className="signal-v mono">{data.solar_wind.speed_kms.toFixed(0)} km/s</span>
          </div>
          <div className="signal">
            <span className="signal-l">F10.7 flux</span>
            <span className="signal-v mono">{data.solar_wind.f107_sfu.toFixed(0)} sfu</span>
          </div>
          <div className="signal">
            <span className="signal-l">X-ray flare class</span>
            <span className="signal-v mono">{data.xray.flare_class}</span>
          </div>
          <div className="signal">
            <span className="signal-l">Proton flux (SEP)</span>
            <span className={`signal-v mono ${data.protons.sep_active ? 'danger-text' : ''}`}>
              {data.protons.flux_pfu.toFixed(2)} pfu {data.protons.sep_active ? '⚠' : ''}
            </span>
          </div>
        </div>
      </section>
    </div>
  )
}
