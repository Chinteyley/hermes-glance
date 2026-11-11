"""pre_tool_call, pre_verify and transform_llm_output. None of them may raise: a raising
pre_tool_call blocks the edit it was meant to observe."""

from __future__ import annotations

import logging
import re

from . import capture, state
from .verdicts import FAILING, PASS

logger = logging.getLogger(__name__)

UI_SUFFIXES = (".tsx", ".jsx", ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".swift", ".kt", ".dart")
# Hermes's own file-writing tools (tools/file_tools.py). patch also takes V4A multi-file patches.
WRITE_TOOLS = frozenset({"write_file", "patch"})
_V4A_PATH = re.compile(r"^\*\*\* (?:Add File|Update File|Move to): (.+?)\s*$", re.M)

# Baseline capture runs inside the edit's own hook, which Hermes fails closed after 30 s. These cap it
# at about 3.6 s (lock, simctl then adb probe, screenshot); a simulator screenshot takes about 0.45 s.
BASELINE_FIND_TIMEOUT = 0.8
BASELINE_SHOT_TIMEOUT = 1.5
# A running glance_check holds the session lock while it settles; the edit does not wait for it.
BASELINE_LOCK_TIMEOUT = 0.5
MAX_NUDGE_ATTEMPT = 2

NOT_LOOKED = ("Glance: you changed UI files but have not looked at the screen. "
              "Call glance_check, then finish.")
NOT_SEEN = ("Glance: PASS means the screen changed, not that it changed correctly, and Glance could not show you "
            "the after screen ({compare}) as an image: the active model does not take images in tool results, or "
            "vision is off. Check the result against the request with what you have. If you cannot confirm it, "
            "say in your reply that you did not see it on screen.")


def is_ui_path(path: str) -> bool:
    return str(path).lower().endswith(UI_SUFFIXES)


def edited_paths(tool_name: str, args: dict) -> list[str]:
    if tool_name not in WRITE_TOOLS or not isinstance(args, dict):
        return []
    if tool_name == "patch" and args.get("mode") == "patch":
        return _V4A_PATH.findall(str(args.get("patch") or ""))
    path = args.get("path")
    return [path] if isinstance(path, str) and path else []


def pre_tool_call(tool_name: str = "", args: dict | None = None, session_id: str = "", *,
                  device: str = "", **kwargs) -> None:
    try:
        ui_paths = [p for p in edited_paths(tool_name, args or {}) if is_ui_path(p)]
        if not ui_paths:
            return None
        session_lock = state.lock(session_id)
        if session_lock.acquire(timeout=BASELINE_LOCK_TIMEOUT):
            try:
                if state.snapshot(session_id).phase is state.Phase.IDLE:
                    _baseline_quietly(session_id, device, tool_name, ui_paths[0])
            finally:
                session_lock.release()
        state.note_edit(session_id)
    except Exception:
        logger.warning("glance: pre_tool_call bookkeeping failed for %s", tool_name, exc_info=True)
    return None


def _baseline_quietly(session_id: str, device: str, tool_name: str, path: str) -> None:
    from .tools import take_baseline

    target = capture.find_target(device, timeout=BASELINE_FIND_TIMEOUT)
    if target is None:
        return
    try:
        take_baseline(session_id, target, BASELINE_SHOT_TIMEOUT, trigger_tool=tool_name, trigger_path=path)
    except capture.CaptureError as exc:
        logger.info("glance: no baseline before the edit: %s", exc)


def pre_verify(session_id: str = "", attempt: int = 0, changed_paths: list | None = None, **kwargs) -> dict | None:
    try:
        if attempt >= MAX_NUDGE_ATTEMPT or not any(is_ui_path(p) for p in changed_paths or ()):
            return None
        message = _nudge(session_id)
        if message:
            logger.info("glance: pre_verify continue, attempt %d, session %s: %s", attempt, session_id, message)
            return {"action": "continue", "message": message}
    except Exception:
        logger.warning("glance: pre_verify failed", exc_info=True)
    return None


def _nudge(session_id: str) -> str | None:
    snap = state.snapshot(session_id)
    if snap.phase in (state.Phase.BASELINED, state.Phase.STALE):
        return NOT_LOOKED
    if snap.phase is state.Phase.CHECKED and snap.check.verdict in FAILING:
        return _failure_message(snap.check)
    # A PASS the agent never saw gets one honest nudge, then the agent may finish.
    if snap.check and snap.check.verdict == PASS and snap.look is None:
        state.record_look(session_id, snap.check.id, state.TOLD)
        return NOT_SEEN.format(compare=snap.check.compare_png)
    return None


def _failure_message(check: state.Check) -> str:
    boxes = "; ".join(f"x {r['x']:.0%} y {r['y']:.0%} w {r['w']:.0%} h {r['h']:.0%}" for r in check.regions)
    where = f" Changed regions: {boxes}." if boxes else ""
    return (f"Glance: {check.verdict}. {check.reason}{where} Fix it, call glance_check again, "
            f"then finish.")


def transform_llm_output(response_text: str = "", session_id: str = "", **kwargs) -> str | None:
    try:
        snap = state.snapshot(session_id)
        check = snap.latest
        if check is None or not check.compare_png or check.id == snap.delivered_check_id:
            return None
        state.mark_delivered(session_id, check.id)
        line = f"MEDIA:{check.compare_png}"
        if line in response_text:
            return None
        return f"{response_text.rstrip()}\n\n{line}"
    except Exception:
        logger.warning("glance: transform_llm_output failed", exc_info=True)
        return None
