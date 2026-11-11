"""Pure image logic: the verdict and the compare PNG. Takes PIL images, never touches a device.

Every threshold below was calibrated on the real iPhone 18 Pro pairs in tests/fixtures.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from .verdicts import BLANK, ERROR_SCREEN, NO_CHANGE, PASS

# The status bar clock ticks every minute. On the fixtures its content spans rows 76-118 of 2622 and
# app content starts at row 243, so the top 7% is masked out of every comparison.
STATUS_BAR_FRACTION = 0.07
# A pixel counts as changed when any channel moves by more than this.
PIXEL_TOLERANCE = 16
# Below this share of changed pixels the edit changed nothing. One changed digit in the price is
# about 0.08%; the unmasked clock tick is 0.02%.
NO_CHANGE_RATIO = 0.0002
# A frame with one colour over this share of its area shows nothing.
BLANK_SHARE = 0.97
# React Native LogBox colours (Expo's red error screen and Metro's "Failed to compile" overlay both
# draw them): the header band behind the status bar, then the dark body.
LOGBOX_HEADER = (243, 83, 105)
LOGBOX_BODY = (51, 51, 51)
LOGBOX_HEADER_BAND = (0.07, 0.12)
LOGBOX_HEADER_SHARE = 0.8
LOGBOX_BODY_SHARE = 0.35
COLOR_TOLERANCE = 12
# Regions are found on a grid of cells this many frame widths across.
GRID_COLUMNS = 48
MAX_REGIONS = 8

# The Desktop renderer splits the compare PNG with CSS, so this layout is a contract:
# [before | after] at equal size, then a verdict bar of BAR_HEIGHT px across the bottom.
LAYOUT_KIND = "glance-compare/v1"
FRAME_MAX_HEIGHT = 1000
BAR_HEIGHT = 32
_BAR_COLORS = {PASS: (22, 128, 74), NO_CHANGE: (176, 112, 0), ERROR_SCREEN: (190, 38, 38), BLANK: (190, 38, 38)}
_REGION_COLOR = (255, 45, 45)
_ANALYSIS_REDUCE = 3


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
        return [{k: round(v, 4) for k, v in asdict(r).items()} for r in self.regions]


def judge(before: Image.Image, after: Image.Image) -> Diff:
    b = before.convert("RGB")
    a = after.convert("RGB")
    if a.size != b.size:
        a = a.resize(b.size)
    small = a.reduce(_ANALYSIS_REDUCE)
    if is_error_screen(small):
        return Diff(ERROR_SCREEN, "The app shows the React Native error screen instead of the UI. Read the "
                    "error in the compare image or the Metro log, fix the code, then call glance_check again.", 1.0)
    share = dominant_share(small)
    if share >= BLANK_SHARE:
        return Diff(BLANK, f"The screen is empty: one colour covers {share:.1%} of it. A component likely "
                    "returns nothing, or the root failed to render.", 1.0)
    mask = changed_mask(b, a)
    ratio = changed_ratio(mask)
    if ratio < NO_CHANGE_RATIO:
        return Diff(NO_CHANGE, f"Nothing on screen changed ({ratio:.3%} of pixels differ). The edit may be in a "
                    "file this screen does not render, or set a style that was already in effect.", ratio)
    regions = find_regions(mask)
    return Diff(PASS, f"The screen changed in {len(regions)} region(s), {ratio:.1%} of pixels.", ratio, regions)


def changed_mask(before: Image.Image, after: Image.Image) -> Image.Image:
    """255 where a pixel changed, 0 elsewhere, with the status bar band blanked."""
    r, g, b = ImageChops.difference(before, after).split()
    worst = ImageChops.lighter(r, ImageChops.lighter(g, b))
    mask = worst.point(lambda v: 255 if v > PIXEL_TOLERANCE else 0)
    mask.paste(0, (0, 0, mask.width, status_bar_rows(mask.height)))
    return mask


def changed_ratio(mask: Image.Image) -> float:
    return mask.histogram()[255] / (mask.width * mask.height)


def same_screen(first: Image.Image, second: Image.Image) -> bool:
    """True when two frames would judge NO_CHANGE against each other: what settling waits for."""
    a, b = first.convert("RGB"), second.convert("RGB")
    return a.size == b.size and changed_ratio(changed_mask(a, b)) < NO_CHANGE_RATIO


def status_bar_rows(height: int) -> int:
    return round(height * STATUS_BAR_FRACTION)


def share_near(img: Image.Image, color: tuple[int, int, int], tol: int = COLOR_TOLERANCE) -> float:
    r, g, b = ImageChops.difference(img, Image.new("RGB", img.size, color)).split()
    worst = ImageChops.lighter(r, ImageChops.lighter(g, b))
    hist = worst.histogram()
    return sum(hist[: tol + 1]) / (img.width * img.height)


def is_error_screen(img: Image.Image) -> bool:
    w, h = img.size
    top, bottom = (round(h * f) for f in LOGBOX_HEADER_BAND)
    header = img.crop((0, top, w, bottom))
    body = img.crop((0, bottom, w, h))
    return share_near(header, LOGBOX_HEADER) >= LOGBOX_HEADER_SHARE and share_near(body, LOGBOX_BODY) >= LOGBOX_BODY_SHARE


def dominant_share(img: Image.Image) -> float:
    """Share of the frame below the status bar within COLOR_TOLERANCE of its most common colour."""
    body = img.crop((0, status_bar_rows(img.height), img.width, img.height))
    colors = body.getcolors(body.width * body.height) or []
    _, top = max(colors)
    return share_near(body, top)


def find_regions(mask: Image.Image) -> list[Region]:
    """Changed cells on a coarse grid, joined into 8-connected components, at most MAX_REGIONS boxes."""
    cell = max(1, mask.width // GRID_COLUMNS)
    cols, rows = -(-mask.width // cell), -(-mask.height // cell)
    grid = mask.resize((cols, rows), Image.BOX).load()
    hot = {(x, y) for y in range(rows) for x in range(cols) if grid[x, y] > 0}
    boxes = []
    while hot:
        stack = [hot.pop()]
        x0, y0 = x1, y1 = stack[0]
        while stack:
            x, y = stack.pop()
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
            for n in ((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                if n in hot:
                    hot.remove(n)
                    stack.append(n)
        boxes.append((x0, y0, x1 + 1, y1 + 1))
    boxes = _merge_to(boxes, MAX_REGIONS)
    boxes.sort(key=lambda bx: (bx[1], bx[0]))
    fw, fh = mask.width / cell, mask.height / cell
    return [Region(x0 / fw, y0 / fh, min(x1, fw) / fw - x0 / fw, min(y1, fh) / fh - y0 / fh) for x0, y0, x1, y1 in boxes]


def _merge_to(boxes: list[tuple], limit: int) -> list[tuple]:
    """Merge overlapping boxes, then the pair whose union wastes the least area, until at most `limit` remain."""
    def area(bx):
        return (bx[2] - bx[0]) * (bx[3] - bx[1])

    def union(p, q):
        return min(p[0], q[0]), min(p[1], q[1]), max(p[2], q[2]), max(p[3], q[3])

    def overlap(p, q):
        return p[0] < q[2] and q[0] < p[2] and p[1] < q[3] and q[1] < p[3]

    boxes = list(boxes)
    while len(boxes) > 1:
        pairs = [(i, j) for i in range(len(boxes)) for j in range(i + 1, len(boxes))]
        touching = [(i, j) for i, j in pairs if overlap(boxes[i], boxes[j])]
        if touching:
            i, j = touching[0]
        elif len(boxes) > limit:
            _, i, j = min((area(union(boxes[i], boxes[j])) - area(boxes[i]) - area(boxes[j]), i, j) for i, j in pairs)
        else:
            break
        merged = union(boxes[i], boxes[j])
        boxes = [bx for k, bx in enumerate(boxes) if k not in (i, j)] + [merged]
    return boxes


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
