"""Per-session Glance state. Skeleton: in memory; persistence in plugin_db replaces it.

The phase is derived, never stored:
  IDLE       no baseline, or the baseline's latest check passed with no UI edit since
  BASELINED  a baseline exists and nothing has checked it yet
  CHECKED    the baseline's latest check is as new as the latest UI edit
  STALE      a UI edit happened after the latest check
"""

from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

PLUGIN_NAME = "glance"


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


@dataclass
class Session:
    baseline: Baseline | None = None
    edit_seq: int = 0
    check: Check | None = None
    delivered_check_id: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def phase(self) -> Phase:
        if self.baseline is None:
            return Phase.IDLE
        check = self.check if self.check and self.check.baseline_id == self.baseline.id else None
        if check is None:
            return Phase.BASELINED
        if self.edit_seq > check.edit_seq:
            return Phase.STALE
        return Phase.IDLE if check.verdict == "PASS" else Phase.CHECKED


_sessions: dict[str, Session] = {}
_sessions_lock = threading.Lock()


def session(session_id: str) -> Session:
    with _sessions_lock:
        return _sessions.setdefault(session_id or "", Session())


def peek(session_id: str) -> Session | None:
    return _sessions.get(session_id or "")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def shots_dir(session_id: str) -> Path:
    from plugins.plugin_storage import plugin_data_dir

    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "default")[:80]
    return plugin_data_dir(PLUGIN_NAME) / "shots" / safe
