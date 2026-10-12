"""Contact sheets: one PNG that shows an agent (or a human) everything that matters at a glance."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import render
from .report import WEIGHTS, Report
from .svgdoc import SvgDoc, hex_to_rgb, normalize_color

PAPER = (246, 246, 244)
INK = (30, 30, 30)
MUTED = (120, 120, 120)
DARK = (18, 18, 18)
MID = (138, 138, 138)
STATUS_COLORS = {"PASS": (34, 139, 34), "WARN": (196, 120, 0), "FAIL": (200, 30, 30)}


def font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def silhouette(img: Image.Image, color) -> Image.Image:
    out = Image.new("RGBA", img.size, tuple(color) + (0,))
    out.putalpha(img.getchannel("A"))
    return out


def grayscale(img: Image.Image) -> Image.Image:
    g = img.convert("LA").convert("RGBA")
    g.putalpha(img.getchannel("A"))
    return g


def tile(img: Image.Image, size, bg) -> Image.Image:
    tw, th = (size, size) if isinstance(size, int) else size
    t = Image.new("RGB", (tw, th), bg)
    t.paste(img, ((tw - img.width) // 2, (th - img.height) // 2), img)
    return t


def zoom(img: Image.Image, factor: int) -> Image.Image:
    return img.resize((img.width * factor, img.height * factor), Image.NEAREST)


def _label(draw: ImageDraw.ImageDraw, xy, text, size=12, fill=MUTED):
    draw.text(xy, text, font=font(size), fill=fill)


class _Canvas:
    def __init__(self, width: int):
        self.width = width
        self.rows: list[tuple[Image.Image, int]] = []

    def add(self, img: Image.Image, gap: int = 14):
        self.rows.append((img, gap))

    def build(self) -> Image.Image:
        h = sum(r.height + g for r, g in self.rows) + 14
        out = Image.new("RGB", (max([self.width] + [r.width for r, _ in self.rows]), h), PAPER)
        y = 14
        for r, g in self.rows:
            out.paste(r, (0, y))
            y += r.height + g
        return out


def _row(title: str, cells: list[tuple[Image.Image, str]], width: int, pad: int = 16) -> Image.Image:
    h = max(c.height for c, _ in cells) + 22
    need = 110 + sum(c.width + 12 for c, _ in cells) + pad
    row = Image.new("RGB", (max(width, need), h), PAPER)
    d = ImageDraw.Draw(row)
    _label(d, (pad, 4), title.upper(), 12, INK)
    x = 110
    for img, caption in cells:
        row.paste(img, (x, 0))
        _label(d, (x, img.height + 4), caption, 11)
        x += img.width + 12
    return row


def _header(r: Report, width: int) -> Image.Image:
    img = Image.new("RGB", (width, 92), PAPER)
    d = ImageDraw.Draw(img)
    d.text((16, 6), r.file, font=font(20), fill=INK)
    d.text((16, 34), f"{r.score}/100", font=font(28), fill=INK)
    d.text((120, 40), r.status + ("  ship-ready" if r.ship_ready else ""), font=font(18), fill=STATUS_COLORS[r.status])
    x = 330
    for k in WEIGHTS:
        v = r.categories.get(k, 0)
        _label(d, (x, 10), k, 12)
        d.rectangle([x, 28, x + 100, 36], fill=(225, 225, 222))
        d.rectangle([x, 28, x + v, 36], fill=(60, 60, 60) if v >= 80 else (196, 120, 0) if v >= 50 else (200, 30, 30))
        _label(d, (x, 40), str(v), 12, INK)
        x += 120
    issues = [f"{f.level} {f.code}" for f in r.findings if f.level != "INFO"][:5]
    _label(d, (330, 64), "  ·  ".join(issues) if issues else "no FAIL/WARN findings", 12,
           STATUS_COLORS["FAIL" if any(i.startswith("FAIL") for i in issues) else "WARN" if issues else "PASS"])
    return img


def _diagnostics(r: Report, width: int) -> Image.Image:
    doc = r.doc
    size = 320
    base = render.render(doc, size)
    grid = Image.new("RGB", base.size, (255, 255, 255))
    gd = ImageDraw.Draw(grid)
    w, h = base.size
    for i in range(1, 8):
        c = (236, 236, 236) if i % 4 else (205, 205, 205)
        gd.line([(w * i / 8, 0), (w * i / 8, h)], fill=c)
        gd.line([(0, h * i / 8), (w, h * i / 8)], fill=c)
    plain = grid.copy()
    plain.paste(base, (0, 0), base)

    over = grid.copy()
    faded = base.copy()
    faded.putalpha(base.getchannel("A").point(lambda a: a * 0.35))
    over.paste(faded, (0, 0), faded)
    layers = r.analysis.layers if r.analysis else {}
    arr = np.asarray(over).copy()

    def paint(mask, color):
        if mask is None:
            return
        m = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize((w, h), Image.NEAREST)) > 127
        arr[m] = color

    paint(layers.get("filled32"), (40, 110, 255))
    paint(layers.get("thin32"), (235, 30, 30))
    paint(layers.get("mono_lost"), (255, 150, 0))
    over = Image.fromarray(arr)
    od = ImageDraw.Draw(over)
    m = r.metrics
    if m.get("bbox"):
        x0, y0, x1, y1 = m["bbox"]
        od.rectangle([x0 * w, y0 * h, x1 * w - 1, y1 * h - 1], outline=(0, 160, 120))
        cx, cy = m["centroid"]
        od.ellipse([cx * w - 5, cy * h - 5, cx * w + 5, cy * h + 5], outline=(200, 0, 200), width=2)
    od.line([(w / 2, 0), (w / 2, h)], fill=(0, 160, 120))
    od.line([(0, h / 2), (w, h / 2)], fill=(0, 160, 120))

    row = Image.new("RGB", (width, max(h, 214) + 24), PAPER)
    row.paste(plain, (110, 0))
    row.paste(over, (110 + w + 16, 0))
    d = ImageDraw.Draw(row)
    _label(d, (16, 4), "DIAGNOSTICS", 12, INK)
    _label(d, (110, h + 4), "on 8x8 grid", 11)
    _label(d, (110 + w + 16, h + 4), "overlay", 11)
    lx = 110 + 2 * w + 40
    legend = [((235, 30, 30), "red: ink thinner than 1px at 32px"),
              ((40, 110, 255), "blue: gaps that fill in at 32px"),
              ((255, 150, 0), "orange: edges that exist only in colour"),
              ((0, 160, 120), "green: artwork bbox + canvas centre lines"),
              ((200, 0, 200), "magenta ring: visual centre of mass")]
    for i, (c, t) in enumerate(legend):
        d.rectangle([lx, 8 + i * 22, lx + 12, 20 + i * 22], fill=c)
        _label(d, (lx + 20, 7 + i * 22), t, 12, INK)
    if m and not m.get("blank"):
        ss = m["small_sizes"]
        facts = [
            f"extent {m['extent'][0] * 100:.0f}% x {m['extent'][1] * 100:.0f}%   coverage {m['coverage'] * 100:.0f}%",
            f"bbox offset {m['bbox_offset'][0] * 100:+.1f}% / {m['bbox_offset'][1] * 100:+.1f}%",
            f"1px@32 = {ss['32']['px_in_units']:g} units, 1px@16 = {ss['16']['px_in_units']:g} units",
            "palette " + " ".join(c["hex"] for c in m["palette"][:4]),
        ]
        for i, t in enumerate(facts):
            _label(d, (lx, 130 + i * 18), t, 12, INK)
    return row


def single_sheet(r: Report, bg: str | None = None, width: int = 1280) -> Image.Image:
    doc: SvgDoc = r.doc
    brand = hex_to_rgb(normalize_color(bg)) if bg and normalize_color(bg) else None
    c = _Canvas(width)
    c.add(_header(r, width), 6)

    wide = r.metrics.get("size_basis", "box") != "box"
    tall = "tall" if doc.aspect > 1 else "wide"
    for title, back in (("light", (255, 255, 255)), ("dark", DARK)):
        big = render.render(doc, 384) if wide else render.render_square(doc, 256)
        cells = [(tile(big, (big.width + 24, big.height + 24) if wide else 256, back), "384 wide" if wide else "256")]
        if wide:
            for s in (48, 32, 24, 16):
                img = render.render_short(doc, s)
                cells.append((tile(img, (img.width + 12, img.height + 12), back), f"{s}px {tall}"))
            z = zoom(render.render_short(doc, 16), 6)
            cells.append((tile(z, (z.width, z.height), back), f"16px {tall} x6"))
        else:
            for s in (128, 64, 32, 16):
                cells.append((tile(render.render_square(doc, s), max(s, 40) if s < 128 else s, back), f"{s}px"))
            cells.append((tile(zoom(render.render_square(doc, 32), 4), 128, back), "32px x4"))
            cells.append((tile(zoom(render.render_square(doc, 16), 8), 128, back), "16px x8"))
        c.add(_row(title, cells, width))

    base = render.render_square(doc, 128)
    mono = [
        (tile(silhouette(base, (0, 0, 0)), 128, (255, 255, 255)), "1-colour black"),
        (tile(silhouette(base, (255, 255, 255)), 128, (0, 0, 0)), "1-colour reversed"),
        (tile(grayscale(base), 128, (255, 255, 255)), "greyscale"),
        (tile(base, 128, brand or MID), f"on {bg}" if brand else "on mid grey"),
        (tile(silhouette(base, (255, 255, 255)), 128, brand or MID), "white on " + (bg if brand else "grey")),
        (tile(zoom(silhouette(render.render_square(doc, 16), (0, 0, 0)), 8), 128, (255, 255, 255)), "mono 16px x8"),
    ]
    c.add(_row("mono / bg", mono, width))
    c.add(_row("context", _context_cells(doc, brand, wide), width))
    c.add(_diagnostics(r, width))
    return c.build()


def _context_cells(doc: SvgDoc, brand, wide: bool = False) -> list[tuple[Image.Image, str]]:
    cells = []
    for title, chrome, tabc, txt in (("browser tab (light)", (222, 225, 230), (255, 255, 255), INK),
                                    ("browser tab (dark)", (32, 33, 36), (53, 54, 58), (232, 234, 237))):
        tab = Image.new("RGB", (260, 128), chrome)
        d = ImageDraw.Draw(tab)
        d.rounded_rectangle([10, 46, 220, 82], radius=8, fill=tabc)
        icon = render.render_square(doc, 16)
        tab.paste(icon, (22, 56), icon)
        d.text((46, 57), "Brand - Home", font=font(13), fill=txt)
        cells.append((tab, title))
    for title, back in (("app icon", (255, 255, 255)), ("app icon dark", DARK), ("app icon brand", brand)):
        if back is None:
            continue
        app = Image.new("RGB", (128, 128), PAPER)
        mask = Image.new("L", (112, 112), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, 111, 111], radius=26, fill=255)
        sq = Image.new("RGB", (112, 112), back)
        logo = render.render_square(doc, 72)
        sq.paste(logo, (20, 20), logo)
        app.paste(sq, (8, 8), mask)
        ImageDraw.Draw(app).rounded_rectangle([8, 8, 119, 119], radius=26, outline=(210, 210, 210))
        cells.append((app, title))
    line = Image.new("RGB", (260 if wide else 230, 128), (255, 255, 255))
    d = ImageDraw.Draw(line)
    d.text((10, 50), "Powered by", font=font(16), fill=INK)
    icon = render.render_short(doc, 18) if wide else render.render(doc, 24)
    line.paste(icon, (102, 50 + (16 - icon.height) // 2 + 2), icon)
    d.text((102 + icon.width + 6, 50), "Brand", font=font(16), fill=INK)
    cells.append((line, "inline 18px tall" if wide else "inline 24px"))
    return cells


def compare_sheet(reports: list[Report], similar: list[tuple[str, str, float]] | None = None, col: int = 220) -> Image.Image:
    n = len(reports)
    width = 24 + n * (col + 12)
    rows_h = 70 + col + 10 + col + 10 + 140 + 10 + 110 + 10 + 120
    out = Image.new("RGB", (max(width, 640), rows_h + (24 * len(similar or []) + 30)), PAPER)
    d = ImageDraw.Draw(out)
    ranked = sorted(range(n), key=lambda i: -reports[i].score)
    rank_of = {i: k + 1 for k, i in enumerate(ranked)}
    for i, r in enumerate(reports):
        x = 16 + i * (col + 12)
        y = 10
        d.text((x, y), f"#{rank_of[i]}  {r.file}"[:30], font=font(14), fill=INK)
        d.text((x, y + 22), f"{r.score}/100", font=font(22), fill=INK)
        d.text((x + 90, y + 28), r.status, font=font(14), fill=STATUS_COLORS[r.status])
        y += 60
        if r.doc is None or r.analysis is None or r.metrics.get("blank"):
            d.text((x, y), "cannot render", font=font(14), fill=STATUS_COLORS["FAIL"])
            continue
        out.paste(tile(render.render_square(r.doc, col - 20), col, (255, 255, 255)), (x, y))
        y += col + 10
        out.paste(tile(render.render_square(r.doc, col - 20), col, DARK), (x, y))
        y += col + 10
        s32 = render.render_square(r.doc, 32)
        s16 = render.render_square(r.doc, 16)
        strip = Image.new("RGB", (col, 140), (255, 255, 255))
        strip.paste(s32, (10, 10), s32)
        strip.paste(s16, (52, 18), s16)
        z = zoom(s32, 4)
        strip.paste(z, (col - 128 - 6, 6), z)
        out.paste(strip, (x, y))
        _label(d, (x, y + 124), "32 · 16 · 32x4", 11)
        y += 150
        base = render.render_square(r.doc, 96)
        out.paste(tile(silhouette(base, (0, 0, 0)), 104, (255, 255, 255)), (x, y))
        out.paste(tile(silhouette(base, (255, 255, 255)), 104, (0, 0, 0)), (x + 112, y))
        y += 116
        issues = [f.code for f in r.findings if f.level != "INFO"][:6]
        for k, code in enumerate(issues or ["no FAIL/WARN"]):
            _label(d, (x, y + k * 16), code, 12, INK if issues else STATUS_COLORS["PASS"])
    y = rows_h
    if similar:
        _label(d, (16, y), "Too similar (silhouette IoU) - concepts should explore different ideas:", 13, STATUS_COLORS["WARN"])
        for k, (a, b, s) in enumerate(similar):
            _label(d, (16, y + 22 + k * 22), f"{a}  ~  {b}   IoU {s:.2f}", 13, INK)
    return out
