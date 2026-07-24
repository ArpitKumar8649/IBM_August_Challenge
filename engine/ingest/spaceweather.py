"""Space-weather ingestion — the storm flag.

Geomagnetic storms heat and expand the upper atmosphere, increasing drag and
making TLE predictions diverge from reality. Any conjunction whose prediction
window straddles a storm has inflated uncertainty; the correct action is to
re-screen closer to TCA, not to trust the miss distance. This module fetches the
NOAA SWPC 3-day Kp forecast and NASA DONKI storm notifications and exposes a
storm flag for an event's TCA.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from engine.models import SpaceWeatherState

SWPC_FORECAST_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
DONKI_URL = "https://api.nasa.gov/DONKI/notifications"

STORM_KP_THRESHOLD = 6.0  # Kp >= 6 -> storm-level drag uncertainty


def _nasa_key() -> str:
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("NASA_API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("NASA_API_KEY", "DEMO_KEY")


def fetch_space_weather(client: httpx.Client | None = None) -> SpaceWeatherState:
    """Fetch current geomagnetic conditions. Degrades to a calm state on failure."""
    own_client = client is None
    http = client or httpx.Client(timeout=60.0)
    now = datetime.now(timezone.utc)
    max_kp = 0.0
    forecast: list[dict] = []
    active_storm = False
    try:
        # NOAA SWPC 3-day Kp forecast (no auth). Each row is a dict:
        # {"time_tag": "...", "kp": float, "observed": ..., "noaa_scale": ...}
        resp = http.get(SWPC_FORECAST_URL)
        resp.raise_for_status()
        rows = resp.json()
        for row in rows:
            try:
                kp = float(row["kp"])
                forecast.append({"time": row["time_tag"], "kp": kp})
                max_kp = max(max_kp, kp)
            except (ValueError, KeyError, TypeError):
                continue

        # NASA DONKI geomagnetic-storm notifications over the last 3 days.
        start = (now - timedelta(days=3)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        resp = http.get(
            DONKI_URL,
            params={
                "startDate": start,
                "endDate": end,
                "type": "GST",
                "api_key": _nasa_key(),
            },
        )
        if resp.status_code == 200:
            active_storm = len(resp.json()) > 0
    except httpx.HTTPError:
        pass  # calm defaults
    finally:
        if own_client:
            http.close()

    return SpaceWeatherState(
        max_kp_3day=max_kp,
        kp_forecast=forecast,
        active_storm=active_storm,
        fetched_at=now,
    )


def storm_flag_for_event(tca: datetime, state: SpaceWeatherState) -> bool:
    """True if the [now, TCA] window straddles storm-level geomagnetic activity.

    Flags when either (a) a DONKI storm notification is currently active, or
    (b) the SWPC forecast predicts Kp >= STORM_KP_THRESHOLD before the TCA.
    """
    if state.active_storm:
        return True
    now = datetime.now(timezone.utc)
    if tca.tzinfo is None:
        tca = tca.replace(tzinfo=timezone.utc)
    for entry in state.kp_forecast:
        try:
            t = datetime.fromisoformat(entry["time"]).replace(tzinfo=timezone.utc)
        except (ValueError, KeyError):
            continue
        if now <= t <= tca and entry.get("kp", 0.0) >= STORM_KP_THRESHOLD:
            return True
    return False
