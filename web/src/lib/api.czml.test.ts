/**
 * Specs for the 5.1 CZML client (fetchConjunctionCzml) — Phase A of
 * docs/PHASE5_1_GLOBE_PLAN.md.
 *
 * Pins the two things the globe panel depends on:
 *   1. URL building (engine query contract: maneuver_kind / window_min),
 *   2. cache semantics (content toggles refetch, identical requests don't,
 *      failures are never cached so Retry re-hits the engine).
 * All fetch calls are stubbed — nothing here touches the network or Cesium.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConjunctionCzml } from '../types'
import {
  CZML_CACHE_MAX,
  clearConjunctionCzmlCache,
  ConjunctionCzmlError,
  fetchConjunctionCzml,
  type ConjunctionCzmlOpts,
} from './api'

const SCENE: ConjunctionCzml = {
  available: true,
  event_id: 7,
  primary: 'ISS',
  secondary: 'COSMOS 2251 DEB',
  secondary_norad: 99998,
  tca: '2026-08-12T04:00:00Z',
  maneuver_kind: null,
  document: [{ id: 'document', version: '1.0' }],
}

/** Stub the global fetch to resolve ok-200 with `body`. Returns the mock. */
function mockFetchOk(body: unknown = SCENE, ok = true) {
  const fn = vi.fn().mockResolvedValue({
    ok,
    status: ok ? 200 : 500,
    json: async () => body,
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

beforeEach(() => clearConjunctionCzmlCache())
afterEach(() => vi.unstubAllGlobals())

describe('fetchConjunctionCzml — URL contract', () => {
  it('hits the plain scene URL when no options are given', async () => {
    const fetchMock = mockFetchOk()
    await fetchConjunctionCzml(7)
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/events/7/czml')
  })

  const urlCases: Array<[ConjunctionCzmlOpts, string]> = [
    [{ maneuverKind: 'nominal' }, '/api/events/7/czml?maneuver_kind=nominal'],
    [{ windowMin: 30 }, '/api/events/7/czml?window_min=30'],
    [
      { maneuverKind: 'cheapest-safe', windowMin: 120 },
      '/api/events/7/czml?maneuver_kind=cheapest-safe&window_min=120',
    ],
  ]
  it.each(urlCases)('maps %j to %s', async (opts, expectedUrl) => {
    const fetchMock = mockFetchOk()
    await fetchConjunctionCzml(7, opts)
    expect(fetchMock.mock.calls[0][0]).toBe(expectedUrl)
  })

  it("omits maneuver_kind when kind is 'none' (no track requested)", async () => {
    const fetchMock = mockFetchOk()
    await fetchConjunctionCzml(7, { maneuverKind: 'none' })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/events/7/czml')
  })
})

describe('fetchConjunctionCzml — response handling', () => {
  it('returns the parsed scene on success', async () => {
    mockFetchOk(SCENE)
    await expect(fetchConjunctionCzml(7)).resolves.toEqual(SCENE)
  })

  it('throws the engine note when the scene is unavailable', async () => {
    mockFetchOk({ ...SCENE, available: false, note: 'primary orbit failed to propagate' })
    await expect(fetchConjunctionCzml(7)).rejects.toThrow(
      new ConjunctionCzmlError('primary orbit failed to propagate'),
    )
  })

  it('surfaces the backend detail on a 4xx/5xx response', async () => {
    const fn = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'event 999 not found' }),
    })
    vi.stubGlobal('fetch', fn)
    await expect(fetchConjunctionCzml(7)).rejects.toThrow(
      new ConjunctionCzmlError('event 999 not found'),
    )
  })

  it('falls back to the HTTP status when the error body has no detail', async () => {
    mockFetchOk(SCENE, false) // status 500, body = SCENE (no detail)
    await expect(fetchConjunctionCzml(7)).rejects.toThrow(
      new ConjunctionCzmlError('engine error (HTTP 500)'),
    )
  })

  it('returns null when the network fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(fetchConjunctionCzml(7)).resolves.toBeNull()
  })

  it('returns null when the body is not JSON (200 with garbage)', async () => {
    const fn = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError('Unexpected token < in JSON')
      },
    })
    vi.stubGlobal('fetch', fn)
    await expect(fetchConjunctionCzml(7)).resolves.toBeNull()
  })
})

describe('fetchConjunctionCzml — cache semantics', () => {
  it('serves repeated identical requests from cache (one fetch)', async () => {
    const fetchMock = mockFetchOk()
    const first = await fetchConjunctionCzml(7)
    const second = await fetchConjunctionCzml(7)
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(second).toBe(first)
  })

  it('refetches when scene content (kind / window) differs', async () => {
    const fetchMock = mockFetchOk()
    await fetchConjunctionCzml(7, { maneuverKind: 'nominal' })
    await fetchConjunctionCzml(7, { maneuverKind: 'conservative' })
    await fetchConjunctionCzml(7, { windowMin: 30 })
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('never caches failures, so Retry re-hits the engine', async () => {
    const fetchMock = mockFetchOk()
    fetchMock.mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({}) })
    await expect(fetchConjunctionCzml(7)).rejects.toThrow(/HTTP 500/)
    await expect(fetchConjunctionCzml(7)).resolves.toEqual(SCENE)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('evicts the oldest entry when the cache overflows', async () => {
    const fetchMock = mockFetchOk()
    // Fill past the cap with distinct events (derived from the exported constant).
    for (let id = 1; id <= CZML_CACHE_MAX + 1; id++) await fetchConjunctionCzml(id)
    await fetchConjunctionCzml(1) // oldest → evicted → refetch
    const mid = Math.min(7, CZML_CACHE_MAX) // still cached → hit
    await fetchConjunctionCzml(mid)
    expect(fetchMock).toHaveBeenCalledTimes(CZML_CACHE_MAX + 2)
  })

  it('clearConjunctionCzmlCache forces a refetch', async () => {
    const fetchMock = mockFetchOk()
    await fetchConjunctionCzml(7)
    clearConjunctionCzmlCache()
    await fetchConjunctionCzml(7)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})

describe('fetchConjunctionCzml — abort plumbing', () => {
  it('resolves null promptly when the caller aborts mid-flight', async () => {
    const controller = new AbortController()
    const fetchMock = vi.fn().mockImplementation(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () =>
            reject(new DOMException('aborted', 'AbortError')),
          )
        }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const pending = fetchConjunctionCzml(7, {}, controller.signal)
    controller.abort()
    await expect(pending).resolves.toBeNull()
  })

  it('handles an already-aborted signal without fetching', async () => {
    const controller = new AbortController()
    controller.abort()
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => SCENE })
    vi.stubGlobal('fetch', fetchMock)
    await expect(fetchConjunctionCzml(7, {}, controller.signal)).resolves.toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('honors an already-aborted signal even when the scene is cached', async () => {
    const fetchMock = mockFetchOk()
    await fetchConjunctionCzml(7) // populate the cache
    const controller = new AbortController()
    controller.abort()
    await expect(fetchConjunctionCzml(7, {}, controller.signal)).resolves.toBeNull()
    expect(fetchMock).toHaveBeenCalledTimes(1) // cache untouched, no second fetch
  })
})
