"""Pure image logic: the verdict and the compare PNG. Takes PIL images, never touches a device.

Skeleton: judge() is pixel equality only; the calibrated engine replaces it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from .verdicts import BLANK, ERROR_SCREEN, NO_CHANGE, PASS

# The Desktop renderer splits the compare PNG with CSS, so this layout is a contract:
# [before | after] at equal size, then a verdict bar of BAR_HEIGHT px across the bottom.
LAYOUT_KIND = "glance-compare/v1"
FRAME_MAX_HEIGHT = 1000
BAR_HEIGHT = 32
_BAR_COLORS = {PASS: (22, 128, 74), NO_CHANGE: (176, 112, 0), ERROR_SCREEN: (190, 38, 38), BLANK: (190, 38, 38)}
_REGION_COLOR = (255, 45, 45)


@dataclass(frozen=True)
class Region:
    """A changed area as fractions of the frame, so it survives any scaling."""
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class Diff:
    verdict: str
    reason: str
    changed_ratio: float
    regions: list[Region] = field(default_factory=list)

    def regions_json(self) -> list[dict]:
        return [asdict(r) for r in self.regions]


def judge(before: Image.Image, after: Image.Image) -> Diff:
    b, a = before.convert("RGB"), after.convert("RGB").resize(before.size)
    box = ImageChops.difference(b, a).getbbox()
    if box is None:
        return Diff(NO_CHANGE, "The screen is pixel-identical to the baseline.", 0.0)
    w, h = b.size
    x0, y0, x1, y1 = box
    region = Region(x0 / w, y0 / h, (x1 - x0) / w, (y1 - y0) / h)
    return Diff(PASS, "The screen changed.", region.w * region.h, [region])


def write_compare(before: Image.Image, after: Image.Image, diff: Diff, dest: Path) -> dict:
    scale = min(1.0, FRAME_MAX_HEIGHT / before.height)
    size = (round(before.width * scale), round(before.height * scale))
    b = before.convert("RGB").resize(size, Image.LANCZOS)
    a = after.convert("RGB").resize(size, Image.LANCZOS)
    w, h = size
    canvas = Image.new("RGB", (2 * w, h + BAR_HEIGHT), _BAR_COLORS.get(diff.verdict, (60, 60, 60)))
    canvas.paste(b, (0, 0))
    canvas.paste(a, (w, 0))
    draw = ImageDraw.Draw(canvas)
    for r in diff.regions:
        x0, y0 = w + r.x * w, r.y * h
        draw.rectangle((x0, y0, x0 + r.w * w, y0 + r.h * h), outline=_REGION_COLOR, width=3)
    draw.line((w, 0, w, h), fill=(255, 255, 255), width=1)
    label = f"GLANCE  {diff.verdict}   {diff.changed_ratio:.1%} changed   before | after"
    draw.text((12, h + BAR_HEIGHT // 2), label, fill=(255, 255, 255), anchor="lm", font=ImageFont.load_default(size=16))
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, format="PNG")
    return {"kind": LAYOUT_KIND, "order": ["before", "after"], "frame_width": w, "frame_height": h,
            "bar_height": BAR_HEIGHT, "bar": "bottom"}
