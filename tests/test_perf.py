"""Budget tests (EffiBench lesson: correct-but-slow is a bug too).

Worst cases for each cost driver: tonal gradients (palette), 4:1 lockups (pixel budget), hundreds of
shapes (render), extreme aspect (no upsampling), deep-but-legal nesting, very long paths (inventory).
Measured on the reference container: 0.01–0.27 s and ≤ 15 MB per check; budgets leave CI headroom.
"""

import random
import time
import tracemalloc

import pytest

from varness.report import check
from varness.sheet import single_sheet
from varness.svgdoc import MAX_DEPTH, SvgDoc

BUDGET = {"seconds": 1.5, "peak_mb": 64.0}


def _svg(vb: str, body: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">{body}</svg>'


def _cases() -> dict[str, str]:
    rnd = random.Random(1)
    stops = "".join(f'<stop offset="{i / 20:.2f}" stop-color="#{(i * 12) % 256:02x}{(255 - i * 9) % 256:02x}'
                    f'{(i * 37) % 256:02x}"/>' for i in range(21))
    tonal = "".join(f'<circle cx="{80 + i * 95}" cy="256" r="{40 + (i % 5) * 20}" fill="url(#g)"/>' for i in range(20))
    busy = "".join(f'<rect x="{rnd.randint(0, 500)}" y="{rnd.randint(0, 500)}" width="{rnd.randint(1, 12)}" '
                   f'height="{rnd.randint(1, 12)}" fill="#{rnd.randint(0, 0xFFFFFF):06x}"/>' for _ in range(400))
    long_path = "M10 10" + "".join(f"L{rnd.randint(0, 512)} {rnd.randint(0, 512)}" for _ in range(5000)) + "Z"
    depth = MAX_DEPTH - 2
    return {
        "wide_tonal": _svg("0 0 2048 512", f'<defs><radialGradient id="g">{stops}</radialGradient></defs>{tonal}'),
        "busy": _svg("0 0 512 512", busy),
        "extreme_aspect": _svg("0 0 10 1000", '<rect x="2" y="10" width="6" height="980" fill="#123"/>'),
        "deep_nesting": _svg("0 0 512 512", "<g>" * depth + '<circle cx="256" cy="256" r="200"/>' + "</g>" * depth),
        "long_path": _svg("0 0 512 512", f'<path d="{long_path}" fill="#111" fill-rule="evenodd"/>'),
        # 300 chained <use>: segfaulted resvg on the default 8 MB main-thread stack
        "use_chain": _svg("0 0 512 512", '<defs><circle id="u0" cx="256" cy="256" r="200"/>'
                          + "".join(f'<use id="u{i}" href="#u{i - 1}"/>' for i in range(1, 300))
                          + '</defs><use href="#u299"/>'),
    }


@pytest.fixture(scope="module", autouse=True)
def warm_up():
    check(SvgDoc.from_string(_svg("0 0 10 10", '<rect width="5" height="5"/>')))


@pytest.mark.parametrize("name", list(_cases()))
def test_check_and_sheet_within_budget(name):
    doc = SvgDoc.from_string(_cases()[name])
    tracemalloc.start()
    try:
        t0 = time.perf_counter()
        report = check(doc)
        single_sheet(report)
        seconds = time.perf_counter() - t0
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    peak_mb = peak / 2**20
    assert seconds <= BUDGET["seconds"], f"{name}: {seconds:.2f}s > {BUDGET['seconds']}s"
    assert peak_mb <= BUDGET["peak_mb"], f"{name}: {peak_mb:.1f}MB > {BUDGET['peak_mb']}MB"


def test_stack_hungry_inputs_are_flagged_not_fatal():
    deep = check(SvgDoc.from_string(_cases()["use_chain"]))
    assert "use-chain" in {f.code for f in deep.findings} and deep.status == "FAIL"
    cyc = check(SvgDoc.from_string(_svg("0 0 10 10", '<g id="a"><use href="#a"/></g>')))
    assert "use-cycle" in {f.code for f in cyc.findings}


def test_render_cache_is_per_document():
    """No process-wide cache: renders die with their document."""
    doc = SvgDoc.from_string(_cases()["busy"])
    check(doc)
    assert doc.render_cache
    other = SvgDoc.from_string(_cases()["busy"])
    assert not other.render_cache
