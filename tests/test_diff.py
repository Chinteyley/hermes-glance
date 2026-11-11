import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops

from support import FIXTURES, fixture_cases, load_glance

load_glance()
from glance import diff  # noqa: E402


def judge(case: str) -> diff.Diff:
    with Image.open(FIXTURES / case / "before.png") as before, Image.open(FIXTURES / case / "after.png") as after:
        return diff.judge(before, after)


class VerdictTest(unittest.TestCase):
    def test_visible_edit_passes_with_a_region_around_the_button(self):
        d = judge("button-color")
        self.assertEqual(d.verdict, "PASS")
        self.assertEqual(len(d.regions), 1)
        self.assertAlmostEqual(d.regions[0].y, 0.74, delta=0.02)

    def test_edit_to_an_unused_file_is_no_change(self):
        self.assertEqual(judge("noop-wrong-file").verdict, "NO_CHANGE")

    def test_clock_tick_alone_is_no_change(self):
        with Image.open(FIXTURES / "clock-drift" / "before.png") as b, Image.open(FIXTURES / "clock-drift" / "after.png") as a:
            self.assertIsNotNone(ImageChops.difference(b.convert("RGB"), a.convert("RGB")).getbbox(),
                                 "the clock-drift pair really differs")
        self.assertEqual(judge("clock-drift").verdict, "NO_CHANGE")

    def test_expo_render_error_is_error_screen(self):
        self.assertEqual(judge("render-error").verdict, "ERROR_SCREEN")

    def test_metro_compile_error_is_error_screen(self):
        self.assertEqual(judge("syntax-error").verdict, "ERROR_SCREEN")

    def test_root_returning_null_is_blank(self):
        self.assertEqual(judge("blank-screen").verdict, "BLANK")

    def test_every_fixture_gets_its_expected_verdict(self):
        cases = fixture_cases()
        got = {c["case"]: judge(c["case"]).verdict for c in cases}
        want = {c["case"]: c["expected"] for c in cases}
        self.assertEqual(got, want)


class CompareImageTest(unittest.TestCase):
    def test_layout_matches_the_side_by_side_contract(self):
        d = judge("layout-shift")
        self.assertLessEqual(len(d.regions), diff.MAX_REGIONS)
        with tempfile.TemporaryDirectory() as tmp, \
                Image.open(FIXTURES / "layout-shift" / "before.png") as before, \
                Image.open(FIXTURES / "layout-shift" / "after.png") as after:
            dest = Path(tmp) / "compare.png"
            layout = diff.write_compare(before, after, d, dest)
            with Image.open(dest) as out:
                self.assertEqual(out.size, (2 * layout["frame_width"], layout["frame_height"] + layout["bar_height"]))


if __name__ == "__main__":
    unittest.main()
