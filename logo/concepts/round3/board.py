"""Presentation board for the two developed systems (slider, skeleton).

    python logo/concepts/round3/board.py   # writes board.png next to this file
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from varness import render
from varness.svgdoc import SvgDoc

HERE = Path(__file__).resolve().parent
NAVY, CREAM, DARK, PAPER = "#14213d", "#f3f1ea", (16, 18, 24), (246, 246, 244)
W = 1480


def doc(name: str, dark: bool = False) -> SvgDoc:
    text = (HERE / name).read_text()
    return SvgDoc.from_string(text.replace(NAVY, CREAM) if dark else text)


def tile(d: SvgDoc, box: int, bg, pad: int = 0, w: int | None = None, h: int | None = None) -> Image.Image:
    img = render.render(d, box)
    t = Image.new("RGBA", (w or img.width + 2 * pad, h or img.height + 2 * pad), bg + (255,) if len(bg) == 3 else bg)
    t.alpha_composite(img, ((t.width - img.width) // 2, (t.height - img.height) // 2))
    return t


def zoom(img: Image.Image, k: int) -> Image.Image:
    return img.resize((img.width * k, img.height * k), Image.NEAREST)


def small_strip(name: str, bg) -> Image.Image:
    d = doc(name, dark=bg == DARK)
    parts = [tile(d, s, bg, 8) for s in (64, 32, 16)] + [zoom(tile(d, 16, bg, 2), 5)]
    w = sum(p.width for p in parts) + 12 * (len(parts) - 1)
    strip = Image.new("RGBA", (w, max(p.height for p in parts)), (0, 0, 0, 0))
    x = 0
    for p in parts:
        strip.alpha_composite(p, (x, (strip.height - p.height) // 2))
        x += p.width + 12
    return strip


def section(title: str, caption: str, mark: str, small: str, icon: str | None, lockup: str) -> Image.Image:
    font_t, font_c = ImageFont.load_default(size=28), ImageFont.load_default(size=15)
    sec = Image.new("RGBA", (W, 900), PAPER + (255,))
    d = ImageDraw.Draw(sec)
    d.text((40, 24), title, font=font_t, fill="#111")
    d.text((40, 62), caption, font=font_c, fill="#555")
    y = 100
    a = tile(doc(mark), 300, (255, 255, 255), w=340, h=340)
    b = tile(doc(mark, dark=True), 300, DARK, w=340, h=340)
    sec.alpha_composite(a, (40, y))
    sec.alpha_composite(b, (400, y))
    x = 760
    if icon:
        sec.alpha_composite(tile(doc(icon), 300, (255, 255, 255), w=340, h=340), (x, y))
        x += 360
    s1, s2 = small_strip(small, (255, 255, 255)), small_strip(small, DARK)
    bw = max(W - x - 40, s1.width + 20)
    sec.alpha_composite(Image.new("RGBA", (bw, 160), (255, 255, 255, 255)), (x, y))
    sec.alpha_composite(s1, (x + 10, y + (160 - s1.height) // 2))
    sec.alpha_composite(Image.new("RGBA", (bw, 160), DARK + (255,)), (x, y + 180))
    sec.alpha_composite(s2, (x + 10, y + 180 + (160 - s2.height) // 2))
    d.text((x, y + 346), "small sizes: 64 · 32 · 16 · 16 zoomed x5", font=font_c, fill="#555")
    y += 380
    lw = (W - 100) // 2
    for i, dark in enumerate((False, True)):
        l = tile(doc(lockup, dark), lw - 60, DARK if dark else (255, 255, 255), w=lw, h=190)
        sec.alpha_composite(l, (40 + i * (lw + 20), y))
    y += 210
    for i, dark in enumerate((False, True)):
        l = tile(doc(lockup, dark), 300, DARK if dark else (255, 255, 255), w=lw, h=110)
        sec.alpha_composite(l, (40 + i * (lw + 20), y))
    return sec.crop((0, 0, W, y + 130))


if __name__ == "__main__":
    a = section("SLIDER", "handle tracks with square thumbs on an anchor key  ·  JetBrains Mono Bold",
                "s5-key.svg", "s5-key-small.svg", None, "l-slider-jetbrains.svg")
    b = section("SKELETON", "Kaushan Script V with its real bezier skeleton  ·  IBM Plex Mono SemiBold",
                "k-kaushan-light.svg", "k-kaushan-mark.svg", "k-kaushan-outline.svg", "l-skeleton-plex.svg")
    board = Image.new("RGB", (W, a.height + b.height), PAPER)
    board.paste(a, (0, 0))
    board.paste(b, (0, a.height))
    board.save(HERE / "board.png")
    print(board.size)
