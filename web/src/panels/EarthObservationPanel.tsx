import { useEffect, useState } from 'react'
import type { GroundTrack, ImageryScene, NeoObject } from '../types'
import { fetchGroundTrack, fetchImagery, fetchNeo } from '../lib/api'

/** Phase C/A — Earth observation: ground track, imagery under the satellite, NEO watch. */
export default function EarthObservationPanel() {
  const [track, setTrack] = useState<GroundTrack | null>(null)
  const [scenes, setScenes] = useState<ImageryScene[]>([])
  const [neos, setNeos] = useState<NeoObject[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([fetchGroundTrack(90), fetchImagery('sentinel-2'), fetchNeo(7)]).then(
      ([t, img, neo]) => {
        setTrack(t)
        setScenes(img?.scenes ?? [])
        setNeos(neo ?? [])
        setLoading(false)
      },
    )
  }, [])

  if (loading) return <div className="panel-loading">Loading Earth observation…</div>

  return (
    <div className="eo-grid">
      {/* Ground track */}
      <section className="panel">
        <span className="eyebrow">ground track · next 90 min</span>
        {track ? (
          <>
            <div className="track-meta mono">
              {track.satellite} · now at {track.current.latitude.toFixed(1)}°,{' '}
              {track.current.longitude.toFixed(1)}° · {track.current.altitude_km.toFixed(0)} km
            </div>
            <GroundTrackMap track={track} />
          </>
        ) : (
          <div className="panel-empty">Ground track unavailable.</div>
        )}
      </section>

      {/* Imagery under the satellite */}
      <section className="panel">
        <span className="eyebrow">imagery under satellite · Sentinel-2</span>
        {scenes.length > 0 ? (
          <div className="scene-list">
            {scenes.slice(0, 3).map((s) => (
              <div key={s.id} className="scene-card">
                {s.thumbnail_url && (
                  <img src={s.thumbnail_url} alt={s.id} className="scene-thumb" loading="lazy" />
                )}
                <div className="scene-meta mono">
                  <div>{s.platform || 'sentinel-2'}</div>
                  <div>{s.datetime?.slice(0, 10)}</div>
                  <div>cloud {s.cloud_cover.toFixed(0)}%</div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="panel-empty">No recent cloud-filtered scenes under the satellite.</div>
        )}
      </section>

      {/* NEO watch */}
      <section className="panel">
        <span className="eyebrow">near-Earth objects ·7 days</span>
        {neos.length > 0 ? (
          <div className="neo-list">
            {neos.slice(0, 6).map((n) => (
              <div key={n.name} className="neo-row">
                <span className={`neo-flag ${n.hazardous ? 'danger' : 'good'}`}>
                  {n.hazardous ? '⚠ PHA' : '○'}
                </span>
                <span className="neo-name">{n.name}</span>
                <span className="neo-meta mono">
                  Ø{(n.diameter_km * 1000).toFixed(0)} m
                  {n.approaches[0] && ` · ${(n.approaches[0].miss_lunar).toFixed(1)} LD`}
               </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="panel-empty">No near-Earth object data.</div>
        )}
      </section>
    </div>
  )
}

/** Simple equirectangular ground-track plot (SVG). */
function GroundTrackMap({ track }: { track: GroundTrack }) {
  const W = 480
  const H = 240
  const project = (lat: number, lon: number) => ({
    x: ((lon + 180) / 360) * W,
    y: ((90 - lat) / 180) * H,
  })

  // Split the path at antimeridian crossings to avoid wrap-around lines.
  const segments: { x: number; y: number }[][] = []
  let current: { x: number; y: number }[] = []
  let prevLon: number | null = null
  for (const p of track.track) {
    if (prevLon !== null && Math.abs(p.lon - prevLon) > 180) {
      if (current.length) segments.push(current)
      current = []
    }
    current.push(project(p.lat, p.lon))
    prevLon = p.lon
  }
  if (current.length) segments.push(current)

  const now = project(track.current.latitude, track.current.longitude)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="track-map">
      <rect x="0" y="0" width={W} height={H} className="track-bg" />
      {/* graticule */}
      {[0.25,0.5, 0.75].map((f) => (
        <line key={`v${f}`} x1={W * f} y1="0" x2={W * f} y2={H} className="track-grid" />
      ))}
      {[0.25, 0.5, 0.75].map((f) => (
        <line key={`h${f}`} x1="0" y1={H * f} x2={W} y2={H * f} className="track-grid" />
      ))}
      <line x1="0" y1={H / 2} x2={W} y2={H / 2} className="track-equator" />
      {/* ground track path */}
      {segments.map((seg, i) => (
        <polyline
          key={i}
          points={seg.map((pt) => `${pt.x},${pt.y}`).join(' ')}
          className="track-path"
        />
      ))}
      {/* current position */}
      <circle cx={now.x} cy={now.y} r="5" className="track-now" />
      <circle cx={now.x} cy={now.y} r="9" className="track-now-ring" />
    </svg>
  )
}
