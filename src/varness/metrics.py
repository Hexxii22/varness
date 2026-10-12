"""Pixel-level measurements of a rendered logo.

Everything here works on actual renders, so it catches what XML inspection cannot: features that
vanish at favicon size, counters that fill in, marks that only read in colour, white "knockouts",
off-centre visual weight.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image

from . import render
from .svgdoc import SvgDoc

REF = 512          # reference render (longest side, px)
MORPH = 256        # working resolution for morphology
SMALL_SIZES = (16, 32, 64)
CIRCLE_CONTOUR = 2 * np.sqrt(np.pi)  # perimeter / sqrt(area) of a disc


@dataclass
class Analysis:
    metrics: dict
    layers: dict = field(default_factory=dict)  # numpy masks for diagnostic overlays (not serialised)


# -- small helpers ---------------------------------------------------------------------------

def to_array(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGBA"), dtype=np.float32) / 255.0


def over(rgba: np.ndarray, bg=(1.0, 1.0, 1.0)) -> np.ndarray:
    a = rgba[..., 3:4]
    return rgba[..., :3] * a + np.asarray(bg, dtype=np.float32) * (1 - a)


def luma(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def rel_luminance(rgb255) -> float:
    c = np.asarray(rgb255, dtype=np.float64) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return float(0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2])


def contrast(rgb_a, rgb_b) -> float:
    la, lb = rel_luminance(rgb_a), rel_luminance(rgb_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _window_any(mask: np.ndarray, k: int, pad_value: bool) -> np.ndarray:
    if k <= 1:
        return mask.copy()
    r = k // 2
    p = np.pad(mask, r, constant_values=pad_value)
    rows = sliding_window_view(p, k, axis=0).any(axis=-1)
    return sliding_window_view(rows, k, axis=1).any(axis=-1)


def dilate(mask: np.ndarray, k: int) -> np.ndarray:
    return _window_any(mask, k, False)


def erode(mask: np.ndarray, k: int) -> np.ndarray:
    return ~_window_any(~mask, k, True)


def edges(gray: np.ndarray, thr: float) -> np.ndarray:
    gx = np.zeros_like(gray, dtype=bool)
    gy = np.zeros_like(gray, dtype=bool)
    gx[:, 1:] = np.abs(np.diff(gray, axis=1)) > thr
    gy[1:, :] = np.abs(np.diff(gray, axis=0)) > thr
    return gx | gy


def bbox(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def mirror_iou(mask: np.ndarray, axis: int) -> float:
    b = bbox(mask)
    if b is None:
        return 0.0
    crop = mask[b[1]:b[3], b[0]:b[2]]
    flipped = np.flip(crop, axis=axis)
    union = (crop | flipped).sum()
    return float((crop & flipped).sum() / union) if union else 0.0


def morph_kernel(short_px: int, size: int) -> int:
    """Odd square kernel ≈ one target pixel when the short side of the art is rendered at `size` px."""
    k = max(1, round(short_px / size))
    return k if k % 2 else k - 1


def long_ratio(doc: SvgDoc) -> float:
    return min(4.0, max(doc.aspect, 1 / doc.aspect))


def size_basis(doc: SvgDoc) -> str:
    """How 'N px' is meant: marks fit an N×N box; wide lockups are N px tall, tall ones N px wide."""
    if 0.75 <= doc.aspect <= 1.33:
        return "box"
    return "height" if doc.aspect > 1 else "width"


def palette(rgba: np.ndarray, min_share: float = 0.01, merge_dist: float = 40.0) -> tuple[list[dict], bool]:
    """Dominant flat colours of opaque ink, plus whether the art looks tonal (gradients)."""
    opaque = rgba[..., 3] > 0.95
    if not opaque.any():
        return [], False
    px = np.round(rgba[..., :3][opaque] * 255).astype(np.int32)
    keys = (px[:, 0] >> 3) << 10 | (px[:, 1] >> 3) << 5 | (px[:, 2] >> 3)
    uniq, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
    order = np.argsort(-counts)
    total = counts.sum()
    covered = np.cumsum(counts[order]) / total
    tonal = int(np.searchsorted(covered, 0.9)) + 1 > 24
    clusters: list[dict] = []
    for idx in order:
        share = counts[idx] / total
        if share < min_share / 4:
            break
        mean = px[inverse == idx].mean(axis=0)
        for c in clusters:
            if np.linalg.norm(c["sum"] / c["n"] - mean) < merge_dist:
                c["sum"] += mean * counts[idx]
                c["n"] += counts[idx]
                break
        else:
            clusters.append({"sum": mean * counts[idx], "n": counts[idx]})
    out = []
    for c in sorted(clusters, key=lambda c: -c["n"]):
        share = c["n"] / total
        if share >= min_share:
            rgb = np.clip(np.round(c["sum"] / c["n"]), 0, 255).astype(int)
            out.append({"hex": "#%02x%02x%02x" % tuple(rgb), "rgb": [int(v) for v in rgb], "share": round(float(share), 3)})
    return out, bool(tonal)


# -- main entry ------------------------------------------------------------------------------

def analyze(doc: SvgDoc, bg: str | None = None) -> Analysis:
    ratio = long_ratio(doc)
    img = render.render(doc, round(REF * ratio))
    rgba = to_array(img)
    h, w = rgba.shape[:2]
    alpha = rgba[..., 3]
    mask = alpha > 0.5
    ink = int(mask.sum())
    cw, ch = doc.canvas_size()
    m: dict = {"render_px": [w, h], "canvas_units": [round(cw, 3), round(ch, 3)], "aspect": round(doc.aspect, 3),
               "size_basis": size_basis(doc)}
    layers: dict = {}

    m["coverage"] = round(ink / mask.size, 4)
    m["blank"] = ink < mask.size * 0.002
    if m["blank"]:
        return Analysis(m, layers)

    corners = [alpha[:4, :4], alpha[:4, -4:], alpha[-4:, :4], alpha[-4:, -4:]]
    m["background_fill"] = all(float(c.min()) > 0.95 for c in corners)

    # composition -------------------------------------------------------------------------
    x0, y0, x1, y1 = bbox(mask)
    m["bbox"] = [round(x0 / w, 4), round(y0 / h, 4), round(x1 / w, 4), round(y1 / h, 4)]
    m["margins"] = {"left": round(x0 / w, 4), "top": round(y0 / h, 4),
                    "right": round((w - x1) / w, 4), "bottom": round((h - y1) / h, 4)}
    m["extent"] = [round((x1 - x0) / w, 4), round((y1 - y0) / h, 4)]
    m["bbox_offset"] = [round(((x0 + x1) / 2 - w / 2) / w, 4), round(((y0 + y1) / 2 - h / 2) / h, 4)]
    ys, xs = np.mgrid[0:h, 0:w]
    wsum = float(alpha.sum())
    cx, cy = float((alpha * xs).sum() / wsum), float((alpha * ys).sum() / wsum)
    m["centroid"] = [round(cx / w, 4), round(cy / h, 4)]
    m["centroid_offset"] = [round((cx + 0.5 - w / 2) / w, 4), round((cy + 0.5 - h / 2) / h, 4)]
    m["symmetry"] = {"mirror_lr": round(mirror_iou(mask, 1), 3), "mirror_tb": round(mirror_iou(mask, 0), 3)}
    perimeter = int((mask & ~erode(mask, 3)).sum())
    m["contour_complexity"] = round(perimeter / np.sqrt(ink) / CIRCLE_CONTOUR, 2)

    # small sizes (morphology at MORPH resolution) ---------------------------------------
    mw, mh = render.fit(doc.aspect, round(MORPH * ratio))
    small_alpha = np.asarray(img.getchannel("A").resize((mw, mh), Image.BOX), dtype=np.float32) / 255.0
    smask = small_alpha > 0.5
    sink = max(1, int(smask.sum()))
    # "N px" = the short side of the canvas at N px (for square marks: an N×N box)
    short_units, short_px = min(cw, ch), min(mw, mh)
    m["small_sizes"] = {}
    for size in SMALL_SIZES:
        k = morph_kernel(short_px, size)
        opened = dilate(erode(smask, k), k)
        closed = erode(dilate(smask, k), k)
        thin = smask & ~opened
        filled = closed & ~smask
        m["small_sizes"][str(size)] = {
            "thin_ink": round(float(thin.sum() / sink), 4),
            "gap_fill": round(float(filled.sum() / sink), 4),
            "px_in_units": round(short_units / size, 2),
        }
        if size == 32:
            layers["thin32"], layers["filled32"], layers["mask_small"] = thin, filled, smask

    # colour --------------------------------------------------------------------------------
    pal, tonal = palette(rgba)
    m["palette"] = [{k: v for k, v in c.items() if k != "rgb"} for c in pal]
    m["color_count"] = len(pal)
    m["tonal"] = tonal
    if pal:
        main = [c for c in pal if c["share"] >= 0.1] or pal[:1]
        m["contrast_on_white"] = round(max(contrast(c["rgb"], (255, 255, 255)) for c in main), 2)
        m["contrast_on_black"] = round(max(contrast(c["rgb"], (0, 0, 0)) for c in main), 2)
        if bg:
            from .svgdoc import hex_to_rgb, normalize_color

            bg_hex = normalize_color(bg)
            if bg_hex:
                m["contrast_on_bg"] = {"bg": bg_hex, "ratio": round(max(contrast(c["rgb"], hex_to_rgb(bg_hex)) for c in main), 2)}
        sig = [c for c in pal if c["share"] >= 0.05]
        pairs = [(contrast(a["rgb"], b["rgb"]), a["hex"], b["hex"]) for i, a in enumerate(sig) for b in sig[i + 1:]]
        if pairs:
            lo = min(pairs)
            m["min_color_pair_contrast"] = {"ratio": round(lo[0], 2), "colors": [lo[1], lo[2]]}

    opaque = alpha > 0.95
    whiteish = opaque & (luma(rgba[..., :3]) > 0.94)
    m["white_ink"] = round(float(whiteish.sum() / ink), 4)

    on_white = over(rgba)
    lum = luma(on_white)
    e_rgb = edges(on_white[..., 0], 0.15) | edges(on_white[..., 1], 0.15) | edges(on_white[..., 2], 0.15)
    e_lum = edges(lum, 0.06)
    e_color = e_lum | e_rgb  # every edge visible in the colour render on white
    e_sil = edges(1.0 - alpha, 0.06)
    n_color = max(1, int(e_color.sum()))
    internal = e_color & ~dilate(e_sil, 5)
    near_white = dilate(whiteish, 5)
    m["mono_loss"] = round(float((internal & ~near_white).sum() / n_color), 4)
    m["mono_loss_knockout"] = round(float((internal & near_white).sum() / n_color), 4)
    n_rgb = max(1, int(e_rgb.sum()))
    m["gray_loss"] = round(float((e_rgb & ~dilate(e_lum, 3)).sum() / n_rgb), 4)
    layers["mono_lost"] = internal
    layers["mask"] = mask
    return Analysis(m, layers)


def silhouette_mask(doc: SvgDoc, box: int = 128) -> np.ndarray:
    """Square, bbox-normalised silhouette used to compare candidates with each other."""
    a = np.asarray(render.render(doc, REF).getchannel("A"))
    b = bbox(a > 127)
    if b is None:
        return np.zeros((box, box), dtype=bool)
    crop = Image.fromarray(a[b[1]:b[3], b[0]:b[2]])
    side = max(crop.size)
    sq = Image.new("L", (side, side), 0)
    sq.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
    return np.asarray(sq.resize((box, box), Image.BOX)) > 127


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    union = (a | b).sum()
    return float((a & b).sum() / union) if union else 1.0
