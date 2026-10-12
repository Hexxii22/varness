"""Round 2 of the varness logo: technical pen-tool language from the references.

Hollow square anchors with heavy borders, thin handles ending in round knobs, an orange accent, rulers.
Geometry helpers come from ../build.py; every concept is written as an SVG next to this file.

    python logo/concepts/round2/build.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build as B  # noqa: E402
from build import NAVY, Pt, Shape, add, bar, circle, f, hollow_square, ring, square, unit  # noqa: E402

B.HERE = Path(__file__).parent
ORANGE = "#f05a28"
GAP = 22

Cubic = tuple[Pt, Pt, Pt, Pt]


# -- cubic paths ------------------------------------------------------------------------------------
def line_seg(a: Pt, b: Pt) -> Cubic:
    return a, add(a, (b[0] - a[0], b[1] - a[1]), 1 / 3), add(a, (b[0] - a[0], b[1] - a[1]), 2 / 3), b


def cpt(c: Cubic, t: float) -> Pt:
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = c
    m = 1 - t
    return (m ** 3 * x0 + 3 * m * m * t * x1 + 3 * m * t * t * x2 + t ** 3 * x3,
            m ** 3 * y0 + 3 * m * m * t * y1 + 3 * m * t * t * y2 + t ** 3 * y3)


def cder(c: Cubic, t: float) -> Pt:
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = c
    m = 1 - t
    return (3 * m * m * (x1 - x0) + 6 * m * t * (x2 - x1) + 3 * t * t * (x3 - x2),
            3 * m * m * (y1 - y0) + 6 * m * t * (y2 - y1) + 3 * t * t * (y3 - y2))


def csub(c: Cubic, t0: float, t1: float) -> Cubic:
    """Exact sub-curve [t0, t1] (de Casteljau twice)."""
    def split(c: Cubic, t: float) -> tuple[Cubic, Cubic]:
        p01, p12, p23 = (add(c[0], (c[1][0] - c[0][0], c[1][1] - c[0][1]), t),
                         add(c[1], (c[2][0] - c[1][0], c[2][1] - c[1][1]), t),
                         add(c[2], (c[3][0] - c[2][0], c[3][1] - c[2][1]), t))
        p012 = add(p01, (p12[0] - p01[0], p12[1] - p01[1]), t)
        p123 = add(p12, (p23[0] - p12[0], p23[1] - p12[1]), t)
        m = add(p012, (p123[0] - p012[0], p123[1] - p012[1]), t)
        return (c[0], p01, p012, m), (m, p123, p23, c[3])
    right = split(c, t0)[1]
    return split(right, (t1 - t0) / (1 - t0) if t0 < 1 else 0)[0] if t1 < 1 else right


def stroke(segs: list[Cubic], w: float, color: str, cap: str = "butt") -> Shape:
    d = f"M{f(segs[0][0][0])} {f(segs[0][0][1])}" + "".join(
        f"C{f(c[1][0])} {f(c[1][1])} {f(c[2][0])} {f(c[2][1])} {f(c[3][0])} {f(c[3][1])}" for c in segs)
    pts = [add(cpt(c, i / 30), (s * w / 2, s * w / 2)) for c in segs for i in range(31) for s in (-1, 1)]
    return Shape(f'<path fill="none" stroke="{color}" stroke-width="{f(w)}" stroke-linecap="{cap}" '
                 f'stroke-linejoin="round" d="{d}"/>', pts)


def visible(segs: list[Cubic], w: float, holes: list[tuple[Pt, float]]) -> list[list[Cubic]]:
    """Pieces of the stroked path whose whole cross-section stays out of the square holes."""
    def ok(c: Cubic, t: float) -> bool:
        p, d = cpt(c, t), cder(c, t)
        n = math.hypot(*d) or 1.0
        nx, ny = -d[1] / n, d[0] / n
        for s in (-1, -0.5, 0, 0.5, 1):
            q = (p[0] + nx * s * w / 2, p[1] + ny * s * w / 2)
            if any(abs(q[0] - c0[0]) < h and abs(q[1] - c0[1]) < h for c0, h in holes):
                return False
        return True

    pieces, cur = [], []
    for c in segs:
        steps = 400
        start = None
        for i in range(steps + 1):
            t = i / steps
            if ok(c, t):
                start = t if start is None else start
            elif start is not None:
                cur.append(csub(c, start, (i - 1) / steps))
                pieces.append(cur)
                cur, start = [], None
        if start is not None:
            cur.append(csub(c, start, 1.0) if start > 0 else c)
        elif cur:
            pieces.append(cur)
            cur = []
    if cur:
        pieces.append(cur)
    return [p for p in pieces if p]


def handle(node: Pt, knob: Pt, keep_out: float, w: float, r: float, t: float, color: str) -> list[Shape]:
    """Handle line from a gap outside the anchor square to a hollow knob."""
    start = B.clear_of_square(node, keep_out, node, knob, w, GAP)
    u, _ = unit(knob, start)
    return [bar(start, add(knob, u, r - t / 2), w, color), ring(knob, r, t, color)]


# 1. PEN — the V as a path: straight strokes, hollow anchors on every node, the top nodes show handles --
def pen() -> None:
    tl, a, tr = (104, 128), (256, 420), (408, 128)
    s, t, w = 104, 24, 56
    holes = [(p, s / 2 - t) for p in (tl, a, tr)]
    segs = [line_seg(tl, a), line_seg(a, tr)]
    shapes = [stroke(piece, w, NAVY) for piece in visible(segs, w, holes)]
    shapes += [hollow_square(p, s, t, NAVY) for p in (tl, a, tr)]
    for node in (tl, tr):
        u, _ = unit(a, node)
        shapes += handle(node, add(node, u, 168), s / 2, 16, 32, 14, ORANGE)
    B.write("1-pen", "varness — pen: the V as an editable path", shapes)


# 2. SMOOTH — the pen-tool icon turned into a V: the apex is a smooth node with a level handle --------
def smooth() -> None:
    tl, tr, v0 = (112, 112), (400, 112), (256, 440)
    s, t, w = 100, 24, 56
    u, _ = unit(v0, tl)
    j1, j2 = add(v0, u, 132), add(v0, (-u[0], u[1]), 132)
    a = (256, 396)
    c_left = (j1, add(j1, (v0[0] - j1[0], v0[1] - j1[1]), 0.62), (a[0] - 64, a[1]), a)
    c_right = (a, (a[0] + 64, a[1]), add(j2, (v0[0] - j2[0], v0[1] - j2[1]), 0.62), j2)
    segs = [line_seg(tl, j1), c_left, c_right, line_seg(j2, tr)]
    holes = [(p, s / 2 - t) for p in (tl, a, tr)]
    shapes = [stroke(piece, w, NAVY) for piece in visible(segs, w, holes)]
    shapes += [hollow_square(p, s, t, NAVY) for p in (tl, a, tr)]
    for k in ((a[0] - 176, a[1]), (a[0] + 176, a[1])):
        shapes += handle(a, k, s / 2, 18, 34, 16, NAVY)
    B.write("2-smooth", "varness — smooth: the pen-tool curve turned into a V", shapes)


# 3. SKELETON — a calligraphic V knocked out of a key-shaped plate, its own bezier skeleton on top -----
def skeleton() -> None:
    n = [(92, 100), (212, 100), (262, 312), (376, 116), (432, 100), (276, 432)]
    segs: list[Cubic] = [
        line_seg(n[0], n[1]),
        (n[1], (218, 196), (236, 262), n[2]),          # inner edge of the thick stroke
        (n[2], (296, 228), (330, 150), n[3]),          # inner edge of the hairline
        (n[3], (392, 100), (414, 92), n[4]),           # hairline terminal
        (n[4], (366, 196), (318, 348), n[5]),          # outer edge of the hairline
        (n[5], (214, 424), (104, 240), n[0]),          # outer edge of the thick stroke
    ]
    v_path = f"M{f(n[0][0])} {f(n[0][1])}" + "".join(
        f"C{f(c[1][0])} {f(c[1][1])} {f(c[2][0])} {f(c[2][1])} {f(c[3][0])} {f(c[3][1])}" for c in segs) + "Z"
    x0, y0, side, rad = 24, 24, 464, 104
    plate_d = (f"M{x0 + rad} {y0}H{x0 + side - rad}A{rad} {rad} 0 0 1 {x0 + side} {y0 + rad}V{y0 + side - rad}"
               f"A{rad} {rad} 0 0 1 {x0 + side - rad} {y0 + side}H{x0 + rad}A{rad} {rad} 0 0 1 {x0} {y0 + side - rad}"
               f"V{y0 + rad}A{rad} {rad} 0 0 1 {x0 + rad} {y0}Z")
    plate = Shape(f'<path fill="{NAVY}" fill-rule="evenodd" d="{plate_d}{v_path}"/>', [(x0, y0), (x0 + side, y0 + side)])
    shapes = [plate]
    # show the handles of the two outer edges only, extended like a designer dragging them
    for c in (segs[5], segs[4]):
        for node, ctrl in ((c[0], c[1]), (c[3], c[2])):
            u, length = unit(node, ctrl)
            knob = add(node, u, max(length, 90))
            shapes += [bar(node, knob, 10, ORANGE), circle(knob, 15, ORANGE)]
    shapes += [square(p, 34, ORANGE) for p in n]
    B.write("3-skeleton", "varness — skeleton: a calligraphic V with its bezier skeleton", shapes, fill=0.9)


# 4. RULER — the editor canvas: rulers with ticks, the V path, and a knob being dragged ----------------
def ruler() -> None:
    w_r, x_r, y_r = 40, 40, 40                       # ruler thickness, left/top ruler positions
    ext = 472
    top = [(x_r, y_r), (ext, y_r), (ext, y_r + w_r), (x_r, y_r + w_r)]
    left = [(x_r, y_r), (x_r + w_r, y_r), (x_r + w_r, ext), (x_r, ext)]
    # ticks are real notches cut into the rulers (evenodd)
    notch = ""
    for i, pos in enumerate(range(x_r + w_r + 32, ext - 8, 40)):
        depth = 22 if i % 2 else 12
        notch += f"M{pos - 7} {y_r + w_r}V{y_r + w_r - depth}H{pos + 7}V{y_r + w_r}Z"
        notch += f"M{x_r + w_r} {pos - 7}H{x_r + w_r - depth}V{pos + 7}H{x_r + w_r}Z"
    rul_d = ("M" + "L".join(f"{f(x)} {f(y)}" for x, y in [(x_r, y_r), (ext, y_r), (ext, y_r + w_r),
             (x_r + w_r, y_r + w_r), (x_r + w_r, ext), (x_r, ext)]) + "Z" + notch)
    shapes = [Shape(f'<path fill="{NAVY}" fill-rule="evenodd" d="{rul_d}"/>', top + left)]
    tl, a, tr = (156, 160), (276, 404), (396, 160)
    s, t, w = 72, 18, 40
    holes = [(p, s / 2 - t) for p in (tl, a, tr)]
    shapes += [stroke(piece, w, NAVY) for piece in visible([line_seg(tl, a), line_seg(a, tr)], w, holes)]
    shapes += [hollow_square(p, s, t, NAVY) for p in (tl, a, tr)]
    knob = (a[0] + 150, a[1])                           # apex handle being dragged out to the right
    start = B.clear_of_square(a, s / 2, a, knob, 16, GAP)
    shapes += [bar(start, knob, 16, ORANGE), circle(knob, 36, ORANGE)]
    B.write("4-ruler", "varness — ruler: the V on an editor canvas", shapes, fill=0.88)


# 5. SLIDERS — the liked direction in the pen-tool language: an anchor key at the point, two handle tracks
#    ending in knobs, solid square thumbs set to different values ------------------------------------
def sliders() -> None:
    apex, w, thumb, s, t, r = (256, 420), 28, 76, 84, 22, 32
    shapes = [hollow_square(apex, s, t, NAVY)]
    for top, at in (((104, 104), 0.34), ((408, 104), 0.5)):
        u, n = unit(apex, top)
        start = B.clear_of_square(apex, s / 2, apex, top, w, GAP)
        centre = add(apex, u, n * (1 - at))
        ang = math.degrees(math.atan2(u[1], u[0]))
        half = thumb / 2 + GAP                             # thumb is aligned with its track
        shapes += [bar(start, add(centre, u, -half), w, NAVY), bar(add(centre, u, half), add(top, u, -(r - 11)), w, NAVY),
                   ring(top, r, 18, NAVY), square(centre, thumb, ORANGE, ang)]
    B.write("5-sliders", "varness — sliders: handle tracks with square thumbs on an anchor key", shapes)


if __name__ == "__main__":
    smooth()
    skeleton()
    ruler()
    sliders()
