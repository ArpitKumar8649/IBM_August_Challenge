"""NASA DONKI — full space-weather notification types.

Extends the DONKI integration from Geomagnetic Storm (GST) only to the complete
notification set: GST, CME (coronal mass ejection), FLR (solar flare), HSS
(high-speed stream), SEP (solar energetic particles), RBE (radiation belt
enhancement), and more.

CME → GST causal chains are modeled: a CME notification often precedes the GST it
causes, so we surface "CME detected → geomagnetic storm expected" as a predictive
signal (drag will increase when the CME arrives).

Verified endpoint (2026-07-27):
  GET https://api.nasa.gov/DONKI/notifications?startDate=…&endDate=…&api_key=…
  → JSON array of notifications (all types when no `type` filter)
  → fields: messageID, messageType, messageIssueTime, messageURL, messageBody

Cache TTL 1 h.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import httpx

from engine.ingest.cache import DiskCache
from engine.ingest.nasa_open import _nasa_key
from engine.models import DonkiNotification

API_BASE = "https://api.nasa.gov"
TTL = 3600  # 1 h

# Notification types and their operational meaning.
NOTIFICATION_TYPES = {
    "GST": "Geomagnetic storm — drag inflation",
    "CME": "Coronal mass ejection — precursor to geomagnetic storms",
    "FLR": "Solar flare — X-ray burst",
    "HSS": "High-speed solar wind stream — sustained drag increase",
    "SEP": "Solar energetic particles — radiation risk to electronics",
    "RBE": "Radiation belt enhancement — spacecraft charging risk",
    "IPS": "Interplanetary shock",
    "MPC": "Magnetopause crossing",
    "WDS": "Warning (general)",
    "Report": "Space weather report",
}

# Types that are predictive precursors to geomagnetic storms (drag inflation).
STORM_PRECURSORS = {"CME", "HSS", "IPS"}
STORM_TYPES = {"GST"}


def _summarize(body: str, max_len: int =200) -> str:
    """Extract a short summary from the (long) DONKI message body."""
    if not body:
        return ""
    # The body is a multi-line text block; take the first meaningful lines.
    lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("##")]
    summary = " ".join(lines)
    return summary[:max_len] + ("..." if len(summary) > max_len else "")


def _parse_notifications(data: list) -> list[dict]:
    notifications = []
    for n in data:
        notifications.append(
            DonkiNotification(
                message_id=n.get("messageID", ""),
                message_type=n.get("messageType", ""),
                issue_time=n.get("messageIssueTime", ""),
                message_url=n.get("messageURL", ""),
                summary=_summarize(n.get("messageBody", "")),
            ).model_dump()
        )
    return notifications


def fetch_donki_all(
    start_date: date | None = None,
    end_date: date | None = None,
    client: httpx.Client | None = None,
) -> list[DonkiNotification]:
    """Fetch all DONKI notifications over a date range (default: last 7 days)."""
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=7)
    params = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "api_key": _nasa_key(),
    }
    cache = DiskCache()

    def _fetch():
        own = client is None
        http = client or httpx.Client()
        try:
            resp = http.get(f"{API_BASE}/DONKI/notifications", params=params, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            return _parse_notifications(data) if isinstance(data, list) else []
        except (httpx.HTTPError, ValueError):
            return []
        finally:
            if own:
                http.close()

    try:
        raw = cache.get_or_set("donki_all", _fetch, params=params, ttl_s=TTL)
        return [DonkiNotification.model_validate(n) for n in raw]
    except Exception:  # noqa: BLE001
        return []


def analyze_donki(notifications: list[DonkiNotification]) -> dict:
    """Summarize DONKI notifications: counts by type, active storms, precursors.

    Returns a structured picture: how many of each type, whether a geomagnetic
    storm is active, and whether storm precursors (CME/HSS) are present — the
    predictive "a storm is building" signal.
    """
    by_type: dict[str, int] = {}
    for n in notifications:
        by_type[n.message_type] = by_type.get(n.message_type, 0) + 1

    active_storm = by_type.get("GST", 0) > 0
    precursors = [t for t in STORM_PRECURSORS if by_type.get(t, 0) > 0]

    # Predictive signal: precursors present but no active storm yet → storm building.
    storm_building = bool(precursors) and not active_storm

    return {
        "total": len(notifications),
        "by_type": by_type,
        "active_storm": active_storm,
        "storm_precursors": precursors,
        "storm_building": storm_building,
        "type_meanings": {
            t: NOTIFICATION_TYPES.get(t, "Other") for t in by_type
        },
    }
