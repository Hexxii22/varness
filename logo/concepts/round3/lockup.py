"""Horizontal lockups: a mark (any 512×512 concept SVG) + the outlined word "varness".

    python logo/concepts/round3/lockup.py <font dir>

The wordmark is set as <text> and outlined with `varness outline` (so the shipped file has no live
text); the mark is embedded from its own SVG, scaled to the lockup height.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from varness.outline import outline
from varness.svgdoc import SVG_NS, SvgDoc

HERE = Path(__file__).resolve().parent
NAVY = "#14213d"


def mark_group(svg_file: Path, x: float, y: float, size: float) -> str:
    root = ET.fromstring(svg_file.read_text())
    inner = "".join(ET.tostring(ch, encoding="unicode") for ch in root if not ch.tag.endswith("title"))
    inner = inner.replace(f' xmlns="{SVG_NS}"', "").replace("ns0:", "")
    return f'<g transform="translate({x} {y}) scale({size / 512:.5f})">{inner}</g>'


def wordmark(font: str, size: float, x: float, baseline: float, spacing: float = 0.0) -> str:
    src = (f'<svg xmlns="{SVG_NS}" viewBox="0 0 2000 512"><text x="{x}" y="{baseline}" font-size="{size}" '
           f'letter-spacing="{spacing}" fill="{NAVY}">varness</text></svg>')
    svg, notes = outline(SvgDoc.from_string(src), font)
    if any("missing" in n for n in notes):
        raise SystemExit(f"{font}: {notes}")
    body = ET.fromstring(svg)
    return "".join(ET.tostring(ch, encoding="unicode") for ch in body).replace(f' xmlns="{SVG_NS}"', "")


def drawn_right(mark: Path) -> float:
    """Right edge of what the mark actually draws, as a fraction of its 512 canvas (from a render)."""
    from varness import metrics as M

    return M.analyze(SvgDoc.load(mark)).metrics["bbox"][2]


def lockup(name: str, mark: Path, font: str, *, mark_size=400, font_size=300, gap=72, spacing=-6) -> None:
    pad = (512 - mark_size) / 2
    text_x = pad + mark_size * drawn_right(mark) + gap      # gap from the drawn edge, not the canvas
    baseline = pad + mark_size * 0.86                      # x-height sits in the mark's lower two thirds
    body = mark_group(mark, pad, pad, mark_size) + wordmark(font, font_size, text_x, baseline, spacing)
    width = int(text_x + font_size * 0.62 * 7 + pad)       # 7 glyphs; trimmed below by the real extent
    svg = f'<svg xmlns="{SVG_NS}" viewBox="0 0 {width} 512"><title>varness</title>{body}</svg>'
    doc = SvgDoc.from_string(svg)
    # trim the canvas to the drawn extent + equal padding, measured on a real render
    from varness import metrics as M

    a = M.analyze(doc)
    x0, _, x1, _ = a.metrics["bbox"]
    cw = doc.canvas_size()[0]
    left, right = x0 * cw, x1 * cw
    new_w = right - left + 2 * pad
    svg = svg.replace(f'viewBox="0 0 {width} 512"', f'viewBox="{left - pad:.0f} 0 {new_w:.0f} 512"')
    (HERE / f"{name}.svg").write_text(svg + "\n")
    print(name, f"{new_w:.0f}×512")


if __name__ == "__main__":
    fonts = Path(sys.argv[1])
    jb = str(fonts / "JetBrainsMono-Bold.ttf")
    plex = str(fonts / "IBMPlexMono-SemiBold.ttf")
    grotesk = str(fonts / "SpaceGrotesk-Bold.ttf")
    lockup("l-slider-jetbrains", HERE / "s5-key.svg", jb)
    lockup("l-slider-grotesk", HERE / "s5-key.svg", grotesk, spacing=-10)
    lockup("l-skeleton-plex", HERE / "k-kaushan-light.svg", plex)
    lockup("l-skeleton-grotesk", HERE / "k-kaushan-light.svg", grotesk, spacing=-10)
