import { useMemo } from 'react'

/** Ambient starfield + nebula wash behind the whole app. */
export default function SpaceBackground() {
  const stars = useMemo(
    () =>
      Array.from({ length: 130 }, (_, i) => ({
        id: i,
        left: Math.random() * 100,
        top: Math.random() * 100,
        size: Math.random() < 0.85 ? 1.5 : 2.5,
        delay: Math.random() * 4,
        duration: 3 + Math.random() * 4,
      })),
    [],
  )

  return (
    <>
      <div className="space-bg" aria-hidden="true" />
      <div className="starfield" aria-hidden="true">
        {stars.map((s) => (
          <i
            key={s.id}
            style={{
              left: `${s.left}%`,
              top: `${s.top}%`,
              width: s.size,
              height: s.size,
              animationDelay: `${s.delay}s`,
              animationDuration: `${s.duration}s`,
            }}
          />
        ))}
      </div>
    </>
  )
}
