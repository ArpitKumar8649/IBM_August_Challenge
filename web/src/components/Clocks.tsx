import { useEffect, useState } from 'react'

/** Live ticking countdown to a target time (for TCA). */
export function TcaCountdown({ target }: { target: string }) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const diff = Math.max(0, new Date(target).getTime() - now)
  const d = Math.floor(diff / 86_400_000)
  const h = Math.floor((diff % 86_400_000) / 3_600_000)
  const m = Math.floor((diff % 3_600_000) / 60_000)
  const s = Math.floor((diff % 60_000) / 1000)
  const pad = (n: number) => String(n).padStart(2, '0')

  return (
    <span className="mono">
      {d > 0 && `${d}d `}
      {pad(h)}:{pad(m)}:{pad(s)}
    </span>
  )
}

/** Live UTC mission clock. */
export function MissionClock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return <span className="mono">{now.toISOString().slice(11, 19)} UTC</span>
}
