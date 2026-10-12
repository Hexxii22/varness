"""Convert <text> to outlined <path> using a real font file (needs fontTools; uharfbuzz improves kerning).

LLMs cannot draw good letterforms by hand. Writing the wordmark as <text> with a chosen font and
then outlining it gives exact type in a self-contained, machine-independent SVG.
"""

from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET

from .svgdoc import NUMBER_RE, SVG_NS, SvgDoc, local, parse_style

FONT_PROPS = {"font-family", "font-size", "font-weight", "font-style", "text-anchor", "letter-spacing",
              "dominant-baseline", "font-variant", "word-spacing", "text-rendering", "font-stretch"}
FC_WEIGHTS = {100: 0, 200: 40, 300: 50, 400: 80, 500: 100, 600: 180, 700: 200, 800: 205, 900: 210}


class OutlineError(Exception):
    pass


def _num(value, default=0.0) -> float:
    if value is None:
        return default
    m = NUMBER_RE.search(str(value))
    return float(m.group(0)) if m else default


def _fmt(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def resolve_font(family: str, weight: str = "400", style: str = "normal") -> str:
    if not shutil.which("fc-match"):
        raise OutlineError("no --font given and fc-match is not installed to find one")
    w = {"normal": 400, "bold": 700}.get(weight, None) or int(_num(weight, 400))
    fcw = FC_WEIGHTS[min(FC_WEIGHTS, key=lambda k: abs(k - w))]
    slant = ":slant=100" if style in ("italic", "oblique") else ""
    pattern = f"{family}:weight={fcw}{slant}"
    proc = subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True, timeout=20)
    path = proc.stdout.strip()
    if proc.returncode != 0 or not path:
        raise OutlineError(f"fc-match found nothing for {pattern!r}")
    return path


def _load_font(path: str, fonts: dict):
    """Fonts are cached per outline() call (the dict lives in the call), keyed by path."""
    if path not in fonts:
        try:
            from fontTools.ttLib import TTFont
        except ImportError as e:
            raise OutlineError("outlining needs fontTools: pip install 'varness[fonts]'") from e
        fonts[path] = TTFont(path, fontNumber=0, lazy=True)
    return fonts[path]


def _shape(font, path: str, text: str) -> list[tuple[str, float, float, float]]:
    """(glyph name, x_advance, x_offset, y_offset) in font units; HarfBuzz if available."""
    try:
        import uharfbuzz as hb

        blob = hb.Blob.from_file_path(path)
        hbfont = hb.Font(hb.Face(blob))
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(hbfont, buf, {"kern": True, "liga": True})
        return [(font.getGlyphName(i.codepoint), p.x_advance, p.x_offset, p.y_offset)
                for i, p in zip(buf.glyph_infos, buf.glyph_positions)]
    except ImportError:
        pass
    cmap = font.getBestCmap() or {}
    hmtx = font["hmtx"]
    kern = {}
    if "kern" in font:
        for table in getattr(font["kern"], "kernTables", []):
            kern.update(getattr(table, "kernTable", {}) or {})
    out = []
    prev = None
    for ch in text:
        g = cmap.get(ord(ch), ".notdef")
        adv = hmtx[g][0]
        if prev is not None and (prev, g) in kern and out:
            name, a, xo, yo = out[-1]
            out[-1] = (name, a + kern[(prev, g)], xo, yo)
        out.append((g, adv, 0, 0))
        prev = g
    return out


def _prop(el: ET.Element, name: str, parents: dict) -> str | None:
    node = el
    while node is not None:
        style = parse_style(node.get("style", ""))
        if name in style:
            return style[name]
        if node.get(name) is not None:
            return node.get(name)
        node = parents.get(node)
    return None


def outline(doc: SvgDoc, font_path: str | None = None) -> tuple[str, list[str]]:
    try:
        from fontTools.pens.svgPathPen import SVGPathPen
        from fontTools.pens.transformPen import TransformPen
    except ImportError as e:
        raise OutlineError("outlining needs fontTools: pip install 'varness[fonts]'") from e

    root = doc.clone_root()
    parents = {c: p for p in root.iter() for c in p}
    notes: list[str] = []
    fonts: dict = {}
    texts = [el for el in root.iter() if local(el.tag) == "text"]
    if not texts:
        return doc.raw, ["no <text> elements found"]
    for el in texts:
        content = "".join(el.itertext()).strip()
        if any(local(c.tag) == "tspan" for c in el.iter()):
            notes.append("tspans were flattened into one run (their own x/y/dx are ignored)")
        family = (_prop(el, "font-family", parents) or "sans-serif").split(",")[0].strip().strip("'\"")
        weight = _prop(el, "font-weight", parents) or "400"
        fstyle = _prop(el, "font-style", parents) or "normal"
        path = font_path or resolve_font(family, weight, fstyle)
        font = _load_font(path, fonts)
        size = _num(_prop(el, "font-size", parents), 16.0)
        ls = _prop(el, "letter-spacing", parents)
        spacing = 0.0 if ls in (None, "normal") else _num(ls, 0.0)
        anchor = (_prop(el, "text-anchor", parents) or "start").strip()
        x, y = _num(el.get("x")), _num(el.get("y"))
        upem = font["head"].unitsPerEm
        s = size / upem
        glyphs = _shape(font, path, content)
        width = sum(a for _, a, _, _ in glyphs) * s + spacing * max(0, len(glyphs) - 1)
        x0 = x - (width / 2 if anchor == "middle" else width if anchor == "end" else 0)
        glyph_set = font.getGlyphSet()
        pen = SVGPathPen(glyph_set, ntos=_fmt)
        cursor = 0.0
        missing = 0
        for name, adv, xo, yo in glyphs:
            if name == ".notdef":
                missing += 1
            tx = x0 + (cursor + xo) * s
            glyph_set[name].draw(TransformPen(pen, (s, 0, 0, -s, tx, y - yo * s)))
            cursor += adv + spacing / s
        if missing:
            notes.append(f"{missing} character(s) of {content!r} are missing from {path}")
        new = ET.Element(f"{{{SVG_NS}}}path")
        for k, v in el.attrib.items():
            if k in ("x", "y", "dx", "dy", "style") or k in FONT_PROPS:
                continue
            new.set(k, v)
        rest = {k: v for k, v in parse_style(el.get("style", "")).items() if k not in FONT_PROPS}
        if rest:
            new.set("style", ";".join(f"{k}:{v}" for k, v in rest.items()))
        new.set("d", pen.getCommands())
        new.set("data-text", content)
        parent = parents[el]
        idx = list(parent).index(el)
        parent.remove(el)
        parent.insert(idx, new)
        notes.append(f"outlined {content!r} with {path} at {size:g}px, width {width:.1f} units")
    return ET.tostring(root, encoding="unicode"), notes
