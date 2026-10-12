"""Pixel-level measurements of a rendered logo.

Everything here works on actual renders, so it catches what XML inspection cannot: features that
vanish at favicon size, counters that fill in, marks that only read in colour, white "knockouts",
off-centre visual weight.

SPEC of the small-size metrics (O = octagon ≈ disc one target pixel across, in morphology pixels):
  thin_ink(N) = |ink \\ opening(ink, O)| / |ink|   — ink not covered by any placement of O inside the ink
  gap_fill(N) = |closing(ink, O) \\ ink| / |ink|   — background not covered by any O inside background
  "N px" means the short side of the canvas at N px (a mark in an N×N box; a lockup N px tall).
  Outside the canvas counts as background. Both are monotone: smaller N (larger k) never loses less.
Fast versions run in O(pixels) per call via integral images; tests/reference.py holds the brute
definitions they are differentially tested against.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from . import render
from .svgdoc import SvgDoc, hex_to_rgb, normalize_color

ANALYSIS_PIXELS = 512 * 512   # render budget for the reference image, whatever the aspect
MORPH_SHORT = 256             # short side of the morphology image: 1px@16 = 16, @32 = 8, @64 = 4 px
MAX_RATIO = 4.0               # beyond 4:1 the long side stops growing
SMALL_SIZES = (16, 32, 64)
SQUARE_ASPECT = (0.75, 1.33)  # aspects treated as a square mark (N px = N×N box)
CIRCLE_CONTOUR = 2 * math.sqrt(math.pi)  # perimeter / sqrt(area) of a disc


@dataclass
class Analysis:
    metrics: dict
    layers: dict = field(default_factory=dict)  # numpy masks for diagnostic overlays (not serialised)


# -- colour helpers ----------------------------------------------------------------------------

def luma(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def rel_luminance(rgb255) -> float:
    c = [v / 255.0 for v in rgb255]
    c = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(rgb_a, rgb_b) -> float:
    la, lb = rel_luminance(rgb_a), rel_luminance(rgb_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# -- morphology (integral images, O(pixels) for any k) ----------------------------------------

def box_count(m: np.ndarray, k: int) -> np.ndarray:
    """count[y, x] = number of True cells in m[y:y+k, x:x+k] (only windows fully inside m)."""
    H, W = m.shape
    s = np.zeros((H + 1, W + 1), dtype=np.int32)
    np.cumsum(m, axis=0, dtype=np.int32, out=s[1:, 1:])
    np.cumsum(s[1:, 1:], axis=1, out=s[1:, 1:])
    return s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]


def octagon(k: float) -> tuple[int, int]:
    """(a, b) such that S(a) ⊕ D(b) — an a×a square plus an L1 ball of radius b — is an octagon about
    k px across along both the axes (a + 2b) and the diagonals (√2·(a + b)): a near-isotropic stand-in
    for a disc of diameter k. A plain square would call a 1.2px diagonal stroke 'thinner than 1px'."""
    if k < 1.5:
        return 1, 0
    b = round(k * (1 - 1 / math.sqrt(2)))
    return max(1, round(k) - 2 * b), b


def _plus(x: np.ndarray, erode_: bool, outside: bool) -> np.ndarray:
    """Erode/dilate by the 3×3 cross (the L1 ball of radius 1)."""
    p = np.pad(x, 1, constant_values=outside)
    c, up, down, left, right = p[1:-1, 1:-1], p[:-2, 1:-1], p[2:, 1:-1], p[1:-1, :-2], p[1:-1, 2:]
    return c & up & down & left & right if erode_ else c | up | down | left | right


def opening(m: np.ndarray, a: int, b: int = 0, outside: bool = False) -> np.ndarray:
    """Union of every placement of the octagon S(a) ⊕ D(b) lying entirely in m.

    Cells beyond the array count as `outside`; placements may stick out of the array.
    O(pixels · (1 + b)): squares via integral images, the L1 ball as b crosses.
    """
    if a <= 1 and b == 0:
        return m.copy()
    M = a - 1 + 2 * b                                     # how far a placement can reach past the array
    x = np.pad(m, M, constant_values=outside)
    e = box_count(np.pad(x, ((0, a - 1), (0, a - 1)), constant_values=outside), a) == a * a
    for _ in range(b):
        e = _plus(e, True, outside)
    for _ in range(b):
        e = _plus(e, False, False)
    o = box_count(np.pad(e, ((a - 1, 0), (a - 1, 0))), a) > 0
    H, W = m.shape
    return o[M:M + H, M:M + W]


def closing(m: np.ndarray, a: int, b: int = 0) -> np.ndarray:
    """Complement of every octagon placement lying entirely in background (outside = background)."""
    return ~opening(~m, a, b, outside=True)


def dilate(m: np.ndarray, k: int) -> np.ndarray:
    """Centred k×k window (k odd) contains any True; outside is False."""
    if k <= 1:
        return m.copy()
    return box_count(np.pad(m, k // 2), k) > 0


def erode(m: np.ndarray, k: int) -> np.ndarray:
    """Centred k×k window (k odd) is all True; outside is False."""
    if k <= 1:
        return m.copy()
    return box_count(np.pad(m, k // 2), k) == k * k


def edges(gray: np.ndarray, thr: float) -> np.ndarray:
    out = np.zeros(gray.shape, dtype=bool)
    out[:, 1:] |= np.abs(np.diff(gray, axis=1)) > thr
    out[1:, :] |= np.abs(np.diff(gray, axis=0)) > thr
    return out


def bbox(mask: np.ndarray):
    rows, cols = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
    if len(rows) == 0:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def centroid(alpha: np.ndarray) -> tuple[float, float]:
    """Alpha-weighted centre of mass in pixel coordinates (pixel i spans [i, i+1))."""
    total = float(alpha.sum())
    cx = float(alpha.sum(axis=0) @ (np.arange(alpha.shape[1]) + 0.5)) / total
    cy = float(alpha.sum(axis=1) @ (np.arange(alpha.shape[0]) + 0.5)) / total
    return cx, cy


def mirror_iou(mask: np.ndarray, axis: int) -> float:
    b = bbox(mask)
    if b is None:
        return 0.0
    crop = mask[b[1]:b[3], b[0]:b[2]]
    flipped = np.flip(crop, axis=axis)
    union = (crop | flipped).sum()
    return float((crop & flipped).sum() / union) if union else 0.0


def size_kernels(short_px: int) -> dict[int, tuple[int, int]]:
    """Octagon per target size; one target pixel = short_px / size morphology pixels.

    Parameters are forced to nest (16px ⊇ 32px ⊇ 64px), so thin_ink and gap_fill are monotone in size.
    """
    out: dict[int, tuple[int, int]] = {}
    pa, pb = 1, 0
    for size in sorted(SMALL_SIZES, reverse=True):
        a, b = octagon(short_px / size)
        pa, pb = max(a, pa), max(b, pb)
        out[size] = (pa, pb)
    return out


def long_ratio(doc: SvgDoc) -> float:
    return min(MAX_RATIO, max(doc.aspect, 1 / doc.aspect))


def analysis_box(doc: SvgDoc) -> int:
    """Long side of the reference render: a fixed pixel budget regardless of aspect."""
    return round(math.sqrt(ANALYSIS_PIXELS * long_ratio(doc)))


def size_basis(doc: SvgDoc) -> str:
    """How 'N px' is meant: marks fit an N×N box; wide lockups are N px tall, tall ones N px wide."""
    if SQUARE_ASPECT[0] <= doc.aspect <= SQUARE_ASPECT[1]:
        return "box"
    return "height" if doc.aspect > 1 else "width"


# -- palette ---------------------------------------------------------------------------------

def bin_stats(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per 5-bit colour bin: pixel counts (32768,) and colour sums (32768, 3). One pass, O(pixels)."""
    px = rgb.reshape(-1, 3).astype(np.int32)
    keys = (px[:, 0] >> 3) << 10 | (px[:, 1] >> 3) << 5 | (px[:, 2] >> 3)
    counts = np.bincount(keys, minlength=32768)
    sums = np.stack([np.bincount(keys, weights=px[:, c], minlength=32768) for c in range(3)], axis=1)
    return counts, sums


def palette(rgb_opaque: np.ndarray, min_share: float = 0.01, merge_dist: float = 40.0) -> tuple[list[dict], bool]:
    """Dominant flat colours of opaque ink (N×3 uint8), plus whether the art looks tonal (gradients)."""
    if len(rgb_opaque) == 0:
        return [], False
    counts, sums = bin_stats(rgb_opaque)
    nz = np.flatnonzero(counts)
    order = nz[np.argsort(-counts[nz], kind="stable")]
    total = int(counts.sum())
    covered = np.cumsum(counts[order]) / total
    tonal = int(np.searchsorted(covered, 0.9)) + 1 > 24
    clusters: list[list] = []                     # [colour sum, pixel count]
    for idx in order:
        n = int(counts[idx])
        if n < total * min_share / 4:
            break
        mean = sums[idx] / n
        for c in clusters:
            if np.linalg.norm(c[0] / c[1] - mean) < merge_dist:
                c[0] = c[0] + sums[idx]
                c[1] += n
                break
        else:
            clusters.append([sums[idx].copy(), n])
    out = []
    for s, n in sorted(clusters, key=lambda c: -c[1]):
        if n / total >= min_share:
            rgb = [int(v) for v in np.clip(np.round(s / n), 0, 255)]
            out.append({"hex": "#%02x%02x%02x" % tuple(rgb), "rgb": rgb, "share": round(n / total, 3)})
    return out, bool(tonal)


# -- main entry ------------------------------------------------------------------------------

def analyze(doc: SvgDoc, bg: str | None = None) -> Analysis:
    img = render.render(doc, analysis_box(doc))
    px = np.asarray(img)                          # H×W×4 uint8, no copy
    h, w = px.shape[:2]
    a8 = px[..., 3]
    mask = a8 > 127
    ink = int(mask.sum())
    cw, ch = doc.canvas_size()
    m: dict = {"render_px": [w, h], "canvas_units": [round(cw, 3), round(ch, 3)], "aspect": round(doc.aspect, 3),
               "size_basis": size_basis(doc)}
    layers: dict = {}

    m["coverage"] = round(ink / mask.size, 4)
    m["blank"] = ink < mask.size * 0.002
    if m["blank"]:
        return Analysis(m, layers)
    alpha = a8.astype(np.float32) / 255.0

    c = min(4, h, w)
    corners = [a8[:c, :c], a8[:c, -c:], a8[-c:, :c], a8[-c:, -c:]]
    m["background_fill"] = all(int(q.min()) > 242 for q in corners)

    # composition -------------------------------------------------------------------------
    x0, y0, x1, y1 = bbox(mask)
    m["bbox"] = [round(x0 / w, 4), round(y0 / h, 4), round(x1 / w, 4), round(y1 / h, 4)]
    m["margins"] = {"left": round(x0 / w, 4), "top": round(y0 / h, 4),
                    "right": round((w - x1) / w, 4), "bottom": round((h - y1) / h, 4)}
    m["extent"] = [round((x1 - x0) / w, 4), round((y1 - y0) / h, 4)]
    m["bbox_offset"] = [round(((x0 + x1) / 2 - w / 2) / w, 4), round(((y0 + y1) / 2 - h / 2) / h, 4)]
    cx, cy = centroid(alpha)
    m["centroid"] = [round(cx / w, 4), round(cy / h, 4)]
    m["centroid_offset"] = [round((cx - w / 2) / w, 4), round((cy - h / 2) / h, 4)]
    m["symmetry"] = {"mirror_lr": round(mirror_iou(mask, 1), 3), "mirror_tb": round(mirror_iou(mask, 0), 3)}
    perimeter = int((mask & ~erode(mask, 3)).sum())
    m["contour_complexity"] = round(perimeter / math.sqrt(ink) / CIRCLE_CONTOUR, 2)

    # small sizes ---------------------------------------------------------------------------
    scale = min(1.0, MORPH_SHORT / min(w, h))   # never upsample (extreme aspects have a tiny short side)
    mw, mh = max(1, round(w * scale)), max(1, round(h * scale))
    small = img.getchannel("A")
    if (mw, mh) != (w, h):
        small = small.resize((mw, mh), Image.BOX)
    smask = np.asarray(small) > 127
    sink = max(1, int(smask.sum()))
    short_units, short_px = min(cw, ch), min(mw, mh)
    m["small_sizes"] = {}
    for size, (ka, kb) in sorted(size_kernels(short_px).items()):
        thin = smask & ~opening(smask, ka, kb)
        filled = closing(smask, ka, kb) & ~smask
        m["small_sizes"][str(size)] = {
            "thin_ink": round(float(thin.sum() / sink), 4),
            "gap_fill": round(float(filled.sum() / sink), 4),
            "px_in_units": round(short_units / size, 2),
        }
        if size == 32:
            layers["thin32"], layers["filled32"] = thin, filled

    # colour --------------------------------------------------------------------------------
    opaque = a8 > 242
    pal, tonal = palette(px[..., :3][opaque])
    m["palette"] = [{k: v for k, v in c.items() if k != "rgb"} for c in pal]
    m["color_count"] = len(pal)
    m["tonal"] = tonal
    if pal:
        main = [c for c in pal if c["share"] >= 0.1] or pal[:1]
        m["contrast_on_white"] = round(max(contrast(c["rgb"], (255, 255, 255)) for c in main), 2)
        m["contrast_on_black"] = round(max(contrast(c["rgb"], (0, 0, 0)) for c in main), 2)
        bg_hex = normalize_color(bg) if bg else None
        if bg_hex:
            m["contrast_on_bg"] = {"bg": bg_hex, "ratio": round(max(contrast(c["rgb"], hex_to_rgb(bg_hex)) for c in main), 2)}
        sig = [c for c in pal if c["share"] >= 0.05]
        pairs = [(contrast(a["rgb"], b["rgb"]), a["hex"], b["hex"]) for i, a in enumerate(sig) for b in sig[i + 1:]]
        if pairs:
            lo = min(pairs)
            m["min_color_pair_contrast"] = {"ratio": round(lo[0], 2), "colors": [lo[1], lo[2]]}

    rgb = px[..., :3].astype(np.float32) / 255.0
    whiteish = opaque & (luma(rgb) > 0.94)
    m["white_ink"] = round(float(whiteish.sum() / ink), 4)

    on_white = rgb * alpha[..., None] + (1.0 - alpha[..., None])
    e_rgb = edges(on_white[..., 0], 0.15) | edges(on_white[..., 1], 0.15) | edges(on_white[..., 2], 0.15)
    e_lum = edges(luma(on_white), 0.06)
    e_color = e_lum | e_rgb  # every edge visible in the colour render on white
    e_sil = edges(alpha, 0.06)
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


def true_bbox_units(doc: SvgDoc) -> tuple[float, float, float, float] | None:
    """Bounding box of the art in user units, including parts clipped by the current viewBox."""
    x, y, cw, ch = doc.viewbox or (0.0, 0.0, *doc.canvas_size())
    ex, ey, ew, eh = x - cw, y - ch, 3 * cw, 3 * ch
    variant = doc.with_viewbox((ex, ey, ew, eh))
    img = render.render(SvgDoc.from_string(variant), analysis_box(doc))  # 3× canvas: ~0.6% precision, padding absorbs it
    b = bbox(np.asarray(img.getchannel("A")) > 127)
    if b is None:
        return None
    sx, sy = ew / img.width, eh / img.height
    return ex + b[0] * sx, ey + b[1] * sy, (b[2] - b[0]) * sx, (b[3] - b[1]) * sy


def silhouette_mask(mask: np.ndarray, box: int = 128) -> np.ndarray:
    """Square, bbox-normalised silhouette used to compare candidates with each other."""
    b = bbox(mask)
    if b is None:
        return np.zeros((box, box), dtype=bool)
    crop = Image.fromarray((mask[b[1]:b[3], b[0]:b[2]] * 255).astype(np.uint8))
    side = max(crop.size)
    sq = Image.new("L", (side, side), 0)
    sq.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
    return np.asarray(sq.resize((box, box), Image.BOX)) > 127


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    union = (a | b).sum()
    return float((a & b).sum() / union) if union else 1.0
