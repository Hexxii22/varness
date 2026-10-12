"""Metamorphic properties of the metrics on real renders, and verification of the fixes we suggest.

The analogue of "the reconstructed path must cost what dp says": a suggested viewBox/translate is only
worth printing if applying it actually removes the finding.
"""

import re

import pytest

from hypothesis import given, settings
from hypothesis import strategies as st

from varness.report import check
from varness.svgdoc import SvgDoc

PROP = settings(max_examples=max(30, settings.default.max_examples // 10))


def doc(body: str, vb: str = "0 0 512 512") -> SvgDoc:
    return SvgDoc.from_string(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}"><title>t</title>{body}</svg>')


def codes(r) -> set[str]:
    return {f.code for f in r.findings}


def fix(r, code: str) -> str:
    return next(f.fix for f in r.findings if f.code == code)


def small(r, size: str, key: str) -> float:
    return r.metrics["small_sizes"][size][key]


THRESHOLDS = (8, 16, 32)  # 1px at 64 / 32 / 16 px on a 512 canvas, in user units


def clear_of_thresholds(*features: float, margin: float = 4) -> bool:
    """Spec: thin/gap shares are step functions of feature width at 1 target pixel. Invariance can
    only hold for features at least 2 morphology px (4 units) away from those steps."""
    return all(abs(f - t) >= margin for f in features for t in THRESHOLDS)


def clear_widths(lo: int, hi: int) -> st.SearchStrategy[int]:
    return st.sampled_from([w for w in range(lo, hi + 1) if clear_of_thresholds(w)])


@st.composite
def mark(draw):
    """A ring plus a bar inside it; every stroke and gap is clear of the 1-target-pixel steps."""
    sw = draw(clear_widths(4, 40))
    bar = draw(clear_widths(4, 60))
    gap = draw(st.integers(36, 60))                 # bar ends ↔ ring inner edge
    r = sw + 2 * gap
    assert clear_of_thresholds(sw, bar, gap, r - sw / 2 - bar / 2)
    reach = r + sw // 2 + 8
    cx, cy = draw(st.integers(reach, 512 - reach)), draw(st.integers(reach, 512 - reach))
    body = (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#14213d" stroke-width="{sw}"/>'
            f'<rect x="{cx - bar // 2}" y="{cy - r // 2}" width="{bar}" height="{r}" fill="#14213d"/>')
    return body


@PROP
@given(mark(), st.sampled_from([2, 10, 0.5]))
def test_uniform_scale_changes_only_units(body, s):
    a = check(doc(body))
    scaled = re.sub(r'(cx|cy|r|stroke-width|x|y|width|height)="(\d+)"',
                    lambda m: f'{m.group(1)}="{int(m.group(2)) * s:g}"', body)
    b = check(doc(scaled, f"0 0 {512 * s:g} {512 * s:g}"))
    for size in ("16", "32", "64"):
        for key in ("thin_ink", "gap_fill"):
            # resvg rasterises in f32: 2px features at the 50% threshold flip a few pixels when coordinates grow ×10;
            # a units bug would move these shares by tens of percent
            assert abs(small(a, size, key) - small(b, size, key)) <= 0.02
        assert abs(small(b, size, "px_in_units") - s * small(a, size, "px_in_units")) <= 0.02 * s
    # shares may move by the f32 noise above (×200–300 weight in scalability), so the score gets ±3;
    # findings outside scalability depend on geometry only and must not change at all
    assert abs(a.score - b.score) <= 3
    geometric = lambda r: {f.code for f in r.findings if f.category != "scalability"}  # noqa: E731
    assert geometric(a) == geometric(b)


@PROP
@given(mark())
def test_mirror_and_recolor_invariance(body):
    a = check(doc(body))
    mirrored = check(doc(f'<g transform="translate(512 0) scale(-1 1)">{body}</g>'))
    recolored = check(doc(body.replace("#14213d", "#7a1f5c")))
    for other in (mirrored, recolored):
        for size in ("16", "32", "64"):
            for key in ("thin_ink", "gap_fill"):
                assert abs(small(a, size, key) - small(other, size, key)) <= 0.02
    assert abs(a.metrics["bbox_offset"][0] + mirrored.metrics["bbox_offset"][0]) <= 0.004


def test_thicker_strokes_never_get_thinner():
    prev = None
    for sw in (2, 4, 8, 12, 16, 24, 32, 48):
        r = check(doc(f'<circle cx="256" cy="256" r="180" fill="none" stroke="#111" stroke-width="{sw}"/>'))
        cur = (small(r, "16", "thin_ink"), small(r, "32", "thin_ink"), small(r, "64", "thin_ink"))
        if prev:
            assert all(c <= p + 0.01 for c, p in zip(cur, prev)), (sw, cur, prev)
        prev = cur
    assert prev[1] == 0.0  # 48 units ≫ 16 units (1px at 32px)


@pytest.mark.parametrize("angle", [0, 30, 45, 60])
def test_thin_threshold_is_isotropic(angle):
    """A bar 18 units wide (> 16 units = 1px at 32px) is never 'thin', whatever its direction;
    a bar 12 units wide always is. A square structuring element calls the 18-unit bar thin at 30–60°."""
    for width, thin in ((18, False), (12, True)):
        r = check(doc(f'<rect x="96" y="{256 - width / 2}" width="320" height="{width}" fill="#111" '
                      f'transform="rotate({angle} 256 256)"/>'))
        assert (small(r, "32", "thin_ink") > 0.5) is thin, (angle, width, small(r, "32", "thin_ink"))


@pytest.mark.parametrize("gap,closes", [(4, True), (10, True), (14, True), (18, False), (24, False), (40, False)])
def test_gap_threshold_is_one_target_pixel(gap, closes):
    """Spec: gaps narrower than 1px at 32px (16 units) fill in, wider ones never do."""
    r = check(doc(f'<rect x="96" y="96" width="140" height="320" fill="#111"/>'
                  f'<rect x="{236 + gap}" y="96" width="140" height="320" fill="#111"/>'))
    assert (small(r, "32", "gap_fill") > 0) is closes, (gap, small(r, "32", "gap_fill"))


@PROP
@given(st.integers(20, 380), st.integers(20, 380), st.integers(15, 90))
def test_suggested_viewbox_fixes_underfilled_and_off_center(x, y, r):
    a = check(doc(f'<circle cx="{x + r}" cy="{y + r}" r="{r}" fill="#222"/>'))
    if "underfilled" not in codes(a):
        return
    vb = re.search(r'viewBox="([^"]+)"', fix(a, "underfilled")).group(1)
    b = check(doc(f'<circle cx="{x + r}" cy="{y + r}" r="{r}" fill="#222"/>', vb))
    assert not codes(b) & {"underfilled", "off-center", "touches-edge"}, (vb, codes(b))


@PROP
@given(st.integers(-60, 60), st.integers(-60, 60))
def test_suggested_translate_fixes_off_center(dx, dy):
    body = f'<rect x="{156 + dx}" y="{156 + dy}" width="200" height="200" fill="#222"/>'
    a = check(doc(body))
    if "off-center" not in codes(a):
        return
    tx, ty = re.search(r'translate\(([-\d.]+) ([-\d.]+)\)', fix(a, "off-center")).groups()
    b = check(doc(f'<g transform="translate({tx} {ty})">{body}</g>'))
    assert "off-center" not in codes(b)


@PROP
@given(st.integers(-200, 300), st.integers(-200, 300), st.integers(150, 400))
def test_reframe_fixes_clipped_art(x, y, side):
    body = f'<rect x="{x}" y="{y}" width="{side}" height="{side}" rx="{side // 5}" fill="#222"/>'
    a = check(doc(body))
    if "touches-edge" not in codes(a) or a.metrics.get("blank"):
        return
    m = re.search(r'viewBox="([^"]+)"', fix(a, "touches-edge"))
    assert m, fix(a, "touches-edge")
    b = check(doc(body, m.group(1)))
    assert not codes(b) & {"touches-edge", "underfilled", "off-center"}, (m.group(1), codes(b))
    assert abs(max(b.metrics["extent"]) - 1 / 1.16) < 0.02  # the whole art, with 8% padding
