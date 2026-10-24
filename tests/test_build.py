"""`varness build`: geometry checked against closed-form areas, real holes in the render, spec errors, grids."""

import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from PIL import Image, ImageDraw

pathops = pytest.importorskip("pathops")

from varness import render  # noqa: E402
from varness.build import BuildError, _Builder, build  # noqa: E402
from varness.cli import main  # noqa: E402
from varness.report import check  # noqa: E402
from varness.sheet import draw_grid  # noqa: E402
from varness.svgdoc import SvgDoc  # noqa: E402


def area(shape, snap=None):
    return abs(_Builder(512, 512, snap).node(shape).area)


def close(a, b, rel=2e-3):
    assert a == pytest.approx(b, rel=rel), (a, b)


def test_primitive_areas():
    close(area({"circle": [256, 256, 100]}), math.pi * 100**2)
    close(area({"ring": [256, 256, 200, 150]}), math.pi * (200**2 - 150**2))
    close(area({"arc": [256, 256, 200, 150, 290, 61]}), 131 / 360 * math.pi * (200**2 - 150**2))
    close(area({"arc": [256, 256, 200, 150, 0, 360]}), math.pi * (200**2 - 150**2))
    close(area({"arc": [256, 256, 200, 0, 0, 90]}), math.pi * 200**2 / 4)  # r=0: a pie slice
    close(area({"ngon": [256, 256, 200, 6]}), 3 * math.sqrt(3) / 2 * 200**2)
    close(area({"polygon": [[0, 0], [100, 0], [0, 100]]}), 5000, rel=1e-9)


@given(w=st.integers(40, 400), h=st.integers(40, 400), r=st.integers(0, 300))
def test_rounded_rect_area(w, h, r):
    # fillets are clamped to half the shorter side, each corner loses (4 - π)·r²/4
    rr = min(r, w / 2, h / 2)
    close(area({"rect": [10, 10, w, h], "r": r}), w * h - (4 - math.pi) * rr**2)


def test_booleans_repeat_mirror():
    disc = {"circle": [256, 256, 200]}
    hole = {"circle": [256, 256, 80]}
    close(area({"subtract": [disc, hole]}), math.pi * (200**2 - 80**2))
    close(area({"intersect": [disc, {"rect": [0, 0, 512, 256]}]}), math.pi * 200**2 / 2)
    close(area({"union": [disc, hole]}), math.pi * 200**2)
    close(area({"circle": [256, 100, 40], "repeat": 5}), 5 * math.pi * 40**2)
    close(area({"circle": [100, 256, 40], "mirror": "x"}), 2 * math.pi * 40**2)
    # rotating about the canvas centre keeps the area; translating keeps it too
    close(area({"rect": [100, 200, 300, 60], "rotate": 37, "translate": [8, 8]}), 300 * 60)


def test_cut_is_a_real_hole():
    svg, warnings = build({"layers": [{"fill": "#123456", "shape": {"subtract": [
        {"circle": [256, 256, 200]}, {"ngon": [256, 256, 120, 5], "star": 50, "r": 8}]}}]})
    assert not warnings
    img = np.asarray(render.render(SvgDoc.from_string(svg), 128))
    assert img[64, 64, 3] == 0  # centre of the star is transparent, not white paint
    assert img[64, 24, 3] == 255  # the disc itself is there (x=96 of 512)


def test_cli_build_then_check(tmp_path):
    spec = tmp_path / "logo.json"
    spec.write_text('{"title": "A & B", "snap": 8, "layers": [{"fill": "#1f3a93", "shape": '
                    '{"subtract": [{"rect": [64, 64, 384, 384], "r": 96}, {"circle": [256, 256, 96]}]}}]}')
    out = tmp_path / "logo.svg"
    assert main(["build", str(spec), "-o", str(out)]) == 0
    r = check(str(out))
    assert r.status == "PASS", [f.code for f in r.findings]
    assert "<title>A &amp; B</title>" in out.read_text()


def test_polar_points():
    # a square given in polar form about its centre equals the same square in x/y
    sq = [{"polar": [100 * math.sqrt(2), a], "about": [200, 200]} for a in (45, 135, 225, 315)]
    close(area({"polygon": sq}), 200 * 200)
    _, warnings = build({"snap": 8, "layers": [{"shape": {"polygon": [{"polar": [200, 13]}, {"polar": [200, 77]},
                                                                      {"polar": [96, 45]}]}}]})
    assert not warnings  # computed x/y are irrational, but r and the centre are on the grid


def test_per_corner_radius():
    # only the [x, y, r] corner is rounded; "r" fills the rest, 0 keeps a corner sharp
    one = area({"polygon": [[100, 100, 40], [300, 100], [300, 300], [100, 300]]})
    close(one, 200 * 200 - (4 - math.pi) * 40**2 / 4)
    close(area({"polygon": [[100, 100, 0], [300, 100, 0], [300, 300], [100, 300]], "r": 40}),
          200 * 200 - (4 - math.pi) * 40**2 / 2)
    # a mirrored half whose corners on the axis stay sharp has no notch on the seam
    half = {"polygon": [[256, 100, 0], [400, 100], [400, 400], [256, 400, 0]], "r": 32, "mirror": "x"}
    close(area(half), 288 * 300 - (4 - math.pi) * 32**2)


def test_snap_warnings():
    _, warnings = build({"snap": 8, "layers": [{"shape": {"circle": [256, 250, 100], "translate": [3, 0]}},
                                               {"shape": {"arc": [256, 256, 200, 160, 13, 77]}}]})
    assert warnings == ["layers[0].circle: 250 is off the 8-unit grid", "layers[0].circle: 100 is off the 8-unit grid",
                        "layers[0].circle.translate: 3 is off the 8-unit grid"]  # angles are not snapped


@pytest.mark.parametrize("spec, msg", [
    ({}, "non-empty \"layers\""),
    ({"layers": [{"fill": "#000"}]}, "needs \"shape\""),
    ({"layers": [{"shape": {"circle": [1, 2]}}]}, "layers[0].circle: bad arguments"),
    ({"layers": [{"shape": {"circle": [1, 2, 3], "rect": [0, 0, 1, 1]}}]}, "exactly one of"),
    ({"layers": [{"shape": {"union": [{"blob": 1}]}}]}, "layers[0].union[0]: needs exactly one of"),
    ({"layers": [{"shape": {"polygon": [[0, 0], [1, 1]]}}]}, "at least 3 points"),
    ({"layers": [{"shape": {"polygon": [{"at": [1, 2]}, [0, 0], [1, 1]]}}]}, "layers[0].polygon: bad arguments"),
    ({"layers": [{"shape": {"polygon": [[0, 0, 1, 2], [9, 0], [9, 9]]}}]}, "[x, y, corner_radius]"),
    ({"layers": [{"shape": {"circle": [9, 9, 9], "mirror": "z"}}]}, "mirror"),
])
def test_spec_errors(spec, msg):
    with pytest.raises(BuildError) as e:
        build(spec)
    assert msg in str(e.value)


def test_empty_cut_warns():
    svg, warnings = build({"layers": [{"shape": {"subtract": [{"circle": [256, 256, 10]}, {"circle": [256, 256, 50]}]}}]})
    assert warnings and "empty" in warnings[0] and "<path" not in svg


@pytest.mark.parametrize("kind", ["8x8", "thirds", "golden", "keyline", "radial:12"])
def test_grids_draw(kind):
    img = Image.new("RGB", (64, 64), (255, 255, 255))
    draw_grid(ImageDraw.Draw(img), 64, 64, kind)
    assert np.asarray(img).min() < 255


@pytest.mark.parametrize("kind", ["hex", "radial:x"])
def test_bad_grid(kind):
    with pytest.raises(ValueError):
        draw_grid(ImageDraw.Draw(Image.new("RGB", (8, 8))), 8, 8, kind)
