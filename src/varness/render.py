"""SVG rasterization through whichever backend is available.

Order of preference: resvg-py (pip, no system deps) → cairosvg → rsvg-convert → resvg CLI → inkscape.
Override with the VARNESS_RENDERER environment variable or ``--renderer``.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache

from PIL import Image

from .svgdoc import SvgDoc

BACKENDS = ("resvg-py", "cairosvg", "rsvg-convert", "resvg", "inkscape")


class RenderError(Exception):
    pass


def _available(name: str) -> bool:
    if name == "resvg-py":
        try:
            import resvg_py  # noqa: F401
        except ImportError:
            return False
        return True
    if name == "cairosvg":
        try:
            import cairosvg  # noqa: F401
        except (ImportError, OSError):
            return False
        return True
    return shutil.which(name) is not None


def available_backends() -> list[str]:
    return [b for b in BACKENDS if _available(b)]


_selected: str | None = None


def select(name: str | None = None) -> str:
    """Pick the backend (explicit name, $VARNESS_RENDERER, or first available)."""
    global _selected
    wanted = name or os.environ.get("VARNESS_RENDERER")
    if wanted:
        if wanted not in BACKENDS:
            raise RenderError(f"unknown renderer {wanted!r}; choose from {', '.join(BACKENDS)}")
        if not _available(wanted):
            raise RenderError(f"renderer {wanted!r} is not installed")
        _selected = wanted
        return wanted
    if _selected:
        return _selected
    found = available_backends()
    if not found:
        raise RenderError("no SVG renderer found: pip install resvg-py (or cairosvg, or install rsvg-convert)")
    _selected = found[0]
    return _selected


def fit(doc_or_aspect: SvgDoc | float, box: int) -> tuple[int, int]:
    """Pixel size that fits the drawing inside a box×box square, preserving aspect."""
    aspect = doc_or_aspect.aspect if isinstance(doc_or_aspect, SvgDoc) else doc_or_aspect
    if aspect >= 1:
        return box, max(1, round(box / aspect))
    return max(1, round(box * aspect)), box


def render_svg(svg: str, width: int, height: int) -> Image.Image:
    return _render_cached(svg, int(width), int(height), select()).copy()


def render(doc: SvgDoc, box: int, svg: str | None = None) -> Image.Image:
    """Render a document (or a rewritten variant of it) to fit a box×box square."""
    w, h = fit(doc, box)
    return render_svg(svg if svg is not None else doc.raw, w, h)


def render_short(doc: SvgDoc, short: int, svg: str | None = None) -> Image.Image:
    """Render so that the short side of the canvas is `short` px (how lockups are sized in use)."""
    if doc.aspect >= 1:
        w, h = max(1, round(short * doc.aspect)), short
    else:
        w, h = short, max(1, round(short / doc.aspect))
    return render_svg(svg if svg is not None else doc.raw, w, h)


def render_square(doc: SvgDoc, box: int, svg: str | None = None, pad: float = 0.0) -> Image.Image:
    """Render centred on a transparent box×box canvas with optional padding fraction."""
    inner = max(1, round(box * (1 - 2 * pad)))
    img = render(doc, inner, svg)
    canvas = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    canvas.alpha_composite(img, ((box - img.width) // 2, (box - img.height) // 2))
    return canvas


@lru_cache(maxsize=256)
def _render_cached(svg: str, width: int, height: int, backend: str) -> Image.Image:
    data = _render_bytes(svg, width, height, backend)
    try:
        img = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception as e:  # noqa: BLE001 - PIL raises many types
        raise RenderError(f"{backend} produced unreadable output: {e}") from e
    if img.size != (width, height):
        img = img.resize((width, height), Image.LANCZOS)
    return img


def _render_bytes(svg: str, width: int, height: int, backend: str) -> bytes:
    try:
        if backend == "resvg-py":
            import resvg_py

            return bytes(resvg_py.svg_to_bytes(svg_string=svg, width=width, height=height))
        if backend == "cairosvg":
            import cairosvg

            return cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=width, output_height=height)
    except Exception as e:  # noqa: BLE001 - backends raise arbitrary errors
        raise RenderError(f"{backend}: {e}") from e

    with tempfile.TemporaryDirectory(prefix="varness-") as tmp:
        src = os.path.join(tmp, "in.svg")
        out = os.path.join(tmp, "out.png")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(svg)
        if backend == "rsvg-convert":
            cmd = ["rsvg-convert", "-w", str(width), "-h", str(height), "-o", out, src]
        elif backend == "resvg":
            cmd = ["resvg", "-w", str(width), "-h", str(height), src, out]
        else:
            cmd = ["inkscape", src, "--export-type=png", f"--export-filename={out}",
                   f"--export-width={width}", f"--export-height={height}"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0 or not os.path.exists(out):
            raise RenderError(f"{backend} failed: {proc.stderr.strip()[:300]}")
        with open(out, "rb") as fh:
            return fh.read()
