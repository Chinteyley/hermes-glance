"""glance_check and glance_baseline. Handlers return JSON strings and never raise."""

from __future__ import annotations

import json
import logging

from . import capture, state
from .verdicts import NO_BASELINE, NO_TARGET

logger = logging.getLogger(__name__)


def glance_check(args: dict, session_id: str = "", *, device: str = "", **kwargs) -> str:
    try:
        return json.dumps(check(session_id, device))
    except Exception as exc:
        logger.exception("glance_check failed")
        return json.dumps({"error": f"glance_check failed: {exc}"})


def glance_baseline(args: dict, session_id: str = "", *, device: str = "", **kwargs) -> str:
    try:
        target = capture.find_target(device)
        if target is None:
            return json.dumps(_no_target(device))
        with state.lock(session_id):
            baseline = take_baseline(session_id, target, trigger_tool="glance_baseline")
        return json.dumps({"baseline_png": baseline.png, "target": target.to_dict(),
                           "message": "Saved the current screen as the baseline for the next glance_check."})
    except Exception as exc:
        logger.exception("glance_baseline failed")
        return json.dumps({"error": f"glance_baseline failed: {exc}"})


def take_baseline(session_id: str, target: capture.Target, timeout: float = 3.0,
                  trigger_tool: str = "", trigger_path: str = "") -> state.Baseline:
    baseline_id = state.new_id()
    png = capture.screenshot(target, state.shots_dir(session_id) / f"{baseline_id}-before.png", timeout)
    baseline = state.Baseline(baseline_id, str(png), target.to_dict())
    state.save_baseline(session_id, baseline, trigger_tool, trigger_path)
    return baseline


def _no_target(device: str) -> dict:
    where = f"device {device}" if device else "a booted iOS Simulator or Android emulator"
    return {"verdict": NO_TARGET, "reason": f"Glance found no {where}, so it could not look at the screen.",
            "regions": [], "target": None, "settled": None, "compare_png": None, "layout": None}


def check(session_id: str, device: str) -> dict:
    from PIL import Image

    from . import diff

    with state.lock(session_id):
        snap = state.snapshot(session_id)
        check_id = state.new_id()
        target = capture.find_target(device)
        if target is None:
            return _record(session_id, check_id, snap.baseline, snap.edit_seq, _no_target(device))

        after_png, settled = capture.settle(target, state.shots_dir(session_id) / f"{check_id}-after.png",
                                            snap.last_edit_at)
        if snap.baseline is None:
            baseline = state.Baseline(state.new_id(), str(after_png), target.to_dict())
            state.save_baseline(session_id, baseline, trigger_tool="glance_check")
            return _record(session_id, check_id, baseline, snap.edit_seq, {
                "verdict": NO_BASELINE, "target": target.to_dict(), "regions": [], "settled": settled,
                "compare_png": None, "layout": None, "after_png": str(after_png),
                "reason": "Glance had no before-screenshot, so it saved the current screen as the baseline. "
                          "Make the UI change, then call glance_check again."})

        compare_png = after_png.with_name(f"glance-compare-{check_id}.png")
        with Image.open(snap.baseline.png) as before, Image.open(after_png) as after:
            d = diff.judge(before, after)
            layout = diff.write_compare(before, after, d, compare_png)
        reason = d.reason
        if not settled:
            reason += (f" The screen was still changing after {capture.SETTLE_TIMEOUT:.0f} s, so this frame may "
                       "be mid-animation; call glance_check again if the verdict looks wrong.")
        return _record(session_id, check_id, snap.baseline, snap.edit_seq, {
            "verdict": d.verdict, "reason": reason, "changed_ratio": round(d.changed_ratio, 4),
            "regions": d.regions_json(), "target": target.to_dict(), "settled": settled,
            "compare_png": str(compare_png), "layout": layout,
            "before_png": snap.baseline.png, "after_png": str(after_png)})


def _record(session_id: str, check_id: str, baseline: state.Baseline | None, edit_seq: int, result: dict) -> dict:
    state.save_check(session_id, state.Check(
        id=check_id, baseline_id=baseline.id if baseline else None, verdict=result["verdict"],
        reason=result["reason"], regions=result["regions"], compare_png=result["compare_png"], edit_seq=edit_seq,
    ), after_png=result.get("after_png"), changed_ratio=result.get("changed_ratio"))
    return result
