import type { VisiblePass } from '../types'

/**
 * Polar sky chart (Phase 5.3) — the "look here" diagram.
 *
 * The horizon is the outer circle; the zenith is the centre. A pass is drawn
 * as the arc the satellite traces: start → apex → end, with the apex marked
 * as a diamond (its time + height labelled). Markers are shape-distinct —
 * circle, diamond, square — so the chart never relies on colour alone.
 */
export default function SkyChart({ pass }: { pass: VisiblePass | null }) {
  const SIZE = 320
  const CX = SIZE / 2
  const CY = SIZE / 2
  const R = 126

  const project = (az: number, elev: number) => {
    const rad = (az * Math.PI) / 180
    const r = ((90 - Math.max(0, Math.min(90, elev))) / 90) * R
    return { x: CX + r * Math.sin(rad), y: CY - r * Math.cos(rad) }
  }

  const ring = (elev: number) => {
    const r = ((90 - elev) / 90) * R
    return `M ${CX - r} ${CY} a ${r} ${r} 0 1 0 ${2 * r} 0 a ${r} ${r} 0 1 0 ${-2 * r} 0`
  }

  const arcPoints = (p: VisiblePass): string => {
    const p0 = project(p.azimuth_start_deg, p.elevation_start_deg)
    const p1 = project(p.azimuth_apex_deg, p.max_elevation_deg)
    const p2 = project(p.azimuth_end_deg, p.elevation_end_deg)
    const pts: string[] = []
    for (let t = 0; t <= 1.0001; t += 0.04) {
      const mt = 1 - t
      const x = mt * mt * p0.x + 2 * mt * t * p1.x + t * t * p2.x
      const y = mt * mt * p0.y + 2 * mt * t * p1.y + t * t * p2.y
      pts.push(`${x.toFixed(1)},${y.toFixed(1)}`)
    }
    return pts.join(' ')
  }

  const label = (az: number, text: string) => {
    const rad = (az * Math.PI) / 180
    const r = R + 14
    return { x: CX + r * Math.sin(rad), y: CY - r * Math.cos(rad), text }
  }

  const describe = pass
    ? `${pass.name}: starts in the ${pass.direction_from}, peaks at ${pass.max_elevation_deg}° above the horizon, ends in the ${pass.direction_to}.`
    : 'No pass selected.'

  const start = pass ? project(pass.azimuth_start_deg, pass.elevation_start_deg) : null
  const apex = pass ? project(pass.azimuth_apex_deg, pass.max_elevation_deg) : null
  const end = pass ? project(pass.azimuth_end_deg, pass.elevation_end_deg) : null
  const cardinal = [label(0, 'N'), label(90, 'E'), label(180, 'S'), label(270, 'W')]

  return (
    <svg
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      className="sky-chart"
      role="img"
      aria-label={describe}
    >
      <title>{describe}</title>

      {/* horizon + elevation rings */}
      <circle cx={CX} cy={CY} r={R} className="sky-horizon" />
      <path d={ring(60)} className="sky-ring" />
      <path d={ring(30)} className="sky-ring" />
      <text x={CX + 4} y={CY - R * 0.34 + 4} className="sky-ring-label">60°</text>
      <text x={CX + 4} y={CY - R * 0.67 + 4} className="sky-ring-label">30°</text>
      <text x={CX + 6} y={CY - 4} className="sky-zenith">overhead</text>

      {/* cardinal points */}
      {cardinal.map((c) => (
        <text key={c.text} x={c.x - 4} y={c.y + 4} className="sky-cardinal">
          {c.text}
        </text>
      ))}

      {pass && start && apex && end && (
        <g>
          <polyline points={arcPoints(pass)} className="sky-arc" />
          {/* start: open circle · apex: diamond · end: square (shape-first) */}
          <circle cx={start.x} cy={start.y} r="4" className="sky-mark-start" />
          <circle cx={start.x} cy={start.y} r="7" className="sky-mark-start-ring" />
          <rect x={end.x - 4} y={end.y - 4} width="8" height="8" className="sky-mark-end" />
          <path
            d={`M ${apex.x} ${apex.y - 7} L ${apex.x + 5.5} ${apex.y} L ${apex.x} ${apex.y + 7} L ${apex.x - 5.5} ${apex.y} Z`}
            className="sky-mark-apex"
          />
          <text x={apex.x} y={apex.y - 11} textAnchor="middle" className="sky-apex-label">
            {pass.max_elevation_deg.toFixed(0)}° up
          </text>
        </g>
      )}
    </svg>
  )
}
