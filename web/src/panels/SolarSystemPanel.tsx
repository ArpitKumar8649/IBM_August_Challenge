import { useEffect, useState } from 'react'
import type { PlanetPosition, IssPosition, Astronauts } from '../types'
import { fetchPlanet, fetchIss, fetchAstronauts } from '../lib/api'

const PLANETS = ['mercury', 'venus', 'mars', 'jupiter', 'saturn']

/** Phase D/A — solar system: planet positions (Horizons) + live ISS & astronauts. */
export default function SolarSystemPanel() {
  const [planets, setPlanets] = useState<Record<string, PlanetPosition | null>>({})
  const [iss, setIss] = useState<IssPosition | null>(null)
  const [astronauts, setAstronauts] = useState<Astronauts | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      ...PLANETS.map((p) => fetchPlanet(p)),
      fetchIss(),
      fetchAstronauts(),
    ]).then((results) => {
      const planetResults = results.slice(0, PLANETS.length) as (PlanetPosition | null)[]
      const map: Record<string, PlanetPosition | null> = {}
      PLANETS.forEach((p, i) => {
        map[p] = planetResults[i]
      })
      setPlanets(map)
      setIss(results[PLANETS.length] as IssPosition | null)
      setAstronauts(results[PLANETS.length + 1] as Astronauts | null)
      setLoading(false)
    })
  }, [])

  if (loading) return <div className="panel-loading">Loading solar system…</div>

  return (
    <div className="solar-grid">
      {/* Planet positions */}
      <section className="panel">
        <span className="eyebrow">planet positions · JPL Horizons (geocentric)</span>
        <div className="planet-list">
          {PLANETS.map((p) => {
            const pos = planets[p]
            return (
              <div key={p} className="planet-row">
                <span className="planet-name">{p}</span>
                {pos ? (
                  <span className="planet-dist mono">
                    {pos.distance_from_earth_au.toFixed(2)} AU
                    <span className="planet-km"> · {(pos.distance_from_earth_km / 1e6).toFixed(1)}M km</span>
                  </span>
                ) : (
                  <span className="planet-dist mono planet-na">unavailable</span>
                )}
              </div>
            )
          })}
        </div>
      </section>

      {/* Live ISS */}
      <section className="panel stat-panel">
        <span className="eyebrow">international space station · live</span>
        {iss ? (
          <>
            <div className="big-score">
              <span className="risk-big good">{iss.latitude.toFixed(1)}°</span>
              <span className="risk-l">latitude</span>
            </div>
            <div className="signal-list">
              <div className="signal">
                <span className="signal-l">Longitude</span>
                <span className="signal-v mono">{iss.longitude.toFixed(1)}°</span>
              </div>
              <div className="signal">
                <span className="signal-l">Source</span>
                <span className="signal-v mono">{iss.source}</span>
              </div>
            </div>
          </>
        ) : (
          <div className="panel-empty">ISS position unavailable.</div>
        )}
      </section>

      {/* Astronauts */}
      <section className="panel stat-panel">
        <span className="eyebrow">humans in space</span>
        {astronauts ? (
          <>
            <div className="big-score">
              <span className="risk-big good">{astronauts.number}</span>
              <span className="risk-l">people in orbit</span>
            </div>
            <div className="astro-list">
              {astronauts.people.slice(0, 6).map((a) => (
                <div key={a.name} className="astro-row mono">
                  {a.name} <span className="astro-craft">· {a.craft}</span>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="panel-empty">Astronaut data unavailable.</div>
        )}
      </section>
    </div>
  )
}
