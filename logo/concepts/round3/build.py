"""Round 3: develop the two chosen directions — SLIDERS and SKELETON.

    python logo/concepts/round3/build.py      # writes s*.svg and k*.svg next to this file
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import build as B  # noqa: E402
from build import NAVY, Shape, add, bar, hollow_square, ring, square, unit  # noqa: E402

B.HERE = HERE
ORANGE, CREAM = "#f05a28", "#f3f1ea"
GAP = 18
GLYPHS = json.loads((HERE / "glyphs.json").read_text())


# =================================================================================================
# SLIDERS — the V's arms are handle tracks from an anchor key to round knobs; square thumbs on them
# =================================================================================================
APEX, TOPS = (256, 424), ((100, 100), (412, 100))
VALUES = (0.62, 0.42)                    # thumb positions, measured from the apex


def track_frame(top):
    u, n = unit(APEX, top)
    return u, n, math.degrees(math.atan2(u[1], u[0]))


def slider(name: str, title: str, *, apex: str = "key", track: float = 30, thin: float | None = None,
           thumb: float = 72, ticks: bool = False, knob_r: float = 32, knob_t: float = 18) -> None:
    shapes: list[Shape] = []
    key_s, key_t = 88, 22
    if apex == "solid":                       # small-size member: no holes to fill in
        shapes.append(square(APEX, key_s, NAVY))
    elif apex in ("key", "attached"):
        shapes.append(hollow_square(APEX, key_s, key_t, NAVY))
    else:
        shapes.append(ring(APEX, 40, 18, NAVY))
    for top, value in zip(TOPS, VALUES):
        u, n, ang = track_frame(top)
        if apex == "key":
            start = B.clear_of_square(APEX, key_s / 2, APEX, top, track, GAP)
        elif apex in ("attached", "solid"):
            start = B.clear_of_square(APEX, key_s / 2 - key_t, APEX, top, track, 0)   # ends inside the frame
        else:
            start = add(APEX, u, 40 - 9)
        end = add(top, u, -(knob_r - knob_t / 2))
        centre = add(APEX, u, n * value)
        half = thumb / 2 + GAP
        below, above = add(centre, u, -half), add(centre, u, half)
        shapes.append(bar(start, below, track, NAVY))                        # filled part (value)
        shapes.append(bar(above, end, thin or track, NAVY))                  # rest of the track
        knob = B.circle(top, knob_r, NAVY) if apex == "solid" else ring(top, knob_r, knob_t, NAVY)
        shapes += [knob, square(centre, thumb, ORANGE, ang)]
        if ticks:
            nx, ny = u[1], -u[0]                                             # outer normal
            if top[0] > APEX[0]:
                nx, ny = -nx, -ny
            for i in range(1, 6):
                p = add(start, u, (math.dist(start, end)) * i / 6)
                if math.dist(p, centre) < half + 14:
                    continue
                a = add(p, (nx, ny), track / 2 + 16)
                shapes.append(bar(a, add(a, (nx, ny), 26 if i % 2 else 40), 14, NAVY))
    B.write(name, title, shapes)


# =================================================================================================
# SKELETON — a real calligraphic glyph, knocked out of a key plate, with its own bezier skeleton
# =================================================================================================
NUM_PAIR = re.compile(r"(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)")


def placed(key: str, height: float, centre=(266, 256)):
    """Glyph outline and skeleton scaled to `height` and centred (in 512 canvas coordinates)."""
    g = GLYPHS[key]
    x0, y0, x1, y1 = g["box"]
    k = height / (y1 - y0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    def tr(p):
        return centre[0] + (p[0] - cx) * k, centre[1] + (p[1] - cy) * k

    d = NUM_PAIR.sub(lambda m: "{:.1f} {:.1f}".format(*tr((float(m.group(1)), float(m.group(2))))), g["d"])
    nodes = [tr(p) for p in g["nodes"]]
    handles = [(tr(a), tr(b)) for a, b in g["handles"]]
    w, h = (x1 - x0) * k, height
    return d, nodes, handles, (centre[0] - w / 2, centre[1] - h / 2, centre[0] + w / 2, centre[1] + h / 2)


def rounded_rect(x0, y0, side, rad) -> str:
    return (f"M{x0 + rad} {y0}H{x0 + side - rad}A{rad} {rad} 0 0 1 {x0 + side} {y0 + rad}V{y0 + side - rad}"
            f"A{rad} {rad} 0 0 1 {x0 + side - rad} {y0 + side}H{x0 + rad}A{rad} {rad} 0 0 1 {x0} {y0 + side - rad}"
            f"V{y0 + rad}A{rad} {rad} 0 0 1 {x0 + rad} {y0}Z")


def letter_mask(d: str):
    """Pixel mask of the letter in 512 canvas coordinates (for 'does this knob leave the letter?')."""
    import io

    import numpy as np
    import resvg_py
    from PIL import Image

    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><path d="{d}"/></svg>'
    img = Image.open(io.BytesIO(bytes(resvg_py.svg_to_bytes(svg_string=svg, width=512, height=512))))
    return np.asarray(img.getchannel("A")) > 127


def overlay(nodes, handles, *, node=26, line=7, knob=11, min_handle=22, color=ORANGE,
            letter: str | None = None, reach: float = 0.0) -> list[Shape]:
    """Skeleton in the editor convention: square nodes, handle lines ending in round knobs.

    Handles shorter than `min_handle` are hidden (noise). With `letter`, only handles whose knob lies
    outside the letterform are shown — handles running along the contour merge with it and read as
    clutter — and those are drawn at least `reach` long, always along their true tangent.
    """
    mask = letter_mask(letter) if letter else None
    out = []
    for a, b in handles:
        length = math.dist(a, b)
        if length < min_handle:
            continue
        u = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
        tip = add(a, u, max(length, reach))
        if mask is not None:
            x, y = int(round(tip[0])), int(round(tip[1]))
            if 0 <= x < 512 and 0 <= y < 512 and mask[y, x]:
                continue
        out += [bar(a, tip, line, color), B.circle(tip, knob, color)]
    out += [square(p, node, color) for p in nodes]
    return out


def merge_close_nodes(key: str, limit: float = 30.0) -> None:
    """Drop an on-curve node that sits within `limit` (glyph units) of the next one, joining the two
    cubic segments into one (endpoint tangents kept). Edits GLYPHS[key] in place."""
    g = GLYPHS[key]
    nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", g["d"])]
    start, segs = (nums[0], nums[1]), [tuple(nums[i:i + 6]) for i in range(2, len(nums) - 1, 6)]
    pts = [start] + [(c[4], c[5]) for c in segs]
    out = []
    i = 0
    while i < len(segs):
        c = segs[i]
        if i + 1 < len(segs) and math.dist((c[4], c[5]), pts[i]) > 0 and math.dist(pts[i + 1], pts[i + 2]) < limit:
            nxt = segs[i + 1]
            dx, dy = nxt[4] - c[4], nxt[5] - c[5]            # carry the incoming handle to the new end
            out.append((c[0], c[1], c[2] + dx, c[3] + dy, nxt[4], nxt[5]))
            i += 2
            continue
        out.append(c)
        i += 1
    d = f"M{start[0]:.1f} {start[1]:.1f}" + "".join("C" + " ".join(f"{v:.1f}" for v in c) for c in out) + "Z"
    nodes = [start] + [(c[4], c[5]) for c in out[:-1]]
    handles = []
    prev = start
    for c in out:
        handles += [(prev, (c[0], c[1])), ((c[4], c[5]), (c[2], c[3]))]
        prev = (c[4], c[5])
    g.update(d=d, nodes=nodes, handles=handles)


def skeleton(name: str, title: str, key: str, *, style: str) -> None:
    if style == "plate":            # knocked out of a navy key plate, skeleton on top
        d, nodes, handles, _ = placed(key, 352)
        plate = Shape(f'<path fill="{NAVY}" fill-rule="evenodd" d="{rounded_rect(24, 24, 464, 108)}{d}"/>', [(24, 24), (488, 488)])
        B.write(name, title, [plate] + overlay(nodes, handles, letter=d, reach=72), fill=0.92)
    elif style == "outline":        # the reference look: cream letter, orange contour, skeleton
        d, nodes, handles, _ = placed(key, 352)
        plate = Shape(f'<path fill="{NAVY}" d="{rounded_rect(24, 24, 464, 108)}"/>', [(24, 24), (488, 488)])
        letter = Shape(f'<path fill="{CREAM}" stroke="{ORANGE}" stroke-width="6" stroke-linejoin="round" d="{d}"/>', [])
        B.write(name, title, [plate, letter] + overlay(nodes, handles, letter=d, reach=72), fill=0.92)
    elif style == "pro":            # master: real knockout + orange contour + skeleton (mono-safe letter)
        d, nodes, handles, _ = placed(key, 368)
        plate = Shape(f'<path fill="{NAVY}" fill-rule="evenodd" d="{rounded_rect(24, 24, 464, 108)}{d}"/>', [(24, 24), (488, 488)])
        contour = Shape(f'<path fill="none" stroke="{ORANGE}" stroke-width="7" stroke-linejoin="round" d="{d}"/>', [])
        B.write(name, title, [plate, contour] + overlay(nodes, handles, node=28, line=8, knob=12, letter=d, reach=72), fill=0.92)
    elif style == "light":          # no plate: navy letter, orange skeleton
        d, nodes, handles, (x0, y0, x1, y1) = placed(key, 400)
        letter = Shape(f'<path fill="{NAVY}" d="{d}"/>', [(x0, y0), (x1, y1)])
        B.write(name, title, [letter] + overlay(nodes, handles, node=28, line=8, knob=12, letter=d, reach=80), fill=0.86)
    elif style == "mark":           # the plain letter: the small-size member of the system
        d, _, _, (x0, y0, x1, y1) = placed(key, 400)
        B.write(name, title, [Shape(f'<path fill="{NAVY}" d="{d}"/>', [(x0, y0), (x1, y1)])], fill=0.86)


if __name__ == "__main__":
    merge_close_nodes("kaushan-V", limit=80)
    slider("s1-track", "varness — slider: continuous tracks", track=32)
    slider("s2-progress", "varness — slider: filled value, thin remainder", track=40, thin=16)
    slider("s3-gauge", "varness — slider: tracks with gauge ticks", track=30, ticks=True)
    slider("s4-knob", "varness — slider: tracks meet at a knob", apex="knob", track=32)
    slider("s5-key", "varness — slider: tracks meet at an anchor key", apex="attached", track=34, thumb=80)
    slider("s5-key-small", "varness — slider: small-size version", apex="solid", track=40, thumb=88, knob_r=36)
    for key, tag in (("kaushan-V", "kaushan"), ("instrument-v", "instrument"), ("dancing-V", "dancing")):
        skeleton(f"k-{tag}-plate", f"varness — skeleton ({tag}): plate", key, style="plate")
    skeleton("k-kaushan-pro", "varness — skeleton (kaushan): knockout + contour", "kaushan-V", style="pro")
    skeleton("k-kaushan-outline", "varness — skeleton (kaushan): outline", "kaushan-V", style="outline")
    skeleton("k-kaushan-light", "varness — skeleton (kaushan): light", "kaushan-V", style="light")
    skeleton("k-kaushan-mark", "varness — skeleton (kaushan): plain mark", "kaushan-V", style="mark")
