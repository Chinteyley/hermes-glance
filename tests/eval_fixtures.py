"""Run the verdict engine over every recorded simulator pair and score it against cases.json.

    python tests/eval_fixtures.py
"""

import sys
import time

from PIL import Image

from support import FIXTURES, fixture_cases, load_glance

load_glance()
from glance import diff  # noqa: E402


def main() -> int:
    cases = fixture_cases()
    caught = 0
    for case in cases:
        name, want = case["case"], case["expected"]
        with Image.open(FIXTURES / name / "before.png") as before, Image.open(FIXTURES / name / "after.png") as after:
            started = time.perf_counter()
            got = diff.judge(before, after)
            ms = (time.perf_counter() - started) * 1000
        ok = got.verdict == want
        caught += ok
        print(f"{'ok  ' if ok else 'MISS'} {name:<16} want {want:<12} got {got.verdict:<12} "
              f"{got.changed_ratio:7.2%} changed  {len(got.regions)} region(s)  {ms:4.0f} ms")
    print(f"{caught}/{len(cases)} caught, no model calls")
    return 0 if caught == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
