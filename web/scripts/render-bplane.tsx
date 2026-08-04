/**
 * Offline render harness for the B-plane figure (dev only — not shipped).
 *
 * Renders BPlaneFigure to static SVG with react-dom/server for each payload shape
 * that stresses the figure differently, inlines the resolved plot CSS, and writes
 * standalone .svg files. This is the dataviz "render it and look at it" step: the
 * palette validator checks colour, not layout, so label collisions and geometry have
 * to be seen. One case swaps in a high-contrast stylesheet, because the
 * `forced-colors: active` rules are a media query this harness cannot trigger.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { createElement } from 'react'
import { writeFileSync } from 'node:fs'
import { BPlaneFigure } from '../src/viz/BPlanePlot'
import type { BPlane, SigmaContour } from '../src/types'

const contours = (a: number, b: number, rot: number): SigmaContour[] =>
  [1, 2, 3].map((level) => ({
    level,
    semi_major_km: a * level,
    semi_minor_km: b * level,
    rotation_deg: rot,
  }))

function payload(over: Partial<BPlane> = {}): BPlane {
  const base: BPlane = {
    available: true,
    event_id: 1,
    secondary_name: 'COSMOS 2251 DEB',
    secondary_norad: 99998,
    tca: '2026-07-31T04:12:07Z',
    miss_bp: { xi: 73.48, zeta: -1.62 },
    miss_norm_km: 73.4902,
    miss_3d_km: 73.4883,
    vrel_kms: 0.134,
    hbr_km: 0.005,
    miss_inside_hbr: false,
    ellipse: { semi_major_km: 0.99998, semi_minor_km: 0.5, rotation_deg: 0.3928 },
    sigma_levels: contours(0.99998, 0.5, 0.3928),
    mahalanobis_sigma: 73.49,
    sigma_contour_containing_miss: null,
    axes_rsw: { xi: [-0, 0.99994, 0.01104], zeta: [-0.78393, 0.00685, -0.62081] },
    pc: 0,
    realism: {
      factor: 2,
      ellipse: { semi_major_km: 1.41417, semi_minor_km: 0.70711, rotation_deg: 0.3928 },
      sigma_levels: contours(1.41417, 0.70711, 0.3928),
      pc: 0,
      mahalanobis_sigma: 51.97,
    },
    note:
      'Covariance is the documented fixed diagonal RSW assumption (engine/pc.py); ' +
      'realism.pc inflates it by k for operational realism (Foster/Hall).',
  }
  return { ...base, ...over }
}

/** The plot CSS with var() resolved, so a standalone SVG renders identically. */
const CSS = `
.bp-bg { fill: #0a0f1e; stroke: rgba(122,152,222,0.14); stroke-width: 1; }
.bp-grid { stroke: rgba(122,152,222,0.14); stroke-width: 0.5; }
.bp-axis { stroke: rgba(122,152,222,0.3); stroke-width: 0.75; }
.bp-tick { fill: #6c7896; font-family: monospace; font-size: 8px; }
.bp-axis-title { fill: #6c7896; font-family: monospace; font-size: 8.5px; }
.bp-sigma { fill: none; stroke-width: 2; }
.bp-sigma-1 { stroke: #9ec5f4; }
.bp-sigma-2 { stroke: #5598e7; }
.bp-sigma-3 { stroke: #256abf; }
.bp-realism { fill: none; stroke: #256abf; stroke-width: 1.5; stroke-dasharray: 5 4; opacity: 0.75; }
.bp-sigma-blob { fill: #5598e7; fill-opacity: 0.3; stroke: #9ec5f4; stroke-width: 1.5; }
.bp-leader { stroke: rgba(122,152,222,0.3); stroke-width: 1; }
.bp-primary { fill: #a9b5d1; }
.bp-hbr { fill: none; stroke: #ff6b6b; stroke-width: 2; }
.bp-hbr-hit { fill: none; stroke: transparent; stroke-width: 14; }
.bp-missline { stroke: #f5b04c; stroke-width: 1; opacity: 0.45; }
.bp-miss-ring { fill: #0a0f1e; }
.bp-miss { fill: #f5b04c; }
.bp-miss-label { fill: #a9b5d1; font-family: monospace; font-size: 9px; }
.bp-label-bg { fill: #0a0f1e; fill-opacity: 0.82; }
.bp-label-halo { fill: none; stroke: #0a0f1e; stroke-width: 3.5; stroke-linejoin: round; font-family: monospace; font-size: 9px; }
.bp-hit { fill: transparent; }
`

/**
 * Windows high-contrast emulation: every hue collapses to one system colour, so the
 * validated σ ramp stops separating the contours and the `forced-colors: active`
 * block in dashboard.css must carry the encoding on dash patterns alone. Rendered as
 * its own case because that block is a media query the harness cannot trigger.
 */
const CSS_FORCED = `
.bp-bg { fill: #000; stroke: #fff; stroke-width: 1; }
.bp-grid { stroke: #fff; stroke-width: 0.5; opacity: 0.35; }
.bp-axis { stroke: #fff; stroke-width: 0.75; }
.bp-tick { fill: #fff; font-family: monospace; font-size: 8px; }
.bp-axis-title { fill: #fff; font-family: monospace; font-size: 8.5px; }
.bp-sigma { fill: none; stroke: #fff; stroke-width: 2; }
.bp-sigma-1 { stroke-dasharray: none; }
.bp-sigma-2 { stroke-dasharray: 7 3; }
.bp-sigma-3 { stroke-dasharray: 2 3; }
.bp-realism { fill: none; stroke: #fff; stroke-width: 1.5; stroke-dasharray: 11 3 2 3; }
.bp-sigma-blob { fill: #fff; fill-opacity: 0.3; stroke: #fff; stroke-width: 1.5; }
.bp-leader { stroke: #fff; stroke-width: 1; }
.bp-primary { fill: #fff; }
.bp-hbr { fill: none; stroke: #fff; stroke-width: 3; }
.bp-hbr-hit { fill: none; stroke: transparent; stroke-width: 14; }
.bp-missline { stroke: #fff; stroke-width: 1; opacity: 0.45; }
.bp-miss-ring { fill: #000; }
.bp-miss { fill: #fff; }
.bp-miss-label { fill: #fff; font-family: monospace; font-size: 9px; }
.bp-label-bg { fill: #000; fill-opacity: 0.82; }
.bp-label-halo { fill: none; stroke: #000; stroke-width: 3.5; stroke-linejoin: round; font-family: monospace; font-size: 9px; }
.bp-hit { fill: transparent; }
`

const HBR_CASE = payload({
  miss_bp: { xi: 0.0032, zeta: -0.0018 },
  miss_norm_km: 0.00367,
  miss_3d_km: 0.0041,
  miss_inside_hbr: true,
  mahalanobis_sigma: 0.0073,
  sigma_contour_containing_miss: 1,
  pc: 2.4e-5,
  ellipse: { semi_major_km: 0.02, semi_minor_km: 0.011, rotation_deg: -31.4 },
  sigma_levels: contours(0.02, 0.011, -31.4),
  realism: {
    factor: 2,
    ellipse: { semi_major_km: 0.0283, semi_minor_km: 0.0156, rotation_deg: -31.4 },
    sigma_levels: contours(0.0283, 0.0156, -31.4),
    pc: 1.2e-5,
    mahalanobis_sigma: 0.0052,
  },
})

const cases: [string, BPlane, 'full' | 'encounter', string?][] = [
  // The real event: a 73 km miss against a 3 km 3σ contour.
  ['far', payload(), 'full'],
  // The same event in "zoom σ" — contours resolve, the miss goes off scale and is
  // drawn as a bearing rather than clamped to the edge.
  ['far-sigma', payload(), 'encounter'],
  // A genuinely close pass — contours resolve, HBR still sub-mark, no zoom offered
  // (zooming to the cross-section cannot help while the miss is 300 HBRs away).
  [
    'close',
    payload({
      miss_bp: { xi: 1.42, zeta: -0.86 },
      miss_norm_km: 1.66,
      miss_3d_km: 1.71,
      mahalanobis_sigma: 2.31,
      sigma_contour_containing_miss: 3,
      pc: 1.8e-5,
      vrel_kms: 9.886,
    }),
    'full',
  ],
  // Inside the hard-body radius: the collision case. In "fit all" the near field is
  // a speck at the origin, so the figure offers "zoom HBR".
  ['hbr', HBR_CASE, 'full'],
  // The same collision case zoomed to the cross-section: HBR and miss resolve, the
  // outer contours leave the frame entirely and drop out of the legend.
  ['hbr-zoom', HBR_CASE, 'encounter'],
  // The close pass with every hue collapsed, as Windows high contrast renders it:
  // the σ levels must still be tellable apart on dash pattern alone.
  [
    'close-forced',
    payload({
      miss_bp: { xi: 1.42, zeta: -0.86 },
      miss_norm_km: 1.66,
      miss_3d_km: 1.71,
      mahalanobis_sigma: 2.31,
      sigma_contour_containing_miss: 3,
      pc: 1.8e-5,
      vrel_kms: 9.886,
    }),
    'full',
    CSS_FORCED,
  ],
]

for (const [name, bp, initialMode, css = CSS] of cases) {
  const html = renderToStaticMarkup(createElement(BPlaneFigure, { bp, live: true, initialMode }))
  const m = html.match(/<svg viewBox="0 0 (\d+) (\d+)"[\s\S]*?<\/svg>/)
  if (!m) throw new Error(`no plot svg found for ${name}`)
  // Rasterize at 2× the viewBox so 8px type is legible in the PNG.
  const [w, h] = [Number(m[1]) * 2, Number(m[2]) * 2]
  const svg = m[0].replace(
    /^<svg /,
    `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" `,
  ).replace(/>/, `><style>${css}</style>`)
  writeFileSync(`/tmp/bplane-${name}.svg`, svg)
  console.log(`${name}: ${w}×${h}, ${svg.length} bytes`)
  // Report the header/legend/note text too, so collisions in the HTML chrome show.
  // The long <desc> in the middle is the screen-reader summary and is checked by the
  // unit tests, so print the head (controls + stat row) and the tail (legend + note),
  // which are the parts that change with framing.
  const text = html
    .replace(/<style[\s\S]*?<\/style>/g, '')
    .replace(/<svg[\s\S]*?<\/svg>/g, ' ⟨plot⟩ ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  console.log(`  chrome: ${text}`)
}
