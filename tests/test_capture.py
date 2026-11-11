import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import FIXTURES, load_glance

load_glance()
from glance import capture, hooks, tools  # noqa: E402

SIM = capture.Target("ios", "SIM-1", "iPhone")


def fake_frames(*paths: Path):
    """A screenshot stand-in that copies the given PNGs in turn, repeating the last one."""
    frames = list(paths)

    def shoot(target, dest, timeout=3.0):
        shutil.copyfile(frames.pop(0) if len(frames) > 1 else frames[0], dest)
        return dest
    return shoot


def completed(stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


class SettleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        sleep = mock.patch.object(capture.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_settles_once_two_frames_match(self):
        changing, still = FIXTURES / "button-color" / "before.png", FIXTURES / "button-color" / "after.png"
        with mock.patch.object(capture, "screenshot", fake_frames(changing, still, still)):
            out, settled = capture.settle(SIM, self.tmp / "after.png")
        self.assertTrue(settled)
        self.assertEqual(out.read_bytes(), still.read_bytes())
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["after.png"])

    def test_reports_unsettled_when_the_screen_keeps_moving(self):
        a, b = FIXTURES / "button-color" / "before.png", FIXTURES / "button-color" / "after.png"
        with mock.patch.object(capture, "screenshot", fake_frames(*[a, b] * 50)):
            out, settled = capture.settle(SIM, self.tmp / "after.png", timeout=0)
        self.assertFalse(settled)
        self.assertTrue(out.is_file())


class TargetTest(unittest.TestCase):
    def test_nothing_booted_is_no_target(self):
        def run(argv, timeout, text=True):
            return completed(json.dumps({"devices": {}}) if argv[0] == "xcrun" else "List of devices attached\n\n")
        with mock.patch.object(capture, "_run", run):
            self.assertIsNone(capture.find_target())
            result = json.loads(tools.glance_check({}, session_id="no-target"))
        self.assertEqual(result["verdict"], "NO_TARGET")

    def test_android_emulator_is_found_when_no_simulator_is_booted(self):
        adb = "List of devices attached\nemulator-5554  device product:sdk model:Pixel_10 device:emu64a\n\n"
        with mock.patch.object(capture, "_run", lambda argv, timeout, text=True: None if argv[0] == "xcrun" else completed(adb)):
            self.assertEqual(capture.find_target(), capture.Target("android", "emulator-5554", "Pixel 10"))


class BaselineNeverBlocksTest(unittest.TestCase):
    def test_edit_proceeds_when_the_baseline_capture_fails(self):
        def broken(*args, **kwargs):
            raise capture.CaptureError("simctl screenshot failed: timed out")
        with mock.patch.object(capture, "find_target", return_value=SIM), \
                mock.patch.object(capture, "screenshot", broken):
            got = hooks.pre_tool_call(tool_name="write_file", args={"path": "App.tsx", "content": ""},
                                      session_id="broken-capture")
        self.assertIsNone(got)


if __name__ == "__main__":
    unittest.main()
