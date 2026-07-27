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
