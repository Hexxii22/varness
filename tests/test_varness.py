import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from varness import history
from varness.cli import main
from varness.lint import lint
from varness.report import check
from varness.svgdoc import SvgDoc, SvgError, normalize_color


def svg(body: str, vb: str = "0 0 512 512", title: bool = True) -> str:
    t = "<title>Test</title>" if title else ""
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">{t}{body}</svg>'


# disc with a real square hole and a second colour separated by negative space
GOOD = svg('<path fill="#1f3a93" fill-rule="evenodd" d="M56 256a200 200 0 1 0 400 0a200 200 0 1 0-400 0z'
           'M176 176v160h160V176z"/><path fill="#f2b705" d="M212 212h88v88h-88z"/>')


@pytest.fixture
def write(tmp_path):
    def _write(name: str, text: str) -> Path:
        p = tmp_path / name
        p.write_text(text)
        return p
    return _write


def codes(report):
    return {f.code for f in report.findings}


# -- svgdoc -----------------------------------------------------------------------------------

def test_normalize_color():
    assert normalize_color("#ABC") == "#aabbcc"
    assert normalize_color("rgb(255, 0, 0)") == "#ff0000"
    assert normalize_color("white") == "#ffffff"
    assert normalize_color("none") is None
    assert normalize_color("url(#g)") is None


def test_recolor_keeps_invisible_gradient_lines_invisible():
    # a gradient stroke on a zero-height line renders nothing (objectBoundingBox), so recolor must not reveal it;
    # userSpaceOnUse gradients and lines with a real box still get the flat colour (found by test_fuzz)
    grad = '<linearGradient id="g"{units}><stop offset="0" stop-color="#14213d"/></linearGradient>'
    line = '<line x1="-153.6" y1="0" x2="2" y2="{y2}" stroke="url(#g)" stroke-width="5"/>'
    for units, y2, want in (("", "0", "none"), (' gradientUnits="userSpaceOnUse"', "0", "#ff0000"),
                            ("", "40", "#ff0000"), ("", "10%", "#ff0000")):
        doc = SvgDoc.from_string(svg(f"<defs>{grad.format(units=units)}</defs>" + line.format(y2=y2)))
        assert f'stroke="{want}"' in doc.recolor("#ff0000"), (units, y2)


def test_rejects_non_svg_and_entities():
    with pytest.raises(SvgError):
        SvgDoc.from_string("<html/>")
    with pytest.raises(SvgError):
        SvgDoc.from_string('<!DOCTYPE svg [<!ENTITY a "x">]><svg xmlns="http://www.w3.org/2000/svg"/>')


def test_recolor_and_clean():
    doc = SvgDoc.from_string(svg(
        '<defs><linearGradient id="g"><stop offset="0" stop-color="red"/></linearGradient></defs>'
        '<path d="M10.123456 20.987654L30 40Z" fill="url(#g)" style="stroke:#00f;stroke-width:3"/>'
        '<rect x="1" y="1" width="5" height="5" fill="none"/>'))
    mono = doc.recolor("#000000")
    assert "url(#g)" not in mono and "#00f" not in mono
    assert 'fill="none"' in mono
    cleaned = SvgDoc.from_string(svg('<path d="M10.123456 20.987654L30 40Z"/>')).clean(2)
    assert "10.12" in cleaned and "20.99" in cleaned and "123456" not in cleaned


# -- lint ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("body,code", [
    ('<text x="10" y="50">Hi</text>', "live-text"),
    ('<image href="a.png" width="10" height="10"/>', "raster-image"),
    ('<rect width="10" height="10" fill="url(#missing)"/>', "dangling-ref"),
    ('<script>alert(1)</script>', "script"),
    ('<rect width="10" height="10" onclick="x()"/>', "script"),
])
def test_lint_fails(body, code):
    found = {f.code: f.level for f in lint(SvgDoc.from_string(svg(body)))}
    assert found.get(code) == "FAIL"


def test_lint_missing_viewbox():
    doc = SvgDoc.from_string('<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>')
    assert {f.code: f.level for f in lint(doc)}["no-viewbox"] == "FAIL"


# -- pixel metrics ------------------------------------------------------------------------------

def test_good_mark_is_ship_ready(write):
    r = check(write("good.svg", GOOD))
    assert r.status == "PASS", [f.code for f in r.findings]
    assert r.ship_ready and r.score >= 90
    assert r.metrics["symmetry"]["mirror_lr"] > 0.95
    assert abs(r.metrics["bbox_offset"][0]) < 0.01


def test_blank_render_fails(write):
    r = check(write("blank.svg", svg('<rect width="100" height="100" fill="none"/>')))
    assert r.status == "FAIL" and "renders-blank" in codes(r)


def test_off_center_and_underfilled(write):
    r = check(write("off.svg", svg('<circle cx="120" cy="120" r="80" fill="#222"/>')))
    assert {"off-center", "underfilled"} <= codes(r)
    fix = next(f.fix for f in r.findings if f.code == "underfilled")
    assert 'viewBox="' in fix


def test_touching_edge(write):
    r = check(write("edge.svg", svg('<rect x="0" y="100" width="300" height="300" fill="#222"/>')))
    assert "touches-edge" in codes(r)


def test_hairlines_vanish_small(write):
    body = '<circle cx="256" cy="256" r="200" fill="none" stroke="#111" stroke-width="3"/>'
    r = check(write("hair.svg", svg(body)))
    assert {"thin-at-64", "thin-at-32"} <= codes(r)
    assert r.categories["scalability"] < 50


def test_narrow_gaps_close(write):
    bars = "".join(f'<rect x="{56 + i * 28}" y="80" width="20" height="352" fill="#111"/>' for i in range(15))
    r = check(write("gaps.svg", svg(bars)))
    assert "gaps-close-at-32" in codes(r)


def test_white_knockout(write):
    body = '<circle cx="256" cy="256" r="220" fill="#1f3a93"/><circle cx="256" cy="256" r="90" fill="#fff"/>'
    r = check(write("ko.svg", svg(body)))
    assert "white-knockout" in codes(r)
    real_hole = ('<path fill="#1f3a93" fill-rule="evenodd" d="M36 256a220 220 0 1 0 440 0a220 220 0 1 0-440 0z'
                 'M166 256a90 90 0 1 0 180 0a90 90 0 1 0-180 0z"/>')
    assert "white-knockout" not in codes(check(write("hole.svg", svg(real_hole))))


def test_color_only_structure(write):
    body = ('<rect x="56" y="56" width="200" height="400" fill="#d62828"/>'
            '<rect x="256" y="56" width="200" height="400" fill="#1d6fd6"/>')
    r = check(write("split.svg", svg(body)))
    assert r.metrics["mono_loss"] > 0.1


def test_similar_lightness(write):
    body = "".join(
        f'<rect x="{56 + i * 80}" y="56" width="80" height="400" fill="{c}"/>'
        for i, c in enumerate(["#e0457b", "#2e9e8f", "#e0457b", "#2e9e8f", "#e0457b"]))
    r = check(write("hue.svg", svg(body)))
    assert r.metrics["gray_loss"] > 0.25 and "similar-lightness" in codes(r)


def test_wide_lockup_uses_height(write):
    body = '<rect x="20" y="20" width="760" height="160" rx="20" fill="#16224a"/>'
    r = check(write("wide.svg", svg(body, vb="0 0 800 200")))
    assert r.metrics["size_basis"] == "height"
    assert r.metrics["small_sizes"]["32"]["px_in_units"] == pytest.approx(200 / 32, rel=0.01)


def test_parse_error_reported(write):
    r = check(write("broken.svg", "<svg"))
    assert r.status == "FAIL" and "parse-error" in codes(r)


# -- history ------------------------------------------------------------------------------------

def test_history_tracks_and_flags_regression(write, tmp_path):
    root = tmp_path / "hist"
    good = write("a.svg", GOOD)
    e1 = history.record("brand", good, check(good), root=root)
    assert e1["version"] == "v001"
    again = history.record("brand", good, check(good), root=root)
    assert again.get("duplicate")
    worse = write("b.svg", svg('<circle cx="120" cy="120" r="80" fill="#222"/>'))
    e2 = history.record("brand", worse, check(worse), root=root)
    assert e2["version"] == "v002"
    text = history.describe(e2)
    assert "regression" in text and "v001" in text
    out = tmp_path / "restored.svg"
    history.restore("brand", "v001", out, root=root)
    assert out.read_text() == GOOD


# -- cli / export -------------------------------------------------------------------------------

def test_cli_check_json_and_sheet(write, tmp_path, capsys):
    f = write("good.svg", GOOD)
    sheet = tmp_path / "sheet.png"
    assert main(["--history-dir", str(tmp_path / "h"), "check", str(f), "--json", "--sheet", str(sheet), "--track", "t"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["score"] >= 90 and data["history"]["version"] == "v001"
    assert Image.open(sheet).size[0] >= 1200


def test_cli_compare_flags_near_duplicates(write, tmp_path, capsys):
    a = write("a.svg", GOOD)
    b = write("b.svg", GOOD.replace("h88v88h-88z", "h90v88h-90z"))
    c = write("c.svg", svg('<path fill="#111" d="M256 56 456 456H56z"/>'))
    assert main(["compare", str(a), str(b), str(c), "-o", str(tmp_path / "cmp.png"), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    pairs = {(p["a"], p["b"]) for p in data["too_similar"]}
    assert ("a.svg", "b.svg") in pairs and not any("c.svg" in p for p in pairs)


def test_export_kit(write, tmp_path, capsys):
    f = write("good.svg", GOOD)
    out = tmp_path / "dist"
    assert main(["export", str(f), "-o", str(out), "--name", "acme"]) == 0
    for rel in ("svg/acme.svg", "svg/acme-black.svg", "svg/acme-white.svg", "png/acme-16.png", "png/acme-1024.png",
                "favicon.ico", "apple-touch-icon.png", "icon-maskable-512.png", "site.webmanifest", "sheet.png"):
        assert (out / rel).exists(), rel
    ico = Image.open(out / "favicon.ico")
    assert (48, 48) in ico.info.get("sizes", {(48, 48)})
    black = np.asarray(Image.open(out / "png" / "acme-512.png"))
    assert black.shape[2] == 4


def test_export_refuses_fail(write, tmp_path):
    f = write("t.svg", svg('<text x="10" y="50">Hi</text>'))
    assert main(["export", str(f), "-o", str(tmp_path / "d")]) == 1


@pytest.mark.skipif(shutil.which("fc-match") is None, reason="needs fontconfig")
def test_outline_text(write, tmp_path):
    pytest.importorskip("fontTools")
    f = write("w.svg", svg('<text x="400" y="130" font-family="sans-serif" font-size="100" '
                           'text-anchor="middle" fill="#123">Avo</text>', vb="0 0 800 200"))
    out = tmp_path / "o.svg"
    assert main(["outline", str(f), "-o", str(out)]) == 0
    doc = SvgDoc.load(out)
    assert not doc.counts().get("text") and doc.counts().get("path") == 1
    r = check(doc)
    assert "live-text" not in codes(r)
    assert abs(r.metrics["bbox_offset"][0]) < 0.03  # text-anchor=middle honoured


@pytest.mark.parametrize("flavor", ["woff2", "woff"])
def test_outline_reads_web_fonts(write, tmp_path, flavor):
    """HarfBuzz cannot open WOFF/WOFF2; outline must still find every glyph (regression)."""
    fontTools = pytest.importorskip("fontTools.ttLib")
    pytest.importorskip("brotli") if flavor == "woff2" else None
    src = shutil.which("fc-match") and __import__("subprocess").run(
        ["fc-match", "-f", "%{file}", "DejaVu Sans"], capture_output=True, text=True).stdout.strip()
    if not src or not src.endswith(".ttf"):
        pytest.skip("needs a TrueType system font")
    web = tmp_path / f"font.{flavor}"
    f = fontTools.TTFont(src)
    f.flavor = flavor
    f.save(str(web))
    svg_in = write("t.svg", svg('<text x="20" y="300" font-size="200" fill="#123">vax</text>'))
    from_web, from_ttf = tmp_path / "web.svg", tmp_path / "ttf.svg"
    assert main(["outline", str(svg_in), "-o", str(from_web), "--font", str(web)]) == 0
    assert main(["outline", str(svg_in), "-o", str(from_ttf), "--font", src]) == 0
    # differential: same glyph data in a different container must give the very same outline
    assert from_web.read_text() == from_ttf.read_text()
    assert "live-text" not in codes(check(SvgDoc.load(from_web)))
