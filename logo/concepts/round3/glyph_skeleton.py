"""Extract a glyph's real bezier skeleton (on-curve nodes, off-curve handles) from a font.

TrueType outlines are quadratic; they are converted to cubic with fontTools' Qu2CuPen (merging
quadratic splines into as few cubic segments as the tolerance allows), which is what a type designer
sees after opening the glyph in a cubic editor.
"""

from __future__ import annotations

from dataclasses import dataclass

from fontTools.pens.qu2cuPen import Qu2CuPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont

Pt = tuple[float, float]


@dataclass
class Skeleton:
    d: str                                   # SVG path of the glyph (y down, fitted)
    nodes: list[Pt]                          # on-curve points
    handles: list[tuple[Pt, Pt]]             # (node, control point)
    box: tuple[float, float, float, float]   # fitted bbox x0, y0, x1, y1


def glyph_skeleton(font_path: str, char: str, box: tuple[float, float, float, float], max_err: float = 1.0) -> Skeleton:
    font = TTFont(font_path)
    gname = font.getBestCmap()[ord(char)]
    rec = RecordingPen()
    glyph = font.getGlyphSet()[gname]
    glyph.draw(Qu2CuPen(rec, max_err=max_err, all_cubic=True))

    xs, ys = [], []
    for _, pts in rec.value:
        for x, y in pts:
            xs.append(x)
            ys.append(y)
    gx0, gx1, gy0, gy1 = min(xs), max(xs), min(ys), max(ys)
    bx0, by0, bx1, by1 = box
    k = min((bx1 - bx0) / (gx1 - gx0), (by1 - by0) / (gy1 - gy0))
    ox = bx0 + ((bx1 - bx0) - (gx1 - gx0) * k) / 2
    oy = by0 + ((by1 - by0) - (gy1 - gy0) * k) / 2

    def tr(p: Pt) -> Pt:
        return ox + (p[0] - gx0) * k, oy + (gy1 - p[1]) * k

    def fmt(p: Pt) -> str:
        return f"{p[0]:.1f} {p[1]:.1f}"

    d, nodes, handles = [], [], []
    cur: Pt | None = None
    for op, pts in rec.value:
        if op == "moveTo":
            cur = tr(pts[0])
            d.append("M" + fmt(cur))
            nodes.append(cur)
        elif op == "lineTo":
            cur = tr(pts[0])
            d.append("L" + fmt(cur))
            nodes.append(cur)
        elif op == "curveTo":
            c1, c2, p = (tr(q) for q in pts)
            d.append("C" + " ".join(fmt(q) for q in (c1, c2, p)))
            handles += [(cur, c1), (p, c2)]
            cur = p
            nodes.append(p)
        elif op in ("closePath", "endPath"):
            d.append("Z")
    # a closed contour repeats its start point as the last node; keep unique positions
    uniq: list[Pt] = []
    for n in nodes:
        if all(abs(n[0] - u[0]) > 0.5 or abs(n[1] - u[1]) > 0.5 for u in uniq):
            uniq.append(n)
    fitted = (ox, oy, ox + (gx1 - gx0) * k, oy + (gy1 - gy0) * k)
    return Skeleton("".join(d), uniq, handles, fitted)
