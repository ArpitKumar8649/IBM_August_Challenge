import type { ScoredConjunction, SatelliteInfo, SpaceWeather, ManeuverOption } from '../types'
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
