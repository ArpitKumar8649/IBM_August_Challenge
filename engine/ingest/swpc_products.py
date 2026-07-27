"""NOAA SWPC multi-signal space-weather products.

Extends the storm flag from a single Kp forecast to a **multi-signal** picture:
solar-wind magnetic field (Bt, Bz), solar-wind speed, X-ray flux (flares),
energetic proton flux (SEP events), and the 10.7 cm radio flux (F10.7 proxy that
drives the NRLMSISE-00 drag model).

A composite storm-risk indicator (0-100) combines all signals into one number
with a qualitative level (quiet / unsettled / active / storm / severe) and the
list of active drivers — so the operator sees *why* the risk is elevated.

Verified endpoints (2026-07-27):
  · solar-wind-mag-field  → bt, bz_gsm, time_tag
  · solar-wind-speed      → proton_speed, time_tag
  · xrays-6-hour (GOES)   → flux (0.1-0.8 nm), time_tag
  · integral-protons-1-day (GOES) → flux (>=10 MeV), time_tag
  · 10cm-flux             → flux (sfu), time_tag
  · noaa-planetary-k-index-forecast → Kp forecast (already used)

No auth. Cache TTL 5 min (space weather changes fast). Values may be strings.
"""

from __future__ import annotations

import httpx

from engine.ingest.cache import DiskCache
from engine.models import ProtonState, SolarWindState, StormRiskComposite, XrayState

SWPC = "https://services.swpc.noaa.gov"
TTL = 300  # 5 min

# Thresholds for the composite storm-risk indicator.
KP_STORM = 6.0  # Kp >= 6 → geomagnetic storm
BZ_SOUTHWARD = -5.0  # Bz <= -5 nT → strong southward IMF (storm driver)
SPEED_FAST = 600.0  # solar wind >= 600 km/s → fast stream / HSS
SEP_THRESHOLD = 10.0  # proton flux >= 10 pfu → SEP event (NOAA S-scale)


def _get_json(client: httpx.Client, url: str):
    try:
        resp = client.get(url, timeout=20.0)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


def _latest_entry(data: list | None) -> dict:
    """Return the last entry of a SWPC time-series list (or {})."""
    if data and isinstance(data, list) and len(data) > 0:
        return data[-1]
    return {}


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# --- individual products ----------------------------------------------------


def fetch_solar_wind(client: httpx.Client | None = None) -> SolarWindState:
    """Solar-wind magnetic field (Bt, Bz) + speed + F10.7 proxy."""
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            mag = _latest_entry(_get_json(http, f"{SWPC}/products/summary/solar-wind-mag-field.json"))
            speed = _latest_entry(_get_json(http, f"{SWPC}/products/summary/solar-wind-speed.json"))
            flux10 = _latest_entry(_get_json(http, f"{SWPC}/products/summary/10cm-flux.json"))
            return SolarWindState(
                bt_nt=_to_float(mag.get("bt")),
                bz_gsm_nt=_to_float(mag.get("bz_gsm")),
                speed_kms=_to_float(speed.get("proton_speed")),
                f107_sfu=_to_float(flux10.get("flux"), 150.0),
                time_tag=mag.get("time_tag", ""),
            ).model_dump()
        finally:
            if own:
                http.close()

    try:
        raw = cache.get_or_set("swpc_solar_wind", _fetch, ttl_s=TTL)
        return SolarWindState.model_validate(raw)
    except Exception:  # noqa: BLE001
        return SolarWindState()


def fetch_xray_flux(client: httpx.Client | None = None) -> XrayState:
    """GOES X-ray flux (0.1-0.8 nm) and flare class."""
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            # Filter to the 0.1-0.8 nm (long) channel, take the latest.
            data = _get_json(http, f"{SWPC}/json/goes/primary/xrays-6-hour.json") or []
            long_channel = [d for d in data if d.get("energy") == "0.1-0.8nm"]
            entry = _latest_entry(long_channel or data)
            flux = _to_float(entry.get("flux"))
            return XrayState(
                flux_w_m2=flux,
                flare_class=_xray_class(flux),
                time_tag=entry.get("time_tag", ""),
            ).model_dump()
        finally:
            if own:
                http.close()

    try:
        raw = cache.get_or_set("swpc_xray", _fetch, ttl_s=TTL)
        return XrayState.model_validate(raw)
    except Exception:  # noqa: BLE001
        return XrayState()


def _xray_class(flux_w_m2: float) -> str:
    """Map X-ray flux (W/m²) to the GOES flare class (A/B/C/M/X)."""
    if flux_w_m2 >= 1e-4:
        return "X"
    if flux_w_m2 >= 1e-5:
        return "M"
    if flux_w_m2 >= 1e-6:
        return "C"
    if flux_w_m2 >= 1e-7:
        return "B"
    return "A"


def fetch_proton_flux(client: httpx.Client | None = None) -> ProtonState:
    """GOES integral proton flux (>=10 MeV) and SEP-event flag."""
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            data = _get_json(http, f"{SWPC}/json/goes/primary/integral-protons-1-day.json") or []
            # Use the >=10 MeV channel (the NOAA SEP threshold channel).
            ten_mev = [d for d in data if "10" in str(d.get("energy", ""))]
            entry = _latest_entry(ten_mev or data)
            flux = _to_float(entry.get("flux"))
            return ProtonState(
                flux_pfu=flux,
                sep_active=flux >= SEP_THRESHOLD,
                time_tag=entry.get("time_tag", ""),
            ).model_dump()
        finally:
            if own:
                http.close()

    try:
        raw = cache.get_or_set("swpc_proton", _fetch, ttl_s=TTL)
        return ProtonState.model_validate(raw)
    except Exception:  # noqa: BLE001
        return ProtonState()


# --- composite storm-risk indicator -----------------------------------------


def _risk_level(score: float) -> str:
    if score >= 80:
        return "severe"
    if score >= 60:
        return "storm"
    if score >= 40:
        return "active"
    if score >= 20:
        return "unsettled"
    return "quiet"


def storm_risk_composite(
    kp_max_3day: float,
    solar_wind: SolarWindState | None = None,
    xray: XrayState | None = None,
    proton: ProtonState | None = None,
) -> StormRiskComposite:
    """Combine all space-weather signals into one 0-100 storm-risk score.

    Weighting (each contributes up to its cap; total capped at 100):
      · Kp forecast        — up to 40 (the primary geomagnetic indicator)
      · Southward Bz       — up to 25 (strong southward IMF drives storms)
      · Fast solar wind    — up to 15 (high-speed streams / CME arrival)
      · X-ray flare class  — up to 10 (solar activity / precursor)
      · SEP event          — up to 10 (radiation risk to electronics)
    """
    drivers: list[str] = []
    score = 0.0

    # Kp (up to 40): linear from 0 at Kp=0 to 40 at Kp=8+.
    kp_score = min(kp_max_3day / 8.0, 1.0) * 40.0
    score += kp_score
    if kp_max_3day >= KP_STORM:
        drivers.append(f"Kp forecast {kp_max_3day:.0f} (geomagnetic storm)")

    bz = solar_wind.bz_gsm_nt if solar_wind else 0.0
    speed = solar_wind.speed_kms if solar_wind else 0.0
    f107 = solar_wind.f107_sfu if solar_wind else 150.0

    # Southward Bz (up to 25): scales with how negative Bz is.
    if bz <= BZ_SOUTHWARD:
        bz_score = min(abs(bz) / 20.0, 1.0) * 25.0
        score += bz_score
        drivers.append(f"Bz {bz:.1f} nT southward")

    # Fast solar wind (up to 15).
    if speed >= SPEED_FAST:
        speed_score = min((speed - SPEED_FAST) / 400.0, 1.0) * 15.0
        score += speed_score
        drivers.append(f"solar wind {speed:.0f} km/s")

    # X-ray flare class (up to 10): A=0, B=2, C=4, M=7, X=10.
    xray_class = xray.flare_class if xray else "A"
    xray_scores = {"A": 0.0, "B": 2.0, "C": 4.0, "M": 7.0, "X": 10.0}
    xray_score = xray_scores.get(xray_class, 0.0)
    score += xray_score
    if xray_class in ("M", "X"):
        drivers.append(f"{xray_class}-class solar flare")

    # SEP event (up to 10).
    sep_active = proton.sep_active if proton else False
    if sep_active:
        score += 10.0
        drivers.append("solar energetic particle event")

    score = min(score, 100.0)
    return StormRiskComposite(
        score=round(score, 1),
        level=_risk_level(score),
        drivers=drivers,
        kp_max_3day=kp_max_3day,
        bz_gsm_nt=bz,
        speed_kms=speed,
        xray_class=xray_class,
        sep_active=sep_active,
        f107_sfu=f107,
    )
