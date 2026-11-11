"""Find the running device and screenshot it. No image logic lives here."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Target:
    platform: str
    device_id: str
    name: str

    def to_dict(self) -> dict:
        return asdict(self)


class CaptureError(Exception):
    pass


def find_target(preferred: str = "", timeout: float = 2.0) -> Target | None:
    try:
        proc = subprocess.run(
            ["xcrun", "simctl", "list", "devices", "booted", "-j"],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        devices = json.loads(proc.stdout or "{}").get("devices", {})
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    booted = [
        Target("ios", d["udid"], d.get("name", d["udid"]))
        for runtime in devices.values() for d in runtime
        if d.get("state") == "Booted" and d.get("udid")
    ]
    if preferred:
        return next((t for t in booted if t.device_id == preferred), None)
    return booted[0] if booted else None


def screenshot(target: Target, dest: Path, timeout: float = 3.0) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            ["xcrun", "simctl", "io", target.device_id, "screenshot", "--type=png", str(dest)],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CaptureError(f"simctl screenshot failed: {exc}") from exc
    if proc.returncode != 0 or not dest.is_file():
        raise CaptureError(f"simctl screenshot failed: {(proc.stderr or '').strip()[:200]}")
    return dest
