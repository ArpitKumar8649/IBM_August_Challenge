"""Space-Track SATCAT enrichment.

Adds object metadata (type, radar cross-section, country) to catalog objects.
Used to derive the hard-body radius and to flag unmaneuverable secondaries
(debris / rocket bodies). Degrades gracefully: if login or a query fails, the
pipeline continues with default object info.

Rate limits: ~300 queries/min, ~3,000/day. We batch NORAD ids into single queries
and pace requests ~2 s apart (sessions drop under rapid fire).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import httpx

from engine.models import ObjectInfo

ST_LOGIN = "https://www.space-track.org/ajaxauth/login"
ST_SATCAT = "https://www.space-track.org/basicspacedata/query/class/satcat"

# Representative diameter (m) per RCS band, for hard-body radius when exact size
# is unknown. Conservative (slightly large) — overestimating HBR overstates Pc,
# which is the safe direction for a triage tool.
RCS_SIZE_M = {"SMALL": 0.5, "MEDIUM": 2.0, "LARGE": 10.0}
BATCH_SIZE = 200  # NORAD ids per SATCAT query
QUERY_PAUSE_S = 2.0


def _load_credentials() -> tuple[str, str]:
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    return os.environ.get("SPACETRACK_USERNAME", ""), os.environ.get("SPACETRACK_PASSWORD", "")


def login(client: httpx.Client) -> bool:
    """Authenticate via cookie session. Returns True on success."""
    user, pw = _load_credentials()
    if not user or not pw:
        return False
    try:
        client.post(ST_LOGIN, data={"identity": user, "password": pw})
        return True
    except httpx.HTTPError:
        return False


def _to_object_info(row: dict) -> ObjectInfo:
    rcs = (row.get("RCS_SIZE") or "").upper()
    return ObjectInfo(
        norad_id=int(row["NORAD_CAT_ID"]),
        object_type=(row.get("OBJECT_TYPE") or "UNKNOWN").upper(),
        country=row.get("COUNTRY") or "",
        rcs_size=rcs,
        size_m=RCS_SIZE_M.get(rcs, 1.0),
    )


def enrich(
    norad_ids: list[int], client: httpx.Client | None = None
) -> dict[int, ObjectInfo]:
    """Fetch SATCAT metadata for a list of NORAD ids. Returns {} on any failure."""
    if not norad_ids:
        return {}
    own_client = client is None
    http = client or httpx.Client(timeout=120.0)
    result: dict[int, ObjectInfo] = {}
    try:
        if not login(http):
            return {}
        time.sleep(QUERY_PAUSE_S)
        unique = sorted(set(norad_ids))
        for i in range(0, len(unique), BATCH_SIZE):
            batch = unique[i : i + BATCH_SIZE]
            id_list = ",".join(str(n) for n in batch)
            try:
                resp = http.get(f"{ST_SATCAT}/NORAD_CAT_ID/{id_list}/format/json/")
                resp.raise_for_status()
                for row in resp.json():
                    info = _to_object_info(row)
                    result[info.norad_id] = info
            except (httpx.HTTPError, ValueError, KeyError):
                continue  # skip this batch, keep the rest
            time.sleep(QUERY_PAUSE_S)
        return result
    finally:
        if own_client:
            http.close()
