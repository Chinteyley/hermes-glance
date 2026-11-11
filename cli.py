"""`hermes glance doctor`: which device Glance would look at, whether a screenshot works, where data lives."""

from __future__ import annotations

import time


def setup(subparser) -> None:
    subs = subparser.add_subparsers(dest="glance_command")
    subs.add_parser("doctor", help="Show the detected device, take a test screenshot, print the data dir")


def run(args, device: str = "") -> int:
    if getattr(args, "glance_command", None) != "doctor":
        print("Usage: hermes glance doctor")
        return 2
    return doctor(device)


def doctor(device: str = "") -> int:
    from PIL import Image

    from . import capture, state

    print(f"Data dir:  {state.data_dir()}")
    print(f"Device setting: {device or '(empty: first booted simulator, then first adb device)'}")
    target = capture.find_target(device)
    if target is None:
        print("Device:    none running. glance_check returns NO_TARGET until a simulator or emulator boots.")
        return 1
    print(f"Device:    {target.name} ({target.platform}, {target.device_id})")
    dest = state.data_dir() / "doctor.png"
    started = time.monotonic()
    try:
        capture.screenshot(target, dest)
    except capture.CaptureError as exc:
        print(f"Capture:   FAILED. {exc}")
        return 1
    with Image.open(dest) as shot:
        width, height = shot.size
    print(f"Capture:   ok, {width}x{height} in {(time.monotonic() - started) * 1000:.0f} ms ({dest})")
    return 0
