"""Build an SVG from a JSON shape spec: primitives, real boolean cuts, radial repeats, fillets, grid snapping.

Agents get geometry wrong when they hand-compute arcs and fake holes; here they describe *what* (a ring,
an arc with radial ends, a disc minus a drop) and the curves, cuts and rounding are computed exactly.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

try:
    import pathops
except ImportError:  # optional: pip install 'varness[build]'
    pathops = None


class BuildError(ValueError):
    pass


PRIMITIVES = ("circle", "rect", "ring", "arc", "polygon", "ngon")
OPS = ("union", "subtract", "intersect")


def _polar(cx, cy, r, deg):
    """Designer angles: 0° = 12 o'clock, clockwise."""
    a = math.radians(deg)
    return cx + r * math.sin(a), cy - r * math.cos(a)


def _closed(p):
    p.close()
    p.convertConicsToQuads(0.2)  # path ops reject conics (what arcTo makes); 0.2 units is invisible
    return p


def _circle(cx, cy, r, clockwise=True):
    p = pathops.Path()
    sweep = pathops.Direction.CW if clockwise else pathops.Direction.CCW
    p.moveTo(cx, cy - r)
    p.arcTo(r, r, 0, pathops.ArcSize.SMALL, sweep, cx, cy + r)
    p.arcTo(r, r, 0, pathops.ArcSize.SMALL, sweep, cx, cy - r)
    return _closed(p)


def _arc(cx, cy, R, r, a0, a1):
    """Annular sector from a0 to a1 (clockwise) with radial ends."""
    span = (a1 - a0) % 360 or 360
    if span >= 360:
        return _op(_circle(cx, cy, R), _circle(cx, cy, r), "subtract")
    large = pathops.ArcSize.LARGE if span > 180 else pathops.ArcSize.SMALL
    p = pathops.Path()
    p.moveTo(*_polar(cx, cy, R, a0))
    p.arcTo(R, R, 0, large, pathops.Direction.CW, *_polar(cx, cy, R, a0 + span))
    p.lineTo(*_polar(cx, cy, r, a0 + span))
    if r > 0:
        p.arcTo(r, r, 0, large, pathops.Direction.CCW, *_polar(cx, cy, r, a0))
    return _closed(p)


def _polygon(pts, radius=0):
    """Closed polygon; radius (one number or one per corner) rounds corners with a true tangent arc,
    clamped to fit the edges."""
    n = len(pts)
    if n < 3:
        raise BuildError("polygon needs at least 3 points")
    radii = list(radius) if isinstance(radius, (list, tuple)) else [radius] * n
    p = pathops.Path()
    if not any(radii):
        p.moveTo(*pts[0])
        for q in pts[1:]:
            p.lineTo(*q)
        return _closed(p)
    for i in range(n):
        (ax, ay), (vx, vy), (bx, by) = pts[i - 1], pts[i], pts[(i + 1) % n]
        ux, uy, la = ax - vx, ay - vy, math.hypot(ax - vx, ay - vy)
        wx, wy, lb = bx - vx, by - vy, math.hypot(bx - vx, by - vy)
        if not la or not lb:
            raise BuildError("polygon has repeated points")
        half = math.acos(max(-1.0, min(1.0, (ux * wx + uy * wy) / (la * lb)))) / 2
        if half <= 1e-6 or half >= math.pi / 2 - 1e-6:  # straight or folded corner: nothing to round
            t1 = t2 = (vx, vy)
            r = 0
        else:
            d = min(radii[i] / math.tan(half), la / 2, lb / 2)
            r = d * math.tan(half)
            t1 = (vx + ux / la * d, vy + uy / la * d)
            t2 = (vx + wx / lb * d, vy + wy / lb * d)
        (p.moveTo if i == 0 else p.lineTo)(*t1)
        if r:
            turn = ux * wy - uy * wx  # sign of the corner's turn decides the arc direction
            p.arcTo(r, r, 0, pathops.ArcSize.SMALL,
                    pathops.Direction.CCW if turn > 0 else pathops.Direction.CW, *t2)
    return _closed(p)


def _ngon(cx, cy, R, n, star=None, rot=0):
    if n < 3:
        raise BuildError("ngon needs n >= 3")
    if star:
        return [_polar(cx, cy, R if k % 2 == 0 else star, rot + k * 180 / n) for k in range(2 * n)]
    return [_polar(cx, cy, R, rot + k * 360 / n) for k in range(n)]


def _op(a, b, kind):
    which = {"union": pathops.PathOp.UNION, "subtract": pathops.PathOp.DIFFERENCE,
             "intersect": pathops.PathOp.INTERSECTION}[kind]
    try:
        return pathops.op(a, b, which)
    except pathops.PathOpsError as e:
        raise BuildError(f"{kind} failed: {e}") from None


def _rotate(path, deg, cx, cy):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return path.transform(c, s, -s, c, cx - c * cx + s * cy, cy - s * cx - c * cy)


class _Builder:
    def __init__(self, w, h, snap):
        self.w, self.h, self.snap = w, h, snap
        self.warnings: list[str] = []

    def check_snap(self, where, values):
        if not self.snap:
            return
        for v in values:
            if abs(v / self.snap - round(v / self.snap)) > 1e-6:
                self.warnings.append(f"{where}: {v:g} is off the {self.snap:g}-unit grid")

    def node(self, n, where="shape"):
        if not isinstance(n, dict):
            raise BuildError(f"{where}: expected an object, got {n!r}")
        kinds = [k for k in (*PRIMITIVES, *OPS) if k in n]
        if len(kinds) != 1:
            raise BuildError(f"{where}: needs exactly one of {', '.join(PRIMITIVES + OPS)}")
        kind = kinds[0]
        arg = n[kind]
        here = f"{where}.{kind}"
        try:
            path = self._make(kind, arg, n, here)
        except (TypeError, ValueError, KeyError) as e:
            if isinstance(e, BuildError):
                raise
            raise BuildError(f"{here}: bad arguments {arg!r} ({e})") from None
        cx, cy = self.w / 2, self.h / 2
        if "translate" in n:
            dx, dy = n["translate"]
            self.check_snap(f"{here}.translate", (dx, dy))
            path = path.transform(1, 0, 0, 1, dx, dy)
        if "rotate" in n:
            deg, *about = n["rotate"] if isinstance(n["rotate"], list) else [n["rotate"]]
            path = _rotate(path, deg, *(about or (cx, cy)))
        if "mirror" in n:
            m = n["mirror"]
            if m not in ("x", "y"):
                raise BuildError(f"{here}.mirror: use \"x\" (left-right) or \"y\" (top-bottom)")
            flip = path.transform(-1, 0, 0, 1, 2 * cx, 0) if m == "x" else path.transform(1, 0, 0, -1, 0, 2 * cy)
            path = _op(path, flip, "union")
        if "repeat" in n:
            k, *about = n["repeat"] if isinstance(n["repeat"], list) else [n["repeat"]]
            if k < 1:
                raise BuildError(f"{here}.repeat: needs n >= 1")
            base, about = path, about or (cx, cy)
            for i in range(1, int(k)):
                path = _op(path, _rotate(base, 360 * i / k, *about), "union")
        return path

    def _point(self, pt, here):
        """[x, y] / [x, y, corner_r], or {"polar": [r, angle], "about": [x, y], "r": corner_r}
        (about defaults to the canvas centre; only r and about snap). Returns (x, y, corner_r or None)."""
        if isinstance(pt, dict):
            rad, deg = pt["polar"]
            about = pt.get("about", (self.w / 2, self.h / 2))
            self.check_snap(here, (rad, *about))
            return (*_polar(*about, rad, deg), pt.get("r"))
        self.check_snap(here, pt)
        x, y, *own = pt
        if len(own) > 1:
            raise BuildError(f"{here}: a point is [x, y] or [x, y, corner_radius], got {pt!r}")
        return x, y, (own or [None])[0]

    def _make(self, kind, arg, n, here):
        r = n.get("r", 0)
        if kind == "circle":
            cx, cy, rad = arg
            self.check_snap(here, arg)
            return _circle(cx, cy, rad)
        if kind == "ring":
            cx, cy, R, rin = arg
            self.check_snap(here, arg)
            return _op(_circle(cx, cy, R), _circle(cx, cy, rin), "subtract")
        if kind == "arc":
            cx, cy, R, rin, a0, a1 = arg
            self.check_snap(here, arg[:4])
            return _arc(cx, cy, R, rin, a0, a1)
        if kind == "rect":
            x, y, w, h = arg
            self.check_snap(here, (*arg, r))
            return _polygon([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], r)
        if kind == "polygon":
            self.check_snap(here, [r])
            pts = [self._point(pt, here) for pt in arg]  # a corner's own radius (0 = sharp) beats "r"
            return _polygon([(x, y) for x, y, _ in pts], [r if own is None else own for _, _, own in pts])
        if kind == "ngon":
            cx, cy, R, k = arg
            self.check_snap(here, (cx, cy, R))
            return _polygon(_ngon(cx, cy, R, int(k), n.get("star"), n.get("rot", 0)), r)
        parts = [self.node(c, f"{here}[{i}]") for i, c in enumerate(arg)]
        if not parts:
            raise BuildError(f"{here}: needs at least one shape")
        out = parts[0]
        for p in parts[1:]:
            out = _op(out, p, kind)
        return out


def _fmt(v):
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def path_d(path) -> str:
    """Path → SVG d with 1-decimal coordinates."""
    V = pathops.PathVerb
    cmd = {V.MOVE: ("M", 1), V.LINE: ("L", 1), V.QUAD: ("Q", 2), V.CUBIC: ("C", 3), V.CLOSE: ("Z", 0)}
    pts = iter(path.points)
    out = []
    for verb in path.verbs:
        letter, n = cmd[verb]  # no CONIC: _closed() converted them
        out.append(letter + " ".join(f"{_fmt(x)} {_fmt(y)}" for x, y in (next(pts) for _ in range(n))))
    return "".join(out)


def build(spec: dict) -> tuple[str, list[str]]:
    """Return (svg text, warnings)."""
    if pathops is None:
        raise BuildError("`varness build` needs skia-pathops: pip install 'varness[build]'")
    size = spec.get("size", 512)
    w, h = (size, size) if isinstance(size, (int, float)) else size
    layers = spec.get("layers")
    if not layers:
        raise BuildError("spec needs a non-empty \"layers\" list")
    b = _Builder(w, h, spec.get("snap"))
    body = []
    for i, layer in enumerate(layers):
        if "shape" not in layer:
            raise BuildError(f"layers[{i}]: needs \"shape\"")
        d = path_d(b.node(layer["shape"], f"layers[{i}]"))
        if not d:
            b.warnings.append(f"layers[{i}]: shape is empty (a cut removed everything?)")
            continue
        body.append(f'  <path fill={quoteattr(str(layer.get("fill", "#000")))} d="{d}"/>')
    title = f"<title>{escape(str(spec['title']))}</title>\n" if spec.get("title") else ""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_fmt(w)} {_fmt(h)}">\n{title}'
           + "\n".join(body) + "\n</svg>\n")
    return svg, b.warnings


def build_file(spec_path: str | Path) -> tuple[str, list[str]]:
    try:
        spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise BuildError(f"{spec_path}: invalid JSON ({e})") from None
    return build(spec)
