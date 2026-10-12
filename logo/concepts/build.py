"""Build the varness logo concepts: square anchor keys, bezier handles with knobs, the letter V.

Geometry is computed, not eyeballed: handle bars are exact polygons, every part that has its own colour
is separated from its neighbours by a real gap (so the 1-colour version keeps the structure), and each
concept is translated so its bounding box sits in the centre of a 512 canvas.

    python logo/concepts/build.py      # writes logo/concepts/*.svg
"""

from __future__ import annotations

import math
from pathlib import Path

NAVY, AMBER = "#14213d", "#fca311"
HERE = Path(__file__).parent
GAP = 24          # separation between differently coloured parts (≥16 = 1px at 32px)

Pt = tuple[float, float]


def f(v: float) -> str:
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def add(a: Pt, b: Pt, k: float = 1.0) -> Pt:
    return a[0] + b[0] * k, a[1] + b[1] * k


def unit(a: Pt, b: Pt) -> tuple[Pt, float]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    return (dx / n, dy / n), n


class Shape:
    def __init__(self, svg: str, pts: list[Pt]):
        self.svg, self.pts = svg, pts           # pts: points spanning the shape's extent


def poly(pts: list[Pt], color: str) -> Shape:
    d = "M" + "L".join(f"{f(x)} {f(y)}" for x, y in pts) + "Z"
    return Shape(f'<path fill="{color}" d="{d}"/>', pts)


def bar(a: Pt, b: Pt, w: float, color: str) -> Shape:
    """Straight handle bar of width w from a to b (butt ends)."""
    u, _ = unit(a, b)
    n = (-u[1] * w / 2, u[0] * w / 2)
    return poly([add(a, n), add(b, n), add(b, n, -1), add(a, n, -1)], color)


def square(c: Pt, s: float, color: str, rot: float = 0.0) -> Shape:
    h = s / 2
    corners = [(-h, -h), (h, -h), (h, h), (-h, h)]
    r = math.radians(rot)
    pts = [(c[0] + x * math.cos(r) - y * math.sin(r), c[1] + x * math.sin(r) + y * math.cos(r)) for x, y in corners]
    return poly(pts, color)


def hollow_square(c: Pt, s: float, t: float, color: str) -> Shape:
    h, i = s / 2, s / 2 - t
    d = (f"M{f(c[0] - h)} {f(c[1] - h)}H{f(c[0] + h)}V{f(c[1] + h)}H{f(c[0] - h)}Z"
         f"M{f(c[0] - i)} {f(c[1] - i)}V{f(c[1] + i)}H{f(c[0] + i)}V{f(c[1] - i)}Z")
    return Shape(f'<path fill="{color}" fill-rule="evenodd" d="{d}"/>', [(c[0] - h, c[1] - h), (c[0] + h, c[1] + h)])


def circle(c: Pt, r: float, color: str) -> Shape:
    return Shape(f'<circle cx="{f(c[0])}" cy="{f(c[1])}" r="{f(r)}" fill="{color}"/>',
                 [(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)])


def ring(c: Pt, r: float, t: float, color: str) -> Shape:
    i = r - t
    d = (f"M{f(c[0] - r)} {f(c[1])}a{f(r)} {f(r)} 0 1 0 {f(2 * r)} 0a{f(r)} {f(r)} 0 1 0 {f(-2 * r)} 0Z"
         f"M{f(c[0] - i)} {f(c[1])}a{f(i)} {f(i)} 0 1 1 {f(2 * i)} 0a{f(i)} {f(i)} 0 1 1 {f(-2 * i)} 0Z")
    return Shape(f'<path fill="{color}" fill-rule="evenodd" d="{d}"/>', [(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)])


def clear_of(a: Pt, b: Pt, w: float, inside) -> Pt:
    """First point along a→b where a bar of width w is entirely outside the keep-out region."""
    u, n = unit(a, b)
    nx, ny = -u[1], u[0]
    for i in range(int(n)):
        p = add(a, u, i)
        if not any(inside(add(p, (nx, ny), s * w / 2)) for s in (-1, -0.5, 0, 0.5, 1)):
            return p
    raise ValueError("bar never clears the shape")


def clear_of_square(c: Pt, half: float, a: Pt, b: Pt, w: float, gap: float) -> Pt:
    lim = half + gap
    return clear_of(a, b, w, lambda q: abs(q[0] - c[0]) <= lim and abs(q[1] - c[1]) <= lim)


def clear_of_diamond(c: Pt, half_diag: float, a: Pt, b: Pt, w: float, gap: float) -> Pt:
    lim = half_diag + gap * math.sqrt(2)
    return clear_of(a, b, w, lambda q: abs(q[0] - c[0]) + abs(q[1] - c[1]) <= lim)


def clear_of_circle(c: Pt, r: float, a: Pt, b: Pt, w: float, gap: float) -> Pt:
    return clear_of(a, b, w, lambda q: math.hypot(q[0] - c[0], q[1] - c[1]) <= r + gap)


def quad(p0: Pt, c: Pt, p1: Pt, w: float, color: str, t0: float = 0.0, t1: float = 1.0) -> Shape:
    """Part [t0, t1] of a quadratic bezier as a stroke (exact sub-curve via de Casteljau)."""
    def at(t):
        return ((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p1[0],
                (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p1[1])

    def ctrl(ta, tb):  # control point of the sub-curve [ta, tb]
        da = (2 * ((1 - ta) * (c[0] - p0[0]) + ta * (p1[0] - c[0])), 2 * ((1 - ta) * (c[1] - p0[1]) + ta * (p1[1] - c[1])))
        return add(at(ta), da, (tb - ta) / 2)

    a, b, k = at(t0), at(t1), ctrl(t0, t1)
    pts = []
    for i in range(41):
        q = at(t0 + (t1 - t0) * i / 40)
        pts += [(q[0] - w / 2, q[1] - w / 2), (q[0] + w / 2, q[1] + w / 2)]
    d = f"M{f(a[0])} {f(a[1])}Q{f(k[0])} {f(k[1])} {f(b[0])} {f(b[1])}"
    return Shape(f'<path fill="none" stroke="{color}" stroke-width="{f(w)}" stroke-linecap="round" d="{d}"/>', pts)


def write(name: str, title: str, shapes: list[Shape], extra_defs: str = "", fill: float = 0.84) -> None:
    xs = [p[0] for s in shapes for p in s.pts]
    ys = [p[1] for s in shapes for p in s.pts]
    ext = max(max(xs) - min(xs), max(ys) - min(ys))
    k = 512 * fill / ext
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    tf = f"translate(256 256) scale({k:.4f}) translate({f(-cx)} {f(-cy)})"
    body = "".join(s.svg for s in shapes)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><title>{title}</title>{extra_defs}'
           f'<g transform="{tf}">{body}</g></svg>\n')
    (HERE / f"{name}.svg").write_text(svg)
    print(f"{name}: extent {max(xs) - min(xs):.0f}×{max(ys) - min(ys):.0f}, scale {k:.3f}")


def dilated(shape: Shape, g: float) -> str:
    """The shape grown by g in every direction, painted black (for cutting a gap out of a plate)."""
    svg = shape.svg
    if 'stroke-width="' in svg:
        w = float(svg.split('stroke-width="')[1].split('"')[0])
        svg = svg.replace(f'stroke-width="{f(w)}"', f'stroke-width="{f(w + 2 * g)}"')
        return svg.replace('stroke="' + svg.split('stroke="')[1].split('"')[0] + '"', 'stroke="#000"')
    color = svg.split('fill="')[1].split('"')[0]
    return svg.replace(f'fill="{color}"', f'fill="#000" stroke="#000" stroke-width="{f(2 * g)}" stroke-linejoin="round"')


# 1. CORNER — two handle arms meet at a corner key (a square turned 45°: its tip is the V's point) ----
def corner_shapes(color_arm: str = NAVY, color_key: str = AMBER) -> list[Shape]:
    d, h, w, r = (256, 396), 64, 60, 46        # key centre, half-diagonal, arm width, knob radius
    shapes = [square(d, h * math.sqrt(2), color_key, 45)]
    for k in ((108, 120), (404, 120)):
        shapes += [bar(clear_of_diamond(d, h, d, k, w, GAP), k, w, color_arm), circle(k, r, color_arm)]
    return shapes


def corner() -> None:
    write("1-corner", "varness — corner: handle arms meet at a corner key", corner_shapes())


def qpoint(p0: Pt, c: Pt, p1: Pt, t: float) -> Pt:
    return ((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p1[0],
            (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p1[1])


def leave(p0: Pt, c: Pt, p1: Pt, outside, t: float = 0.0, step: float = 0.0025) -> float:
    """Walk t (forward if step > 0) until the curve point satisfies `outside`."""
    while not outside(qpoint(p0, c, p1, t)):
        t += step
    return t


# 2. CONTROL — the V *is* the control polygon of a bezier: thin handles from two square anchor keys to
#    one shared control knob; the curve (the actual drawing) hangs inside in the accent colour ----------
def control() -> None:
    a, b, c = (96, 136), (416, 136), (256, 440)
    s, wh, wc, r = 84, 22, 50, 34
    shapes = []
    for p in (a, b):
        shapes.append(bar(clear_of_square(p, s / 2, p, c, wh, GAP), c, wh, NAVY))       # handle
    shapes += [circle(c, r, NAVY), square(a, s, NAVY), square(b, s, NAVY)]
    lim = s / 2 + GAP + wc / 2
    away = lambda key: (lambda q: max(abs(q[0] - key[0]), abs(q[1] - key[1])) > lim)  # noqa: E731
    t0 = leave(a, c, b, away(a))
    t1 = leave(a, c, b, away(b), 1.0, -0.0025)
    shapes.append(quad(a, c, b, wc, AMBER, t0, t1))
    write("2-control", "varness — control: the V is a bezier's control polygon", shapes)


# 3. SLIDERS — the V is two slider tracks meeting at a knob; square thumbs sit at different values ----
def sliders() -> None:
    apex, w, thumb, r = (256, 420), 26, 84, 40
    shapes = [circle(apex, r, NAVY)]
    for top, at in (((100, 104), 0.36), ((412, 104), 0.62)):
        u, n = unit(top, apex)
        centre = add(top, u, n * at)
        ang = math.degrees(math.atan2(u[1], u[0]))
        half = thumb / 2 + GAP
        before, after = add(centre, u, -half), add(centre, u, half)
        shapes += [bar(top, before, w, NAVY), bar(after, apex, w, NAVY),
                   circle(top, w / 2, NAVY),                               # rounded track end
                   square(centre, thumb, AMBER, ang)]
    write("3-sliders", "varness — sliders: the V is two vector sliders", shapes)


# 4. BADGE — the corner-key V cut out of a rounded square key: the app-icon direction ----------------
def badge() -> None:
    v = corner_shapes(AMBER, AMBER)
    xs = [p[0] for sh in v for p in sh.pts]
    ys = [p[1] for sh in v for p in sh.pts]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    side = max(max(xs) - min(xs), max(ys) - min(ys)) * 1.42
    x0, y0, rad = cx - side / 2, cy - side / 2, side * 0.24
    plate = Shape(f'<rect x="{f(x0)}" y="{f(y0)}" width="{f(side)}" height="{f(side)}" rx="{f(rad)}" '
                  f'fill="{NAVY}" mask="url(#cut)"/>', [(x0, y0), (x0 + side, y0 + side)])
    mask = (f'<defs><mask id="cut" maskUnits="userSpaceOnUse" x="{f(x0)}" y="{f(y0)}" width="{f(side)}" height="{f(side)}">'
            f'<rect x="{f(x0)}" y="{f(y0)}" width="{f(side)}" height="{f(side)}" fill="#fff"/>'
            + "".join(dilated(sh, GAP) for sh in v) + "</mask></defs>")
    write("4-badge", "varness — badge: the corner-key V cut out of a square key", [plate] + v, mask, fill=0.88)


if __name__ == "__main__":
    corner()
    control()
    sliders()
    badge()
