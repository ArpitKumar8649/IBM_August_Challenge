import type {
  ScoredConjunction,
  SatelliteInfo,
  SpaceWeather,
  ManeuverOption,
  BPlane,
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
  KnowledgeChunk,
  ConjunctionCzml,
  ManeuverKind,
} from '../types'
import {
  SAMPLE_EVENTS,
  SAMPLE_SATELLITE,
  SAMPLE_WEATHER,
  SAMPLE_MANEUVERS,
  SAMPLE_KNOWLEDGE,
  SAMPLE_MODULE_CHUNKS,
  sampleBPlane,
} from '../data/sample'

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
// B-plane — the canonical conjunction diagram (5.2)
// ============================================================

/**
 * Fetch the B-plane diagram for an event.
 *
 * Falls back to a geometry computed from the sample event's own RSW miss, so the
 * plot is never empty offline — and never shows numbers that contradict the event
 * card beside it. `live` says which one the reader is looking at.
 */
export async function fetchBPlane(
  event: ScoredConjunction,
  realismFactor = 2,
): Promise<{ data: BPlane; live: boolean }> {
  const data = await fetchRaw<BPlane>(
    `/api/events/${event.event_id}/bplane?realism_factor=${realismFactor}`,
  )
  return data?.available
    ? { data, live: true }
    : { data: sampleBPlane(event, realismFactor), live: false }
}

// ============================================================
// 5.1 — 3D conjunction globe (CZML)
// ============================================================

/** CZML fetch options. `maneuverKind: 'none'` explicitly requests no track. */
export interface ConjunctionCzmlOpts {
  maneuverKind?: ManeuverKind | 'none'
  windowMin?: number
}

const CZML_TIMEOUT_MS = 8000 // the scene can take ~1–3 s to compose (maneuver track)
/** Cache capacity — exported so tests derive their eviction scenarios from it. */
export const CZML_CACHE_MAX = 12

/**
 * Module-scope scene cache, keyed by the exact query used.
 *
 * Content toggles (kind / window) refetch; presentation toggles (covariance
 * visibility) are client-side and never touch this. Failures are NOT cached, so
 * Retry always re-hits the engine. LRU-ish: overflow evicts the oldest entry.
 */
const czmlCache = new Map<string, ConjunctionCzml>()

/** Drop every cached scene — e.g. after the backend re-screens an event. */
export function clearConjunctionCzmlCache(): void {
  czmlCache.clear()
}

function czmlUrl(eventId: number, opts: ConjunctionCzmlOpts): string {
  const params = new URLSearchParams()
  if (opts.maneuverKind && opts.maneuverKind !== 'none') {
    params.set('maneuver_kind', opts.maneuverKind)
  }
  if (opts.windowMin !== undefined) {
    params.set('window_min', String(opts.windowMin))
  }
  const qs = params.toString()
  return `/api/events/${eventId}/czml${qs ? `?${qs}` : ''}`
}

/**
 * A reachable engine answered with an error (4xx/5xx, or a scene marked
 * `available: false`). The message carries the backend's own words — the
 * `detail` of the HTTP error, or the envelope's `note` — so the panel can show
 * a real error state ("event 999 not found", "no feasible maneuver option…")
 * instead of a misleading offline card for a backend that is actually up.
 */
export class ConjunctionCzmlError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ConjunctionCzmlError'
  }
}

/**
 * Fetch the CZML scene for one conjunction (Phase 5.1 — 3D globe).
 *
 * - Resolves the scene when the engine composed one.
 * - Throws {@link ConjunctionCzmlError} when the engine is reachable but
 *   answered with an error (HTTP error, or `available: false`) — the message
 *   is the backend's `detail` / `note`.
 * - Resolves `null` when the backend is unreachable, the request was aborted,
 *   or the body was not a usable scene — the caller's stale-guard decides.
 *
 * There is deliberately NO sample fallback: a fabricated orbit would be a
 * fabricated number, so the caller shows an honest offline state instead. Pass
 * an AbortSignal to cancel a superseded request (stale-response guard); a
 * timeout (8 s) is applied regardless. Failures are never cached, so Retry
 * always re-hits the engine.
 */
export async function fetchConjunctionCzml(
  eventId: number,
  opts: ConjunctionCzmlOpts = {},
  signal?: AbortSignal,
): Promise<ConjunctionCzml | null> {
  // Already-cancelled callers never touch the network — checked BEFORE the cache
  // so abort semantics are uniform regardless of what is cached.
  if (signal?.aborted) return null

  const url = czmlUrl(eventId, opts)
  const cached = czmlCache.get(url)
  if (cached) return cached

  // Combine the caller's abort signal with a hard timeout.
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(new DOMException('timeout', 'TimeoutError')), CZML_TIMEOUT_MS)
  const onExternalAbort = () => controller.abort(signal?.reason)
  signal?.addEventListener('abort', onExternalAbort, { once: true })

  try {
    const res = await fetch(url, { signal: controller.signal })
    if (!res.ok) {
      // FastAPI answers 4xx/5xx with {"detail": "…"} — surface the message.
      let detail: string | null = null
      try {
        const errBody = (await res.json()) as { detail?: unknown }
        if (typeof errBody?.detail === 'string' && errBody.detail) detail = errBody.detail
      } catch {
        /* non-JSON error body — fall back to the HTTP status */
      }
      throw new ConjunctionCzmlError(detail ?? `engine error (HTTP ${res.status})`)
    }
    const body = (await res.json()) as ConjunctionCzml
    if (!body || body.available !== true) {
      // available:false is still an engine answer — carry its note when present.
      throw new ConjunctionCzmlError(body?.note ?? 'the engine could not compose this scene')
    }
    czmlCache.set(url, body)
    if (czmlCache.size > CZML_CACHE_MAX) {
      const oldest = czmlCache.keys().next().value
      if (oldest !== undefined) czmlCache.delete(oldest)
    }
    return body
  } catch (err) {
    if (err instanceof ConjunctionCzmlError) throw err
    return null // network error, timeout, or abort — caller's stale-guard decides
  } finally {
    clearTimeout(timeout)
    signal?.removeEventListener('abort', onExternalAbort)
  }
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

// ============================================================
// Phase 5.4 — Explainers & Knowledge Base
// ============================================================

/**
 * Fetch knowledge-base chunks for the Learn tab.
 *
 * Live: vector-retrieved from the same KB the analyst cites (plain + technical text).
 * Offline: falls back to the sample mirror — `moduleId` picks the curated chunk set
 * (SAMPLE_MODULE_CHUNKS); a raw query matches topic keywords.
 */
export async function fetchKnowledge(query: string, k = 3, moduleId?: string): Promise<KnowledgeChunk[] | null> {
  const data = await fetchRaw<{ chunks: KnowledgeChunk[] }>(
    `/api/knowledge/learn?query=${encodeURIComponent(query)}&k=${k}`,
  )
  if (data?.chunks?.length) return data.chunks

  if (moduleId && SAMPLE_MODULE_CHUNKS[moduleId]) {
    const ids = SAMPLE_MODULE_CHUNKS[moduleId]
    return ids.map((id) => SAMPLE_KNOWLEDGE.find((c) => c.chunk_id === id)!).filter(Boolean)
  }
  const words = query.toLowerCase().split(/\s+/).filter((w) => w.length > 3)
  const scored = SAMPLE_KNOWLEDGE.map((c) => ({
    c,
    n: words.filter((w) => `${c.title} ${c.topic} ${c.plain}`.toLowerCase().includes(w)).length,
  }))
  const hits = scored.filter((s) => s.n > 0).sort((a, b) => b.n - a.n).map((s) => s.c)
  return hits.length ? hits.slice(0, k) : SAMPLE_KNOWLEDGE.slice(0, k)
}
