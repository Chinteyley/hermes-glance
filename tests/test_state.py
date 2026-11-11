import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest import mock

from support import FIXTURES, load_glance

load_glance()
from glance import capture, hooks, state, tools  # noqa: E402

SIM = capture.Target("ios", "SIM-1", "iPhone")
UI_EDIT = {"path": "/app/src/Checkout.tsx", "content": "export default null"}


class Screen:
    """Stands in for the simulator: every capture returns whatever fixture frame it is showing."""

    def __init__(self, frame: Path):
        self.frame = frame

    def screenshot(self, target, dest, timeout=3.0):
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.frame, dest)
        return dest

    def settle(self, target, dest, last_edit_at=None, timeout=5.0):
        return self.screenshot(target, dest), True


class StateMachineTest(unittest.TestCase):
    def setUp(self):
        self.session = uuid.uuid4().hex
        self.screen = Screen(FIXTURES / "button-color" / "before.png")
        for name, value in (("find_target", lambda *a, **k: SIM), ("screenshot", self.screen.screenshot),
                            ("settle", self.screen.settle)):
            patcher = mock.patch.object(capture, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def edit(self, tool="write_file", args=UI_EDIT):
        self.assertIsNone(hooks.pre_tool_call(tool_name=tool, args=args, session_id=self.session))

    def look(self, case: str, side: str = "after") -> dict:
        self.screen.frame = FIXTURES / case / f"{side}.png"
        return json.loads(tools.glance_check({}, session_id=self.session))

    def verify(self, attempt=0):
        return hooks.pre_verify(session_id=self.session, attempt=attempt, changed_paths=[UI_EDIT["path"]])

    def phase(self):
        return state.snapshot(self.session).phase

    def test_idle_session_finishes_freely_and_ignores_non_ui_edits(self):
        self.edit(args={"path": "/app/README.md", "content": "x"})
        self.assertIs(self.phase(), state.Phase.IDLE)
        self.assertIsNone(self.verify())

    def test_first_ui_edit_baselines_and_finishing_unlooked_is_sent_back(self):
        self.edit()
        self.assertIs(self.phase(), state.Phase.BASELINED)
        self.assertEqual(self.verify(), {"action": "continue", "message": hooks.NOT_LOOKED})

    def test_multi_file_patch_counts_as_a_ui_edit(self):
        self.edit("patch", {"mode": "patch", "patch": "*** Begin Patch\n*** Update File: src/api.ts\n"
                                                     "*** Update File: src/Card.tsx\n*** End Patch"})
        self.assertIs(self.phase(), state.Phase.BASELINED)

    def test_failing_check_is_checked_and_sent_back_until_the_throttle(self):
        self.edit()
        self.assertEqual(self.look("noop-wrong-file")["verdict"], "NO_CHANGE")
        self.assertIs(self.phase(), state.Phase.CHECKED)
        nudge = self.verify()
        self.assertEqual(nudge["action"], "continue")
        self.assertIn("NO_CHANGE", nudge["message"])
        self.assertIsNone(self.verify(attempt=hooks.MAX_NUDGE_ATTEMPT))

    def test_edit_after_a_check_is_stale(self):
        self.edit()
        self.look("render-error")
        self.edit()
        self.assertIs(self.phase(), state.Phase.STALE)
        self.assertEqual(self.verify()["message"], hooks.NOT_LOOKED)

    def test_pass_resets_to_idle_and_the_next_edit_takes_a_fresh_baseline(self):
        self.edit()
        first = state.snapshot(self.session).baseline
        self.assertEqual(self.look("button-color")["verdict"], "PASS")
        self.assertIs(self.phase(), state.Phase.IDLE)
        self.assertIsNone(self.verify())
        self.edit()
        snap = state.snapshot(self.session)
        self.assertIs(snap.phase, state.Phase.BASELINED)
        self.assertNotEqual(snap.baseline.id, first.id)

    def test_check_without_a_baseline_saves_one(self):
        result = self.look("button-color", "before")
        self.assertEqual(result["verdict"], "NO_BASELINE")
        self.assertIs(self.phase(), state.Phase.CHECKED)
        self.assertIsNone(self.verify())

    def test_reply_gets_the_compare_image_once(self):
        self.edit()
        compare = self.look("button-color")["compare_png"]
        reply = hooks.transform_llm_output(response_text="Done.", session_id=self.session)
        self.assertEqual(reply, f"Done.\n\nMEDIA:{compare}")
        self.assertIsNone(hooks.transform_llm_output(response_text="Anything else?", session_id=self.session))


if __name__ == "__main__":
    unittest.main()
