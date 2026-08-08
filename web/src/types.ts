/** Shared domain types mirroring the engine's pydantic models. */

export interface ScoredConjunction {
  event_id: number
  secondary_name: string
  secondary_norad: number
  secondary_type: string
  tca: string
  miss_km: number
  vrel_kms: number
  geometry: 'in-track' | 'radial' | 'cross-track'
  pc: number
  risk_score: number
  storm_flag: boolean
  secondary_maneuverable: boolean
  miss_rsw_km?: { radial: number; in_track: number; cross_track: number }
}

export interface ManeuverOption {
  kind: string
  burn_epoch: string
  lead_time_min: number
  dv_total_ms: number
  dv_rsw_ms: { radial: number; in_track: number; cross_track: number }
  propellant_g: number
  post_burn_miss_km: number
  satisfies_constraints: boolean
}

export interface SatelliteInfo {
  norad_id: number
  name: string
  tle_age_days: number
  inclination_deg: number
  perigee_alt_km: number
  apogee_alt_km: number
  object_type: string
}

// ============================================================
// B-plane — the canonical conjunction-assessment diagram (5.2)
// ============================================================

/** One covariance contour: the 1σ ellipse scaled by `level`. */
export interface SigmaContour {
  level: number
  semi_major_km: number
  semi_minor_km: number
  rotation_deg: number
}

/** The 1σ covariance ellipse in the B-plane. Orientation is mod 180°, in [-90, 90). */
export interface CovarianceEllipse {
  semi_major_km: number
  semi_minor_km: number
  rotation_deg: number
}

/** The same geometry under the covariance-realism factor (Foster/Hall). */
export interface BPlaneRealism {
  factor: number
  ellipse: CovarianceEllipse
  sigma_levels: SigmaContour[]
  pc: number
  mahalanobis_sigma: number
}

export interface BPlane {
  available: boolean
  event_id: number
  secondary_name: string
  secondary_norad: number
  tca: string
  /** The miss point projected onto the encounter plane (km). */
  miss_bp: { xi: number; zeta: number }
  /** In-plane miss distance — always <= the 3-D miss, since a component is projected out. */
  miss_norm_km: number
  miss_3d_km: number
  vrel_kms: number
  /** Hard-body radius: the combined collision cross-section (km). */
  hbr_km: number
  miss_inside_hbr: boolean
  ellipse: CovarianceEllipse
  sigma_levels: SigmaContour[]
  /** The miss expressed in sigmas of the uncertainty distribution. */
  mahalanobis_sigma: number
  /** Smallest contour containing the miss, or null beyond 3σ. */
  sigma_contour_containing_miss: number | null
  /** The ξ/ζ axes in RSW components, so the axes can be labelled honestly. */
  axes_rsw: { xi: number[]; zeta: number[] }
  pc: number
  realism: BPlaneRealism
  note: string
}

export interface SpaceWeather {
  available: boolean
  max_kp_3day: number
  active_storm: boolean
}

export interface ChatEvent {
  type: 'tool_call' | 'tool_result' | 'content' | 'done'
  name?: string
  text?: string
  audit_passed?: boolean
}

// ============================================================
// Phase E — astronomy & discovery
// ============================================================

export interface Transient {
  oid: string
  ra: number
  dec: number
  classification: string
  last_observed: string
  n_detections: number
}

export interface ExoplanetStats {
  available: boolean
  confirmed_since: number
  count: number
  recent: { name: string; discovery_method: string; year: number; host_star: string }[]
  methods_in_sample: Record<string, number>
}

export interface Star {
  source_id: string
  ra: number
  dec: number
  g_mag: number
}

// ============================================================
// Phase D — precision ephemerides
// ============================================================

export interface PlanetPosition {
  available: boolean
  body: string
  time: string
  position_eci_km: { x: number; y: number; z: number }
  distance_from_earth_km: number
  distance_from_earth_au: number
}

// ============================================================
// Phase C — Earth observation
// ============================================================

export interface GroundTrackPoint {
  lat: number
  lon: number
  time: string
}

export interface GroundTrack {
  available: boolean
  satellite: string
  num_points: number
  current: { latitude: number; longitude: number; altitude_km: number }
  bbox: { west: number; south: number; east: number; north: number }
  center: { latitude: number; longitude: number }
  track: GroundTrackPoint[]
}

export interface ImageryScene {
  id: string
  datetime: string
  cloud_cover: number
  platform: string
  thumbnail_url: string
}

// ============================================================
// Phase A — NASA / catalog / engagement
// ============================================================

export interface NeoObject {
  name: string
  hazardous: boolean
  diameter_km: number
  approaches: { date: string; miss_km: number; miss_lunar: number; velocity_kmh: number }[]
}

export interface IssPosition {
  available: boolean
  latitude: number
  longitude: number
  source: string
}

export interface Astronauts {
  number: number
  people: { name: string; craft: string }[]
}

export interface CatalogStats {
  available: boolean
  global: { orbital_payloads: number; orbital_debris: number; orbital_total: number; decayed_total: number }
  top_countries: { country: string; orbital_payloads: number; orbital_debris: number; orbital_total: number }[]
}

// ============================================================
// Phase B — space weather (detailed)
// ============================================================

export interface SpaceWeatherDetailed {
  composite: { score: number; level: string; drivers: string[] }
  kp_max_3day: number
  solar_wind: { bt_nt: number; bz_gsm_nt: number; speed_kms: number; f107_sfu: number }
  xray: { flux_w_m2: number; flare_class: string }
  protons: { flux_pfu: number; sep_active: boolean }
}

// ============================================================
// Operational health
// ============================================================

export interface SourceHealth {
  source: string
  name: string
  status: 'ok' | 'stale' | 'unknown'
  detail: string
}

export interface SystemHealth {
  status: 'ok' | 'degraded'
  checked_at: string
  database: { status: string; last_run?: string; candidates?: number }
  sources_ok: number
  sources_stale: number
  sources_unknown: number
  sources_total: number
  sources: SourceHealth[]
}

// ============================================================
// Knowledge Base
// ============================================================

export interface KnowledgeChunk {
  chunk_id: string
  title: string
  topic: string
  plain: string
  body: string
  score?: number
}

// ============================================================
// 5.1 — 3D conjunction globe (CZML)
// ============================================================

/** The curated maneuver kinds the engine can compose into a CZML scene. */
export type ManeuverKind = 'cheapest-safe' | 'nominal' | 'conservative'

/**
 * A CZML scene for one conjunction, as returned by GET /api/events/{id}/czml.
 *
 * Only the envelope fields are parsed by the UI (for the clock, camera, legend,
 * and the "kind actually used" notice). `document` is opaque JSON handed to
 * Cesium's CzmlDataSource whole — the frontend never reads orbit coordinates
 * out of it (the engine is the only source of numbers).
 */
export interface ConjunctionCzml {
  available: boolean
  event_id: number
  primary: string
  secondary: string
  secondary_norad: number
  /** ISO 8601 with 'Z' — the TCA anchor for the Cesium clock and camera. */
  tca: string
  /** The kind actually composed; may differ from the requested kind (curated
   *  kinds can collide) — the UI must show this verbatim. */
  maneuver_kind: ManeuverKind | null
  note?: string
  document: Array<Record<string, unknown>>
}

// ============================================================
// 5.3 — "What's passing over me?" (Tonight's Sky)
// ============================================================

/**
 * One naked-eye satellite pass for a location tonight, as computed by the
 * engine (engine/viz/passes.py). Times are ISO 8601 UTC with 'Z'.
 */
export interface VisiblePass {
  norad_id: number
  name: string
  start: string
  max_elevation_time: string
  end: string
  max_elevation_deg: number
  elevation_start_deg: number
  elevation_end_deg: number
  azimuth_start_deg: number
  azimuth_apex_deg: number
  azimuth_end_deg: number
  /** 16-point compass label at start, e.g. 'NW'. */
  direction_from: string
  direction_to: string
  range_km_at_max: number
  /** Apparent magnitude at apex — smaller is brighter. An estimate. */
  magnitude: number
  brightness_label: string
  object_blurb: string
  look_instruction: string
}

export interface PassesResponse {
  available: boolean
  latitude: number
  longitude: number
  /** Observer-local date (YYYY-MM-DD) the prediction is for. */
  date: string
  night_start: string | null
  night_end: string | null
  max_tle_age_days: number
  passes: VisiblePass[]
  /** Assumptions & caveats, in plain language. */
  note: string
}
