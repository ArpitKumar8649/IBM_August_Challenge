/**
 * Shared media-query hooks.
 *
 * `usePrefersReducedMotion` tracks `prefers-reduced-motion` and reacts to
 * changes (the OS setting can flip while the app is open). Used by the 3D globe
 * so its animation defaults respect the user's motion preference.
 */

import { useEffect, useState } from 'react'

export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(() =>
    typeof window !== 'undefined'
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false,
  )

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const onChange = () => setReduced(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  return reduced
}
