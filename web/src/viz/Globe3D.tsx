/**
 * Globe3D — CesiumJS scene renderer for OrbitWarden's 3D conjunction view (5.1).
 *
 * Mounts one Viewer for its lifetime and renders whatever CZML scene the parent
 * supplies: both orbits, the TCA moment, the covariance ellipsoid, and the
 * maneuver track. The CZML document is treated as opaque — the engine composed
 * it — so this component only:
 *   • loads it via CzmlDataSource,
 *   • anchors the Cesium clock to the scene's own clock (TCA-centred, looping),
 *   • shows/hides the covariance ellipsoid by entity id (a presentation toggle,
 *     never a refetch),
 *   • flies the camera to the encounter on first load, and on demand via the
 *     jumpToTca() handle.
 *
 * Imagery: Ion-backed Bing Maps Aerial + world terrain when VITE_CESIUM_ION_TOKEN
 * is set; otherwise OpenStreetMap tiles — no Ion dependency either way.
 *
 * Lazy-load this component so the Cesium bundle stays out of the critical path.
 */

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import type { Cartesian3, DataSource, JulianDate, Viewer as CesiumViewer } from 'cesium'
import { usePrefersReducedMotion } from '../lib/media'

const ION_TOKEN = import.meta.env.VITE_CESIUM_ION_TOKEN as string | undefined
const CESIUM_ACCESS_TOKEN = ION_TOKEN || ''

/** Entity ids the engine guarantees in every scene (engine/viz/czml.py). */
const COVARIANCE_ELLIPSOID_ID = 'covariance-ellipsoid'
const MANEUVER_TRACK_ID = 'maneuver-track'
const TCA_ENTITY_IDS = ['tca-primary', 'tca-secondary']

export interface Globe3DProps {
  /** Opaque CZML scene (the `document` field of GET /api/events/{id}/czml). Null = no scene. */
  czml: Array<Record<string, unknown>> | null
  /** TCA as ISO-8601 — fallback clock anchor if the document carries no clock packet. */
  tca: string | null
  /** Client-side visibility of the covariance ellipsoid (never refetches). */
  showCovariance: boolean
  /**
   * Client-side visibility of the maneuver track (never refetches). Lets the
   * panel hide a burn instantly without re-composing the scene; the track only
   * exists in the document when a maneuver was requested.
   */
  showManeuverTrack: boolean
  onReady?: (info: { tcaEntities: number }) => void
  onError?: (message: string) => void
  onLoadingChange?: (loading: boolean) => void
}

export interface Globe3DHandle {
  /** Snap the clock to TCA and fly the camera to the encounter. */
  jumpToTca: () => void
  play: () => void
  pause: () => void
}

/**
 * Fly the camera to frame the TCA moment — both objects, top-down-ish.
 * `animate` is false under reduced motion: the camera jumps instead of flying.
 */
function flyToEncounter(
  viewer: CesiumViewer,
  cesium: typeof import('cesium'),
  dataSource: DataSource | null,
  tcaTime: JulianDate,
  animate: boolean,
): void {
  const { BoundingSphere, HeadingPitchRange } = cesium
  const positions: Cartesian3[] = []
  if (dataSource) {
    for (const id of TCA_ENTITY_IDS) {
      const position = dataSource.entities.getById(id)?.position?.getValue(tcaTime)
      if (position) positions.push(position)
    }
  }
  if (positions.length === 0) return // nothing to frame — keep the current view
  const sphere = BoundingSphere.fromPoints(positions, new BoundingSphere())
  const range = Math.max(sphere.radius * 4, 30000)
  viewer.camera.flyToBoundingSphere(sphere, {
    offset: new HeadingPitchRange(0, -Math.PI / 2.2, range),
    duration: animate ? 1.8 : 0,
  })
}

const Globe3D = forwardRef<Globe3DHandle, Globe3DProps>(function Globe3D(
  { czml, tca, showCovariance, showManeuverTrack, onReady, onError, onLoadingChange },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null)
  /** Live scene state — read imperatively by effects/handles, never for render. */
  const sceneRef = useRef<{
    viewer: CesiumViewer | null
    cesium: typeof import('cesium') | null
    dataSource: DataSource | null
    tcaTime: JulianDate | null
    flewOnce: boolean
  }>({ viewer: null, cesium: null, dataSource: null, tcaTime: null, flewOnce: false })
  /** Monotonic token so a superseded load never wins the race with a newer one. */
  const loadTokenRef = useRef(0)
  const destroyedRef = useRef(false)
  /** Mirrors of the presentation toggles so the async load path never applies stale values. */
  const showCovarianceRef = useRef(showCovariance)
  const showManeuverTrackRef = useRef(showManeuverTrack)
  /** Reduced-motion mirror — the load path and camera read the latest value. */
  const reducedMotion = usePrefersReducedMotion()
  const reducedMotionRef = useRef(reducedMotion)
  const [viewerReady, setViewerReady] = useState(false)

  // Keep the reduced-motion mirror fresh BEFORE any load effect reads it, so a
  // preference change and a scene load in the same commit never read a stale value.
  useEffect(() => {
    reducedMotionRef.current = reducedMotion
  }, [reducedMotion])
  const [sceneState, setSceneState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  // ── imperative handle (the panel drives the camera/clock) ─────────────
  useImperativeHandle(ref, () => ({
    jumpToTca() {
      const { viewer, cesium, dataSource, tcaTime } = sceneRef.current
      if (!viewer || !cesium || !tcaTime) return
      viewer.clock.currentTime = tcaTime
      flyToEncounter(viewer, cesium, dataSource, tcaTime, !reducedMotionRef.current)
    },
    play() {
      const { viewer } = sceneRef.current
      if (viewer) viewer.clock.shouldAnimate = true
    },
    pause() {
      const { viewer } = sceneRef.current
      if (viewer) viewer.clock.shouldAnimate = false
    },
  }), [])

  // ── viewer lifecycle (once per mount) ─────────────────────────────────
  useEffect(() => {
    let cancelled = false
    destroyedRef.current = false

    async function init() {
      const Cesium = await import('cesium')
      const { Ion, Viewer, OpenStreetMapImageryProvider, Color } = Cesium
      if (CESIUM_ACCESS_TOKEN) Ion.defaultAccessToken = CESIUM_ACCESS_TOKEN
      if (cancelled || destroyedRef.current || !containerRef.current) return

      const viewer = new Viewer(containerRef.current, {
        animation: false,
        timeline: true,
        baseLayerPicker: false,
        fullscreenButton: false,
        geocoder: false,
        homeButton: false,
        sceneModePicker: false,
        navigationHelpButton: false,
        requestRenderMode: true,
        maximumRenderTimeChange: Infinity,
      })

      // Theme the scene to the dashboard: near-black space, a sun-lit globe.
      viewer.scene.backgroundColor = Color.fromCssColorString('#05070f')
      viewer.scene.globe.enableLighting = true
      // Reduced motion: show the TCA frame, never auto-animate — the analyst
      // can still press play explicitly (WCAG allows motion on user intent).
      viewer.clock.shouldAnimate = !reducedMotionRef.current

      sceneRef.current.viewer = viewer
      sceneRef.current.cesium = Cesium

      if (CESIUM_ACCESS_TOKEN) {
        // Ion token set → the default base layer is already Bing Maps Aerial;
        // add world terrain on top.
        try {
          const terrain = await Cesium.createWorldTerrainAsync()
          if (!cancelled && !destroyedRef.current) viewer.terrainProvider = terrain
        } catch {
          /* no terrain — the globe still renders on flat imagery */
        }
      } else {
        // No Ion token → swap to OpenStreetMap (open tiles, no token required).
        viewer.imageryLayers.removeAll()
        viewer.imageryLayers.addImageryProvider(
          new OpenStreetMapImageryProvider({ url: 'https://tile.openstreetmap.org' }),
        )
      }

      if (!cancelled && !destroyedRef.current) setViewerReady(true)
    }

    init()

    return () => {
      cancelled = true
      destroyedRef.current = true
      sceneRef.current.viewer?.destroy()
      sceneRef.current = { viewer: null, cesium: null, dataSource: null, tcaTime: null, flewOnce: false }
    }
  }, [])

  // ── scene load / swap (runs for each new czml) ─────────────────────────
  useEffect(() => {
    const { viewer, cesium } = sceneRef.current
    if (!viewerReady || !viewer || !cesium) return

    const token = ++loadTokenRef.current

    if (!czml) {
      // No scene: drop whatever was loaded and hand the empty state to the parent.
      const prev = sceneRef.current.dataSource
      if (prev) {
        viewer.dataSources.remove(prev, true)
        sceneRef.current.dataSource = null
        sceneRef.current.tcaTime = null
      }
      setSceneState('idle')
      setErrorMsg(null)
      onLoadingChange?.(false)
      return
    }

    let active = true
    setSceneState('loading')
    onLoadingChange?.(true)

    async function loadScene() {
      if (!viewer || !cesium) return // closure-local narrowing
      try {
        const dataSource = await cesium.CzmlDataSource.load(czml)
        if (!active || token !== loadTokenRef.current || destroyedRef.current || !viewer) {
          // Superseded or unmounted — never added to the viewer, so there is
          // nothing to tear down; the data source is simply dropped (GC).
          return
        }

        // Swap in the new scene; the old one is destroyed with it.
        const prev = sceneRef.current.dataSource
        if (prev) viewer.dataSources.remove(prev, true)
        viewer.dataSources.add(dataSource)
        sceneRef.current.dataSource = dataSource

        // Anchor the viewer clock to the scene's clock (TCA-centred, looping).
        // Fall back to the tca prop if the document carries no clock packet.
        const clock = dataSource.clock
        let tcaTime: JulianDate | null = clock ? clock.currentTime : null
        if (!tcaTime && tca) tcaTime = cesium.JulianDate.fromIso8601(tca)
        if (clock) {
          viewer.clock.startTime = clock.startTime
          viewer.clock.stopTime = clock.stopTime
          viewer.clock.currentTime = clock.currentTime
          viewer.clock.multiplier = Math.min(600, Math.max(1, Math.round(clock.multiplier)))
          viewer.clock.clockRange = clock.clockRange
          viewer.clock.shouldAnimate = !reducedMotionRef.current
        }
        sceneRef.current.tcaTime = tcaTime

        // Presentation toggles applied at load time (later flips handled below).
        // Read the ref mirrors so a toggle made mid-load is never overridden by
        // the stale values captured in this effect's closure.
        const covariance = dataSource.entities.getById(COVARIANCE_ELLIPSOID_ID)
        if (covariance) covariance.show = showCovarianceRef.current
        const track = dataSource.entities.getById(MANEUVER_TRACK_ID)
        if (track) track.show = showManeuverTrackRef.current

        // First successful scene: fly to the encounter so the "two orbits
        // converge" moment is the first thing the analyst sees (instant jump
        // under reduced motion).
        if (!sceneRef.current.flewOnce && tcaTime) {
          sceneRef.current.flewOnce = true
          flyToEncounter(viewer, cesium, dataSource, tcaTime, !reducedMotionRef.current)
        }

        setSceneState('idle')
        setErrorMsg(null)
        onReady?.({
          tcaEntities: TCA_ENTITY_IDS.filter((id) => dataSource.entities.getById(id)).length,
        })
      } catch (err) {
        if (!active || destroyedRef.current) return
        const message = err instanceof Error ? err.message : 'failed to compose the 3D scene'
        setSceneState('error')
        setErrorMsg(message)
        onError?.(message)
      } finally {
        if (active && token === loadTokenRef.current) onLoadingChange?.(false)
      }
    }

    loadScene()
    return () => {
      active = false
    }
    // `tca` is a fallback anchor, not a trigger; `showCovariance` has its own effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [czml, viewerReady])

  // ── covariance ellipsoid visibility (client-side, no refetch) ──────────
  useEffect(() => {
    showCovarianceRef.current = showCovariance
    const covariance = sceneRef.current.dataSource?.entities.getById(COVARIANCE_ELLIPSOID_ID)
    if (covariance) covariance.show = showCovariance
  }, [showCovariance])

  // ── maneuver track visibility (client-side, no refetch) ────────────────
  useEffect(() => {
    showManeuverTrackRef.current = showManeuverTrack
    const track = sceneRef.current.dataSource?.entities.getById(MANEUVER_TRACK_ID)
    if (track) track.show = showManeuverTrack
  }, [showManeuverTrack])

  // ── camera follows the encounter, not the toggle ───────────────────────
  // The TCA identifies the encounter: switching events (new TCA) re-flies the
  // camera to the fresh encounter; toggling a maneuver kind (same TCA) keeps
  // the analyst exactly where they are to watch the track swap in.
  useEffect(() => {
    sceneRef.current.flewOnce = false
  }, [tca])

  // ── container-driven resize (Cesium in a flex/grid layout) ─────────────
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const observer = new ResizeObserver(() => sceneRef.current.viewer?.resize())
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  return (
    <div className="globe3d">
      <div ref={containerRef} className="globe3d-canvas" aria-label="3D conjunction globe" />
      {sceneState === 'loading' && (
        <div className="globe-overlay" role="status" aria-live="polite">
          <div className="globe-spinner" />
          <div className="globe-loading-text">composing the encounter…</div>
        </div>
      )}
      {sceneState === 'error' && errorMsg && (
        <div className="globe-overlay error">
          <div className="globe-error-card" role="alert">
            <div className="globe-error-title">scene unavailable</div>
            <div className="globe-error-msg">{errorMsg}</div>
          </div>
        </div>
      )}
    </div>
  )
})

export default Globe3D
