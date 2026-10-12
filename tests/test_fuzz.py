"""Robustness: random edge-biased SVGs must never crash the harness and its outputs must stay consistent."""

import json

import numpy as np
from hypothesis import given, settings

from svggen import nested, svg_doc
from varness import render
from varness.export import SAME_RENDER_MAX, render_drift, verification_pixels
from varness.lint import LEVELS
from varness.report import WEIGHTS, check
from varness.svgdoc import SvgDoc, SvgError

FUZZ = settings(max_examples=max(80, settings.default.max_examples // 2))


@FUZZ
@given(svg_doc())
def test_check_never_crashes_and_is_consistent(text):
    r = check(SvgDoc.from_string(text))
    json.dumps(r.to_dict())                                  # only plain JSON types
    assert isinstance(r.score, int) and 0 <= r.score <= 100
    assert set(r.categories) == set(WEIGHTS)
    assert all(isinstance(v, int) and 0 <= v <= 100 for v in r.categories.values())
    levels = {f.level for f in r.findings}
    assert levels <= set(LEVELS)
    assert (r.status == "FAIL") == ("FAIL" in levels)
    assert (r.status == "PASS") == (levels <= {"INFO"})
    if r.status == "FAIL":
        assert r.score <= 49
    if r.ship_ready:
        assert r.status == "PASS" and r.score >= 85
    m = r.metrics
    if m and not m.get("blank"):
        ss = m["small_sizes"]
        # larger target pixel (smaller size) can only lose more: opening/closing are monotone in k
        assert ss["16"]["thin_ink"] >= ss["32"]["thin_ink"] >= ss["64"]["thin_ink"]
        assert ss["16"]["gap_fill"] >= ss["32"]["gap_fill"] >= ss["64"]["gap_fill"]
        assert 0 <= m["coverage"] <= 1 and 0 <= m["white_ink"] <= 1
        assert 0 <= m["mono_loss"] <= 1 and 0 <= m["gray_loss"] <= 1
        assert abs(sum(c["share"] for c in m["palette"]) - 1) <= 1.0  # shares are fractions


@FUZZ
@given(svg_doc())
def test_clean_master_renders_like_the_original(text):
    doc = SvgDoc.from_string(text)
    cleaned = SvgDoc.from_string(doc.clean())
    a, b = verification_pixels(doc, box=128), verification_pixels(cleaned, box=128)
    assert render_drift(a, b) <= SAME_RENDER_MAX, "clean() changed the drawing"


@FUZZ
@given(svg_doc())
def test_recolor_keeps_silhouette_and_is_one_colour(text):
    doc = SvgDoc.from_string(text)
    if doc.counts().get("filter") or doc.counts().get("image"):
        return
    base = verification_pixels(doc, box=128)
    mono = verification_pixels(doc, doc.recolor("#ff0000"), box=128)
    assert render_drift(base[..., 3], mono[..., 3]) <= SAME_RENDER_MAX, "recolor changed the alpha"
    solid = mono[..., 3] > 242
    if solid.any():
        off = np.abs(mono[solid][:, :3].astype(int) - [255, 0, 0]).max(axis=1) > 8
        assert not off.any(), "recolor left other colours"


def test_deep_nesting_is_rejected_not_crashing():
    try:
        doc = SvgDoc.from_string(nested(5000))
    except SvgError:
        return
    doc.clean()
    doc.recolor("#000")
