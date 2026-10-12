"""Brute-force reference implementations ("brute" in the differential harness).

Written straight from the definitions, no tricks, only for small inputs. The fast versions in
varness.metrics must agree with these exactly.
"""

import numpy as np


def octagon_offsets(a: int, b: int) -> list[tuple[int, int]]:
    """Cells of S(a) ⊕ D(b): every square cell plus every L1 offset of radius ≤ b (built independently)."""
    ball = [(dy, dx) for dy in range(-b, b + 1) for dx in range(-b, b + 1) if abs(dy) + abs(dx) <= b]
    return sorted({(sy + dy, sx + dx) for sy in range(a) for sx in range(a) for dy, dx in ball})


def opening(m: np.ndarray, a: int, b: int = 0, outside: bool = False) -> np.ndarray:
    """Union of every placement of the structuring element lying entirely in m (beyond = `outside`)."""
    H, W = m.shape
    se = octagon_offsets(a, b)
    lo_y, hi_y = min(o[0] for o in se), max(o[0] for o in se)
    lo_x, hi_x = min(o[1] for o in se), max(o[1] for o in se)
    out = np.zeros((H, W), dtype=bool)
    for py in range(-hi_y, H - lo_y):
        for px in range(-hi_x, W - lo_x):
            cells = [(py + dy, px + dx) for dy, dx in se]
            if all(m[y, x] if 0 <= y < H and 0 <= x < W else outside for y, x in cells):
                for y, x in cells:
                    if 0 <= y < H and 0 <= x < W:
                        out[y, x] = True
    return out


def closing(m: np.ndarray, a: int, b: int = 0) -> np.ndarray:
    """Complement of every SE placement lying entirely in background, where outside counts as background."""
    return ~opening(~m, a, b, outside=True)


def dilate(m: np.ndarray, k: int) -> np.ndarray:
    """Centred k×k (k odd) window contains any True; outside is False."""
    H, W = m.shape
    r = k // 2
    out = np.zeros((H, W), dtype=bool)
    for y in range(H):
        for x in range(W):
            out[y, x] = m[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1].any()
    return out


def erode(m: np.ndarray, k: int) -> np.ndarray:
    """Centred k×k (k odd) window is all True; outside is False."""
    H, W = m.shape
    r = k // 2
    out = np.zeros((H, W), dtype=bool)
    for y in range(H):
        for x in range(W):
            if y - r < 0 or x - r < 0 or y + r >= H or x + r >= W:
                continue
            out[y, x] = m[y - r:y + r + 1, x - r:x + r + 1].all()
    return out


def centroid(alpha: np.ndarray) -> tuple[float, float]:
    """Alpha-weighted centre of mass in pixel coordinates (pixel i spans [i, i+1))."""
    H, W = alpha.shape
    total = sx = sy = 0.0
    for y in range(H):
        for x in range(W):
            a = float(alpha[y, x])
            total += a
            sx += a * (x + 0.5)
            sy += a * (y + 0.5)
    return sx / total, sy / total


def bin_stats(rgb: np.ndarray) -> dict[int, tuple[int, np.ndarray]]:
    """Per 5-bit colour bin: (pixel count, mean colour) — straight loop over pixels."""
    acc: dict[int, list] = {}
    for r, g, b in rgb.reshape(-1, 3).astype(int):
        key = (r >> 3) << 10 | (g >> 3) << 5 | (b >> 3)
        entry = acc.setdefault(key, [0, np.zeros(3)])
        entry[0] += 1
        entry[1] += (r, g, b)
    return {k: (n, s / n) for k, (n, s) in acc.items()}
