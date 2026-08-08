/**
 * Specs for the 5.3 "Tonight's Sky" client (fetchPasses), the offline sample
 * mirror (samplePasses), and the polar sky chart (SkyChart).
 *
 * Pins the honesty contract: a reachable engine's envelope is passed through
 * verbatim (including available:false with its note — never masked by the
 * sample), and only a truly unreachable backend falls back to the clearly
 * labelled sample. All fetch calls are stubbed; the chart is rendered with
 * react-dom/server so no DOM test-library is needed.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { PassesResponse } from '../types'
import { fetchPasses } from './api'
import { samplePasses } from '../data/sample'
import SkyChart from '../viz/SkyChart'

const RESPONSE: PassesResponse = {
  available: true,
  latitude: 12.97,
  longitude: 77.59,
  date: '2026-08-08',
  night_start: '2026-08-08T13:30:00Z',
  night_end: '2026-08-09T00:30:00Z',
  max_tle_age_days: 0.4,
  passes: [
    {
      norad_id: 25544,
      name: 'ISS (ZARYA)',
      start: '2026-08-08T16:12:00Z',
      max_elevation_time: '2026-08-08T16:15:00Z',
      end: '2026-08-08T16:18:00Z',
      max_elevation_deg: 63,
      elevation_start_deg: 10,
      elevation_end_deg: 10,
      azimuth_start_deg: 312,
      azimuth_apex_deg: 225,
      azimuth_end_deg: 133,
      direction_from: 'NW',
      direction_to: 'SE',
      range_km_at_max: 500,
      magnitude: -2.8,
      brightness_label: 'extremely bright — brighter than any star',
      object_blurb: 'The International Space Station.',
      look_instruction: 'Look NW (312°) at 9:42 PM — ISS will pass high overhead.',
    },
  ],
  note: 'Brightness is an estimate.',
}

function mockFetchOk(body: unknown, ok = true) {
  const fn = vi.fn().mockResolvedValue({
    ok,
    status: ok ? 200 : 500,
    json: async () => body,
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => vi.unstubAllGlobals())

describe('fetchPasses — URL contract', () => {
  it('hits /api/passes with lat & lon', async () => {
    const fetchMock = mockFetchOk(RESPONSE)
    await fetchPasses(12.97, 77.59)
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/passes?lat=12.97&lon=77.59')
  })

  it('appends the date when given', async () => {
    const fetchMock = mockFetchOk(RESPONSE)
    await fetchPasses(40.71, -74.01, '2026-08-09')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/passes?lat=40.71&lon=-74.01&date=2026-08-09')
  })
})

describe('fetchPasses — honesty layering', () => {
  it('passes a live engine envelope through, live: true', async () => {
    mockFetchOk(RESPONSE)
    const { data, live } = await fetchPasses(12.97, 77.59)
    expect(live).toBe(true)
    expect(data).toEqual(RESPONSE)
  })

  it('surfaces an engine available:false envelope with its note (never masks it)', async () => {
    const failure = {
      ...RESPONSE,
      available: false,
      passes: [],
      note: 'Could not fetch fresh orbital elements right now — celestrak unreachable',
    }
    mockFetchOk(failure)
    const { data, live } = await fetchPasses(12.97, 77.59)
    expect(live).toBe(true)
    expect(data.available).toBe(false)
    expect(data.note).toContain('fresh orbital elements')
  })

  it('surfaces a reachable engine HTTP error (never masks it with the sample)', async () => {
    const fn = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({}),
    })
    vi.stubGlobal('fetch', fn)
    const { data, live } = await fetchPasses(12.97, 77.59)
    expect(live).toBe(true)
    expect(data.available).toBe(false)
    expect(data.note).toContain('engine error (HTTP 500)')
    expect(data.passes).toEqual([])
  })

  it('carries the engine detail on a 4xx response', async () => {
    const fn = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'lat 99 out of range (-90..90)' }),
    })
    vi.stubGlobal('fetch', fn)
    const { data, live } = await fetchPasses(99, 0)
    expect(live).toBe(true)
    expect(data.note).toContain('lat 99 out of range')
  })

  it('falls back to the clearly labelled sample only when the backend is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const { data, live } = await fetchPasses(12.97, 77.59)
    expect(live).toBe(false)
    expect(data.available).toBe(true)
    expect(data.passes.length).toBeGreaterThan(0)
    expect(data.note).toContain('Sample')
  })
})

describe('samplePasses — offline mirror', () => {
  it('anchors to the location local date and evening', () => {
    const now = new Date('2026-08-08T12:00:00Z')
    const data = samplePasses(12.97, 77.59, now) // UTC+5:08 → local evening of Aug 8
    expect(data.date).toBe('2026-08-08')
    expect(data.latitude).toBe(12.97)
  })

  it('sorts passes by start time, ISO-Z timestamps, ISS present and brightest', () => {
    const data = samplePasses(12.97, 77.59, new Date('2026-08-08T12:00:00Z'))
    const starts = data.passes.map((p) => p.start)
    expect(starts).toEqual([...starts].sort())
    for (const p of data.passes) {
      expect(p.start.endsWith('Z')).toBe(true)
      expect(p.look_instruction.startsWith('Look ')).toBe(true)
      expect(p.brightness_label).toBeTruthy()
    }
    const iss = data.passes.find((p) => p.norad_id === 25544)
    expect(iss).toBeTruthy()
    const minMag = Math.min(...data.passes.map((p) => p.magnitude))
    expect(iss!.magnitude).toBe(minMag)
  })
})

describe('SkyChart — polar chart', () => {
  const pass = RESPONSE.passes[0]

  it('renders a labelled diagram with the pass arc', () => {
    const html = renderToStaticMarkup(<SkyChart pass={pass} />)
    expect(html).toContain('role="img"')
    expect(html).toContain('ISS (ZARYA)')
    expect(html).toContain('class="sky-arc"')
    expect(html).toContain('overhead')
    expect(html).toContain('>N<')
    expect(html).toContain('>E<')
    expect(html).toContain('>W<')
    expect(html).toContain('63° up') // apex label
    // shape-distinct markers: circle, diamond path, square rect
    expect(html).toContain('class="sky-mark-start"')
    expect(html).toContain('class="sky-mark-apex"')
    expect(html).toContain('class="sky-mark-end"')
  })

  it('renders an empty state when no pass is selected', () => {
    const html = renderToStaticMarkup(<SkyChart pass={null} />)
    expect(html).toContain('No pass selected.')
    expect(html).not.toContain('class="sky-arc"')
  })
})
