"""Differential tests: every fast implementation must agree exactly with its brute-force reference.

Inputs are biased toward the edges: empty and 1-pixel arrays, all-true/all-false, kernels larger
than the array, content touching the border. Hypothesis shrinks any failure to a minimal input.
"""

import numpy as np
import reference as ref
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from varness import metrics as M

DIFF = settings(max_examples=max(300, settings.default.max_examples))


@st.composite
def masks(draw, max_side: int = 12):
    h = draw(st.integers(0, max_side))
    w = draw(st.integers(0, max_side))
    kind = draw(st.sampled_from(["random", "random", "empty", "full", "border", "dot"]))
    if kind == "empty":
        return np.zeros((h, w), dtype=bool)
    if kind == "full":
        return np.ones((h, w), dtype=bool)
    m = draw(arrays(bool, (h, w)))
    if kind == "border" and h and w:
        m[0, :] = m[-1, :] = m[:, 0] = m[:, -1] = True
    if kind == "dot":
        m = np.zeros((h, w), dtype=bool)
        if h and w:
            m[draw(st.integers(0, h - 1)), draw(st.integers(0, w - 1))] = True
    return m


octagons = st.tuples(st.integers(1, 6), st.integers(0, 3))
odd_kernels = st.integers(0, 6).map(lambda i: 2 * i + 1)


@DIFF
@given(masks(), octagons)
def test_opening_matches_brute(m, ab):
    assert np.array_equal(M.opening(m, *ab), ref.opening(m, *ab))


@DIFF
@given(masks(), octagons)
def test_closing_matches_brute(m, ab):
    assert np.array_equal(M.closing(m, *ab), ref.closing(m, *ab))


@DIFF
@given(masks(), odd_kernels)
def test_dilate_erode_match_brute(m, k):
    assert np.array_equal(M.dilate(m, k), ref.dilate(m, k))
    assert np.array_equal(M.erode(m, k), ref.erode(m, k))


@DIFF
@given(masks(), octagons, octagons)
def test_opening_closing_are_monotone_for_nested_octagons(m, p, q):
    small, big = (min(p[0], q[0]), min(p[1], q[1])), (max(p[0], q[0]), max(p[1], q[1]))
    assert not (M.opening(m, *big) & ~M.opening(m, *small)).any()      # larger SE keeps less ink
    assert not (M.closing(m, *small) & ~M.closing(m, *big)).any()      # larger SE fills more gaps
    assert not (M.opening(m, *big) & ~m).any() and not (m & ~M.closing(m, *big)).any()


@given(st.integers(1, 1024))
def test_size_kernels_nest_and_track_one_pixel(short_px):
    ks = M.size_kernels(short_px)
    assert ks[16][0] >= ks[32][0] >= ks[64][0] and ks[16][1] >= ks[32][1] >= ks[64][1]
    if short_px == 256:
        assert {s: a + 2 * b for s, (a, b) in ks.items()} == {16: 16, 32: 8, 64: 4}


@DIFF
@given(masks(max_side=10))
def test_bbox_matches_nonzero(m):
    ys, xs = np.nonzero(m)
    expected = None if len(xs) == 0 else (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    assert M.bbox(m) == expected


@DIFF
@given(arrays(np.float32, st.tuples(st.integers(1, 9), st.integers(1, 9)),
              elements=st.floats(0, 1, width=32)))
def test_centroid_matches_brute(alpha):
    if alpha.sum() <= 1e-3:
        return
    fx, fy = M.centroid(alpha)
    bx, by = ref.centroid(alpha)
    assert abs(fx - bx) < 1e-3 and abs(fy - by) < 1e-3


@DIFF
@given(arrays(np.uint8, st.tuples(st.integers(0, 60), st.just(3)),
              elements=st.sampled_from([0, 7, 8, 128, 200, 248, 255]) | st.integers(0, 255)))
def test_palette_bins_match_brute(rgb):
    counts, sums = M.bin_stats(rgb)
    expected = ref.bin_stats(rgb)
    assert set(np.flatnonzero(counts)) == set(expected)
    for key, (n, mean) in expected.items():
        assert counts[key] == n
        assert np.allclose(sums[key] / n, mean)


def test_seeded_sweep_small_to_large():
    """Harness-style sweep: sizes grow, so the first mismatch (if any) is a minimal one."""
    rng = np.random.default_rng(0)
    for side in range(0, 9):
        for _ in range(40):
            m = rng.random((side, rng.integers(0, 9))) < rng.random()
            for a, b in ((1, 0), (2, 0), (1, 1), (2, 1), (4, 2), (3, 3)):
                assert np.array_equal(M.opening(m, a, b), ref.opening(m, a, b)), (m, a, b)
                assert np.array_equal(M.closing(m, a, b), ref.closing(m, a, b)), (m, a, b)
