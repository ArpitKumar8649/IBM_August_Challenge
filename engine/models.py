"""Shared data models — the vocabulary every OrbitWarden plane speaks.

These models are the contract between the physics engine, the API, the Granite
agent's tools, and the dashboard. Define them once, here.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TLEData(BaseModel):
    """A parsed two-line element set plus cheap derived orbital geometry.

    Derived fields (perigee/apogee altitude) are computed once at parse time so
    the altitude-band pre-filter can screen thousands of objects without ever
    running SGP4.
    """

    norad_id: int = Field(description="NORAD catalog number, e.g. 25544 for the ISS")
    name: str = Field(description="Object name as published in the catalog")
    line1: str = Field(description="TLE line 1 (69 chars)")
    line2: str = Field(description="TLE line 2 (69 chars)")
    epoch: datetime = Field(description="TLE epoch, UTC")
    inclination_deg: float = Field(description="Orbital inclination")
    perigee_alt_km: float = Field(description="Perigee altitude above the WGS-72 Earth radius")
    apogee_alt_km: float = Field(description="Apogee altitude above the WGS-72 Earth radius")

    @property
    def age_days(self) -> float:
        """TLE age in days relative to now — used to flag stale ephemerides."""
        from datetime import datetime, timezone

        return (datetime.now(timezone.utc) - self.epoch).total_seconds() / 86400.0


class ConjunctionCandidate(BaseModel):
    """A close approach found by the screening engine.

    Phase 1 produces coarse candidates (60 s grid + parabolic refinement).
    Phase 2 adds golden-section TCA refinement, RSW geometry, object metadata,
    and the composite risk score.
    """

    primary_norad: int
    secondary_norad: int
    secondary_name: str
    tca: datetime = Field(description="Time of closest approach, UTC")
    miss_distance_km: float = Field(description="Minimum separation at TCA")
    relative_velocity_kms: float = Field(description="Relative speed at TCA")
    coarse: bool = Field(default=True, description="True until Phase 2 refines the TCA")


class ScreeningConfig(BaseModel):
    """Knobs for one screening run — surfaced in the UI with stated assumptions."""

    window_days: float = Field(default=7.0, description="Look-ahead window")
    time_step_s: float = Field(default=60.0, description="Coarse-scan time step")
    miss_threshold_km: float = Field(default=100.0, description="Distance below which a grid point is a candidate")
    band_margin_km: float = Field(default=150.0, description="Altitude-band overlap margin (widen during storms)")
    chunk_size: int = Field(default=500, description="Candidates propagated per vectorized chunk")


class ScreeningRun(BaseModel):
    """Metadata for one screening pass — persisted per run for auditability."""

    primary_norad: int
    primary_name: str
    run_at: datetime
    window_days: float
    catalog_size: int = Field(description="Objects considered before band filtering")
    band_filtered_size: int = Field(description="Objects surviving the altitude-band pre-filter")
    candidates_found: int
    duration_s: float


class ObjectInfo(BaseModel):
    """SATCAT metadata for a catalog object — feeds HBR and maneuverability."""

    norad_id: int
    object_type: str = Field(default="UNKNOWN", description="PAYLOAD / ROCKET BODY / DEBRIS / UNKNOWN")
    country: str = ""
    rcs_size: str = Field(default="", description="SMALL / MEDIUM / LARGE radar cross-section band")
    size_m: float = Field(default=1.0, description="Representative diameter (m) for hard-body radius")


class SpaceWeatherState(BaseModel):
    """Geomagnetic conditions — drives the storm flag."""

    max_kp_3day: float = Field(default=0.0, description="Max forecast Kp over the next 3 days")
    kp_forecast: list[dict] = Field(default_factory=list)
    active_storm: bool = Field(default=False, description="A DONKI geomagnetic-storm notification is current")
    fetched_at: datetime


class ScoredConjunction(BaseModel):
    """A fully analyzed conjunction — everything the dashboard and agent see."""

    primary_norad: int
    secondary_norad: int
    secondary_name: str
    tca: datetime
    miss_distance_km: float
    relative_velocity_kms: float
    # Phase 2: refined geometry + risk
    miss_r_km: float = Field(description="Miss vector radial component (km)")
    miss_s_km: float = Field(description="Miss vector in-track component (km)")
    miss_w_km: float = Field(description="Miss vector cross-track component (km)")
    geometry: str = Field(description="in-track / radial / cross-track dominant")
    hbr_km: float = Field(description="Hard-body radius (km)")
    pc: float = Field(description="Collision probability (Alfriend-Foster, fixed covariance)")
    secondary_type: str = "UNKNOWN"
    secondary_maneuverable: bool = True
    storm_flag: bool = False
    risk_score: float = Field(default=0.0, description="Transparent composite triage score, 0-100")


class ManeuverConstraints(BaseModel):
    """Operator constraints on avoidance-maneuver selection."""

    fuel_margin_g: float | None = Field(
        default=None, description="Propellant that must remain after the burn (g)"
    )
    min_post_burn_miss_km: float = Field(
        default=0.0, description="Required post-burn miss distance (km)"
    )
    blackout_windows: list[tuple[datetime, datetime]] = Field(
        default_factory=list, description="UTC windows in which a burn is not allowed"
    )


class ManeuverOption(BaseModel):
    """One candidate avoidance maneuver, scored by the engine."""

    burn_epoch: datetime
    lead_time_min: float = Field(description="Minutes before TCA the burn occurs")
    dv_r_ms: float = Field(description="Radial Δv component (m/s)")
    dv_s_ms: float = Field(description="In-track Δv component (m/s)")
    dv_w_ms: float = Field(description="Cross-track Δv component (m/s)")
    dv_total_ms: float = Field(description="Total Δv magnitude (m/s)")
    propellant_g: float = Field(description="Propellant consumed (g)")
    post_burn_miss_km: float = Field(description="Predicted miss distance after the burn (km)")
    kind: str = Field(default="", description="cheapest-safe / nominal / conservative")
    satisfies_constraints: bool = True


# ============================================================
# Phase A — external data source models (NASA / Space-Track / Open Notify)
# ============================================================


class NeoCloseApproach(BaseModel):
    """A single close-approach event for a near-Earth object."""

    date: str
    relative_velocity_kmh: float = Field(description="relative velocity (km/h)")
    miss_distance_km: float = Field(description="miss distance (km)")
    miss_distance_lunar: float = Field(default=0.0, description="miss distance (lunar distances)")
    orbiting_body: str = "Earth"


class NeoObject(BaseModel):
    """A near-Earth object from the NASA NEO Feed."""

    neo_id: str
    name: str
    is_potentially_hazardous: bool = False
    estimated_diameter_km: float = Field(default=0.0, description="max estimated diameter (km)")
    close_approaches: list[NeoCloseApproach] = Field(default_factory=list)


class EpicImage(BaseModel):
    """A full-disc Earth image from NASA EPIC (DSCOVR)."""

    identifier: str
    date: str
    caption: str = ""
    centroid_lat: float = 0.0
    centroid_lon: float = 0.0
    image_url: str = Field(default="", description="constructed archive image URL")


class ApodEntry(BaseModel):
    """NASA Astronomy Picture of the Day."""

    title: str
    explanation: str = ""
    url: str = ""
    hd_url: str = ""
    media_type: str = "image"  # "image" or "video"
    date: str = ""


class IssPosition(BaseModel):
    """Live ISS position (from Open Notify, or TLE-computed fallback)."""

    latitude: float
    longitude: float
    timestamp: float = 0.0
    source: str = "open-notify"  # or "tle-computed"


class Astronaut(BaseModel):
    """A human currently in space."""

    name: str
    craft: str = ""


class Astronauts(BaseModel):
    """Humans currently in space (Open Notify)."""

    number: int
    people: list[Astronaut] = Field(default_factory=list)


class CountryStats(BaseModel):
    """Catalog statistics for one country/orbiter (Space-Track boxscore)."""

    country: str
    country_code: str = ""
    orbital_payloads: int = Field(default=0, description="active payloads in orbit")
    orbital_rocket_bodies: int = Field(default=0, description="orbital rocket bodies")
    orbital_debris: int = Field(default=0, description="orbital debris")
    orbital_total: int = Field(default=0, description="total objects currently in orbit")
    decayed_total: int = Field(default=0, description="total objects decayed (reentered)")
    country_total: int = Field(default=0, description="all-time total objects")

    @property
    def active_payloads(self) -> int:
        """Alias for the active-payload count (used by tools/dashboards)."""
        return self.orbital_payloads


class DecayEvent(BaseModel):
    """A predicted reentry/decay event (Space-Track decay class)."""

    norad_id: int
    intl_des: str = ""
    country: str = ""
    decay_epoch: str = Field(default="", description="predicted decay epoch")
    msg_epoch: str = ""
    msg_type: str = ""


class LaunchSite(BaseModel):
    """A launch site (Space-Track launch_site class)."""

    code: str
    name: str = ""
    country: str = ""


class Paper(BaseModel):
    """A scholarly paper from NASA ADS."""

    bibcode: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: str = ""
    abstract: str = ""
    url: str = ""
