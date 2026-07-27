import type {
  ScoredConjunction,
  SatelliteInfo,
  SpaceWeather,
  ManeuverOption,
  Transient,
  ExoplanetStats,
  Star,
  PlanetPosition,
  GroundTrack,
  ImageryScene,
  NeoObject,
  IssPosition,
  Astronauts,
  CatalogStats,
  SpaceWeatherDetailed,
  SystemHealth,
} from '../types'
import { SAMPLE_EVENTS, SAMPLE_SATELLITE, SAMPLE_WEATHER, SAMPLE_MANEUVERS } from '../data/sample'

/**
 * API client with graceful fallback to the bundled sample dataset, so the UI is
 * always alive whether or not the FastAPI backend is running.
 */

async function tryFetch<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(2500) })
    if (!res.ok) return null
    return (await res.json()) as T
  } catch {
    return null
  }
}

/** Fetch that returns the raw response (or null) — for endpoints with no sample fallback. */
async function fetchRaw<T>(url: string, timeoutMs = 8000): Promise<T | null> {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) })
    if (!res.ok) return null
    return (await res.json()) as T
  } catch {
    return null
  }
}

export async function fetchSatellite(): Promise<{ data: SatelliteInfo; live: boolean }> {
  const data = await tryFetch<SatelliteInfo>('/api/satellite')
  return data ? { data, live: true } : { data: SAMPLE_SATELLITE, live: false }
}

export async function fetchEvents(): Promise<{ data: ScoredConjunction[]; live: boolean }> {
  const body = await tryFetch<{ events: ScoredConjunction[] }>('/api/events?limit=20')
  return body ? { data: body.events, live: true } : { data: SAMPLE_EVENTS, live: false }
}

export async function fetchWeather(): Promise<{ data: SpaceWeather; live: boolean }> {
  const data = await tryFetch<SpaceWeather>('/api/space-weather')
  return data && data.available ? { data, live: true } : { data: SAMPLE_WEATHER, live: false }
}

export async function fetchManeuvers(
  eventId: number,
): Promise<{ data: ManeuverOption[]; live: boolean }> {
  const body = await tryFetch<{ options: ManeuverOption[] }>(
    `/api/events/${eventId}/maneuvers?min_post_burn_miss_km=10`,
  )
  return body && body.options.length
    ? { data: body.options, live: true }
    : { data: SAMPLE_MANEUVERS, live: false }
}

// ============================================================
// Phase E — astronomy & discovery
// ============================================================

export async function fetchTransients(limit = 8): Promise<Transient[] | null> {
  const body = await fetchRaw<{ available: boolean; transients: Transient[] }>(
    `/api/transients?limit=${limit}`,
    65000, // ALeRCE is slow
  )
  return body?.available ? body.transients : null
}

export async function fetchExoplanets(sinceYear = 2020): Promise<ExoplanetStats | null> {
  return fetchRaw<ExoplanetStats>(`/api/exoplanets?since_year=${sinceYear}&limit=8`)
}

export async function fetchStars(ra: number, dec: number, radiusArcmin = 5): Promise<Star[] | null> {
  const body = await fetchRaw<{ available: boolean; stars: Star[] }>(
    `/api/stars?ra=${ra}&dec=${dec}&radius_arcmin=${radiusArcmin}&limit=8`,
  )
  return body?.available ? body.stars : null
}

// ============================================================
// Phase D — precision ephemerides
// ============================================================

export async function fetchPlanet(body: string): Promise<PlanetPosition | null> {
  const data = await fetchRaw<PlanetPosition>(`/api/planet/${body}`)
  return data?.available ? data : null
}

// ============================================================
// Phase C — Earth observation
// ============================================================

export async function fetchGroundTrack(minutes = 90): Promise<GroundTrack | null> {
  const data = await fetchRaw<GroundTrack>(`/api/ground-track?minutes=${minutes}`)
  return data?.available ? data : null
}

export async function fetchImagery(collection = 'sentinel-2'): Promise<{
  position: { latitude: number; longitude: number }
  scenes: ImageryScene[]
} | null> {
  const data = await fetchRaw<{ available: boolean; position: any; scenes: ImageryScene[] }>(
    `/api/imagery?collection=${collection}&max_cloud=40`,
    15000,
  )
  return data?.available ? { position: data.position, scenes: data.scenes } : null
}

// ============================================================
// Phase A — NASA / catalog / engagement
// ============================================================

export async function fetchNeo(days = 7): Promise<NeoObject[] | null> {
  const body = await fetchRaw<{ count: number; objects: NeoObject[] }>(`/api/neo?days=${days}`)
  return body?.objects ?? null
}

export async function fetchIss(): Promise<IssPosition | null> {
  const data = await fetchRaw<IssPosition>('/api/iss')
  return data?.available ? data : null
}

export async function fetchAstronauts(): Promise<Astronauts | null> {
  return fetchRaw<Astronauts>('/api/astronauts')
}

export async function fetchCatalogStats(): Promise<CatalogStats | null> {
  const data = await fetchRaw<CatalogStats>('/api/catalog-stats?top_n=8')
  return data?.available ? data : null
}

// ============================================================
// Phase B — space weather (detailed)
// ============================================================

export async function fetchWeatherDetailed(): Promise<SpaceWeatherDetailed | null> {
  return fetchRaw<SpaceWeatherDetailed>('/api/space-weather/detailed')
}

// ============================================================
// Operational health
// ============================================================

export async function fetchSystemHealth(): Promise<SystemHealth | null> {
  return fetchRaw<SystemHealth>('/api/health/full')
}

/** Stream the analyst chat via SSE; yields parsed events. */
export async function* streamChat(message: string): AsyncGenerator<{
  type: string
  name?: string
  text?: string
  audit_passed?: boolean
}> {
  const url = `/api/chat/events?message=${encodeURIComponent(message)}`
  const res = await fetch(url)
  if (!res.ok || !res.body) throw new Error('chat unavailable')
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      const payload = line.replace(/^data: /, '').trim()
      if (!payload) continue
      try {
        yield JSON.parse(payload)
      } catch {
        /* skip malformed frame */
      }
    }
  }
}
