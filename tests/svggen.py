"""Hypothesis strategies for random SVG logos, biased toward the edges where bugs live.

Edge bias (QuickCheck/EvalPlus): empty documents, missing viewBox, degenerate and extreme canvases
(0 0 1 1, 10×1000, 100000²), shapes outside the canvas, zero-size shapes, hairlines, huge strokes,
nested transforms incl. tiny matrix scales, gradients, masks, currentColor, opacity, evenodd holes.
"""

from hypothesis import strategies as st

VIEWBOXES = [
    (0, 0, 512, 512), (0, 0, 1, 1), (0, 0, 24, 24), (-50, -50, 100, 100),
    (0, 0, 2000, 500), (0, 0, 10, 1000), (0, 0, 100000, 100000), (0, 0, 640, 160),
]
COLORS = ["#000", "#fff", "#14213d", "#fca311", "#e0457b", "#2e9e8f", "red", "rgb(10, 200, 30)",
          "currentColor", "none", "url(#g)"]


@st.composite
def number(draw, lo: float, hi: float):
    special = draw(st.sampled_from([None, None, None, lo, hi, (lo + hi) / 2, 0.0]))
    if special is not None:
        return special
    return draw(st.floats(lo, hi, allow_nan=False, allow_infinity=False))


def _fmt(v: float) -> str:
    return f"{v:.4g}"


@st.composite
def shape(draw, vb, depth: int = 0):
    x, y, w, h = vb
    # coordinates may fall outside the canvas on purpose
    X = lambda: _fmt(draw(number(x - 0.3 * w, x + 1.3 * w)))  # noqa: E731
    Y = lambda: _fmt(draw(number(y - 0.3 * h, y + 1.3 * h)))  # noqa: E731
    S = lambda: _fmt(abs(draw(number(0, 0.8 * min(w, h)))))  # noqa: E731
    fill = draw(st.sampled_from(COLORS))
    extra = ""
    if draw(st.booleans()):
        extra += f' stroke="{draw(st.sampled_from(COLORS))}" stroke-width="{S()}"'
    if draw(st.integers(0, 6)) == 0:
        extra += f' opacity="{draw(st.sampled_from(["0", "0.5", "1"]))}"'
    if draw(st.integers(0, 6)) == 0:
        extra += ' fill-rule="evenodd"'
    kind = draw(st.sampled_from(["rect", "circle", "ellipse", "path", "polygon", "line", "group", "text"]))
    if kind == "rect":
        return f'<rect x="{X()}" y="{Y()}" width="{S()}" height="{S()}" rx="{S()}" fill="{fill}"{extra}/>'
    if kind == "circle":
        return f'<circle cx="{X()}" cy="{Y()}" r="{S()}" fill="{fill}"{extra}/>'
    if kind == "ellipse":
        return f'<ellipse cx="{X()}" cy="{Y()}" rx="{S()}" ry="{S()}" fill="{fill}"{extra}/>'
    if kind == "line":
        return f'<line x1="{X()}" y1="{Y()}" x2="{X()}" y2="{Y()}" stroke="{fill}" stroke-width="{S()}"/>'
    if kind == "polygon":
        pts = " ".join(f"{X()},{Y()}" for _ in range(draw(st.integers(0, 6))))
        return f'<polygon points="{pts}" fill="{fill}"{extra}/>'
    if kind == "path":
        d = f"M{X()} {Y()}"
        for _ in range(draw(st.integers(0, 5))):
            cmd = draw(st.sampled_from("LQCAZ"))
            if cmd == "L":
                d += f"L{X()} {Y()}"
            elif cmd == "Q":
                d += f"Q{X()} {Y()} {X()} {Y()}"
            elif cmd == "C":
                d += f"C{X()} {Y()} {X()} {Y()} {X()} {Y()}"
            elif cmd == "A":
                d += f"A{S()} {S()} 0 {draw(st.integers(0, 1))} {draw(st.integers(0, 1))} {X()} {Y()}"
            else:
                d += "Z"
        return f'<path d="{d}" fill="{fill}"{extra}/>'
    if kind == "text":
        return f'<text x="{X()}" y="{Y()}" font-size="{S()}" fill="{fill}">Ab</text>'
    if depth >= 2:
        return f'<rect x="{X()}" y="{Y()}" width="{S()}" height="{S()}" fill="{fill}"/>'
    tf = draw(st.sampled_from([
        "", f"translate({X()} {Y()})", f"rotate({draw(st.integers(-180, 180))} {X()} {Y()})",
        "scale(0.5)", "matrix(0.70710678 0.70710678 -0.70710678 0.70710678 0 0)", "scale(0.004)",
    ]))
    kids = "".join(draw(st.lists(shape(vb, depth + 1), max_size=3)))
    color = ' color="#e0457b"' if draw(st.booleans()) else ""
    tf_attr = f' transform="{tf}"' if tf else ""
    return f"<g{tf_attr}{color}>{kids}</g>"


@st.composite
def svg_doc(draw, max_shapes: int = 6):
    vb = draw(st.sampled_from(VIEWBOXES))
    x, y, w, h = vb
    head = draw(st.sampled_from(["viewbox", "viewbox", "viewbox", "wh", "none"]))
    if head == "viewbox":
        attrs = f'viewBox="{x} {y} {w} {h}"'
    elif head == "wh":
        attrs = f'width="{w}" height="{h}"'
    else:
        attrs = ""
    defs = ('<defs><linearGradient id="g"><stop offset="0" stop-color="#14213d"/>'
            '<stop offset="1" stop-color="#fca311"/></linearGradient></defs>')
    body = "".join(draw(st.lists(shape(vb), max_size=max_shapes)))
    if draw(st.integers(0, 8)) == 0:
        body = (f'<mask id="m"><rect x="{x}" y="{y}" width="{w}" height="{h}" fill="white"/>'
                f'<circle cx="{x + w / 2}" cy="{y + h / 2}" r="{min(w, h) / 6}" fill="black"/></mask>'
                f'<g mask="url(#m)">{body}</g>')
    title = "<title>t</title>" if draw(st.booleans()) else ""
    return f'<svg xmlns="http://www.w3.org/2000/svg" {attrs}>{title}{defs}{body}</svg>'


def nested(depth: int) -> str:
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">' + "<g>" * depth + \
        '<rect width="5" height="5"/>' + "</g>" * depth + "</svg>"
