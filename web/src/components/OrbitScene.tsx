/**
 * OrbitScene — an animated SVG of a conjunction: the primary's orbit, a crossing
 * debris orbit, both satellites in motion, and a pulsing close-approach marker.
 * Pure SVG + SMIL, no dependencies.
 */
export default function OrbitScene() {
  return (
    <svg viewBox="0 0 600 600" className="orbit-scene" role="img" aria-label="Animated orbital conjunction diagram">
      <defs>
        <radialGradient id="earthGrad" cx="38%" cy="35%" r="75%">
          <stop offset="0%" stopColor="#4d9be8" />
          <stop offset="55%" stopColor="#2a6cb8" />
          <stop offset="100%" stopColor="#123a6e" />
        </radialGradient>
        <radialGradient id="atmoGrad" cx="50%" cy="50%" r="50%">
          <stop offset="78%" stopColor="rgba(99,179,255,0)" />
          <stop offset="92%" stopColor="rgba(99,179,255,0.18)" />
          <stop offset="100%" stopColor="rgba(99,179,255,0)" />
        </radialGradient>
        <filter id="glow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="3.5" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* range rings */}
      <circle cx="300" cy="300" r="250" fill="none" stroke="rgba(122,152,222,0.08)" strokeWidth="1" />
      <circle cx="300" cy="300" r="225" fill="none" stroke="rgba(122,152,222,0.05)" strokeWidth="1" strokeDasharray="3 6" />

      {/* Earth + atmosphere */}
      <circle cx="300" cy="300" r="104" fill="url(#atmoGrad)" />
      <circle cx="300" cy="300" r="82" fill="url(#earthGrad)" />
      <ellipse cx="278" cy="278" rx="34" ry="16" fill="rgba(255,255,255,0.10)" transform="rotate(-24 278 278)" />
      <ellipse cx="330" cy="330" rx="26" ry="11" fill="rgba(255,255,255,0.07)" transform="rotate(-24 330 330)" />

      {/* primary orbit (ISS) */}
      <g transform="rotate(-18 300 300)">
        <circle cx="300" cy="300" r="190" fill="none" stroke="rgba(99,179,255,0.45)" strokeWidth="1.4" />
        <circle r="5" fill="#63b3ff" filter="url(#glow)">
          <animateMotion dur="14s" repeatCount="indefinite" path="M 300,110 A 190,190 0 1,1 299.99,110" />
        </circle>
        <circle r="2" fill="#cfe6ff">
          <animateMotion dur="14s" begin="-4.6s" repeatCount="indefinite" path="M 300,110 A 190,190 0 1,1 299.99,110" />
        </circle>
      </g>

      {/* debris orbit */}
      <g transform="rotate(34 300 300)">
        <circle cx="300" cy="300" r="163" fill="none" stroke="rgba(245,176,76,0.4)" strokeWidth="1.2" strokeDasharray="5 5" />
        <circle r="4" fill="#f5b04c" filter="url(#glow)">
          <animateMotion dur="19s" repeatCount="indefinite" path="M 300,137 A 163,163 0 1,0 299.99,137" />
        </circle>
      </g>

      {/* close-approach marker */}
      <g>
        <circle cx="446" cy="206" r="26" fill="none" stroke="rgba(255,107,107,0.5)" strokeWidth="1.2">
          <animate attributeName="r" values="14;30;14" dur="2.4s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.75;0.1;0.75" dur="2.4s" repeatCount="indefinite" />
        </circle>
        <circle cx="446" cy="206" r="5" fill="#ff6b6b" filter="url(#glow)">
          <animate attributeName="r" values="4;6;4" dur="2.4s" repeatCount="indefinite" />
        </circle>
        <line x1="446" y1="206" x2="512" y2="150" stroke="rgba(255,107,107,0.45)" strokeWidth="1" />
        <text x="516" y="146" className="orbit-label" fill="#ff8f8f" fontSize="13" fontFamily="JetBrains Mono, monospace">
          TCA · miss 3.04 km
        </text>
        <text x="516" y="163" fill="#6c7896" fontSize="10.5" fontFamily="JetBrains Mono, monospace">
          2023-091AL · 9.89 km/s
        </text>
      </g>

      {/* primary label */}
      <text x="118" y="452" fill="#8fb8e8" fontSize="11" fontFamily="JetBrains Mono, monospace" opacity="0.85">
        ISS (ZARYA) · 25544
      </text>
    </svg>
  )
}
