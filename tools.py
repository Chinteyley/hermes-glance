"""glance_check and glance_baseline. Handlers return JSON strings and never raise."""

from __future__ import annotations

import json
import logging
import time

from . import capture, state

logger = logging.getLogger(__name__)

# Fast Refresh needs a moment after the last write before the screen reflects it.
SETTLE_SECONDS = 1.0


def glance_check(args: dict, session_id: str = "", *, device: str = "", **kwargs) -> str:
    try:
        return json.dumps(_check(session_id, device))
    except Exception as exc:
        logger.exception("glance_check failed")
        return json.dumps({"error": f"glance_check failed: {exc}"})


def glance_baseline(args: dict, session_id: str = "", *, device: str = "", **kwargs) -> str:
    try:
        target = capture.find_target(device)
        if target is None:
            return json.dumps(_no_target(device))
        sess = state.session(session_id)
        with sess.lock:
            baseline = take_baseline(sess, session_id, target)
        return json.dumps({"baseline_png": baseline.png, "target": target.to_dict(),
                           "message": "Saved the current screen as the baseline for the next glance_check."})
    except Exception as exc:
        logger.exception("glance_baseline failed")
        return json.dumps({"error": f"glance_baseline failed: {exc}"})


def take_baseline(sess: state.Session, session_id: str, target: capture.Target,
                  timeout: float = 3.0) -> state.Baseline:
    baseline_id = state.new_id()
    png = capture.screenshot(target, state.shots_dir(session_id) / f"{baseline_id}-before.png", timeout)
    sess.baseline = state.Baseline(baseline_id, str(png), target.to_dict())
    return sess.baseline


def _no_target(device: str) -> dict:
    where = f"simulator {device}" if device else "a booted iOS Simulator"
    return {"verdict": "NO_TARGET", "reason": f"Glance found no {where}, so it could not look at the screen.",
            "regions": [], "target": None, "settled": None, "compare_png": None, "layout": None}


def _check(session_id: str, device: str) -> dict:
    from . import diff
    from PIL import Image

    sess = state.session(session_id)
    target = capture.find_target(device)
    if target is None:
        result = _no_target(device)
        with sess.lock:
            _record(sess, None, result)
        return result

    time.sleep(SETTLE_SECONDS)
    with sess.lock:
        check_id = state.new_id()
        shots = state.shots_dir(session_id)
        after_png = capture.screenshot(target, shots / f"{check_id}-after.png")
        if sess.baseline is None:
            sess.baseline = state.Baseline(state.new_id(), str(after_png), target.to_dict())
            result = {"verdict": "NO_BASELINE", "target": target.to_dict(), "regions": [], "settled": None,
                      "compare_png": None, "layout": None, "after_png": str(after_png),
                      "reason": "Glance had no before-screenshot, so it saved the current screen as the "
                                "baseline. Make the UI change, then call glance_check again."}
            _record(sess, check_id, result)
            return result

        compare_png = shots / f"glance-compare-{check_id}.png"
        with Image.open(sess.baseline.png) as before, Image.open(after_png) as after:
            d = diff.judge(before, after)
            layout = diff.write_compare(before, after, d, compare_png)
        result = {"verdict": d.verdict, "reason": d.reason, "changed_ratio": round(d.changed_ratio, 4),
                  "regions": d.regions_json(), "target": target.to_dict(), "settled": None,
                  "compare_png": str(compare_png), "layout": layout,
                  "before_png": sess.baseline.png, "after_png": str(after_png)}
        _record(sess, check_id, result)
        return result


def _record(sess: state.Session, check_id: str | None, result: dict) -> None:
    sess.check = state.Check(
        id=check_id or state.new_id(),
        baseline_id=sess.baseline.id if sess.baseline else None,
        verdict=result["verdict"], reason=result["reason"], regions=result["regions"],
        compare_png=result["compare_png"], edit_seq=sess.edit_seq,
    )
