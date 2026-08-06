import { useEffect, useId, useMemo, useState } from 'react'
import type { BPlane, ScoredConjunction, SigmaContour } from '../types'
import { fetchBPlane } from '../lib/api'

/**
 * B-plane plot — the canonical conjunction-assessment diagram (§5.2).
 *
 * The B-plane is the plane perpendicular to the relative-velocity vector at TCA.
 * Everything an analyst needs to judge a conjunction lives in it: the miss point,
 * the hard-body-radius circle, and the covariance contours. The plot renders the
 * exact projection the engine computed Pc from (`engine/viz/bplane.py`), so the
import Explainer from '../components/Explainer'
 * picture and the probability beside it can never disagree.
 *
 * Two honest scales, because the quantities routinely span two or three orders of
 * magnitude and no single frame resolves them. "fit all" contains every feature;
 * "zoom" fits whichever feature the first framing crushes — the covariance region
 * when the miss is tens of kilometres away, or the collision cross-section when
 * the covariance dwarfs it. Nothing is ever rescaled to look bigger than it is:
 * a feature too small to draw honestly is drawn once and labelled, and a mark
 * outside the frame is shown as a bearing rather than clamped to the edge.
 */

/** ξ/ζ basis vectors are reported in RSW, so the axes can be labelled honestly. */
const RSW_NAMES = ['radial', 'in-track', 'cross-track'] as const

/** Plot geometry in SVG user units; the <svg> scales responsively via viewBox.
 *  Tick labels and axis titles live in the gutters, never inside the frame — the
 *  ξ/ζ axes run through the origin, so in-frame labels would collide with them.
 *  The left gutter is the widest because it carries a rotated title *and* the
 *  y-tick labels; the right and top only need to clear a centred edge label. */
const PLOT = 340
const PAD_L = 52
const PAD_R = 20
const PAD_T = 16
const PAD_B = 46
const TOTAL_W = PAD_L + PLOT + PAD_R
const TOTAL_H = PAD_T + PLOT + PAD_B
const FRAME_R = PAD_L + PLOT
const FRAME_B = PAD_T + PLOT

type Mode = 'encounter' | 'full'
type View = 'plot' | 'table'
interface Tip {
  x: number
  y: number
  title: string
  rows: [string, string][]
}

/** km with a decimal count that suits the magnitude; sub-km reads in metres. */
function fmtKm(v: number): string {
  const a = Math.abs(v)
  if (a === 0) return '0'
  if (a < 1) return `${(v * 1000).toFixed(a < 0.01 ? 1 : 0)} m`
  return `${v.toFixed(a >= 10 ? 1 : 2)} km`
}

/** Axis tick label — plain km at the precision the tick step needs (the axis title
 *  carries the unit). Derived from the step, not the value, so 0.005 and 0.010 do
 *  not both round to "0.01" on a metres-scale plot. */
function fmtTick(v: number, step: number): string {
  const dp = Math.min(4, Math.max(0, -Math.floor(Math.log10(step))))
  return v.toFixed(dp)
}

/** A 1/2/5 × 10ⁿ step giving roughly five gridlines across the plot. */
function niceStep(halfWidth: number): number {
  const raw = halfWidth / 2.5
  const mag = 10 ** Math.floor(Math.log10(raw))
  const norm = raw / mag
  return (norm >= 5 ? 5 : norm >= 2 ? 2 : 1) * mag
}

/** Describe a B-plane axis by its dominant RSW component ("mostly cross-track"). */
function describeAxis(v: number[]): string {
  const norm = Math.hypot(...v) || 1
  let i = 0
  for (let k = 1; k < v.length; k++) if (Math.abs(v[k]) > Math.abs(v[i])) i = k
  const frac = Math.abs(v[i]) / norm
  const qual = frac > 0.92 ? '' : frac > 0.6 ? 'mostly ' : 'partly '
  return `${qual}${RSW_NAMES[i]}`
}

/**
 * Place a mark's direct label radially outward from the origin, so it moves away
 * from the crowded centre of the plot instead of into it — flipping back only when
 * outward would leave the frame. `pad` is the radial distance from the mark, which
 * callers raise to clear a ring drawn around the origin. Width is estimated from the
 * character count, which is exact enough for the monospace label face.
 */
function placeLabel(
  x: number,
  y: number,
  ux: number,
  uz: number,
  text: string,
  pad = 13,
): { x: number; y: number; anchor: 'start' | 'end' } {
  const w = text.length * 5.4
  const outward: 'start' | 'end' = ux >= 0 ? 'start' : 'end'
  // Offset along the bearing, plus a horizontal gap so the text never abuts the
  // mark, and a baseline nudge so it reads vertically centred on that point.
  const dx = ux * pad + (ux >= 0 ? 4 : -4)
  const lx = x + dx
  const fits = outward === 'start' ? lx + w <= FRAME_R - 4 : lx - w >= PAD_L + 4
  const anchor = fits ? outward : outward === 'start' ? 'end' : 'start'
  let ly = y - uz * pad + 3.2
  if (ly > FRAME_B - 5) ly = FRAME_B - 5
  if (ly < PAD_T + 10) ly = PAD_T + 10
  return { x: fits ? lx : x - dx, y: ly, anchor }
}

/**
 * Is any part of a contour's curve inside the plot frame?
 *
 * The frame and every contour are centred on the same origin, so the curve is
 * entirely off screen exactly when all four frame corners lie inside the ellipse —
 * the frame is then wholly enclosed and the curve passes outside it on every side.
 * Both shapes are convex and centrally symmetric, so testing the two distinct
 * diagonals settles all four corners. A contour that *partly* overflows stays: an
 * arc running off the edge reads correctly as "wider than this view".
 *
 * @param half half-width of the frame in km (the plot is square)
 */
function contourVisible(c: SigmaContour, half: number): boolean {
  const t = (c.rotation_deg * Math.PI) / 180
  const [ct, st] = [Math.cos(t), Math.sin(t)]
  // Worst case over the corners (±half, ±half): the largest value of the ellipse's
  // quadratic form, which exceeds 1 when that corner is outside the curve.
  let worst = 0
  for (const s of [1, -1]) {
    const u = half * ct + s * half * st
    const v = -half * st + s * half * ct
    worst = Math.max(worst, (u / c.semi_major_km) ** 2 + (v / c.semi_minor_km) ** 2)
  }
  return worst > 1
}

/** An 8-way arrow glyph for a bearing, so an off-scale mark states its direction
 *  in text and not only in geometry. ζ points up, hence the sign on the angle. */
function bearingArrow(ux: number, uz: number): string {
  const deg = (Math.atan2(uz, ux) * 180) / Math.PI
  const i = Math.round(((deg + 360) % 360) / 45) % 8
  return ['→', '↗', '↑', '↖', '←', '↙', '↓', '↘'][i]
}

/**
 * A direct label over the plot, on its own surface scrim.
 *
 * A stroke-only halo pass alone is not enough: the stroke follows the glyphs, so a
 * mark crossing the label shows through the word spaces. A rounded scrim rect closes
 * those gaps, and the halo stays on top of it to keep the glyph edges crisp. Width is
 * estimated from the character count, exact enough for the monospace label face.
 * `paint-order: stroke` would express the halo more tersely but is not honoured by
 * every SVG rasterizer, and this figure is verified by rasterizing it.
 */
function Label({
  x,
  y,
  anchor,
  children,
}: {
  x: number
  y: number
  anchor: 'start' | 'middle' | 'end'
  children: string
}) {
  const w = children.length * 5.4
  const bx = anchor === 'start' ? x - 3 : anchor === 'end' ? x - w - 3 : x - w / 2 - 3
  return (
    <>
      <rect x={bx} y={y - 9} width={w + 6} height={12.5} rx="2.5" className="bp-label-bg" />
      <text x={x} y={y} textAnchor={anchor} className="bp-label-halo" aria-hidden="true">
        {children}
      </text>
      <text x={x} y={y} textAnchor={anchor} className="bp-miss-label">
        {children}
      </text>
    </>
  )
}

/**
 * Container: fetches the encounter plane for an event and hands it to the figure.
 * Kept separate so the figure is a pure function of its payload — that is what
 * makes the plot renderable (and inspectable) outside a browser.
 */
export default function BPlanePlot({ event }: { event: ScoredConjunction }) {
  const [bp, setBp] = useState<BPlane | null>(null)
  const [live, setLive] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let mounted = true
    setLoading(true)
    fetchBPlane(event).then((res) => {
      if (!mounted) return
      setBp(res.data)
      setLive(res.live)
      setLoading(false)
    })
    return () => {
      mounted = false
    }
  }, [event])

  if (!bp) {
    return loading ? (
      <div className="bp-loading mono">Computing encounter plane…</div>
    ) : (
      <div className="panel-empty">B-plane unavailable for this event.</div>
    )
  }
  // On refetch the previous figure is held at reduced opacity rather than
  // replaced by a skeleton — no layout jump between events.
  return <BPlaneFigure bp={bp} live={live} stale={loading} />
}

export function BPlaneFigure({
  bp,
  live,
  stale = false,
  initialMode = 'full',
}: {
  bp: BPlane
  live: boolean
  stale?: boolean
  /** Opening framing. Exposed so the offline render harness can inspect the
   *  "fit σ" branch, where the miss falls outside the frame. */
  initialMode?: Mode
}) {
  const [mode, setMode] = useState<Mode>(initialMode)
  const [view, setView] = useState<View>('plot')
  const [tip, setTip] = useState<Tip | null>(null)
  const uid = useId()
  // useId emits colons, which are legal in an id but awkward inside a url(#…)
  // reference; strip them for the clip-path id specifically.
  const clipId = `bpclip${uid.replace(/[^a-zA-Z0-9_-]/g, '')}`

  /**
   * Plot scale. Both framings are centred on the primary at the origin; they differ
   * only in what they fit. "fit all" contains every feature. "zoom" is offered only
   * when the first framing genuinely crushes one of them, and it fits whichever one
   * that is: the covariance region when the miss is far outside it, or the collision
   * cross-section when the covariance is orders of magnitude larger.
   */
  const geom = useMemo(() => {
    const { xi, zeta } = bp.miss_bp
    const missR = Math.hypot(xi, zeta)
    const outer = Math.max(
      bp.sigma_levels[bp.sigma_levels.length - 1]?.semi_major_km ?? 0,
      bp.realism.sigma_levels[bp.realism.sigma_levels.length - 1]?.semi_major_km ?? 0,
    )
    // The near field: the collision cross-section and the miss point, which sit on
    // top of each other whenever a conjunction is actually dangerous.
    const near = Math.max(bp.hbr_km, missR)
    const fullHalf = Math.max(missR, outer, bp.hbr_km * 3) * 1.18
    const zoom: 'sigma' | 'hbr' | null =
      missR > outer * 1.3 ? 'sigma' : near * 8 < outer ? 'hbr' : null
    const zoomHalf = zoom === 'sigma' ? outer * 1.3 : near * 2.6
    const half = mode === 'encounter' && zoom ? zoomHalf : fullHalf
    const px = PLOT / 2 / half // SVG units per km
    const cx = PAD_L + PLOT / 2 // origin, in SVG user units
    const cy = PAD_T + PLOT / 2
    const toX = (k: number) => cx + k * px
    const toY = (k: number) => cy - k * px // ζ points up
    return { xi, zeta, missR, outer, zoom, half, px, cx, cy, toX, toY }
  }, [bp, mode])

  const step = niceStep(geom.half)
  const ticks: number[] = []
  for (let v = step; v <= geom.half * 1.0001; v += step) ticks.push(v)

  const xiName = describeAxis(bp.axes_rsw.xi)
  const zetaName = describeAxis(bp.axes_rsw.zeta)
  const analyticOuter = bp.sigma_levels[bp.sigma_levels.length - 1]
  const realismOuter = bp.realism.sigma_levels[bp.realism.sigma_levels.length - 1]
  const missOnScale = geom.missR <= geom.half
  // Three 2px rings need room to read as three rings. Scaled to a 73 km miss, a
  // 3 km covariance is a speck — which is the honest picture of a safe pass, but
  // stacked contours there would be one blob. Below the threshold the uncertainty
  // is drawn once, as a region, and labelled; "fit σ" resolves the full set.
  const contoursLegible = geom.outer * geom.px >= 16
  // The hard-body radius is metres against a kilometres-wide plot, so it is often
  // finer than a pixel. It only informs when it is clearly larger than the marks it
  // contains — a 3px ring around a 5px miss dot would read as a decoration on the
  // dot, not as a cross-section enclosing it. Below that it is annotated in the
  // legend and the table instead of being drawn at a size it does not have.
  const hbrPx = bp.hbr_km * geom.px
  const hbrResolvable = hbrPx >= 10
  // When the miss is inside (or near) the hard-body radius, the miss marker and the
  // primary are unresolvably close at any scale that shows the covariance — a miss
  // inside the HBR is by definition less than one HBR from the origin. Drawing both
  // yields a crescent artifact, not information; the crossed axes already pin the
  // origin, so the primary marker stands down and the legend says where it went.
  const primaryVisible = geom.missR * geom.px >= 9
  // The miss marker's surface ring exists to separate it from a contour it crosses.
  // With the HBR circle drawn close by it would instead take a bite out of the
  // collision cross-section — and a miss that near the origin sits inside every
  // contour, with nothing to separate from. So the ring stands down there.
  const missRingClear = !hbrResolvable || Math.abs(geom.missR * geom.px - hbrPx) > 9
  // A contour large enough to enclose the whole frame has no arc on screen at all.
  // Zooming to the collision cross-section does exactly that to the outer contours.
  // Drawing them anyway would add invisible focusable elements and legend keys for
  // marks that are not there, so they drop out of the figure and are called out in
  // the legend instead — the table still carries every contour.
  const inFrame = (c: SigmaContour) => contourVisible(c, geom.half)
  const drawnSigmas = bp.sigma_levels.filter(inFrame)
  const hiddenSigmas = bp.sigma_levels.filter((c) => !inFrame(c)).map((c) => c.level)
  const realismDrawn = !!realismOuter && inFrame(realismOuter)
  const hbrTip = (): Tip => ({
    x: geom.cx,
    y: geom.toY(bp.hbr_km),
    title: 'Hard-body radius',
    rows: [
      ['radius', fmtKm(bp.hbr_km)],
      ['in-plane miss', fmtKm(bp.miss_norm_km)],
      ['miss inside', bp.miss_inside_hbr ? 'YES — collision geometry' : 'no'],
    ],
  })
  /* Drawn as one node used at one of two z-positions: above the miss marker when
     the miss is inside it (so the cross-section reads as a circle around the miss
     rather than a crescent behind it), below otherwise. The `fill: none` stroke is
     2px, so a wider transparent companion carries the hit target. */
  const hbrCircle = (
    <g key="hbr">
      <circle cx={geom.cx} cy={geom.cy} r={hbrPx} className="bp-hbr" />
      <circle
        cx={geom.cx}
        cy={geom.cy}
        r={hbrPx}
        className="bp-hbr-hit"
        tabIndex={0}
        aria-label={`Hard-body radius ${(bp.hbr_km * 1000).toFixed(0)} metres, the collision cross-section — the miss is ${bp.miss_inside_hbr ? 'inside it' : 'outside it'}`}
        onMouseEnter={() => setTip(hbrTip())}
        onFocus={() => setTip(hbrTip())}
        onBlur={() => setTip(null)}
      />
    </g>
  )
  // Unit bearing of the miss, used to push its label radially outward.
  const ux = geom.missR > 0 ? geom.xi / geom.missR : 1
  const uz = geom.missR > 0 ? geom.zeta / geom.missR : 0
  const missLabel = `miss ${fmtKm(bp.miss_norm_km)}`
  // Push the label clear of the hard-body ring when the miss sits inside it —
  // otherwise the text is set *on* the cross-section it is meant to sit within.
  const missLabelPad =
    hbrResolvable && bp.miss_inside_hbr
      ? Math.max(13, hbrPx - geom.missR * geom.px + 11)
      : 13
  const missLabelPos = placeLabel(
    geom.toX(geom.xi),
    geom.toY(geom.zeta),
    ux,
    uz,
    missLabel,
    missLabelPad,
  )
  // Put the collapsed-uncertainty label on the diagonal furthest from the miss
  // bearing: away from the miss vector, and never along either axis rule — which a
  // purely vertical or horizontal leader would be for an axis-aligned encounter.
  const leader = [
    [0.7071, 0.7071],
    [0.7071, -0.7071],
    [-0.7071, 0.7071],
    [-0.7071, -0.7071],
  ].reduce((best, d) => (d[0] * ux + d[1] * uz < best[0] * ux + best[1] * uz ? d : best))

  const missTip: Tip = {
    x: geom.toX(geom.xi),
    y: geom.toY(geom.zeta),
    title: 'Miss point at TCA',
    rows: [
      ['ξ', fmtKm(geom.xi)],
      ['ζ', fmtKm(geom.zeta)],
      ['in-plane miss', fmtKm(bp.miss_norm_km)],
      ['uncertainty', `${bp.mahalanobis_sigma.toFixed(2)}σ out`],
      ['Pc', bp.pc.toExponential(2)],
    ],
  }

  const contourTip = (c: SigmaContour, kind: 'analytic' | 'realism'): Tip => ({
    x: geom.cx,
    y: geom.toY(Math.max(c.semi_major_km, geom.half * 0.06)),
    title: kind === 'analytic' ? `${c.level}σ covariance contour` : `${c.level}σ · k=${bp.realism.factor} realism`,
    rows: [
      ['semi-major', fmtKm(c.semi_major_km)],
      ['semi-minor', fmtKm(c.semi_minor_km)],
      ['orientation', `${c.rotation_deg.toFixed(1)}°`],
      ['miss sits at', `${(kind === 'analytic' ? bp.mahalanobis_sigma : bp.realism.mahalanobis_sigma).toFixed(2)}σ`],
    ],
  })

  return (
    <div className={`bplane${stale ? ' bp-stale' : ''}`}>
      <div className="bp-head">
        <span className="eyebrow" style={{ fontSize: '0.6rem' }}>
          encounter plane · B-plane at TCA
        </span>
        <span className={`chip ${live ? 'good' : 'warn'}`} style={{ fontSize: '0.58rem' }}>
          {live ? 'ENGINE' : 'SAMPLE'}
        </span>
        <div className="bp-toggles">
          {geom.zoom && (
            <div className="bp-seg" role="group" aria-label="Plot scale">
              {(['full', 'encounter'] as Mode[]).map((m) => (
                <button
                  key={m}
                  className={`bp-seg-btn ${mode === m ? 'active' : ''}`}
                  aria-pressed={mode === m}
                  onClick={() => {
                    setMode(m)
                    setTip(null)
                  }}
                >
                  {m === 'full' ? 'fit all' : geom.zoom === 'sigma' ? 'zoom σ' : 'zoom HBR'}
                </button>
              ))}
            </div>
          )}
          <div className="bp-seg" role="group" aria-label="View as plot or table">
            {(['plot', 'table'] as View[]).map((v) => (
              <button
                key={v}
                className={`bp-seg-btn ${view === v ? 'active' : ''}`}
                aria-pressed={view === v}
                onClick={() => setView(v)}
              >
                {v}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Headline: the miss in sigmas. The plot's whole job is to make this legible —
          a 3 km miss under a 1 km covariance is a 3σ event; the same miss under a
          5 km covariance is not. */}
      <div className="bp-stats">
        <div className="bp-hero">
          <span className={`bp-hero-v ${bp.mahalanobis_sigma < 3 ? 'danger-text' : ''}`}>
            {bp.mahalanobis_sigma.toFixed(2)}σ
          </span>
          <span className="bp-hero-l">
            miss sits{' '}
            {bp.sigma_contour_containing_miss === null
              ? 'beyond the 3σ contour'
              : `inside the ${bp.sigma_contour_containing_miss}σ contour`}
          </span>
        </div>
        <div className="bp-substats">
          <div className="bp-sub">
            <span className="bp-sub-v mono">{fmtKm(bp.miss_norm_km)}</span>
            <span className="bp-sub-l">in-plane miss</span>
          </div>
          <div className="bp-sub">
            <span className="bp-sub-v mono">{bp.pc.toExponential(2)}</span>
            <span className="bp-sub-l">Pc · analytic</span>
          </div>
          <div className="bp-sub">
            <span className="bp-sub-v mono">{bp.realism.pc.toExponential(2)}</span>
            <span className="bp-sub-l">Pc · k={bp.realism.factor} realism</span>
          </div>
          <div className="bp-sub">
            <span className="bp-sub-v mono">{(bp.hbr_km * 1000).toFixed(0)} m</span>
            <span className="bp-sub-l">hard-body radius</span>
          </div>
        </div>
      </div>

      {view === 'plot' && (
        <div className="bp-plotwrap">
          <svg
            viewBox={`0 0 ${TOTAL_W} ${TOTAL_H}`}
            className="bp-svg"
            role="group"
            aria-labelledby={`${uid}-t`}
            aria-describedby={`${uid}-d`}
            onMouseLeave={() => setTip(null)}
          >
            <title id={`${uid}-t`}>
              {`B-plane encounter diagram — ${bp.secondary_name} at TCA ${bp.tca}`}
            </title>
            <desc id={`${uid}-d`}>
              {`The miss point lies ${bp.miss_norm_km.toFixed(3)} kilometres from the primary in ` +
                `the encounter plane, which is ${bp.mahalanobis_sigma.toFixed(2)} sigma out on the ` +
                `combined uncertainty distribution — ` +
                (bp.sigma_contour_containing_miss === null
                  ? 'beyond the 3 sigma contour. '
                  : `inside the ${bp.sigma_contour_containing_miss} sigma contour. `) +
                `Collision probability ${bp.pc.toExponential(2)} analytic, ` +
                `${bp.realism.pc.toExponential(2)} with the covariance inflated by ` +
                `${bp.realism.factor}. The horizontal axis is ${xiName}; the vertical axis is ` +
                `${zetaName}. Switch to the table view for every number.`}
            </desc>

            <rect x={PAD_L} y={PAD_T} width={PLOT} height={PLOT} className="bp-bg" rx="8" />

            {/* Contours are clipped to the frame, so a contour wider than the current
                view runs off the edge instead of painting over the tick gutters. */}
            <defs>
              <clipPath id={clipId}>
                <rect x={PAD_L} y={PAD_T} width={PLOT} height={PLOT} rx="8" />
              </clipPath>
            </defs>

            {/* Recessive graticule — solid hairlines, one shade off the surface. */}
            {ticks.map((t) => (
              <g key={`g${t}`}>
                <line x1={geom.toX(t)} y1={PAD_T} x2={geom.toX(t)} y2={FRAME_B} className="bp-grid" />
                <line x1={geom.toX(-t)} y1={PAD_T} x2={geom.toX(-t)} y2={FRAME_B} className="bp-grid" />
                <line x1={PAD_L} y1={geom.toY(t)} x2={FRAME_R} y2={geom.toY(t)} className="bp-grid" />
                <line x1={PAD_L} y1={geom.toY(-t)} x2={FRAME_R} y2={geom.toY(-t)} className="bp-grid" />
              </g>
            ))}

            {/* ξ / ζ axes through the primary at the origin. */}
            <line x1={PAD_L} y1={geom.cy} x2={FRAME_R} y2={geom.cy} className="bp-axis" />
            <line x1={geom.cx} y1={PAD_T} x2={geom.cx} y2={FRAME_B} className="bp-axis" />

            <g clipPath={`url(#${clipId})`}>
              {/* Realism contour (outermost only): the same geometry with the
                  covariance inflated by k. Dashed *here* is meaningful — it is a
                  projection under a different assumption, not a grid. */}
              {contoursLegible && realismOuter && realismDrawn && (
                <ellipse
                  cx={geom.cx}
                  cy={geom.cy}
                  rx={realismOuter.semi_major_km * geom.px}
                  ry={realismOuter.semi_minor_km * geom.px}
                  transform={`rotate(${-realismOuter.rotation_deg} ${geom.cx} ${geom.cy})`}
                  className="bp-realism"
                  tabIndex={0}
                  aria-label={`3 sigma contour with covariance inflated by ${bp.realism.factor}, semi-major ${fmtKm(realismOuter.semi_major_km)}`}
                  onMouseEnter={() => setTip(contourTip(realismOuter, 'realism'))}
                  onFocus={() => setTip(contourTip(realismOuter, 'realism'))}
                  onBlur={() => setTip(null)}
                />
              )}

              {/* 3σ → 1σ covariance contours, drawn outermost-first so the darkest
                  (1σ) sits on top. Validated single-hue ordinal ramp. */}
              {contoursLegible &&
                [...drawnSigmas].reverse().map((c) => (
                  <ellipse
                    key={c.level}
                    cx={geom.cx}
                    cy={geom.cy}
                    rx={c.semi_major_km * geom.px}
                    ry={c.semi_minor_km * geom.px}
                    /* SVG y grows downward, so a mathematical CCW angle rotates CW here. */
                    transform={`rotate(${-c.rotation_deg} ${geom.cx} ${geom.cy})`}
                    className={`bp-sigma bp-sigma-${c.level}`}
                    tabIndex={0}
                    aria-label={`${c.level} sigma covariance contour, semi-major ${fmtKm(c.semi_major_km)}, semi-minor ${fmtKm(c.semi_minor_km)}`}
                    onMouseEnter={() => setTip(contourTip(c, 'analytic'))}
                    onFocus={() => setTip(contourTip(c, 'analytic'))}
                    onBlur={() => setTip(null)}
                  />
                ))}
            </g>

            {/* Uncertainty too small to resolve at this scale: one filled region at
                3σ with a leader line, rather than three rings drawn as a smudge. */}
            {!contoursLegible && analyticOuter && (
              <>
                <ellipse
                  cx={geom.cx}
                  cy={geom.cy}
                  rx={Math.max(analyticOuter.semi_major_km * geom.px, 2.5)}
                  ry={Math.max(analyticOuter.semi_minor_km * geom.px, 2)}
                  transform={`rotate(${-analyticOuter.rotation_deg} ${geom.cx} ${geom.cy})`}
                  className="bp-sigma-blob"
                  tabIndex={0}
                  aria-label={`Combined uncertainty region, 3 sigma semi-major ${fmtKm(analyticOuter.semi_major_km)} — too small to resolve at this scale`}
                  onMouseEnter={() => setTip(contourTip(analyticOuter, 'analytic'))}
                  onFocus={() => setTip(contourTip(analyticOuter, 'analytic'))}
                  onBlur={() => setTip(null)}
                />
                <line
                  x1={geom.cx + leader[0] * 9}
                  y1={geom.cy - leader[1] * 9}
                  x2={geom.cx + leader[0] * 30}
                  y2={geom.cy - leader[1] * 30}
                  className="bp-leader"
                />
                <Label
                  {...placeLabel(
                    geom.cx + leader[0] * 30,
                    geom.cy - leader[1] * 30,
                    leader[0],
                    leader[1],
                    `3σ ≈ ${fmtKm(analyticOuter.semi_major_km)}`,
                  )}
                >
                  {`3σ ≈ ${fmtKm(analyticOuter.semi_major_km)}`}
                </Label>
              </>
            )}

            {/* The primary, at the origin of the encounter plane. */}
            {primaryVisible && (
              <circle cx={geom.cx} cy={geom.cy} r="3.5" className="bp-primary" />
            )}

            {/* Hard-body radius — the actual collision cross-section. Drawn only
                when it is wider than a few pixels; otherwise it is annotated in
                the legend and the table instead of being drawn at a false size.
                When the miss lies inside it, it is drawn *after* the miss marker
                (below) so the cross-section stays a whole circle around it. */}
            {hbrResolvable && !bp.miss_inside_hbr && hbrCircle}

            {/* The miss vector, origin → miss point. */}
            {missOnScale ? (
              <>
                <line
                  x1={geom.cx}
                  y1={geom.cy}
                  x2={geom.toX(geom.xi)}
                  y2={geom.toY(geom.zeta)}
                  className="bp-missline"
                />
                {/* A 2px surface ring separates the marker from whatever it overlaps. */}
                {missRingClear && (
                  <circle
                    cx={geom.toX(geom.xi)}
                    cy={geom.toY(geom.zeta)}
                    r="7"
                    className="bp-miss-ring"
                  />
                )}
                <circle
                  cx={geom.toX(geom.xi)}
                  cy={geom.toY(geom.zeta)}
                  r="5"
                  className="bp-miss"
                />
                {/* The collision case: the cross-section rides on top so it reads as
                    a circle enclosing the miss, not as a crescent behind it. */}
                {hbrResolvable && bp.miss_inside_hbr && hbrCircle}
                {/* Generous hit target — the mark is 10px, the target ~26px. Focusable,
                    so the keyboard reads exactly what hover shows. */}
                <circle
                  cx={geom.toX(geom.xi)}
                  cy={geom.toY(geom.zeta)}
                  r="13"
                  className="bp-hit"
                  tabIndex={0}
                  aria-label={`Miss point: xi ${fmtKm(geom.xi)}, zeta ${fmtKm(geom.zeta)}, in-plane miss ${fmtKm(bp.miss_norm_km)}, ${bp.mahalanobis_sigma.toFixed(2)} sigma out`}
                  onMouseEnter={() => setTip(missTip)}
                  onFocus={() => setTip(missTip)}
                  onBlur={() => setTip(null)}
                />
                {/* Selective direct label — the one mark that carries the story.
                    Placed radially outward so it leaves the crowded centre, and
                    haloed so it stays readable where it crosses a contour. */}
                <Label {...missLabelPos}>{missLabel}</Label>
              </>
            ) : (
              /* Off scale in "fit σ" mode: show the bearing honestly rather than
                 clamping the marker to the edge, which would misreport position. */
              (() => {
                // Pull back far enough that the arrowhead's own 6px tip stays inside
                // the frame rather than poking through the border.
                const reach = PLOT / 2 - 8
                const ex = geom.cx + ux * reach
                const ey = geom.cy - uz * reach
                const text = `miss ${fmtKm(bp.miss_norm_km)} ${bearingArrow(ux, uz)} off scale`
                // The label is a corner callout, not an offset beside the mark: at
                // this framing the contours fill the middle of the plot, so any
                // label set near the exit point reads back across them. The corner
                // is on the miss's own side horizontally and the far side
                // vertically, which is the emptiest quadrant by construction.
                const anchor: 'start' | 'end' = ux >= 0 ? 'end' : 'start'
                const lx = ux >= 0 ? FRAME_R - 8 : PAD_L + 8
                const above = uz <= 0.2
                const ly = above ? PAD_T + 15 : FRAME_B - 9
                // Leader: from the label's near end (which sits on the frame edge the
                // miss exits through) to the arrowhead, stopping clear of both. That
                // keeps it hugging the edge instead of cutting across the plot.
                const sx = lx
                const sy = ly + (above ? 5 : -11)
                const d = Math.hypot(ex - sx, ey - sy) || 1
                return (
                  <g>
                    <line x1={geom.cx} y1={geom.cy} x2={ex} y2={ey} className="bp-missline" />
                    <line
                      x1={sx}
                      y1={sy}
                      x2={sx + ((ex - sx) / d) * (d - 12)}
                      y2={sy + ((ey - sy) / d) * (d - 12)}
                      className="bp-leader"
                    />
                    {/* An arrowhead along the bearing, not a miss dot: the point is
                        outside the frame, and a round marker at the edge would read
                        as its position. A chevron reads "continues this way". */}
                    <polygon
                      points="-6,-5 6,0 -6,5"
                      className="bp-miss"
                      transform={`translate(${ex} ${ey}) rotate(${(Math.atan2(-uz, ux) * 180) / Math.PI})`}
                    />
                    <circle
                      cx={ex}
                      cy={ey}
                      r="13"
                      className="bp-hit"
                      tabIndex={0}
                      aria-label={`Miss point, off scale in this view: in-plane miss ${fmtKm(bp.miss_norm_km)}, ${bp.mahalanobis_sigma.toFixed(2)} sigma out`}
                      onMouseEnter={() => setTip({ ...missTip, x: ex, y: ey })}
                      onFocus={() => setTip({ ...missTip, x: ex, y: ey })}
                      onBlur={() => setTip(null)}
                    />
                    <Label x={lx} y={ly} anchor={anchor}>
                      {text}
                    </Label>
                  </g>
                )
              })()
            )}


            {/* Axis tick labels — in the gutters, with a short tick mark on the
                frame edge to tie each label to its gridline. They cannot sit beside
                the ξ/ζ axes: those run through the centre of the frame, where the
                contours and the miss vector are. */}
            {ticks.map((t) => (
              <g key={`t${t}`}>
                <g className="bp-axis">
                  <line x1={geom.toX(t)} y1={FRAME_B} x2={geom.toX(t)} y2={FRAME_B + 4} />
                  <line x1={geom.toX(-t)} y1={FRAME_B} x2={geom.toX(-t)} y2={FRAME_B + 4} />
                  <line x1={PAD_L - 4} y1={geom.toY(t)} x2={PAD_L} y2={geom.toY(t)} />
                  <line x1={PAD_L - 4} y1={geom.toY(-t)} x2={PAD_L} y2={geom.toY(-t)} />
                </g>
                <g className="bp-tick">
                  <text x={geom.toX(t)} y={FRAME_B + 14} textAnchor="middle">{fmtTick(t, step)}</text>
                  <text x={geom.toX(-t)} y={FRAME_B + 14} textAnchor="middle">{fmtTick(-t, step)}</text>
                  <text x={PAD_L - 8} y={geom.toY(t) + 3} textAnchor="end">{fmtTick(t, step)}</text>
                  <text x={PAD_L - 8} y={geom.toY(-t) + 3} textAnchor="end">{fmtTick(-t, step)}</text>
                </g>
              </g>
            ))}

            {/* Axis titles, named by their dominant RSW component — the in-plane
                orientation is not physical, so this is how a reader orients. */}
            <text
              x={PAD_L + PLOT / 2}
              y={FRAME_B + 30}
              textAnchor="middle"
              className="bp-axis-title"
            >
              ξ · {xiName} · km
            </text>
            <text
              x={11}
              y={PAD_T + PLOT / 2}
              className="bp-axis-title"
              textAnchor="middle"
              transform={`rotate(-90 11 ${PAD_T + PLOT / 2})`}
            >
              ζ · {zetaName} · km
            </text>
          </svg>

          {/* Tooltip — enhances, never gates: every value is also in the table view
              and the stat row above. Positioned in viewBox percentages so it tracks
              the mark at any container width. */}
          {tip && (
            <div
              className="bp-tip"
              role="status"
              style={{
                left: `${(tip.x / TOTAL_W) * 100}%`,
                top: `${(tip.y / TOTAL_H) * 100}%`,
                transform: `translate(${tip.x > TOTAL_W * 0.6 ? '-104%' : '4%'}, ${
                  tip.y > TOTAL_H * 0.6 ? '-104%' : '4%'
                })`,
              }}
            >
              <div className="bp-tip-t">{tip.title}</div>
              {tip.rows.map(([k, v]) => (
                <div key={k} className="bp-tip-r">
                  <span>{k}</span>
                  <span className="mono">{v}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Legend — always present, and the required secondary encoding: the marks
          are never identified by colour alone. It lists exactly what is drawn, so
          the collapsed-uncertainty case does not advertise contours that are absent. */}
      {view === 'plot' && (
        <div className="bp-legend">
          <span className="bp-key">
            <svg width="14" height="14" aria-hidden="true">
              <circle cx="7" cy="7" r="4" className="bp-miss" />
            </svg>
            miss point
            {!missOnScale && <em className="bp-key-note"> · off scale, shown as a bearing</em>}
          </span>
          <span className="bp-key">
            <svg width="14" height="14" aria-hidden="true">
              <circle cx="7" cy="7" r="3" className="bp-primary" />
            </svg>
            primary
            {primaryVisible ? (
              <em className="bp-key-note"> · at the origin</em>
            ) : (
              <em className="bp-key-note"> · at the origin, under the miss point</em>
            )}
          </span>
          {contoursLegible ? (
            <>
              {drawnSigmas.map((c) => (
                <span key={c.level} className="bp-key">
                  <svg width="14" height="14" aria-hidden="true">
                    <ellipse cx="7" cy="7" rx="6" ry="4" className={`bp-sigma bp-sigma-${c.level}`} />
                  </svg>
                  {c.level}σ
                </span>
              ))}
              {realismDrawn && (
                <span className="bp-key">
                  <svg width="14" height="14" aria-hidden="true">
                    <ellipse cx="7" cy="7" rx="6" ry="4" className="bp-realism" />
                  </svg>
                  3σ · k={bp.realism.factor}
                </span>
              )}
              {hiddenSigmas.length > 0 && (
                <span className="bp-key bp-key-note">
                  {hiddenSigmas.join('σ, ')}σ beyond this view — switch to “fit all”
                </span>
              )}
            </>
          ) : (
            <span className="bp-key">
              <svg width="14" height="14" aria-hidden="true">
                <ellipse cx="7" cy="7" rx="5.5" ry="3.5" className="bp-sigma-blob" />
              </svg>
              uncertainty · 3σ {fmtKm(analyticOuter?.semi_major_km ?? 0)}
              <em className="bp-key-note"> · switch to “zoom σ” for all contours</em>
            </span>
          )}
          <span className="bp-key">
            <svg width="14" height="14" aria-hidden="true">
              <circle cx="7" cy="7" r="4.5" className="bp-hbr" />
            </svg>
            hard-body {(bp.hbr_km * 1000).toFixed(0)} m
            {!hbrResolvable && (
              <em className="bp-key-note">
                {geom.zoom === 'hbr' && mode === 'full'
                  ? ' · smaller than a mark at this scale — switch to “zoom HBR”'
                  : ' · smaller than a mark at this scale'}
              </em>
            )}
          </span>
        </div>
      )}

      {view === 'table' && (
        <table className="bp-table">
          <caption className="bp-cap">
            B-plane geometry for event #{bp.event_id} — {bp.secondary_name}, TCA {bp.tca}
          </caption>
          <thead>
            <tr>
              <th scope="col">quantity</th>
              <th scope="col">value</th>
            </tr>
          </thead>
          <tbody>
            {([
              ['miss ξ (' + xiName + ')', fmtKm(geom.xi)],
              ['miss ζ (' + zetaName + ')', fmtKm(geom.zeta)],
              ['in-plane miss', fmtKm(bp.miss_norm_km)],
              ['3-D miss at TCA', fmtKm(bp.miss_3d_km)],
              ['relative velocity', `${bp.vrel_kms.toFixed(3)} km/s`],
              ['hard-body radius', fmtKm(bp.hbr_km)],
              ['miss inside HBR', bp.miss_inside_hbr ? 'YES — collision geometry' : 'no'],
              ...bp.sigma_levels.map((c): [string, string] => [
                `${c.level}σ contour · semi-major × semi-minor`,
                `${fmtKm(c.semi_major_km)} × ${fmtKm(c.semi_minor_km)} at ${c.rotation_deg.toFixed(1)}°`,
              ]),
              ['miss in sigmas (Mahalanobis)', `${bp.mahalanobis_sigma.toFixed(3)}σ`],
              [
                'smallest contour containing miss',
                bp.sigma_contour_containing_miss === null
                  ? 'none — beyond 3σ'
                  : `${bp.sigma_contour_containing_miss}σ`,
              ],
              ['Pc · analytic', bp.pc.toExponential(3)],
              [`Pc · k=${bp.realism.factor} realism`, bp.realism.pc.toExponential(3)],
              [
                `miss in sigmas · k=${bp.realism.factor}`,
                `${bp.realism.mahalanobis_sigma.toFixed(3)}σ`,
              ],
            ] as [string, string][]).map(([k, v]) => (
              <tr key={k}>
                <th scope="row">{k}</th>
                <td className="mono">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p className="bp-note">
        {mode === 'encounter' && geom.zoom === 'sigma'
          ? 'Scaled to the uncertainty region — the miss lies outside this frame, shown as a bearing. '
          : mode === 'encounter' && geom.zoom === 'hbr'
            ? 'Scaled to the collision cross-section — the covariance contours are far outside this frame. '
            : geom.zoom === 'hbr'
              ? 'Scaled to the covariance — the cross-section and the miss are within a pixel of the origin; “zoom HBR” resolves them. '
              : ''}
        {bp.note}
      </p>
    </div>
  )
}
