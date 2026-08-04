import type {
  ScoredConjunction,
  SatelliteInfo,
  SpaceWeather,
  ManeuverOption,
  BPlane,
  CovarianceEllipse,
  SigmaContour,
} from '../types'

/**
 * Sample dataset derived from a real screening run (ISS vs. the active catalog).
 * Used as a graceful fallback when the API isn't running, so the dashboard and
 * landing page are always alive.
 */

export const SAMPLE_SATELLITE: SatelliteInfo = {
  norad_id: 25544,
  name: 'ISS (ZARYA)',
  tle_age_days: 3.7,
  inclination_deg: 51.63,
  perigee_alt_km: 415,
  apogee_alt_km: 424,
  object_type: 'PAYLOAD',
}

export const SAMPLE_WEATHER: SpaceWeather = {
  available: true,
  max_kp_3day: 5.3,
  active_storm: false,
}

export const SAMPLE_EVENTS: ScoredConjunction[] = [
  {
    event_id: 1, secondary_name: '2023-091AL', secondary_norad: 57001,
    secondary_type: 'UNKNOWN', tca: '2026-07-26T01:18:13Z', miss_km: 3.037,
    vrel_kms: 9.886, geometry: 'radial', pc: 6.69e-13, risk_score: 72.4,
    storm_flag: false, secondary_maneuverable: false,
    miss_rsw_km: { radial: 2.91, in_track: 0.62, cross_track: 0.41 },
  },
  {
    event_id: 2, secondary_name: 'COSMOS 2251 DEB', secondary_norad: 36558,
    secondary_type: 'DEBRIS', tca: '2026-07-30T14:05:15Z', miss_km: 9.225,
    vrel_kms: 14.32, geometry: 'radial', pc: 5.23e-62, risk_score: 40.9,
    storm_flag: false, secondary_maneuverable: false,
    miss_rsw_km: { radial: 8.9, in_track: 2.1, cross_track: 0.8 },
  },
  {
    event_id: 3, secondary_name: 'MINXSS-2', secondary_norad: 43901,
    secondary_type: 'PAYLOAD', tca: '2026-07-30T22:25:08Z', miss_km: 6.609,
    vrel_kms: 0.641, geometry: 'cross-track', pc: 1.07e-33, risk_score: 40.3,
    storm_flag: false, secondary_maneuverable: true,
    miss_rsw_km: { radial: 1.2, in_track: 0.9, cross_track: 6.4 },
  },
  {
    event_id: 4, secondary_name: '2023-117C', secondary_norad: 57412,
    secondary_type: 'UNKNOWN', tca: '2026-07-30T02:17:13Z', miss_km: 23.714,
    vrel_kms: 7.38, geometry: 'radial', pc: 0, risk_score: 39.8,
    storm_flag: true, secondary_maneuverable: false,
    miss_rsw_km: { radial: 22.1, in_track: 7.4, cross_track: 1.1 },
  },
  {
    event_id: 5, secondary_name: 'SCS-01 B', secondary_norad: 58210,
    secondary_type: 'UNKNOWN', tca: '2026-07-26T23:02:12Z', miss_km: 32.021,
    vrel_kms: 5.11, geometry: 'radial', pc: 0, risk_score: 39.7,
    storm_flag: false, secondary_maneuverable: false,
    miss_rsw_km: { radial: 30.2, in_track: 9.8, cross_track: 2.4 },
  },
  {
    event_id: 6, secondary_name: 'TRANSPORTER-10 OBJ AD', secondary_norad: 59100,
    secondary_type: 'UNKNOWN', tca: '2026-07-26T02:27:09Z', miss_km: 41.233,
    vrel_kms: 12.9, geometry: 'radial', pc: 0, risk_score: 37.4,
    storm_flag: false, secondary_maneuverable: false,
    miss_rsw_km: { radial: 38.5, in_track: 13.1, cross_track: 3.2 },
  },
  {
    event_id: 7, secondary_name: 'TIGER-8', secondary_norad: 55671,
    secondary_type: 'PAYLOAD', tca: '2026-07-26T16:25:12Z', miss_km: 9.875,
    vrel_kms: 13.4, geometry: 'radial', pc: 4.42e-87, risk_score: 34.8,
    storm_flag: false, secondary_maneuverable: true,
    miss_rsw_km: { radial: 9.4, in_track: 2.8, cross_track: 0.6 },
  },
  {
    event_id: 8, secondary_name: 'GUOWANG TEST OBJ A', secondary_norad: 61234,
    secondary_type: 'UNKNOWN', tca: '2026-07-31T06:31:13Z', miss_km: 35.241,
    vrel_kms: 8.2, geometry: 'cross-track', pc: 0, risk_score: 33.3,
    storm_flag: false, secondary_maneuverable: false,
    miss_rsw_km: { radial: 4.1, in_track: 6.2, cross_track: 34.5 },
  },
]

export const SAMPLE_MANEUVERS: ManeuverOption[] = [
  {
    kind: 'cheapest-safe', burn_epoch: '2026-07-26T00:18:13Z', lead_time_min: 60,
    dv_total_ms: 0.05, dv_rsw_ms: { radial: 0, in_track: 0.05, cross_track: 0 },
    propellant_g: 0.34, post_burn_miss_km: 10.2, satisfies_constraints: true,
  },
  {
    kind: 'nominal', burn_epoch: '2026-07-25T22:18:13Z', lead_time_min: 180,
    dv_total_ms: 0.1, dv_rsw_ms: { radial: 0, in_track: 0.1, cross_track: 0 },
    propellant_g: 0.68, post_burn_miss_km: 11.7, satisfies_constraints: true,
  },
  {
    kind: 'conservative', burn_epoch: '2026-07-25T19:18:13Z', lead_time_min: 360,
    dv_total_ms: 0.2, dv_rsw_ms: { radial: 0, in_track: 0.2, cross_track: 0 },
    propellant_g: 1.36, post_burn_miss_km: 17.2, satisfies_constraints: true,
  },
]

/** CDM validation headline numbers (real results). */
export const CDM_STATS = {
  total: 15,
  detected: 11,
  detection_rate: 0.73,
  median_miss_ratio: 1.07,
  median_tca_err_s: 0.09,
  max_tca_err_s: 3.1,
}

// ============================================================
// B-plane fallback (5.2)
// ============================================================

// The engine's documented fixed 1σ combined covariance in RSW (km) — engine/pc.py.
// The in-track sigma (1.0 km) is absent because the assumed in-track encounter
// projects that axis out of the plane entirely.
const SIGMA_RADIAL_KM = 0.5
const SIGMA_CROSSTRACK_KM = 0.5
const DEFAULT_HBR_KM = 0.005

const scaleContours = (e: CovarianceEllipse): SigmaContour[] =>
  [1, 2, 3].map((level) => ({
    level,
    semi_major_km: e.semi_major_km * level,
    semi_minor_km: e.semi_minor_km * level,
    rotation_deg: e.rotation_deg,
  }))

/**
 * Offline B-plane geometry for a sample event, mirroring engine/viz/bplane.py.
 *
 * The sample events store only the miss magnitude per RSW axis and a relative-speed
 * scalar, so the true encounter plane is not recoverable. This assumes the common
 * in-track-dominated encounter: the B-plane is then the (radial, cross-track) plane,
 * the in-track miss projects out, and the ellipse axes are the radial and
 * cross-track sigmas directly. Numbers are consistent with the event card beside
 * it, and the UI labels the panel SAMPLE so the reader knows which they see.
 */
export function sampleBPlane(event: ScoredConjunction, realismFactor = 2): BPlane {
  const m = event.miss_rsw_km ?? { radial: event.miss_km, in_track: 0, cross_track: 0 }
  // Project out the in-track component (it lies along the assumed relative velocity).
  const xi = m.radial
  const zeta = m.cross_track
  const missNorm = Math.hypot(xi, zeta)

  // Radial sigma < cross-track sigma would flip the axes; they are equal here, so
  // the ellipse is a circle of radius 0.5 km at 0°.
  const ellipse: CovarianceEllipse = {
    semi_major_km: Math.max(SIGMA_RADIAL_KM, SIGMA_CROSSTRACK_KM),
    semi_minor_km: Math.min(SIGMA_RADIAL_KM, SIGMA_CROSSTRACK_KM),
    rotation_deg: 0,
  }

  const mahalanobis = Math.hypot(xi / SIGMA_RADIAL_KM, zeta / SIGMA_CROSSTRACK_KM)
  const pcFrom = (k: number) => {
    const det = k * SIGMA_RADIAL_KM ** 2 * (k * SIGMA_CROSSTRACK_KM ** 2)
    const quad = (mahalanobis * mahalanobis) / k
    return Math.min((DEFAULT_HBR_KM ** 2 / (2 * Math.sqrt(det))) * Math.exp(-0.5 * quad), 1)
  }

  const realismEllipse: CovarianceEllipse = {
    semi_major_km: ellipse.semi_major_km * Math.sqrt(realismFactor),
    semi_minor_km: ellipse.semi_minor_km * Math.sqrt(realismFactor),
    rotation_deg: ellipse.rotation_deg,
  }

  return {
    available: true,
    event_id: event.event_id,
    secondary_name: event.secondary_name,
    secondary_norad: event.secondary_norad,
    tca: event.tca,
    miss_bp: { xi, zeta },
    miss_norm_km: missNorm,
    miss_3d_km: event.miss_km,
    vrel_kms: event.vrel_kms,
    hbr_km: DEFAULT_HBR_KM,
    miss_inside_hbr: missNorm < DEFAULT_HBR_KM,
    ellipse,
    sigma_levels: scaleContours(ellipse),
    mahalanobis_sigma: mahalanobis,
    sigma_contour_containing_miss: [1, 2, 3].find((n) => mahalanobis <= n) ?? null,
    axes_rsw: { xi: [1, 0, 0], zeta: [0, 0, 1] },
    pc: pcFrom(1),
    realism: {
      factor: realismFactor,
      ellipse: realismEllipse,
      sigma_levels: scaleContours(realismEllipse),
      pc: pcFrom(realismFactor),
      mahalanobis_sigma: mahalanobis / Math.sqrt(realismFactor),
    },
    note:
      'Sample geometry — assumes an in-track-dominated encounter. Start the API for the ' +
      'true encounter plane derived from the full relative-velocity vector.',
  }
}
