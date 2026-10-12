"""Turn lint findings + pixel metrics into actionable findings, category scores and a verdict."""

from __future__ import annotations

import math
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


class T:
    """Thresholds shared by findings and scores (one source of truth)."""
    EDGE = 0.005            # margin below which art counts as touching/clipped
    MIN_EXTENT = 0.6        # art should span at least this share of the canvas
    BBOX_OFF = 0.02         # bbox centre offset that triggers off-center
    CENTROID_OFF = 0.06     # centre-of-mass offset that triggers visual-weight
    PAD = 0.08              # padding used by suggested viewBoxes
    THIN64, THIN32, GAP32, BUSY16 = 0.015, 0.08, 0.08, 0.2
    MONO_LOSS, GRAY_LOSS, WHITE_INK = 0.2, 0.25, 0.03
    MAX_COLORS = 4
    INVISIBLE, READABLE, SAME_LIGHTNESS = 1.6, 3.0, 1.15
    INTRICATE = 8


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _num(v: float, size: float) -> str:
    """Round a user-space number to ~1/1000 of the canvas."""
    decimals = max(0, math.ceil(3 - math.log10(size)))
    s = f"{v:.{decimals}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def framed_viewbox(x: float, y: float, w: float, h: float, pad: float = T.PAD) -> tuple[float, float, float, float]:
    """viewBox centred on a bbox with `pad` padding per side (square for near-square art)."""
    lo, hi = M.SQUARE_ASPECT
    if lo <= w / max(h, 1e-12) <= hi:
        vw = vh = max(w, h) * (1 + 2 * pad)
    else:
        p = min(w, h) * 2 * pad
        vw, vh = w + p, h + p
    return x + w / 2 - vw / 2, y + h / 2 - vh / 2, vw, vh


def _vb_text(vb, size: float) -> str:
    return " ".join(_num(v, size) for v in vb)


def metric_findings(doc: SvgDoc, m: dict, lint_codes: set[str]) -> list[Finding]:
    out: list[Finding] = []

    def add(level, code, category, message, fix=""):
        out.append(Finding(level, code, category, message, fix))

    if m.get("blank"):
        add("FAIL", "renders-blank", "integrity", "Renders as (almost) nothing.",
            "Check fills (fill='none'?), transforms that push art off-canvas, and the viewBox.")
        return out

    cw, ch = doc.canvas_size()
    size = max(cw, ch)
    vb = doc.viewbox or (0.0, 0.0, cw, ch)
    bg_fill = m.get("background_fill")
    if bg_fill:
        add("INFO", "opaque-background", "composition",
            "Canvas is fully painted (background shape). Composition checks see the background, not the mark.",
            "Keep the master transparent; put backgrounds in variants (app icon, avatar).")
    else:
        mg = m["margins"]
        clipped = min(mg.values()) < T.EDGE
        if clipped:
            sides = [k for k, v in mg.items() if v < T.EDGE]
            true = M.true_bbox_units(doc)
            fix = (f'Reframe: viewBox="{_vb_text(framed_viewbox(*true), size)}" '
                   f"fits the whole art with {T.PAD:.0%} padding." if true else
                   "Leave ~6–10% padding: enlarge the viewBox or scale the art down.")
            add("WARN", "touches-edge", "composition",
                f"Artwork touches the canvas edge ({', '.join(sides)}): it may be clipped.", fix)
        ext = max(m["extent"])
        bx0, by0, bx1, by1 = m["bbox"]
        if not clipped and ext < T.MIN_EXTENT:
            box = (vb[0] + bx0 * cw, vb[1] + by0 * ch, (bx1 - bx0) * cw, (by1 - by0) * ch)
            add("WARN", "underfilled", "composition",
                f"Artwork spans only {_pct(ext)} of the canvas: it will look tiny at small sizes.",
                f'Tighten the canvas: viewBox="{_vb_text(framed_viewbox(*box), size)}" ({T.PAD:.0%} padding).')
        dx, dy = m["bbox_offset"]
        if not clipped and max(abs(dx), abs(dy)) > T.BBOX_OFF:
            add("WARN", "off-center", "composition",
                f"Artwork bounding box is off-centre by ({dx * 100:+.1f}%, {dy * 100:+.1f}%) of the canvas.",
                f'Wrap the art in <g transform="translate({_num(-dx * cw, size)} {_num(-dy * ch, size)})"> '
                "or adjust the viewBox.")
        lo, hi = M.SQUARE_ASPECT
        if lo <= m["aspect"] <= hi:
            cx, cy = m["centroid_offset"]
            if max(abs(cx), abs(cy)) > T.CENTROID_OFF:
                where = []
                if abs(cx) > T.CENTROID_OFF:
                    where.append("right" if cx > 0 else "left")
                if abs(cy) > T.CENTROID_OFF:
                    where.append("low" if cy > 0 else "high")
                add("INFO", "visual-weight", "composition",
                    f"Visual weight sits {' and '.join(where)} of centre ({cx * 100:+.1f}%, {cy * 100:+.1f}%).",
                    "Asymmetric marks often need an optical nudge toward the light side; judge on the sheet.")

    ss = m["small_sizes"]
    s16, s32, s64 = ss["16"], ss["32"], ss["64"]
    at = {"box": "", "height": " tall", "width": " wide"}[m.get("size_basis", "box")]
    if s64["thin_ink"] > T.THIN64:
        add("WARN", "thin-at-64", "scalability", f"{_pct(s64['thin_ink'])} of the ink is hairline (under 1px even at 64px{at}).",
            f"Nothing should be thinner than ~{_num(2 * s64['px_in_units'], size)} units.")
    if s32["thin_ink"] > T.THIN32:
        add("WARN", "thin-at-32", "scalability", f"{_pct(s32['thin_ink'])} of the ink is thinner than 1px at 32px{at} and will vanish or blur.",
            f"Thicken strokes/details to ≥{_num(s32['px_in_units'], size)} units (≥{_num(2 * s32['px_in_units'], size)} is comfortable).")
    if s32["gap_fill"] > T.GAP32:
        add("WARN", "gaps-close-at-32", "scalability",
            f"Gaps/counters narrower than 1px at 32px{at} fill in (area = {_pct(s32['gap_fill'])} of the ink).",
            f"Open gaps and counters to ≥{_num(s32['px_in_units'], size)} units, or drop the detail.")
    if s16["thin_ink"] > T.BUSY16 or s16["gap_fill"] > T.BUSY16:
        add("INFO", "busy-at-16", "scalability",
            f"At 16px{at} {_pct(s16['thin_ink'])} of ink is sub-pixel and gaps worth {_pct(s16['gap_fill'])} fill in.",
            "Consider a simplified small-size variant (just the core shape).")

    if m["mono_loss"] > T.MONO_LOSS:
        add("WARN", "needs-color", "color",
            f"{_pct(m['mono_loss'])} of visible edges exist only as colour changes: the 1-colour version loses that structure.",
            "Separate parts with real negative space (gaps) instead of colour alone.")
    if m["gray_loss"] > T.GRAY_LOSS:
        add("WARN", "similar-lightness", "color",
            f"{_pct(m['gray_loss'])} of colour edges disappear in greyscale: adjacent colours differ in hue only.",
            "Increase the lightness difference between neighbouring colours.")
    if m["color_count"] > T.MAX_COLORS and "many-colors" not in lint_codes:
        add("WARN", "many-colors", "color", f"{m['color_count']} distinct colours visible.", "Reduce to 1–3 colours.")
    if m["tonal"]:
        add("INFO", "tonal", "color", "Continuous tones (gradients/blends) dominate the render.",
            "Make sure the flat/mono version is the real design.")
    if not bg_fill and m["white_ink"] > T.WHITE_INK:
        add("WARN", "white-knockout", "color",
            f"{_pct(m['white_ink'])} of the ink is white: fake knockouts show as white blobs on dark/colour backgrounds.",
            "Cut real holes (fill-rule='evenodd' or subtract the shape) so the background shows through.")
    cw_ = m.get("contrast_on_white")
    if cw_ is not None:
        if cw_ < T.INVISIBLE:
            add("WARN", "low-contrast-white", "color", f"Even the strongest main colour has only {cw_}:1 contrast on white.",
                "Darken the main colour (≥3:1 on white) or define the logo as light-on-dark.")
        elif cw_ < T.READABLE:
            add("INFO", "low-contrast-white", "color", f"Strongest main colour has {cw_}:1 contrast on white (3:1 recommended).",
                "Darken slightly for use on light backgrounds.")
    if m.get("contrast_on_black", 99) < T.INVISIBLE:
        add("INFO", "reverse-needed", "color", "Mark disappears on dark backgrounds.",
            "Use the white variant on dark backgrounds (`varness export` creates it).")
    cb = m.get("contrast_on_bg")
    if cb:
        if cb["ratio"] < T.INVISIBLE:
            add("WARN", "low-contrast-bg", "color", f"Strongest main colour has {cb['ratio']}:1 contrast on {cb['bg']}.",
                "Pick colours with ≥3:1 contrast against the brand background.")
        elif cb["ratio"] < T.READABLE:
            add("INFO", "low-contrast-bg", "color", f"Strongest main colour has {cb['ratio']}:1 contrast on {cb['bg']} (3:1 recommended).")
    pair = m.get("min_color_pair_contrast")
    if pair and pair["ratio"] < T.SAME_LIGHTNESS:
        add("INFO", "near-duplicate-colors", "color", f"Colours {pair['colors'][0]} and {pair['colors'][1]} are nearly identical in lightness.",
            "Merge them or separate their lightness.")
    if m["contour_complexity"] > T.INTRICATE:
        add("INFO", "intricate-outline", "simplicity",
            f"Outline is {m['contour_complexity']}× as long as a circle of the same area.",
            "Fewer, bolder shapes read faster and survive small sizes.")
    return out


def category_scores(doc: SvgDoc, m: dict, findings: list[Finding]) -> dict:
    """Smooth 0–100 sub-scores so every real improvement moves the number."""
    pen = {"FAIL": 50, "WARN": 12, "INFO": 2}
    integrity = 100 - sum(pen[f.level] for f in findings if f.category == "integrity" and f.code != "renders-blank")
    if m.get("blank"):
        return dict.fromkeys(WEIGHTS, 0)

    ss = m["small_sizes"]
    scal = 100 - 300 * (ss["64"]["thin_ink"] + ss["64"]["gap_fill"]) \
        - 200 * (ss["32"]["thin_ink"] + ss["32"]["gap_fill"]) - 60 * (ss["16"]["thin_ink"] + ss["16"]["gap_fill"])

    comp = 100.0
    if m.get("background_fill"):
        comp -= 10
    else:
        if min(m["margins"].values()) < T.EDGE:
            comp -= 25
        comp -= max(0.0, T.MIN_EXTENT - max(m["extent"])) * 100
        comp -= sum(max(0.0, abs(o) - T.BBOX_OFF / 2) * 400 for o in m["bbox_offset"])
        lo, hi = M.SQUARE_ASPECT
        if lo <= m["aspect"] <= hi:
            comp -= sum(max(0.0, abs(o) - T.CENTROID_OFF * 2 / 3) * 300 for o in m["centroid_offset"])

    color = 100 - 60 * m["mono_loss"] - 40 * m["gray_loss"] - 8 * max(0, m["color_count"] - 3) - 5 * m["tonal"]
    if not m.get("background_fill") and m["white_ink"] > T.WHITE_INK:
        color -= 10
    if m.get("contrast_on_white", 99) < T.INVISIBLE:
        color -= 25
    color -= 2 * sum(1 for f in findings if f.category == "color" and f.level == "INFO")

    inv = doc.inv
    simp = 100 - max(0, inv.path_commands - 80) * 0.15 - max(0, inv.drawables - 20) * 1.0 \
        - max(0.0, m["contour_complexity"] - 6) * 3

    def clamp(v: float) -> int:
        return int(round(max(0.0, min(100.0, v))))

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
