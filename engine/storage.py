"""Screening persistence — SQLite (schema maps 1:1 to the Postgres blueprint).

Stores screening runs, scored events, and object metadata so the API and
dashboard read from cache instead of re-computing. Swapping to Postgres later is
a matter of translating these few statements — the column layout is identical.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from engine.models import ObjectInfo, ScoredConjunction, ScreeningRun, TLEData

DEFAULT_DB = "data/orbitwarden.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS screening_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    primary_norad INTEGER NOT NULL,
    primary_name TEXT,
    run_at TEXT NOT NULL,
    window_days REAL,
    catalog_size INTEGER,
    band_filtered_size INTEGER,
    candidates_found INTEGER,
    duration_s REAL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    secondary_norad INTEGER,
    secondary_name TEXT,
    tca TEXT,
    miss_km REAL,
    vrel_kms REAL,
    miss_r REAL,
    miss_s REAL,
    miss_w REAL,
    geometry TEXT,
    hbr_km REAL,
    pc REAL,
    secondary_type TEXT,
    secondary_maneuverable INTEGER,
    storm_flag INTEGER,
    risk_score REAL
);
CREATE TABLE IF NOT EXISTS objects (
    norad_id INTEGER PRIMARY KEY,
    object_type TEXT,
    country TEXT,
    rcs_size TEXT,
    size_m REAL
);
CREATE TABLE IF NOT EXISTS run_context (
    run_id INTEGER PRIMARY KEY,
    events_json TEXT,
    catalog_json TEXT,
    objects_json TEXT
);
"""


class ScreeningStore:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def save_run(self, run: ScreeningRun) -> int:
        cur = self.conn.execute(
            """INSERT INTO screening_runs
               (primary_norad, primary_name, run_at, window_days, catalog_size,
                band_filtered_size, candidates_found, duration_s)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run.primary_norad,
                run.primary_name,
                run.run_at.isoformat(),
                run.window_days,
                run.catalog_size,
                run.band_filtered_size,
                run.candidates_found,
                run.duration_s,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def save_events(self, run_id: int, events: list[ScoredConjunction]) -> None:
        self.conn.executemany(
            """INSERT INTO events
               (run_id, secondary_norad, secondary_name, tca, miss_km, vrel_kms,
                miss_r, miss_s, miss_w, geometry, hbr_km, pc, secondary_type,
                secondary_maneuverable, storm_flag, risk_score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    run_id,
                    e.secondary_norad,
                    e.secondary_name,
                    e.tca.isoformat(),
                    e.miss_distance_km,
                    e.relative_velocity_kms,
                    e.miss_r_km,
                    e.miss_s_km,
                    e.miss_w_km,
                    e.geometry,
                    e.hbr_km,
                    e.pc,
                    e.secondary_type,
                    int(e.secondary_maneuverable),
                    int(e.storm_flag),
                    e.risk_score,
                )
                for e in events
            ],
        )
        self.conn.commit()

    def save_objects(self, infos: dict[int, ObjectInfo]) -> None:
        self.conn.executemany(
            """INSERT OR REPLACE INTO objects (norad_id, object_type, country, rcs_size, size_m)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (i.norad_id, i.object_type, i.country, i.rcs_size, i.size_m)
                for i in infos.values()
            ],
        )
        self.conn.commit()

    def latest_run(self, primary_norad: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM screening_runs WHERE primary_norad = ? ORDER BY id DESC LIMIT 1",
            (primary_norad,),
        ).fetchone()
        return dict(row) if row else None

    def events_for_run(self, run_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE run_id = ? ORDER BY risk_score DESC", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def save_context(
        self,
        run_id: int,
        events: list[ScoredConjunction],
        catalog: dict[int, TLEData],
        object_info: dict[int, ObjectInfo],
    ) -> None:
        """Persist the full context the API/agent need to serve a run without
        re-screening: scored events, the candidate catalog TLEs, and object info."""
        self.conn.execute(
            "INSERT OR REPLACE INTO run_context (run_id, events_json, catalog_json, objects_json) "
            "VALUES (?, ?, ?, ?)",
            (
                run_id,
                json.dumps([e.model_dump(mode="json") for e in events]),
                json.dumps({str(k): v.model_dump(mode="json") for k, v in catalog.items()}),
                json.dumps({str(k): v.model_dump(mode="json") for k, v in object_info.items()}),
            ),
        )
        self.conn.commit()

    def load_context(self, run_id: int) -> dict | None:
        """Load the persisted context for a run, reconstructed into models."""
        row = self.conn.execute(
            "SELECT * FROM run_context WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        events = [ScoredConjunction.model_validate(e) for e in json.loads(row["events_json"])]
        catalog = {
            int(k): TLEData.model_validate(v) for k, v in json.loads(row["catalog_json"]).items()
        }
        object_info = {
            int(k): ObjectInfo.model_validate(v) for k, v in json.loads(row["objects_json"]).items()
        }
        return {"events": events, "catalog": catalog, "object_info": object_info}

    def close(self) -> None:
        self.conn.close()
