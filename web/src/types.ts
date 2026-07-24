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
