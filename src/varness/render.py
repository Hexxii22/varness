"""SVG rasterization through whichever backend is available.

Order of preference: resvg-py (pip, no system deps) → cairosvg → rsvg-convert → resvg CLI → inkscape.
Override with the VARNESS_RENDERER environment variable or ``--renderer``.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from .svgdoc import SvgDoc

BACKENDS = ("resvg-py", "cairosvg", "rsvg-convert", "resvg", "inkscape")
CACHE_PER_DOC = 64  # renders kept per document (oldest dropped first)
RENDER_STACK = 256 * 1024 * 1024  # virtual reservation; only touched pages are committed
_EXEC: ThreadPoolExecutor | None = None
_EXEC_LOCK = threading.Lock()


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


def _render_doc(doc: SvgDoc, svg: str | None, width: int, height: int) -> Image.Image:
    """Render through the document's own cache (no process-wide cache: it dies with the doc)."""
    backend = select()
    variant = None if svg is None else hashlib.sha1(svg.encode("utf-8")).hexdigest()
    key = (variant, width, height, backend)
    cache = doc.render_cache
    img = cache.get(key)
    if img is None:
        source = doc.render_source if svg is None else doc.pin_canvas(svg)
        img = _decode(_render_bytes(source, width, height, backend), width, height)
        if len(cache) >= CACHE_PER_DOC:
            cache.pop(next(iter(cache)))
        cache[key] = img
    return img.copy()


def render(doc: SvgDoc, box: int, svg: str | None = None) -> Image.Image:
    """Render a document (or a rewritten variant with the same canvas) to fit a box×box square."""
    w, h = fit(doc, box)
    return _render_doc(doc, svg, w, h)


def render_square(doc: SvgDoc, box: int, svg: str | None = None, pad: float = 0.0) -> Image.Image:
    """Render centred on a transparent box×box canvas with optional padding fraction."""
    inner = max(1, round(box * (1 - 2 * pad)))
    img = render(doc, inner, svg)
    canvas = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    canvas.alpha_composite(img, ((box - img.width) // 2, (box - img.height) // 2))
    return canvas


class Views:
    """Many sizes from one reference render: BOX-downsampling gives exact area coverage, costs no extra
    rasterisation, and shows the very raster the metrics were computed on. Sizes above the reference
    fall back to a true render."""

    def __init__(self, doc: SvgDoc, base_box: int):
        self.doc, self.base_box = doc, base_box

    def _from_base(self, w: int, h: int) -> Image.Image:
        bw, bh = fit(self.doc, self.base_box)
        if w > bw or h > bh:
            return _render_doc(self.doc, None, w, h)
        base = _render_doc(self.doc, None, bw, bh)
        return base if (w, h) == (bw, bh) else base.resize((w, h), Image.BOX)

    def fit(self, box: int) -> Image.Image:
        return self._from_base(*fit(self.doc, box))

    def short(self, short: int) -> Image.Image:
        a = self.doc.aspect
        w, h = (max(1, round(short * a)), short) if a >= 1 else (short, max(1, round(short / a)))
        return self._from_base(w, h)

    def square(self, box: int, pad: float = 0.0) -> Image.Image:
        img = self.fit(max(1, round(box * (1 - 2 * pad))))
        canvas = Image.new("RGBA", (box, box), (0, 0, 0, 0))
        canvas.alpha_composite(img, ((box - img.width) // 2, (box - img.height) // 2))
        return canvas


def _decode(data: bytes, width: int, height: int) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception as e:  # noqa: BLE001 - PIL raises many types
        raise RenderError(f"renderer produced unreadable output: {e}") from e
    if img.size != (width, height):
        img = img.resize((width, height), Image.LANCZOS)
    return img


def _executor() -> ThreadPoolExecutor:
    """One worker thread with a large stack: renderers recurse per nesting level / <use> hop, and a
    native stack overflow would kill the whole process instead of raising."""
    global _EXEC
    with _EXEC_LOCK:
        if _EXEC is None:
            _EXEC = _spawn_worker()
    return _EXEC


def _spawn_worker() -> ThreadPoolExecutor:
    ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="varness-render")
    try:
        old = threading.stack_size(RENDER_STACK)
    except (ValueError, RuntimeError):  # platform refuses: keep the default stack
        old = None
    try:
        ex.submit(lambda: None).result()  # spawns the single worker now, with the big stack
    finally:
        if old is not None:
            threading.stack_size(old)
    return ex


def _render_bytes(svg: str, width: int, height: int, backend: str) -> bytes:
    if backend in ("resvg-py", "cairosvg"):  # in-process: run on the big-stack worker
        return _executor().submit(_render_in_process, svg, width, height, backend).result()
    return _render_cli(svg, width, height, backend)


def _render_in_process(svg: str, width: int, height: int, backend: str) -> bytes:
    try:
        if backend == "resvg-py":
            import resvg_py

            return bytes(resvg_py.svg_to_bytes(svg_string=svg, width=width, height=height))
        if backend == "cairosvg":
            import cairosvg

            return cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=width, output_height=height)
    except RecursionError as e:
        raise RenderError(f"{backend}: nesting too deep to render") from e
    except Exception as e:  # noqa: BLE001 - backends raise arbitrary errors
        raise RenderError(f"{backend}: {e}") from e
    raise RenderError(f"{backend} is not an in-process renderer")


def _render_cli(svg: str, width: int, height: int, backend: str) -> bytes:
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
