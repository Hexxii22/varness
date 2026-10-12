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


def _on_bg(doc: SvgDoc, size: int, bg_rgb, pad: float) -> Image.Image:
    img = Image.new("RGBA", (size, size), tuple(bg_rgb) + (255,))
    logo = render.render_square(doc, size, pad=pad)
    img.alpha_composite(logo)
    return img


def _mono_check(doc: SvgDoc, mono_svg: str) -> float:
    """IoU between the mono export's alpha and the original silhouette (should be ~1)."""
    a = np.asarray(render.render(doc, 256).getchannel("A")) > 127
    b = np.asarray(render.render(doc, 256, svg=mono_svg).getchannel("A")) > 127
    union = (a | b).sum()
    return float((a & b).sum() / union) if union else 1.0


def export(report: Report, out_dir: str | Path, name: str = "logo", bg: str | None = None,
           app_bg: str | None = None, precision: int = 2) -> dict:
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

    clean = SvgDoc.from_string(doc.clean(precision))
    write(f"svg/{name}.svg", clean.raw)
    write("favicon.svg", clean.raw)
    for label, color in (("black", "#000000"), ("white", "#ffffff")):
        mono = clean.recolor(color)
        write(f"svg/{name}-{label}.svg", mono)
        if label == "black":
            iou = _mono_check(clean, mono)
            if iou < 0.97:
                notes.append(f"mono variant differs from the colour silhouette (IoU {iou:.2f}): "
                             "white fills or knockouts became solid — cut real holes.")

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
