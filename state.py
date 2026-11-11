"""Per-session Glance state in plugin_db, so it survives a gateway restart.

The phase is derived, never stored:
  IDLE       no baseline, or the baseline's latest check passed with no UI edit since
  BASELINED  a baseline exists and nothing has checked it yet
  CHECKED    the baseline's latest check is as new as the latest UI edit
  STALE      a UI edit happened after the latest check
A PASS reads as IDLE, so the next UI edit takes a fresh baseline.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .verdicts import PASS

PLUGIN_NAME = "glance"

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS baselines (
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL, target_json TEXT NOT NULL, png_path TEXT NOT NULL,
        captured_at REAL NOT NULL, trigger_tool TEXT, trigger_path TEXT)""",
    """CREATE TABLE IF NOT EXISTS checks (
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL, baseline_id TEXT, after_png TEXT, compare_png TEXT,
        verdict TEXT NOT NULL, changed_ratio REAL, regions_json TEXT NOT NULL, reason TEXT NOT NULL,
        created_at REAL NOT NULL, edit_seq INTEGER NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS checks_by_session ON checks (session_id)",
    """CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY, baseline_id TEXT, edit_seq INTEGER NOT NULL DEFAULT 0,
        last_edit_at REAL, delivered_check_id TEXT)""",
)


class Phase(Enum):
    IDLE = "IDLE"
    BASELINED = "BASELINED"
    CHECKED = "CHECKED"
    STALE = "STALE"


@dataclass(frozen=True)
class Baseline:
    id: str
    png: str
    target: dict


@dataclass(frozen=True)
class Check:
    id: str
    baseline_id: str | None
    verdict: str
    reason: str
    regions: list[dict]
    compare_png: str | None
    edit_seq: int


@dataclass(frozen=True)
class Snapshot:
    edit_seq: int
    last_edit_at: float | None
    baseline: Baseline | None
    check: Check | None  # latest check against the active baseline
    latest: Check | None  # latest check of any kind, whose compare image gets delivered
    delivered_check_id: str | None

    @property
    def phase(self) -> Phase:
        if self.baseline is None:
            return Phase.IDLE
        if self.check is None:
            return Phase.BASELINED
        if self.edit_seq > self.check.edit_seq:
            return Phase.STALE
        return Phase.IDLE if self.check.verdict == PASS else Phase.CHECKED


def _key(session_id: str) -> str:
    return session_id or "default"


@contextmanager
def _db():
    from plugins.plugin_storage import plugin_db

    with closing(plugin_db(PLUGIN_NAME)) as conn:
        for statement in _SCHEMA:
            conn.execute(statement)
        with conn:
            yield conn


_CHECK_COLUMNS = "id, baseline_id, verdict, reason, regions_json, compare_png, edit_seq"


def _check(row) -> Check | None:
    if row is None:
        return None
    id_, baseline_id, verdict, reason, regions, compare_png, edit_seq = row
    return Check(id_, baseline_id, verdict, reason, json.loads(regions), compare_png, edit_seq)


def snapshot(session_id: str) -> Snapshot:
    key = _key(session_id)
    with _db() as conn:
        row = conn.execute("SELECT baseline_id, edit_seq, last_edit_at, delivered_check_id FROM sessions "
                           "WHERE session_id = ?", (key,)).fetchone()
        baseline_id, edit_seq, last_edit_at, delivered = row or (None, 0, None, None)
        baseline = check = None
        if baseline_id:
            b = conn.execute("SELECT id, png_path, target_json FROM baselines WHERE id = ?", (baseline_id,)).fetchone()
            baseline = Baseline(b[0], b[1], json.loads(b[2])) if b else None
            check = _check(conn.execute(f"SELECT {_CHECK_COLUMNS} FROM checks WHERE session_id = ? AND baseline_id = ? "
                                        "ORDER BY rowid DESC LIMIT 1", (key, baseline_id)).fetchone())
        latest = _check(conn.execute(f"SELECT {_CHECK_COLUMNS} FROM checks WHERE session_id = ? "
                                     "ORDER BY rowid DESC LIMIT 1", (key,)).fetchone())
    return Snapshot(edit_seq, last_edit_at, baseline, check, latest, delivered)


def _ensure_session(conn, key: str) -> None:
    conn.execute("INSERT OR IGNORE INTO sessions (session_id) VALUES (?)", (key,))


def note_edit(session_id: str) -> None:
    key = _key(session_id)
    with _db() as conn:
        _ensure_session(conn, key)
        conn.execute("UPDATE sessions SET edit_seq = edit_seq + 1, last_edit_at = ? WHERE session_id = ?",
                     (time.time(), key))


def save_baseline(session_id: str, baseline: Baseline, trigger_tool: str = "", trigger_path: str = "") -> None:
    key = _key(session_id)
    with _db() as conn:
        _ensure_session(conn, key)
        conn.execute("INSERT INTO baselines VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (baseline.id, key, json.dumps(baseline.target), baseline.png, time.time(), trigger_tool, trigger_path))
        conn.execute("UPDATE sessions SET baseline_id = ? WHERE session_id = ?", (baseline.id, key))


def save_check(session_id: str, check: Check, after_png: str | None, changed_ratio: float | None) -> None:
    key = _key(session_id)
    with _db() as conn:
        conn.execute("INSERT INTO checks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (check.id, key, check.baseline_id, after_png, check.compare_png, check.verdict, changed_ratio,
                      json.dumps(check.regions), check.reason, time.time(), check.edit_seq))


def mark_delivered(session_id: str, check_id: str) -> None:
    key = _key(session_id)
    with _db() as conn:
        _ensure_session(conn, key)
        conn.execute("UPDATE sessions SET delivered_check_id = ? WHERE session_id = ?", (check_id, key))


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def lock(session_id: str) -> threading.Lock:
    """Serialises baseline and check capture within one session; the database handles the rest."""
    with _locks_guard:
        return _locks.setdefault(_key(session_id), threading.Lock())


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def data_dir() -> Path:
    from plugins.plugin_storage import plugin_data_dir

    return plugin_data_dir(PLUGIN_NAME)


def shots_dir(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", _key(session_id))[:80]
    return data_dir() / "shots" / safe
