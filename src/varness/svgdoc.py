"""Parsing and rewriting of SVG documents (structure only, no rendering)."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)

COLOR_PROPS = ("fill", "stroke", "stop-color", "color", "flood-color", "lighting-color")
NUMBER_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
PATH_CMD_RE = re.compile(r"[MmZzLlHhVvCcSsQqTtAa]")
URL_REF_RE = re.compile(r"url\(\s*['\"]?#([^)'\"\s]+)['\"]?\s*\)")
NAMED_COLORS = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000",
    "blue": "#0000ff", "yellow": "#ffff00", "orange": "#ffa500", "purple": "#800080",
    "gray": "#808080", "grey": "#808080", "navy": "#000080", "teal": "#008080",
    "maroon": "#800000", "olive": "#808000", "lime": "#00ff00", "aqua": "#00ffff",
    "cyan": "#00ffff", "fuchsia": "#ff00ff", "magenta": "#ff00ff", "silver": "#c0c0c0",
}
SKIP_COLOR_VALUES = {"none", "transparent", "inherit", "currentcolor", "context-fill", "context-stroke", ""}


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


@dataclass
class SvgDoc:
    raw: str
    root: ET.Element
    path: str | None = None
    _counts: Counter = field(default=None, repr=False)

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
        return cls(raw=raw, root=root, path=path)

    @property
    def name(self) -> str:
        return Path(self.path).name if self.path else "<string>"

    @property
    def sha(self) -> str:
        return hashlib.sha256(self.raw.encode("utf-8")).hexdigest()[:12]

    # -- geometry --------------------------------------------------------------------------
    @property
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
        if self._counts is None:
            self._counts = Counter(local(el.tag) for el in self.iter())
        return self._counts

    def declared_colors(self) -> set[str]:
        colors: set[str] = set()
        for el in self.iter():
            for prop in COLOR_PROPS:
                v = el.get(prop)
                if v and (c := normalize_color(v)):
                    colors.add(c)
            for prop, v in parse_style(el.get("style", "")).items():
                if prop in COLOR_PROPS and (c := normalize_color(v)):
                    colors.add(c)
            if local(el.tag) == "style" and el.text:
                for m in re.finditer(r"(?:fill|stroke|stop-color|color)\s*:\s*([^;}]+)", el.text):
                    if c := normalize_color(m.group(1)):
                        colors.add(c)
        return colors

    def path_stats(self) -> dict:
        commands = numbers = long_decimals = 0
        for el in self.iter():
            tag = local(el.tag)
            if tag == "path":
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
        return {"commands": commands, "numbers": numbers, "long_decimals": long_decimals}

    def ids(self) -> Counter:
        return Counter(el.get("id") for el in self.iter() if el.get("id"))

    def url_refs(self) -> set[str]:
        refs = set(URL_REF_RE.findall(self.raw))
        for el in self.iter():
            for key in ("href", f"{{{XLINK_NS}}}href"):
                v = el.get(key)
                if v and v.startswith("#"):
                    refs.add(v[1:])
        return refs

    def external_refs(self) -> list[str]:
        found = []
        for el in self.iter():
            for key in ("href", f"{{{XLINK_NS}}}href"):
                v = el.get(key)
                if v and not v.startswith("#"):
                    found.append(v[:80])
        found += re.findall(r"@import[^;]+", self.raw)
        found += [m for m in re.findall(r"url\(\s*['\"]?([^)'\"]+)", self.raw) if not m.startswith("#")]
        return found

    def has_script(self) -> bool:
        if self.counts().get("script"):
            return True
        return any(k.lower().startswith("on") for el in self.iter() for k in el.attrib)

    def foreign_namespaces(self) -> set[str]:
        nss = set()
        for el in self.iter():
            ns = namespace(el.tag)
            if ns and ns != SVG_NS:
                nss.add(ns)
            for k in el.attrib:
                ns = namespace(k)
                if ns and ns not in (SVG_NS, XLINK_NS, "http://www.w3.org/XML/1998/namespace"):
                    nss.add(ns)
        return nss

    def uses_opacity(self) -> bool:
        for el in self.iter():
            props = dict(el.attrib)
            props.update(parse_style(el.get("style", "")))
            for k in ("opacity", "fill-opacity", "stroke-opacity", "stop-opacity"):
                try:
                    if k in props and float(props[k]) < 0.999:
                        return True
                except ValueError:
                    continue
        return False

    def uses_strokes(self) -> bool:
        for el in self.iter():
            props = dict(el.attrib)
            props.update(parse_style(el.get("style", "")))
            stroke = props.get("stroke", "").strip().lower()
            if stroke and stroke != "none" and props.get("stroke-width", "1").strip() not in ("0", "0px"):
                return True
        return False

    # -- rewriting -------------------------------------------------------------------------
    def to_string(self, root: ET.Element | None = None) -> str:
        return ET.tostring(root if root is not None else self.root, encoding="unicode")

    def clone_root(self) -> ET.Element:
        return ET.fromstring(ET.tostring(self.root, encoding="unicode"))

    def recolor(self, color: str) -> str:
        """Return the document with every painted fill/stroke set to one flat colour."""
        root = self.clone_root()

        def paint(value: str) -> str:
            v = value.strip().lower()
            return value if v in SKIP_COLOR_VALUES else color

        for el in root.iter():
            for prop in COLOR_PROPS:
                if prop in el.attrib:
                    el.set(prop, paint(el.get(prop)))
            if "style" in el.attrib:
                props = parse_style(el.get("style"))
                for prop in COLOR_PROPS:
                    if prop in props:
                        props[prop] = paint(props[prop])
                el.set("style", format_style(props))
            if local(el.tag) == "style" and el.text:
                el.text = re.sub(
                    r"((?:fill|stroke|stop-color|color)\s*:\s*)([^;}]+)",
                    lambda m: m.group(1) + paint(m.group(2)),
                    el.text,
                )
        if "fill" not in root.attrib:
            root.set("fill", color)
        return ET.tostring(root, encoding="unicode")

    def clean(self, precision: int = 2) -> str:
        """Strip editor metadata/comments/foreign namespaces and round coordinates."""
        root = self.clone_root()
        drop_tags = {"metadata", "namedview"}

        def strip(parent: ET.Element) -> None:
            for child in list(parent):
                tag = child.tag
                if not isinstance(tag, str) or namespace(tag) not in ("", SVG_NS) or local(tag) in drop_tags:
                    parent.remove(child)
                    continue
                for k in list(child.attrib):
                    ns = namespace(k)
                    if ns and ns not in (XLINK_NS, "http://www.w3.org/XML/1998/namespace"):
                        del child.attrib[k]
                    elif k in ("data-name",):
                        del child.attrib[k]
                strip(child)

        for k in list(root.attrib):
            ns = namespace(k)
            if ns and ns not in (XLINK_NS, "http://www.w3.org/XML/1998/namespace"):
                del root.attrib[k]
        strip(root)

        def rnd(m: re.Match) -> str:
            s = f"{float(m.group(0)):.{precision}f}".rstrip("0").rstrip(".")
            return "0" if s in ("-0", "") else s

        numeric_attrs = {"d", "points", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
                         "width", "height", "transform", "stroke-width", "offset", "fx", "fy"}
        for el in root.iter():
            for k in list(el.attrib):
                if k in numeric_attrs and not el.get(k, "").endswith("%"):
                    el.set(k, NUMBER_RE.sub(rnd, el.get(k)))
            el.tail = None if el.tail is None or not el.tail.strip() else el.tail
            if el.text is not None and not el.text.strip() and len(el):
                el.text = None
        return ET.tostring(root, encoding="unicode")


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
