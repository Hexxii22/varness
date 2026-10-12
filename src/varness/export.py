"""Production kit: cleaned SVG masters, mono variants, PNG sizes, favicon.ico, PWA/Apple icons."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from . import render
from .report import Report
from .svgdoc import SvgDoc, hex_to_rgb, normalize_color

PNG_SIZES = (16, 32, 48, 64, 128, 256, 512, 1024)
SAME_RENDER_MAX = 32  # max blurred difference (of 255) for two renders to count as the same drawing


def _on_bg(doc: SvgDoc, size: int, bg_rgb, pad: float) -> Image.Image:
    img = Image.new("RGBA", (size, size), tuple(bg_rgb) + (255,))
    logo = render.render_square(doc, size, pad=pad)
    img.alpha_composite(logo)
    return img


def verification_pixels(doc: SvgDoc, svg: str | None = None, box: int = 256, supersample: int = 4) -> np.ndarray:
    """Render at `supersample`× and box-downsample: averages away rasteriser quantisation."""
    img = render.render(doc, box * supersample, svg=svg)
    w, h = render.fit(doc, box)
    return np.asarray(img.resize((w, h), Image.BOX))


def _blur3(x: np.ndarray) -> np.ndarray:
    p = np.pad(x.astype(np.float32), [(1, 1), (1, 1)] + [(0, 0)] * (x.ndim - 2), mode="edge")
    h, w = x.shape[:2]
    return sum(p[dy:dy + h, dx:dx + w] for dy in range(3) for dx in range(3)) / 9.0


def render_drift(a: np.ndarray, b: np.ndarray) -> int:
    """Largest per-channel difference between two renders after a 3×3 box blur (255 if sizes differ).

    The blur absorbs rasteriser quantisation (resvg: 16 coverage levels, 4 sub-scanlines) so only
    real geometry changes count: an edge moved by ~0.3px or more exceeds SAME_RENDER_MAX.
    """
    if a.shape != b.shape:
        return 255
    return int(np.ceil(np.abs(_blur3(a) - _blur3(b)).max()))


def verify_clean(original: SvgDoc, cleaned: SvgDoc) -> int:
    """Drift between the original and cleaned renders; ≤ SAME_RENDER_MAX means the same drawing."""
    return render_drift(verification_pixels(original), verification_pixels(cleaned))


def verify_mono(doc: SvgDoc, mono_svg: str, color: str) -> tuple[float, float]:
    """(silhouette IoU with the original, share of solid pixels that are not `color`)."""
    a, b = verification_pixels(doc).astype(np.int16), verification_pixels(doc, mono_svg).astype(np.int16)
    sa, sb = a[..., 3] > 127, b[..., 3] > 127
    union = (sa | sb).sum()
    iou = float((sa & sb).sum() / union) if union else 1.0
    solid = b[..., 3] > 242
    if not solid.any():
        return iou, 0.0
    off = np.abs(b[solid][:, :3] - np.asarray(hex_to_rgb(color), dtype=np.int16)).max(axis=1) > 8
    return iou, float(off.mean())


def export(report: Report, out_dir: str | Path, name: str = "logo", bg: str | None = None,
           app_bg: str | None = None, precision: int | None = None) -> dict:
    doc: SvgDoc = report.doc
    out = Path(out_dir)
    (out / "svg").mkdir(parents=True, exist_ok=True)
    (out / "png").mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    notes: list[str] = []

    def write(rel: str, data: str | bytes) -> None:
        p = out / rel
        if isinstance(data, str):
            p.write_text(data, encoding="utf-8")
        else:
            p.write_bytes(data)
        files.append(rel)

    # the cleaned master must draw exactly what the original draws; otherwise ship the original
    clean = SvgDoc.from_string(doc.clean(precision))
    drift = verify_clean(doc, clean)
    if drift > SAME_RENDER_MAX:
        notes.append(f"cleaning changed the render (max diff {drift}/255); shipping the original markup instead")
        clean = doc
    write(f"svg/{name}.svg", clean.raw)
    write("favicon.svg", clean.raw)
    for label, color in (("black", "#000000"), ("white", "#ffffff")):
        mono = clean.recolor(color)
        write(f"svg/{name}-{label}.svg", mono)
        iou, stray = verify_mono(clean, mono, color)
        if iou < 0.97:
            notes.append(f"{label} variant: silhouette differs from the original (IoU {iou:.2f}) — "
                         "white fills or knockouts became solid; cut real holes.")
        if stray > 0.005:
            notes.append(f"{label} variant: {stray:.1%} of solid pixels are not {color} "
                         "(filters, images or paint the recolouring cannot reach).")

    for s in PNG_SIZES:
        img = render.render(clean, s)
        p = out / "png" / f"{name}-{s}.png"
        img.save(p)
        files.append(f"png/{name}-{s}.png")

    ico_imgs = [render.render_square(clean, s) for s in (16, 32, 48)]
    ico_imgs[-1].save(out / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)],
                      append_images=ico_imgs[:-1])
    files.append("favicon.ico")

    tile_hex = normalize_color(app_bg or bg or "#ffffff") or "#ffffff"
    tile_rgb = hex_to_rgb(tile_hex)
    _on_bg(clean, 180, tile_rgb, 0.12).convert("RGB").save(out / "apple-touch-icon.png")
    files.append("apple-touch-icon.png")
    for s in (192, 512):
        render.render_square(clean, s, pad=0.06).save(out / f"icon-{s}.png")
        files.append(f"icon-{s}.png")
    _on_bg(clean, 512, tile_rgb, 0.2).save(out / "icon-maskable-512.png")
    files.append("icon-maskable-512.png")

    manifest = {
        "name": name, "short_name": name,
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "theme_color": tile_hex, "background_color": tile_hex, "display": "standalone",
    }
    write("site.webmanifest", json.dumps(manifest, indent=2))
    write("head-snippet.html", "\n".join([
        '<link rel="icon" href="/favicon.ico" sizes="48x48">',
        '<link rel="icon" href="/favicon.svg" type="image/svg+xml">',
        '<link rel="apple-touch-icon" href="/apple-touch-icon.png">',
        '<link rel="manifest" href="/site.webmanifest">',
        f'<meta name="theme-color" content="{tile_hex}">',
    ]) + "\n")
    write("report.json", json.dumps(report.to_dict(), indent=2))
    from .sheet import single_sheet

    single_sheet(report, bg=bg).save(out / "sheet.png")
    files.append("sheet.png")
    return {"out": str(out), "files": files, "notes": notes}
