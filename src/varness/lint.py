"""Structural rules for a logo master (what the XML says, before any pixel is drawn)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .svgdoc import SvgDoc

LEVELS = ("FAIL", "WARN", "INFO")
MAX_USE_CHAIN = 32
EDITOR_MARKERS = ("sodipodi:", "inkscape:", "sketch:", "data-name=", "<!-- Generator", "Adobe Illustrator", "figma")


@dataclass
class Finding:
    level: str      # FAIL | WARN | INFO
    code: str
    category: str   # integrity | scalability | composition | color | simplicity
    message: str
    fix: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def lint(doc: SvgDoc) -> list[Finding]:
    out: list[Finding] = []

    def add(level, code, message, fix="", category="integrity"):
        out.append(Finding(level, code, category, message, fix))

    inv = doc.inv
    counts = inv.counts

    if doc.viewbox is None:
        if doc.root.get("width") and doc.root.get("height"):
            add("WARN", "no-viewbox", "No valid viewBox: the logo will not scale predictably.",
                'Add viewBox="0 0 W H" matching the drawing and drop fixed width/height.')
        else:
            add("FAIL", "no-viewbox", "No viewBox and no width/height: renderers fall back to 300×150.",
                'Add viewBox="0 0 512 512" (or the true drawing size).')
    else:
        x, y, w, h = doc.viewbox
        if any(abs(v - round(v)) > 1e-6 for v in (x, y, w, h)):
            add("INFO", "fractional-viewbox", f"viewBox {doc.root.get('viewBox')!r} is fractional.",
                "Integer canvases (e.g. 0 0 512 512) make grid alignment easier.")

    if counts.get("text") or counts.get("tspan"):
        add("FAIL", "live-text", "Contains <text>: fonts differ per machine, so the logo is not a fixed shape.",
            "Outline it: `varness outline logo.svg --font Brand.ttf -o logo.svg`, or draw letterforms as paths.")
    if counts.get("image"):
        add("FAIL", "raster-image", "Contains <image> (embedded or linked raster). A logo master must be pure vector.",
            "Redraw the element as paths.")
    if counts.get("foreignObject"):
        add("FAIL", "foreign-object", "Contains <foreignObject> (HTML inside SVG): not portable.", "Remove it.")
    if inv.has_script:
        add("FAIL", "script", "Contains <script> or on* event handlers.", "Remove all scripting.")
    ext = inv.external_refs
    if ext:
        add("FAIL", "external-ref", f"References external resources: {', '.join(ext[:3])}.",
            "Inline everything; a logo file must be self-contained.")

    if inv.use_cycle:
        add("FAIL", "use-cycle", "A <use> references itself (directly or through other <use>s).",
            "Break the cycle; a logo needs no recursive references.")
    elif inv.use_depth > MAX_USE_CHAIN:
        add("FAIL", "use-chain", f"<use> references are chained {inv.use_depth} deep (renderers recurse per hop).",
            f"Flatten to ≤{MAX_USE_CHAIN} levels: reference the base shape directly.")

    ids = inv.ids
    dupes = [i for i, n in ids.items() if n > 1]
    if dupes:
        add("WARN", "duplicate-id", f"Duplicate id(s): {', '.join(dupes[:5])}.", "Make ids unique.")
    missing = sorted(r for r in inv.local_refs if r not in ids)
    if missing:
        add("FAIL", "dangling-ref", f"References to missing ids: {', '.join(missing[:5])}.",
            "Define the referenced gradient/clipPath/symbol or remove the reference.")

    if counts.get("filter"):
        add("WARN", "filter", "Uses <filter> (blur/shadow/glow): renders inconsistently, cannot be printed or embroidered.",
            "Use flat shapes; put effects only in marketing renders.")
    if counts.get("mask"):
        add("INFO", "mask", "Uses <mask>: fine for exploration, but cutters/embroidery need real geometry.",
            "Bake masks into path geometry (boolean subtraction / fill-rule=evenodd).")
    if counts.get("linearGradient") or counts.get("radialGradient"):
        add("INFO", "gradient", "Uses gradients: make sure a flat version reads just as well.",
            "Check the mono row of the sheet; ship a flat variant.", "color")
    if inv.uses_opacity:
        add("INFO", "opacity", "Uses partial opacity: 1-colour print and embroidery cannot reproduce tints.",
            "Replace tints with solid colours or real overlaps.", "color")
    if counts.get("animate") or counts.get("animateTransform") or counts.get("animateMotion"):
        add("INFO", "animation", "Contains SMIL animation; the master logo should be static.",
            "Keep the static mark as the master and animate a copy.")

    colors = inv.colors
    if len(colors) > 4:
        add("WARN", "many-colors", f"{len(colors)} declared colours: {', '.join(sorted(colors)[:8])}.",
            "Strong marks use 1–3 colours. Merge near-duplicates.", "color")

    if counts.get("style"):
        add("INFO", "style-block", "Uses a <style> block: some tools (email, Office, embroidery) ignore CSS.",
            "Prefer presentation attributes (fill=, stroke=).")
    if not counts.get("title"):
        add("INFO", "no-title", "No <title>: screen readers announce nothing.",
            'Add <title>Brand name logo</title> as the first child of <svg>.')
    if any(m in doc.raw for m in EDITOR_MARKERS) or inv.foreign_namespaces:
        add("INFO", "editor-metadata", "Editor metadata or foreign namespaces present.",
            "Run `varness export` (it ships a cleaned copy).")

    if inv.long_decimals > 10:
        add("INFO", "precision", f"{inv.long_decimals} coordinates have 4+ decimals.",
            "Round to 0–2 decimals; snapping to a grid also reveals misalignments.", "simplicity")
    if inv.path_commands > 250:
        add("WARN", "complex-paths", f"{inv.path_commands} path commands: too intricate for a mark.",
            "Simplify: fewer, bolder shapes; merge overlapping pieces.", "simplicity")
    elif inv.path_commands > 120:
        add("INFO", "complex-paths", f"{inv.path_commands} path commands: on the heavy side for a mark.",
            "Check that every node earns its place.", "simplicity")
    if inv.drawables > 40:
        add("WARN", "many-elements", f"{inv.drawables} drawable elements.", "Merge shapes that share a colour.", "simplicity")

    if inv.uses_strokes:
        add("INFO", "strokes", "Uses strokes: they scale differently in some tools and cannot be boolean-combined.",
            "Fine while designing; expand strokes to fills for the production master.")
    return out
