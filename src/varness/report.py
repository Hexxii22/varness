"""Turn lint findings + pixel metrics into actionable findings, category scores and a verdict."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import metrics as M
from . import render
from .lint import Finding, lint
from .svgdoc import SvgDoc, SvgError

WEIGHTS = {"integrity": 0.25, "scalability": 0.25, "composition": 0.20, "color": 0.15, "simplicity": 0.15}
SHIP_SCORE = 85


@dataclass(eq=False)
class Report:
    file: str
    sha: str
    renderer: str
    score: int
    status: str                       # PASS | WARN | FAIL
    ship_ready: bool
    categories: dict
    findings: list[Finding]
    metrics: dict
    analysis: M.Analysis | None = field(default=None, repr=False)
    doc: SvgDoc | None = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "file": self.file, "sha": self.sha, "renderer": self.renderer, "score": self.score,
            "status": self.status, "ship_ready": self.ship_ready, "categories": self.categories,
            "findings": [f.to_dict() for f in self.findings], "metrics": self.metrics,
        }


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def metric_findings(doc: SvgDoc, m: dict, lint_codes: set[str]) -> list[Finding]:
    out: list[Finding] = []

    def add(level, code, category, message, fix=""):
        out.append(Finding(level, code, category, message, fix))

    if m.get("blank"):
        add("FAIL", "renders-blank", "integrity", "Renders as (almost) nothing.",
            "Check fills (fill='none'?), transforms that push art off-canvas, and the viewBox.")
        return out

    cw, ch = doc.canvas_size()
    vb = doc.viewbox or (0.0, 0.0, cw, ch)
    bg_fill = m.get("background_fill")
    if bg_fill:
        add("INFO", "opaque-background", "composition",
            "Canvas is fully painted (background shape). Composition checks see the background, not the mark.",
            "Keep the master transparent; put backgrounds in variants (app icon, avatar).")
    else:
        mg = m["margins"]
        if min(mg.values()) < 0.005:
            sides = [k for k, v in mg.items() if v < 0.005]
            add("WARN", "touches-edge", "composition", f"Artwork touches the canvas edge ({', '.join(sides)}): it may be clipped.",
                "Leave ~6–10% padding: enlarge the viewBox or scale the art down.")
        ext = max(m["extent"])
        bx0, by0, bx1, by1 = m["bbox"]
        if ext < 0.6:
            ux0, uy0 = vb[0] + bx0 * cw, vb[1] + by0 * ch
            uw, uh = (bx1 - bx0) * cw, (by1 - by0) * ch
            if 0.75 <= uw / max(uh, 1e-9) <= 1.33:
                vw = vh = max(uw, uh) * 1.16
            else:
                pad = min(uw, uh) * 0.16
                vw, vh = uw + pad, uh + pad
            sx, sy = ux0 + uw / 2 - vw / 2, uy0 + uh / 2 - vh / 2
            add("WARN", "underfilled", "composition",
                f"Artwork spans only {_pct(ext)} of the canvas: it will look tiny at small sizes.",
                f'Tighten the canvas, e.g. viewBox="{sx:.0f} {sy:.0f} {vw:.0f} {vh:.0f}" (8% padding).')
        dx, dy = m["bbox_offset"]
        if max(abs(dx), abs(dy)) > 0.02:
            add("WARN", "off-center", "composition",
                f"Artwork bounding box is off-centre by ({dx * 100:+.1f}%, {dy * 100:+.1f}%) of the canvas.",
                f'Wrap the art in <g transform="translate({-dx * cw:.1f} {-dy * ch:.1f})"> or adjust the viewBox.')
        if 0.75 <= m["aspect"] <= 1.33:
            cx, cy = m["centroid_offset"]
            if max(abs(cx), abs(cy)) > 0.06:
                where = []
                if abs(cx) > 0.06:
                    where.append("right" if cx > 0 else "left")
                if abs(cy) > 0.06:
                    where.append("low" if cy > 0 else "high")
                add("INFO", "visual-weight", "composition",
                    f"Visual weight sits {' and '.join(where)} of centre ({cx * 100:+.1f}%, {cy * 100:+.1f}%).",
                    "Asymmetric marks often need an optical nudge toward the light side; judge on the sheet.")

    ss = m["small_sizes"]
    s16, s32, s64 = ss["16"], ss["32"], ss["64"]
    at = {"box": "", "height": " tall", "width": " wide"}[m.get("size_basis", "box")]
    if s64["thin_ink"] > 0.015:
        add("WARN", "thin-at-64", "scalability", f"{_pct(s64['thin_ink'])} of the ink is hairline (under 1px even at 64px{at}).",
            f"Nothing should be thinner than ~{2 * s64['px_in_units']:.0f} units.")
    if s32["thin_ink"] > 0.08:
        add("WARN", "thin-at-32", "scalability", f"{_pct(s32['thin_ink'])} of the ink is thinner than 1px at 32px{at} and will vanish or blur.",
            f"Thicken strokes/details to ≥{s32['px_in_units']:.0f} units (≥{2 * s32['px_in_units']:.0f} is comfortable).")
    if s32["gap_fill"] > 0.08:
        add("WARN", "gaps-close-at-32", "scalability",
            f"Gaps/counters narrower than 1px at 32px{at} fill in (area = {_pct(s32['gap_fill'])} of the ink).",
            f"Open gaps and counters to ≥{s32['px_in_units']:.0f} units, or drop the detail.")
    if s16["thin_ink"] > 0.2 or s16["gap_fill"] > 0.2:
        add("INFO", "busy-at-16", "scalability",
            f"At 16px{at} {_pct(s16['thin_ink'])} of ink is sub-pixel and gaps worth {_pct(s16['gap_fill'])} fill in.",
            "Consider a simplified small-size variant (just the core shape).")

    if m["mono_loss"] > 0.2:
        add("WARN", "needs-color", "color",
            f"{_pct(m['mono_loss'])} of visible edges exist only as colour changes: the 1-colour version loses that structure.",
            "Separate parts with real negative space (gaps) instead of colour alone.")
    if m["gray_loss"] > 0.25:
        add("WARN", "similar-lightness", "color",
            f"{_pct(m['gray_loss'])} of colour edges disappear in greyscale: adjacent colours differ in hue only.",
            "Increase the lightness difference between neighbouring colours.")
    if m["color_count"] > 4 and "many-colors" not in lint_codes:
        add("WARN", "many-colors", "color", f"{m['color_count']} distinct colours visible.", "Reduce to 1–3 colours.")
    if m["tonal"]:
        add("INFO", "tonal", "color", "Continuous tones (gradients/blends) dominate the render.",
            "Make sure the flat/mono version is the real design.")
    if not bg_fill and m["white_ink"] > 0.03:
        add("WARN", "white-knockout", "color",
            f"{_pct(m['white_ink'])} of the ink is white: fake knockouts show as white blobs on dark/colour backgrounds.",
            "Cut real holes (fill-rule='evenodd' or subtract the shape) so the background shows through.")
    cw_ = m.get("contrast_on_white")
    if cw_ is not None:
        if cw_ < 1.6:
            add("WARN", "low-contrast-white", "color", f"Main colour has only {cw_}:1 contrast on white.",
                "Darken the main colour (≥3:1 on white) or define the logo as light-on-dark.")
        elif cw_ < 3:
            add("INFO", "low-contrast-white", "color", f"Main colour has {cw_}:1 contrast on white (3:1 recommended).",
                "Darken slightly for use on light backgrounds.")
    if m.get("contrast_on_black", 99) < 1.6:
        add("INFO", "reverse-needed", "color", "Mark disappears on dark backgrounds.",
            "Use the white variant on dark backgrounds (`varness export` creates it).")
    cb = m.get("contrast_on_bg")
    if cb:
        if cb["ratio"] < 1.6:
            add("WARN", "low-contrast-bg", "color", f"Main colour has {cb['ratio']}:1 contrast on {cb['bg']}.",
                "Pick colours with ≥3:1 contrast against the brand background.")
        elif cb["ratio"] < 3:
            add("INFO", "low-contrast-bg", "color", f"Main colour has {cb['ratio']}:1 contrast on {cb['bg']} (3:1 recommended).")
    pair = m.get("min_color_pair_contrast")
    if pair and pair["ratio"] < 1.15:
        add("INFO", "near-duplicate-colors", "color", f"Colours {pair['colors'][0]} and {pair['colors'][1]} are nearly identical in lightness.",
            "Merge them or separate their lightness.")
    if m["contour_complexity"] > 8:
        add("INFO", "intricate-outline", "simplicity",
            f"Outline is {m['contour_complexity']}× as long as a circle of the same area.",
            "Fewer, bolder shapes read faster and survive small sizes.")
    return out


def category_scores(doc: SvgDoc, m: dict, findings: list[Finding]) -> dict:
    pen = {"FAIL": 50, "WARN": 12, "INFO": 2}
    integrity = 100 - sum(pen[f.level] for f in findings if f.category == "integrity" and f.code != "renders-blank")
    if m.get("blank"):
        return {"integrity": 0, "scalability": 0, "composition": 0, "color": 0, "simplicity": 0}

    ss = m["small_sizes"]
    scal = 100 - 300 * (ss["64"]["thin_ink"] + ss["64"]["gap_fill"]) \
        - 200 * (ss["32"]["thin_ink"] + ss["32"]["gap_fill"]) - 60 * (ss["16"]["thin_ink"] + ss["16"]["gap_fill"])

    comp = 100.0
    if m.get("background_fill"):
        comp -= 10
    else:
        if min(m["margins"].values()) < 0.005:
            comp -= 25
        comp -= max(0.0, 0.6 - max(m["extent"])) * 100
        comp -= sum(max(0.0, abs(o) - 0.01) * 400 for o in m["bbox_offset"])
        if 0.75 <= m["aspect"] <= 1.33:
            comp -= sum(max(0.0, abs(o) - 0.04) * 300 for o in m["centroid_offset"])

    color = 100 - 60 * m["mono_loss"] - 40 * m["gray_loss"] - 8 * max(0, m["color_count"] - 3) - 5 * m["tonal"]
    if not m.get("background_fill") and m["white_ink"] > 0.03:
        color -= 10
    if m.get("contrast_on_white", 99) < 1.6:
        color -= 25
    color -= 2 * sum(1 for f in findings if f.category == "color" and f.level == "INFO")

    stats = doc.path_stats()
    drawables = sum(n for t, n in doc.counts().items() if t in ("path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "use"))
    simp = 100 - max(0, stats["commands"] - 80) * 0.15 - max(0, drawables - 20) * 1.0 - max(0.0, m["contour_complexity"] - 6) * 3

    clamp = lambda v: int(round(max(0.0, min(100.0, v))))  # noqa: E731
    return {"integrity": clamp(integrity), "scalability": clamp(scal), "composition": clamp(comp),
            "color": clamp(color), "simplicity": clamp(simp)}


def check(doc: SvgDoc | str, bg: str | None = None) -> Report:
    if not isinstance(doc, SvgDoc):
        try:
            doc = SvgDoc.load(doc)
        except SvgError as e:
            f = Finding("FAIL", "parse-error", "integrity", str(e), "Fix the XML so it parses as an <svg> document.")
            return Report(str(doc), "", "", 0, "FAIL", False, {k: 0 for k in WEIGHTS}, [f], {})
    renderer = render.select()
    findings = lint(doc)
    try:
        analysis = M.analyze(doc, bg=bg)
    except render.RenderError as e:
        findings.append(Finding("FAIL", "render-error", "integrity", str(e), "Simplify the SVG until it renders."))
        return Report(doc.name, doc.sha, renderer, 0, "FAIL", False, {k: 0 for k in WEIGHTS}, findings, {}, None, doc)
    findings += metric_findings(doc, analysis.metrics, {f.code for f in findings})
    order = {"FAIL": 0, "WARN": 1, "INFO": 2}
    findings.sort(key=lambda f: (order[f.level], list(WEIGHTS).index(f.category)))
    cats = category_scores(doc, analysis.metrics, findings)
    score = round(sum(cats[k] * w for k, w in WEIGHTS.items()))
    levels = {f.level for f in findings}
    status = "FAIL" if "FAIL" in levels else "WARN" if "WARN" in levels else "PASS"
    if status == "FAIL":
        score = min(score, 49)
    ship = status == "PASS" and score >= SHIP_SCORE
    return Report(doc.name, doc.sha, renderer, score, status, ship, cats, findings, analysis.metrics, analysis, doc)


# -- text output -------------------------------------------------------------------------------

def bar(v: int, width: int = 10) -> str:
    full = round(v / 100 * width)
    return "█" * full + "░" * (width - full)


def format_text(r: Report, verbose: bool = False) -> str:
    lines = [f"{r.file} — {r.score}/100  {r.status}" + ("  ✓ ship-ready" if r.ship_ready else "")
             + (f"   (renderer: {r.renderer}, sha {r.sha})" if r.renderer else "")]
    for k in WEIGHTS:
        lines.append(f"  {k:<12} {bar(r.categories.get(k, 0))} {r.categories.get(k, 0):>3}")
    shown = [f for f in r.findings if verbose or f.level != "INFO"]
    hidden = len(r.findings) - len(shown)
    if shown:
        lines.append("findings:")
        for f in shown:
            lines.append(f"  {f.level:<4} {f.code:<20} {f.message}")
            if f.fix:
                lines.append(f"       {'':<20} → {f.fix}")
    if hidden:
        lines.append(f"  (+{hidden} INFO, use -v to show)")
    m = r.metrics
    if m and not m.get("blank"):
        ss = m["small_sizes"]
        pal = " ".join(f"{c['hex']}({c['share'] * 100:.0f}%)" for c in m["palette"][:5])
        lines.append(
            "metrics: coverage {cov} · extent {ex} · bbox offset ({bx:+.1f}%, {by:+.1f}%) · symmetry lr {lr} tb {tb}".format(
                cov=_pct(m["coverage"]), ex="×".join(_pct(e) for e in m["extent"]),
                bx=m["bbox_offset"][0] * 100, by=m["bbox_offset"][1] * 100,
                lr=m["symmetry"]["mirror_lr"], tb=m["symmetry"]["mirror_tb"]))
        lines.append(
            "         thin/gap @64 {a}/{b} · @32 {c}/{d} · @16 {e}/{f} · mono loss {ml} · gray loss {gl}".format(
                a=_pct(ss["64"]["thin_ink"]), b=_pct(ss["64"]["gap_fill"]), c=_pct(ss["32"]["thin_ink"]),
                d=_pct(ss["32"]["gap_fill"]), e=_pct(ss["16"]["thin_ink"]), f=_pct(ss["16"]["gap_fill"]),
                ml=_pct(m["mono_loss"]), gl=_pct(m["gray_loss"])))
        lines.append(f"         palette {pal}")
    return "\n".join(lines)
