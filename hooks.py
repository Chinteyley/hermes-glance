"""pre_tool_call, pre_verify and transform_llm_output. None of them may raise: a raising
pre_tool_call blocks the edit it was meant to observe."""

from __future__ import annotations

import logging
import re

from . import capture, state
from .verdicts import FAILING

logger = logging.getLogger(__name__)

UI_SUFFIXES = (".tsx", ".jsx", ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".swift", ".kt", ".dart")
# Hermes's own file-writing tools (tools/file_tools.py). patch also takes V4A multi-file patches.
WRITE_TOOLS = frozenset({"write_file", "patch"})
_V4A_PATH = re.compile(r"^\*\*\* (?:Add File|Update File|Move to): (.+?)\s*$", re.M)

# Baseline capture runs inside the edit's own hook, which Hermes fails closed after 30 s.
BASELINE_FIND_TIMEOUT = 1.5
BASELINE_SHOT_TIMEOUT = 2.5
MAX_NUDGE_ATTEMPT = 2

NOT_LOOKED = ("Glance: you changed UI files but have not looked at the screen. "
              "Call glance_check, then finish.")


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
        if not any(is_ui_path(p) for p in edited_paths(tool_name, args or {})):
            return None
        sess = state.session(session_id)
        with sess.lock:
            if sess.phase() is state.Phase.IDLE:
                _baseline_quietly(sess, session_id, device)
            sess.edit_seq += 1
    except Exception:
        logger.warning("glance: pre_tool_call bookkeeping failed for %s", tool_name, exc_info=True)
    return None


def _baseline_quietly(sess: state.Session, session_id: str, device: str) -> None:
    from .tools import take_baseline

    target = capture.find_target(device, timeout=BASELINE_FIND_TIMEOUT)
    if target is None:
        return
    try:
        take_baseline(sess, session_id, target, timeout=BASELINE_SHOT_TIMEOUT)
    except capture.CaptureError as exc:
        logger.info("glance: no baseline before the edit: %s", exc)


def pre_verify(session_id: str = "", attempt: int = 0, changed_paths: list | None = None, **kwargs) -> dict | None:
    try:
        if attempt >= MAX_NUDGE_ATTEMPT or not any(is_ui_path(p) for p in changed_paths or ()):
            return None
        sess = state.peek(session_id)
        if sess is None:
            return None
        phase = sess.phase()
        if phase in (state.Phase.BASELINED, state.Phase.STALE):
            return {"action": "continue", "message": NOT_LOOKED}
        if phase is state.Phase.CHECKED and sess.check.verdict in FAILING:
            return {"action": "continue", "message": _failure_message(sess.check)}
    except Exception:
        logger.warning("glance: pre_verify failed", exc_info=True)
    return None


def _failure_message(check: state.Check) -> str:
    boxes = "; ".join(f"x {r['x']:.0%} y {r['y']:.0%} w {r['w']:.0%} h {r['h']:.0%}" for r in check.regions)
    where = f" Changed regions: {boxes}." if boxes else ""
    return (f"Glance: {check.verdict}. {check.reason}{where} Fix it, call glance_check again, "
            f"then finish.")


def transform_llm_output(response_text: str = "", session_id: str = "", **kwargs) -> str | None:
    try:
        sess = state.peek(session_id)
        check = sess.check if sess else None
        if check is None or not check.compare_png or check.id == sess.delivered_check_id:
            return None
        sess.delivered_check_id = check.id
        line = f"MEDIA:{check.compare_png}"
        if line in response_text:
            return None
        return f"{response_text.rstrip()}\n\n{line}"
    except Exception:
        logger.warning("glance: transform_llm_output failed", exc_info=True)
        return None
