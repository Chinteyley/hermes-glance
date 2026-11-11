"""Find the running device, screenshot it, and wait for the screen to stop moving."""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

from . import diff

# Settle loop for glance_check. The first frame waits until FAST_REFRESH_SECONDS after the last UI
# edit (an unmeasured default for Expo Fast Refresh), then frames repeat until two in a row match.
FAST_REFRESH_SECONDS = 2.0
MIN_WAIT_SECONDS = 0.3
SETTLE_INTERVAL = 0.25
SETTLE_TIMEOUT = 5.0
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


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
    """The configured device if it is running, else the first booted iOS Simulator, else the first adb
    device. adb is asked only when no simulator matches: a cold `adb devices` starts the adb server."""
    for probe in (_booted_simulators, _adb_devices):
        targets = probe(timeout)
        found = next((t for t in targets if t.device_id == preferred), None) if preferred else next(iter(targets), None)
        if found:
            return found
    return None


def _run(argv: list[str], timeout: float, text: bool = True) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(argv, capture_output=True, text=text, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def _booted_simulators(timeout: float) -> list[Target]:
    proc = _run(["xcrun", "simctl", "list", "devices", "booted", "-j"], timeout)
    try:
        devices = json.loads(proc.stdout or "{}").get("devices", {}) if proc else {}
    except json.JSONDecodeError:
        return []
    return [Target("ios", d["udid"], d.get("name") or d["udid"])
            for runtime in devices.values() for d in runtime
            if d.get("state") == "Booted" and d.get("udid")]


def _adb_devices(timeout: float) -> list[Target]:
    proc = _run(["adb", "devices", "-l"], timeout)
    if proc is None or proc.returncode != 0:
        return []
    targets = []
    for line in proc.stdout.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "device":
            model = re.search(r"\bmodel:(\S+)", line)
            targets.append(Target("android", fields[0], model.group(1).replace("_", " ") if model else fields[0]))
    return targets


def screenshot(target: Target, dest: Path, timeout: float = 3.0) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if target.platform == "android":
        proc = _run(["adb", "-s", target.device_id, "exec-out", "screencap", "-p"], timeout, text=False)
        if proc is None or proc.returncode != 0 or not proc.stdout.startswith(PNG_MAGIC):
            raise CaptureError(f"adb screencap failed: {_stderr(proc)}")
        dest.write_bytes(proc.stdout)
        return dest
    proc = _run(["xcrun", "simctl", "io", target.device_id, "screenshot", "--type=png", str(dest)], timeout)
    if proc is None or proc.returncode != 0 or not dest.is_file():
        raise CaptureError(f"simctl screenshot failed: {_stderr(proc)}")
    return dest


def _stderr(proc: subprocess.CompletedProcess | None) -> str:
    if proc is None:
        return "the command did not run or timed out"
    err = proc.stderr.decode(errors="replace") if isinstance(proc.stderr, bytes) else (proc.stderr or "")
    return err.strip()[:200] or f"exit code {proc.returncode}"


def settle(target: Target, dest: Path, last_edit_at: float | None = None,
           timeout: float = SETTLE_TIMEOUT) -> tuple[Path, bool]:
    """Screenshot into `dest` once two consecutive frames match. Returns (dest, settled); on timeout
    `dest` holds the last frame and settled is False."""
    since_edit = time.time() - last_edit_at if last_edit_at else FAST_REFRESH_SECONDS
    time.sleep(max(MIN_WAIT_SECONDS, FAST_REFRESH_SECONDS - since_edit))
    spare = dest.with_name(f"{dest.stem}.prev{dest.suffix}")
    deadline = time.monotonic() + timeout
    screenshot(target, spare)
    try:
        while True:
            time.sleep(SETTLE_INTERVAL)
            screenshot(target, dest)
            if _same_screen(spare, dest):
                return dest, True
            if time.monotonic() >= deadline:
                return dest, False
            dest.replace(spare)
    finally:
        spare.unlink(missing_ok=True)


def _same_screen(a: Path, b: Path) -> bool:
    with Image.open(a) as first, Image.open(b) as second:
        return diff.same_screen(first, second)
