"""Parsing and rewriting of SVG documents (structure only, no rendering)."""

from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)

MAX_DEPTH = 256  # ElementTree serialises recursively; deeper trees would hit RecursionError
COLOR_PROPS = ("fill", "stroke", "stop-color", "color", "flood-color", "lighting-color")
NUMBER_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
PATH_CMD_RE = re.compile(r"[MmZzLlHhVvCcSsQqTtAa]")
URL_REF_RE = re.compile(r"url\(\s*['\"]?#([^)'\"\s]+)['\"]?\s*\)")
CSS_COLOR_RE = re.compile(r"((?<![\w-])(?:fill|stroke|stop-color|color|flood-color|lighting-color)\s*:\s*)([^;}]+)")
NAMED_COLORS = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000",
    "blue": "#0000ff", "yellow": "#ffff00", "orange": "#ffa500", "purple": "#800080",
    "gray": "#808080", "grey": "#808080", "navy": "#000080", "teal": "#008080",
    "maroon": "#800000", "olive": "#808000", "lime": "#00ff00", "aqua": "#00ffff",
    "cyan": "#00ffff", "fuchsia": "#ff00ff", "magenta": "#ff00ff", "silver": "#c0c0c0",
}
SKIP_COLOR_VALUES = {"none", "transparent", "inherit", "currentcolor", "context-fill", "context-stroke", ""}
LENGTH_ATTRS = {"d", "points", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "fx", "fy",
                "width", "height", "stroke-width"}
SIZE_ATTRS = {"width", "height", "r", "rx", "ry", "stroke-width"}
DRAWABLE = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "use", "image"}


class SvgError(Exception):
    """Raised when a file is not a parseable SVG."""


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if isinstance(tag, str) and tag.startswith("{") else ""


def parse_style(style: str) -> dict[str, str]:
    out = {}
    for decl in style.split(";"):
        if ":" in decl:
            k, v = decl.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def format_style(props: dict[str, str]) -> str:
    return ";".join(f"{k}:{v}" for k, v in props.items())


def normalize_color(value: str) -> str | None:
    """Return '#rrggbb' for a CSS colour, None for none/url()/unknown."""
    v = value.strip().lower()
    if v in SKIP_COLOR_VALUES or v.startswith("url("):
        return None
    if v in NAMED_COLORS:
        return NAMED_COLORS[v]
    m = re.fullmatch(r"#([0-9a-f]{3,8})", v)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h[:3])
        return "#" + h[:6] if len(h) in (6, 8) else None
    m = re.fullmatch(r"rgba?\(([^)]*)\)", v)
    if m:
        parts = re.split(r"[\s,/]+", m.group(1).strip())
        try:
            rgb = [
                round(float(p[:-1]) * 2.55) if p.endswith("%") else round(float(p))
                for p in parts[:3]
            ]
        except ValueError:
            return None
        return "#" + "".join(f"{max(0, min(255, c)):02x}" for c in rgb)
    return None


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


@dataclass(frozen=True)
class Inventory:
    """Everything lint needs, gathered in one pass over the tree."""
    counts: Counter
    colors: frozenset
    path_commands: int
    path_numbers: int
    long_decimals: int
    ids: Counter
    local_refs: frozenset
    external_refs: tuple
    has_script: bool
    foreign_namespaces: frozenset
    uses_opacity: bool
    uses_strokes: bool
    use_depth: int          # longest chain of <use> → target containing <use> → …
    use_cycle: bool         # a <use> that (indirectly) references itself

    @property
    def drawables(self) -> int:
        return sum(n for t, n in self.counts.items() if t in DRAWABLE)


def _paint_props(el: ET.Element) -> dict[str, str]:
    props = dict(el.attrib)
    if "style" in el.attrib:
        props.update(parse_style(el.attrib["style"]))
    return props


@dataclass(eq=False)
class SvgDoc:
    raw: str
    root: ET.Element
    path: str | None = None
    render_cache: dict = field(default_factory=dict, repr=False)  # lives and dies with this document

    # -- loading ---------------------------------------------------------------------------
    @classmethod
    def load(cls, source: str | Path) -> "SvgDoc":
        p = Path(source)
        try:
            raw = p.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise SvgError(f"{p}: not UTF-8 text ({e})") from e
        return cls.from_string(raw, path=str(p))

    @classmethod
    def from_string(cls, raw: str, path: str | None = None) -> "SvgDoc":
        if re.search(r"<!ENTITY", raw, re.I):
            raise SvgError("DOCTYPE entities are not allowed in a logo master")
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise SvgError(f"XML parse error: {e}") from e
        if local(root.tag) != "svg":
            raise SvgError(f"root element is <{local(root.tag)}>, expected <svg>")
        stack = [(root, 1)]
        while stack:
            el, depth = stack.pop()
            if depth > MAX_DEPTH:
                raise SvgError(f"elements nested deeper than {MAX_DEPTH} levels")
            stack.extend((child, depth + 1) for child in el)
        return cls(raw=raw, root=root, path=path)

    @property
    def name(self) -> str:
        return Path(self.path).name if self.path else "<string>"

    @cached_property
    def sha(self) -> str:
        return hashlib.sha256(self.raw.encode("utf-8")).hexdigest()[:12]

    # -- geometry --------------------------------------------------------------------------
    @cached_property
    def viewbox(self) -> tuple[float, float, float, float] | None:
        vb = self.root.get("viewBox")
        if not vb:
            return None
        nums = [float(n) for n in NUMBER_RE.findall(vb)]
        if len(nums) != 4 or nums[2] <= 0 or nums[3] <= 0:
            return None
        return tuple(nums)  # type: ignore[return-value]

    def canvas_size(self) -> tuple[float, float]:
        """User-space width/height of the drawing (viewBox, else width/height, else 300x150)."""
        vb = self.viewbox
        if vb:
            return vb[2], vb[3]
        w = _length(self.root.get("width")) or 300.0
        h = _length(self.root.get("height")) or 150.0
        return w, h

    @property
    def aspect(self) -> float:
        w, h = self.canvas_size()
        return w / h

    # -- inventory -------------------------------------------------------------------------
    def iter(self):
        return self.root.iter()

    def counts(self) -> Counter:
        return self.inv.counts

    @cached_property
    def inv(self) -> Inventory:
        counts: Counter = Counter()
        colors: set[str] = set()
        ids: Counter = Counter()
        refs = set(URL_REF_RE.findall(self.raw))
        external: list[str] = []
        foreign: set[str] = set()
        commands = numbers = long_decimals = 0
        script = opacity = strokes = False
        id_map: dict[str, ET.Element] = {}
        uses: list[ET.Element] = []
        for el in self.root.iter():
            tag = local(el.tag)
            counts[tag] += 1
            if tag == "use":
                uses.append(el)
            ns = namespace(el.tag)
            if ns and ns != SVG_NS:
                foreign.add(ns)
            for k, v in el.attrib.items():
                kns = namespace(k)
                if kns and kns not in (SVG_NS, XLINK_NS, XML_NS):
                    foreign.add(kns)
                if k.lower().startswith("on"):
                    script = True
                if local(k) == "href":
                    if v.startswith("#"):
                        refs.add(v[1:])
                    else:
                        external.append(v[:80])
            if el.get("id"):
                ids[el.get("id")] += 1
                id_map.setdefault(el.get("id"), el)
            props = _paint_props(el)
            for prop in COLOR_PROPS:
                if prop in props and (c := normalize_color(props[prop])):
                    colors.add(c)
            for k in ("opacity", "fill-opacity", "stroke-opacity", "stop-opacity"):
                try:
                    opacity = opacity or (k in props and float(props[k]) < 0.999)
                except ValueError:
                    pass
            stroke = props.get("stroke", "").strip().lower()
            if stroke and stroke != "none" and props.get("stroke-width", "1").strip() not in ("0", "0px"):
                strokes = True
            if tag == "style" and el.text:
                colors.update(c for m in CSS_COLOR_RE.finditer(el.text) if (c := normalize_color(m.group(2))))
            elif tag == "script":
                script = True
            elif tag == "path":
                d = el.get("d", "")
                commands += len(PATH_CMD_RE.findall(d))
                nums = NUMBER_RE.findall(d)
                numbers += len(nums)
                long_decimals += sum(1 for n in nums if _decimals(n) > 3)
            elif tag in ("polygon", "polyline"):
                nums = NUMBER_RE.findall(el.get("points", ""))
                numbers += len(nums)
                commands += max(1, len(nums) // 2)
            elif tag in ("rect", "circle", "ellipse", "line"):
                commands += 1
        external += re.findall(r"@import[^;]+", self.raw)
        external += [u for u in re.findall(r"url\(\s*['\"]?([^)'\"]+)", self.raw)
                     if not u.startswith(("#", "data:"))]
        use_depth, use_cycle = _use_chains(uses, id_map)
        return Inventory(counts, frozenset(colors), commands, numbers, long_decimals, ids, frozenset(refs),
                         tuple(external), script, frozenset(foreign), opacity, strokes, use_depth, use_cycle)

    # -- rewriting -------------------------------------------------------------------------
    def clone_root(self) -> ET.Element:
        return ET.fromstring(ET.tostring(self.root, encoding="unicode"))

    @cached_property
    def render_source(self) -> str:
        """Markup to rasterise: without a viewBox, pin the canvas to canvas_size() so renderers
        don't auto-fit to the content (metrics and renders must agree on one coordinate system)."""
        return self.raw if self.viewbox else self.with_viewbox((0.0, 0.0, *self.canvas_size()))

    def pin_canvas(self, svg: str) -> str:
        """Apply the same canvas pinning to a rewritten variant of this document."""
        if self.viewbox:
            return svg
        return SvgDoc.from_string(svg).with_viewbox((0.0, 0.0, *self.canvas_size()))

    def with_viewbox(self, vb: tuple[float, float, float, float]) -> str:
        root = self.clone_root()
        root.set("viewBox", " ".join(f"{v:.6g}" for v in vb))
        for k in ("width", "height"):
            root.attrib.pop(k, None)
        return ET.tostring(root, encoding="unicode")

    def recolor(self, color: str) -> str:
        """Return the document with every painted fill/stroke set to one flat colour.

        Mask contents are left alone (their luminance *is* the mask), and the root `color` is set so
        `currentColor` follows the new colour too.
        """
        root = self.clone_root()

        def paint(value: str) -> str:
            return value if value.strip().lower() in SKIP_COLOR_VALUES else color

        stack = [root]
        while stack:
            el = stack.pop()
            tag = local(el.tag)
            if tag == "mask":
                continue
            for prop in COLOR_PROPS:
                if prop in el.attrib:
                    el.set(prop, paint(el.get(prop)))
            if "style" in el.attrib:
                props = parse_style(el.get("style"))
                for prop in COLOR_PROPS:
                    if prop in props:
                        props[prop] = paint(props[prop])
                el.set("style", format_style(props))
            if tag == "style" and el.text:
                el.text = CSS_COLOR_RE.sub(lambda m: m.group(1) + paint(m.group(2)), el.text)
            stack.extend(el)
        if "fill" not in root.attrib:
            root.set("fill", color)
        root.set("color", color)
        return ET.tostring(root, encoding="unicode")

    def clean(self, precision: int | None = None) -> str:
        """Strip editor metadata/foreign namespaces and round lengths.

        Rounding keeps every length within 1/20000 of the canvas (`precision` decimals by default)
        and at least 4 significant digits; transform coefficients keep 6 significant digits; a positive
        size is never rounded to zero (zero disables rendering).
        """
        if precision is None:
            precision = max(0, math.ceil(4 - math.log10(max(self.canvas_size()))))
        root = self.clone_root()
        drop_tags = {"metadata", "namedview"}

        def drop_foreign_attrs(el: ET.Element) -> None:
            for k in list(el.attrib):
                ns = namespace(k)
                if (ns and ns not in (XLINK_NS, XML_NS)) or k == "data-name":
                    del el.attrib[k]

        def rnd(m: re.Match) -> str:
            # absolute error ≤ canvas/20000 AND ≥ 4 significant digits (tiny radii define curvature)
            v = float(m.group(0))
            digits = precision if v == 0 else max(precision, 3 - math.floor(math.log10(abs(v))))
            s = f"{v:.{digits}f}"
            s = s.rstrip("0").rstrip(".") if "." in s else s
            return "0" if s in ("-0", "") else s

        def sig(m: re.Match) -> str:
            return f"{float(m.group(0)):.6g}"

        drop_foreign_attrs(root)
        stack = [root]
        while stack:
            el = stack.pop()
            for child in list(el):
                tag = child.tag
                if not isinstance(tag, str) or namespace(tag) not in ("", SVG_NS) or local(tag) in drop_tags:
                    el.remove(child)
                    continue
                drop_foreign_attrs(child)
                stack.append(child)
            for k, v in list(el.attrib.items()):
                if k in LENGTH_ATTRS and not v.strip().endswith("%"):
                    rounded = NUMBER_RE.sub(rnd, v)
                    # a size of 0 disables rendering (SVG spec): never round a positive size to zero
                    if k in SIZE_ATTRS and _length(rounded) == 0 and (_length(v) or 0) != 0:
                        rounded = v
                    el.set(k, rounded)
                elif k in ("transform", "gradientTransform", "patternTransform"):
                    el.set(k, NUMBER_RE.sub(sig, v))
            if el.tail is not None and not el.tail.strip():
                el.tail = None
            if el.text is not None and not el.text.strip() and len(el):
                el.text = None
        return ET.tostring(root, encoding="unicode")


def _href(el: ET.Element) -> str | None:
    return el.get("href") or el.get(f"{{{XLINK_NS}}}href")


def _use_chains(uses: list[ET.Element], id_map: dict[str, ET.Element]) -> tuple[int, bool]:
    """Longest <use> reference chain and whether any chain is cyclic — iterative DFS (no recursion:
    the chains this guards against are exactly the ones that overflow stacks)."""
    children: dict[int, list[ET.Element]] = {}
    for u in uses:
        ref = _href(u)
        target = id_map.get(ref[1:]) if ref and ref.startswith("#") else None
        children[id(u)] = [d for d in target.iter() if local(d.tag) == "use"] if target is not None else []
    depth: dict[int, int] = {}
    visiting: set[int] = set()
    cyclic = False
    for start in uses:
        if id(start) in depth:
            continue
        stack = [(start, 0)]
        visiting.add(id(start))
        while stack:
            node, i = stack[-1]
            kids = children[id(node)]
            if i < len(kids):
                stack[-1] = (node, i + 1)
                kid = kids[i]
                if id(kid) in visiting:
                    cyclic = True
                elif id(kid) not in depth:
                    visiting.add(id(kid))
                    stack.append((kid, 0))
            else:
                stack.pop()
                visiting.discard(id(node))
                depth[id(node)] = 1 + max((depth.get(id(k), 0) for k in kids), default=0)
    return max(depth.values(), default=0), cyclic


def _decimals(number: str) -> int:
    mantissa = re.split(r"[eE]", number)[0]
    return len(mantissa.split(".", 1)[1]) if "." in mantissa else 0


def _length(value: str | None) -> float | None:
    if not value:
        return None
    m = NUMBER_RE.match(value.strip())
    if not m or value.strip().endswith("%"):
        return None
    return float(m.group(0))
