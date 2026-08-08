/**
 * GlobePanel — the "3D View" tab (Phase 5.1). Owns the CZML scene lifecycle
 * around Globe3D:
 *
 *   • which event to visualize (selector, defaulting to the board's first),
 *   • what the engine composes (maneuver kind, window width) — content toggles,
 *   • what the viewer shows (covariance, maneuver track) — presentation toggles,
 *   • the honest state machine: idle / loading / ready / offline / error.
 *
 * Content changes refetch CZML from the engine (with a module-scope cache and a
 * stale-request guard); presentation changes flip entity.show client-side. The
 * scene is composed by the engine — this panel never fabricates a number, and
 * never shows a fake orbit when the API is down.
 */

import { useEffect, useRef, useState } from 'react'
import type { ConjunctionCzml, ManeuverKind, ScoredConjunction } from '../types'
import { clearConjunctionCzmlCache, fetchConjunctionCzml } from '../lib/api'
import { usePrefersReducedMotion } from '../lib/media'
import Globe3D, { type Globe3DHandle } from '../viz/Globe3D'
import Explainer from '../components/Explainer'

export interface GlobePanelProps {
  /** The conjunction board — the panel derives its selector from it. */
  events: ScoredConjunction[]
  /** Whether the board data came from the live API (honest status chip). */
  live?: boolean
  /**
   * One-shot "view this event in 3D" request from the board (Phase G): when it
   * changes to an event id, the panel selects it, then consumes the request.
   * Lets the B-plane's "view in 3D" button switch tabs with the event preselected.
   */
  preselectEventId?: number | null
  /** Called once the preselect has been applied, so the caller can clear it. */
  onPreselectConsumed?: () => void
}

type Status = 'idle' | 'loading' | 'ready' | 'offline' | 'error'

const KIND_OPTIONS: Array<{ value: ManeuverKind | 'none'; label: string }> = [
  { value: 'none', label: 'no burn' },
  { value: 'cheapest-safe', label: 'cheapest-safe' },
  { value: 'nominal', label: 'nominal' },
  { value: 'conservative', label: 'conservative' },
]

/** Legend swatches — mirror the engine's palette (engine/viz/czml.py). */
const LEGEND = [
  { color: '#0080ff', label: 'primary orbit' },
  { color: '#ff4040', label: 'secondary orbit' },
  { color: '#ffdc00', label: 'miss line @ TCA' },
  { color: '#00ff80', label: 'relative velocity' },
] as const

const WINDOW_MIN = 10
const WINDOW_MAX = 120
const WINDOW_STEP = 5
const WINDOW_DEBOUNCE_MS = 400

export default function GlobePanel({
  events,
  live = false,
  preselectEventId = null,
  onPreselectConsumed,
}: GlobePanelProps) {
  const [selectedId, setSelectedId] = useState<number | null>(events[0]?.event_id ?? null)
  const [maneuverKind, setManeuverKind] = useState<ManeuverKind | 'none'>('none')
  const [showCovariance, setShowCovariance] = useState(true)
  const [windowMin, setWindowMin] = useState(45)
  const [windowDebounced, setWindowDebounced] = useState(45)
  const [scene, setScene] = useState<ConjunctionCzml | null>(null)
  const [status, setStatus] = useState<Status>('idle')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [fetching, setFetching] = useState(false)
  const [composing, setComposing] = useState(false)
  /** Under reduced motion the globe shows the TCA frame and animates only on explicit play. */
  const prefersReducedMotion = usePrefersReducedMotion()
  const [playing, setPlaying] = useState<boolean>(() => !prefersReducedMotion)
  const [fullscreen, setFullscreen] = useState(false)
  const [retryToken, setRetryToken] = useState(0)
  /** True when a refetch failed but a previous scene is still on screen. */
  const [backendDown, setBackendDown] = useState(false)

  const globeRef = useRef<Globe3DHandle>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  /** Latest scene for the fetch effect, which must not depend on `scene`. */
  const sceneRef = useRef<ConjunctionCzml | null>(null)
  /** Latest `playing` for callbacks that fire from Globe3D's async load. */
  const playingRef = useRef(playing)
  /** Latest consume callback — read from a ref so the effect never depends on its identity. */
  const onPreselectConsumedRef = useRef(onPreselectConsumed)
  /** Monotonic id so a superseded fetch never overwrites a newer one. */
  const requestIdRef = useRef(0)
  /** Remembers the previous kind to detect "kind → no burn" presentation-only changes. */
  const prevKindRef = useRef<ManeuverKind | 'none'>('none')

  const activeEvent = events.find((e) => e.event_id === selectedId) ?? events[0] ?? null

  // Keep selection valid when the board changes underneath us.
  useEffect(() => {
    if (selectedId !== null && !events.some((e) => e.event_id === selectedId)) {
      setSelectedId(events[0]?.event_id ?? null)
    }
  }, [events, selectedId])

  // Honor a "view in 3D" request from the board: switch to that event once,
  // then consume the request so the panel's own selection is never clobbered
  // by a stale preselect on a later manual switch.
  useEffect(() => {
    onPreselectConsumedRef.current = onPreselectConsumed
  }, [onPreselectConsumed])
  useEffect(() => {
    if (preselectEventId == null) return
    if (events.some((e) => e.event_id === preselectEventId)) {
      setSelectedId(preselectEventId)
    }
    onPreselectConsumedRef.current?.()
  }, [preselectEventId, events])

  // Debounced window — the slider sweeps freely, the engine refetches once.
  useEffect(() => {
    const t = setTimeout(() => setWindowDebounced(windowMin), WINDOW_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [windowMin])

  // Fullscreen state syncs with the browser.
  useEffect(() => {
    const onFsChange = () => setFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', onFsChange)
    return () => document.removeEventListener('fullscreenchange', onFsChange)
  }, [])

  // Pause when the tab is hidden; resume only if the analyst had it playing.
  useEffect(() => {
    const onVisibility = () => {
      if (document.hidden) globeRef.current?.pause()
      else if (playingRef.current) globeRef.current?.play()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [])

  // If the OS enables reduced motion mid-session, stop animating (WCAG). We do
  // not auto-resume when it is disabled again — the analyst presses play.
  useEffect(() => {
    if (prefersReducedMotion) {
      playingRef.current = false
      setPlaying(false)
      globeRef.current?.pause()
    }
  }, [prefersReducedMotion])

  // ── scene fetch (content changes only) ─────────────────────────────────
  useEffect(() => {
    const requestId = ++requestIdRef.current
    const event = events.find((e) => e.event_id === selectedId) ?? events[0]
    if (!event) {
      sceneRef.current = null
      setScene(null)
      setStatus('idle')
      setErrorMsg(null)
      setFetching(false)
      return
    }

    // Switching a curated burn → "no burn" is a presentation-only change when a
    // scene is already loaded: keep the document and let Globe3D hide the track.
    // Without a scene, 'no burn' is still a content change — refetch without it.
    const prevKind = prevKindRef.current
    prevKindRef.current = maneuverKind
    if (prevKind !== 'none' && maneuverKind === 'none' && sceneRef.current) {
      setFetching(false)
      return
    }

    let cancelled = false
    const controller = new AbortController()
    setFetching(true)
    if (!sceneRef.current) setStatus('loading')

    fetchConjunctionCzml(
      event.event_id,
      { maneuverKind, windowMin: windowDebounced },
      controller.signal,
    )
      .then((result) => {
        if (cancelled || requestId !== requestIdRef.current) return // unmounted/superseded
        setFetching(false)
        if (result) {
          setBackendDown(false)
          sceneRef.current = result
          setScene(result)
          setStatus('ready')
          setErrorMsg(null)
        } else if (sceneRef.current) {
          // Refetch failed but the previous scene is still valid — keep it, and
          // surface the outage honestly instead of silently showing it.
          setBackendDown(true)
          setStatus('ready')
        } else {
          setBackendDown(false)
          setErrorMsg(null)
          setScene(null)
          setStatus('offline')
        }
      })
      .catch((err: unknown) => {
        // The engine answered with an error (4xx/5xx, or available:false) —
        // its message is the backend's own detail/note (see ConjunctionCzmlError).
        if (cancelled || requestId !== requestIdRef.current) return // unmounted/superseded
        setFetching(false)
        const message =
          err instanceof Error && err.message
            ? err.message
            : 'the engine could not compose this scene'
        if (sceneRef.current) {
          // Keep the last good scene; flag the compose error honestly.
          setBackendDown(false)
          setErrorMsg(message)
          setStatus('ready')
        } else {
          setScene(null)
          setErrorMsg(message)
          setStatus('error')
        }
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [selectedId, windowDebounced, maneuverKind, retryToken, events])

  // ── actions ────────────────────────────────────────────────────────────

  const retry = () => {
    clearConjunctionCzmlCache()
    setRetryToken((t) => t + 1)
  }

  const jumpToTca = () => globeRef.current?.jumpToTca()

  const togglePlay = () => {
    const next = !playing
    playingRef.current = next
    setPlaying(next)
    if (next) globeRef.current?.play()
    else globeRef.current?.pause()
  }

  const toggleFullscreen = () => {
    if (document.fullscreenElement) {
      void document.exitFullscreen()
    } else {
      void bodyRef.current?.requestFullscreen()
    }
  }

  // ── derived UI facts ───────────────────────────────────────────────────

  /** The kind the engine actually composed — may differ from the request. */
  const usedKind: ManeuverKind | null = scene?.maneuver_kind ?? null
  const kindSubstituted =
    maneuverKind !== 'none' && usedKind !== null && usedKind !== maneuverKind
  const showManeuverTrack = maneuverKind !== 'none'

  const sceneStatusChip = (() => {
    if (status === 'idle') return <span className="chip">no events</span>
    if (status === 'offline') return <span className="chip danger">engine offline</span>
    if (status === 'error' && !scene) return <span className="chip danger">scene error</span>
    if (fetching) return <span className="chip warn globe-chip-pulse">refreshing…</span>
    if (composing) return <span className="chip warn globe-chip-pulse">composing…</span>
    if (backendDown && scene) return <span className="chip warn">backend unreachable — last scene shown</span>
    if (errorMsg && scene) return <span className="chip warn">compose error — last scene shown</span>
    return <span className="chip good">3D scene ready</span>
  })()

  return (
    <div className="globe-panel panel">
      {/* ── header ─────────────────────────────────────────────────────── */}
      <header className="globe-head">
        <div className="globe-title">
          <span className="eyebrow" style={{ fontSize: '0.62rem' }}>Conjunction · 3D</span>
          <span className="globe-sub">
            <Explainer termId="globe_3d">engine-composed CZML · every coordinate computed</Explainer>
          </span>
        </div>
        <div className="globe-status">
          <span className={`chip ${live ? 'good' : 'warn'}`}>
            <span className="dot" style={{ background: live ? 'var(--good)' : 'var(--warn)' }} />
            {live ? 'LIVE API' : 'SAMPLE DATA'}
          </span>
          {sceneStatusChip}
          {activeEvent?.storm_flag && (
            <span className="chip warn">
              <Explainer termId="storm_flag">⚠ storm-flagged</Explainer>
            </span>
          )}
        </div>
      </header>

      {/* ── toolbar ────────────────────────────────────────────────────── */}
      <div className="globe-toolbar">
        <label className="globe-field" htmlFor="globe-event">
          event
          <select
            id="globe-event"
            className="globe-select"
            value={selectedId ?? ''}
            onChange={(e) => setSelectedId(Number(e.target.value) || null)}
          >
            {events.map((e) => (
              <option key={e.event_id} value={e.event_id}>
                #{e.event_id} · {e.secondary_name}
              </option>
            ))}
          </select>
        </label>

        <div className="globe-field">
          burn
          <div className="globe-seg" role="group" aria-label="maneuver kind">
            {KIND_OPTIONS.map((o) => (
              <button
                key={o.value}
                type="button"
                className={`globe-seg-btn ${maneuverKind === o.value ? 'active' : ''}`}
                aria-pressed={maneuverKind === o.value}
                onClick={() => setManeuverKind(o.value)}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>

        <label className="globe-field globe-switch">
          <input
            type="checkbox"
            role="switch"
            checked={showCovariance}
            onChange={(e) => setShowCovariance(e.target.checked)}
          />
          covariance
        </label>

        <label className="globe-field globe-window" htmlFor="globe-window">
          window
          <input
            id="globe-window"
            type="range"
            min={WINDOW_MIN}
            max={WINDOW_MAX}
            step={WINDOW_STEP}
            value={windowMin}
            onChange={(e) => setWindowMin(Number(e.target.value))}
          />
          <span className="globe-window-val mono">±{windowMin} min</span>
        </label>

        <div className="globe-actions">
          {backendDown && scene && (
            <button type="button" className="globe-btn" onClick={retry} title="Reconnect to the engine">
              ⟳ retry
            </button>
          )}
          <button type="button" className="globe-btn" onClick={jumpToTca} title="Snap the clock to TCA and fly to the encounter">
            ⏱ TCA
          </button>
          <button
            type="button"
            className={`globe-btn ${!playing ? 'active' : ''}`}
            onClick={togglePlay}
            aria-pressed={!playing}
            title={playing ? 'Pause the animation' : 'Resume the animation'}
          >
            {playing ? '⏸ pause' : '▶ play'}
          </button>
          <button
            type="button"
            className={`globe-btn ${fullscreen ? 'active' : ''}`}
            onClick={toggleFullscreen}
            aria-pressed={fullscreen}
            title={fullscreen ? 'Exit fullscreen' : 'Fullscreen'}
          >
            ⛶
          </button>
        </div>
      </div>

      {/* ── the globe ──────────────────────────────────────────────────── */}
      <div
        ref={bodyRef}
        className={`globe-body ${fetching && scene ? 'stale' : ''}`}
      >
        <Globe3D
          ref={globeRef}
          czml={scene ? scene.document : null}
          tca={scene ? scene.tca : null}
          showCovariance={showCovariance}
          showManeuverTrack={showManeuverTrack}
          onReady={() => {
            setStatus('ready')
            setErrorMsg(null)
            // Globe3D resumes the clock on every load — re-assert a paused state
            // so the play button and the animation never disagree.
            if (!playingRef.current) globeRef.current?.pause()
          }}
          onError={(message) => {
            setErrorMsg(message)
            if (!sceneRef.current) setStatus('error')
          }}
          onLoadingChange={setComposing}
        />

        {!scene && status === 'loading' && (
          <div className="globe-empty" role="status" aria-live="polite">
            <div className="globe-empty-inner">
              <div className="globe-spinner" />
              <div className="globe-empty-text">composing the encounter…</div>
            </div>
          </div>
        )}

        {!scene && status === 'offline' && (
          <div className="globe-empty" role="status">
            <div className="globe-empty-card">
              <div className="globe-empty-title">live engine offline</div>
              <p>
                The 3D scene is composed by the OrbitWarden engine, not the browser.
                Start the API with <code>uvicorn api.main:app</code> and retry.
              </p>
              <button type="button" className="btn btn-primary" onClick={retry}>
                Retry
              </button>
            </div>
          </div>
        )}

        {!scene && status === 'error' && (
          <div className="globe-empty" role="alert">
            <div className="globe-empty-card">
              <div className="globe-empty-title">scene unavailable</div>
              <p>{errorMsg ?? 'the engine could not compose this scene.'}</p>
              <button type="button" className="btn btn-primary" onClick={retry}>
                Retry
              </button>
            </div>
          </div>
        )}

        {!scene && status === 'idle' && (
          <div className="globe-empty">
            <div className="globe-empty-text">no conjunctions to visualize</div>
          </div>
        )}
      </div>

      {/* ── footer: legend + honesty ───────────────────────────────────── */}
      <footer className="globe-foot">
        <dl className="globe-legend">
          {LEGEND.map((item) => (
            <div className="globe-key" key={item.label}>
              <dt className="globe-swatch" style={{ background: item.color }} aria-hidden="true" />
              <dd>{item.label}</dd>
            </div>
          ))}
          {showManeuverTrack && (
            <div className="globe-key">
              <dt className="globe-swatch" style={{ background: '#ff8000' }} aria-hidden="true" />
              <dd><Explainer termId="maneuver_track">pre/post-burn track</Explainer></dd>
            </div>
          )}
          {showCovariance && (
            <div className="globe-key">
              <dt className="globe-swatch" style={{ background: '#80ff80' }} aria-hidden="true" />
              <dd><Explainer termId="covariance_ellipsoid">encounter uncertainty (1σ, ×10)</Explainer></dd>
            </div>
          )}
        </dl>

        {kindSubstituted && usedKind && (
          <p className="globe-notice">
            requested {maneuverKind} — showing best available ({usedKind}): the curated
            options can collide, so the engine reports what it actually composed.
          </p>
        )}

        {scene && (
          <p className="globe-note">
            vs {scene.secondary} (NORAD {scene.secondary_norad}) · TCA{' '}
            {new Date(scene.tca).toLocaleString()} · composed by the engine, ±
            {windowDebounced} min window
          </p>
        )}
      </footer>
    </div>
  )
}
