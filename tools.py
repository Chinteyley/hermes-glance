"""glance_check and glance_baseline. Handlers return JSON strings, or on PASS the multimodal envelope that
carries the compare image, and never raise."""

from __future__ import annotations

import json
import logging

from . import capture, state
from .verdicts import NO_BASELINE, NO_TARGET, PASS

logger = logging.getLogger(__name__)

LOOK = ("This is Glance's compare image for a PASS: the before screen on the left, the after screen on the right, "
        "changed regions outlined in red. PASS only means the screen changed. Does the after half show what the "
        "user asked for, and is anything from the before half missing? If it is wrong, fix it and call "
        "glance_check again.")


def glance_check(args: dict, session_id: str = "", *, device: str = "", dispatch=None, **kwargs) -> str | dict:
    try:
        result = check(session_id, device)
        if result["verdict"] == PASS and dispatch is not None:
            return _shown(session_id, result, dispatch, kwargs.get("task_id"))
        return json.dumps(result)
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


def _shown(session_id: str, result: dict, dispatch, task_id: str | None) -> str | dict:
    """A PASS only says the screen changed, so the compare image goes in front of the model through
    vision_analyze. On a model that takes images in tool results that attaches the pixels, and the result
    becomes one envelope with Glance's JSON first. Otherwise the JSON carries whatever vision_analyze said
    instead, and pre_verify tells the agent it has not seen the screen."""
    try:
        seen = dispatch("vision_analyze", {"image_url": result["compare_png"], "question": LOOK}, task_id=task_id)
    except Exception as exc:
        logger.warning("glance: vision_analyze on the compare image failed", exc_info=True)
        seen = f"vision_analyze failed: {exc}"
    if not (isinstance(seen, dict) and seen.get("_multimodal") is True):
        return json.dumps({**result, "vision_analyze": seen})
    state.record_look(session_id, result["check_id"], state.SHOWN)
    text = json.dumps(result)
    return {"_multimodal": True, "content": [{"type": "text", "text": text}, *seen["content"]], "text_summary": text}


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
    return {"check_id": check_id, **result}
