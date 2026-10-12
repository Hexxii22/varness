"""Command-line interface: `varness <command> ...` (see `varness -h`)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, history, render
from .report import Report, check, format_text
from .svgdoc import SvgDoc, SvgError, hex_to_rgb, normalize_color


def _reports(files: list[str], bg: str | None) -> list[Report]:
    return [check(f, bg=bg) for f in files]


def cmd_check(a) -> int:
    if a.sheet and len(a.files) > 1:
        print("--sheet works with one file; use `varness compare` for several", file=sys.stderr)
        return 2
    reports = _reports(a.files, a.bg)
    payload = []
    for path, r in zip(a.files, reports):
        item = r.to_dict()
        if a.track and r.doc is not None:
            entry = history.record(a.track, path, r, a.note or "", a.history_dir)
            item["history"] = {k: entry[k] for k in ("version", "score")} | {"best": entry["best"]["version"]}
            hist_line = history.describe(entry)
        else:
            hist_line = None
        if a.sheet and r.doc is not None and r.analysis is not None:
            from .sheet import single_sheet

            single_sheet(r, bg=a.bg).save(a.sheet)
            item["sheet"] = a.sheet
        payload.append(item)
        if not a.json:
            print(format_text(r, verbose=a.verbose))
            if hist_line:
                print(hist_line)
            if item.get("sheet"):
                print(f"sheet: {a.sheet}  ← look at it before the next edit")
            print()
    if a.json:
        print(json.dumps(payload if len(payload) > 1 else payload[0], indent=2))
    if a.strict and not all(r.ship_ready for r in reports):
        return 1
    return 0


def cmd_sheet(a) -> int:
    from .sheet import single_sheet

    r = check(a.file, bg=a.bg)
    if r.doc is None or r.analysis is None:
        print(format_text(r), file=sys.stderr)
        return 1
    single_sheet(r, bg=a.bg).save(a.out)
    print(f"{a.out}  ({r.file}: {r.score}/100 {r.status})")
    return 0


def cmd_compare(a) -> int:
    from . import metrics as M
    from .sheet import compare_sheet

    reports = _reports(a.files, a.bg)
    sil = {}
    for r in reports:
        if r.doc is not None and r.analysis is not None and not r.metrics.get("blank"):
            sil[r.file] = M.silhouette_mask(r.doc)
    names = list(sil)
    similar = []
    for i, x in enumerate(names):
        for y in names[i + 1:]:
            s = M.similarity(sil[x], sil[y])
            if s >= a.similar:
                similar.append((x, y, s))
    if a.out:
        compare_sheet(reports, similar).save(a.out)
    ranked = sorted(reports, key=lambda r: -r.score)
    if a.json:
        print(json.dumps({
            "ranking": [{"file": r.file, "score": r.score, "status": r.status, "categories": r.categories,
                         "issues": [f.code for f in r.findings if f.level != "INFO"]} for r in ranked],
            "too_similar": [{"a": x, "b": y, "iou": round(s, 3)} for x, y, s in similar],
            "sheet": a.out,
        }, indent=2))
        return 0
    print(f"{'#':<3}{'score':>6}  {'status':<6} {'file':<32} issues")
    for k, r in enumerate(ranked, 1):
        issues = ", ".join(f.code for f in r.findings if f.level != "INFO") or "-"
        print(f"{k:<3}{r.score:>6}  {r.status:<6} {r.file:<32} {issues}")
    for x, y, s in similar:
        print(f"too similar: {x} ≈ {y} (silhouette IoU {s:.2f}) — explore a different idea for one of them")
    if a.out:
        print(f"sheet: {a.out}  ← look at it before choosing")
    return 0


def cmd_export(a) -> int:
    from .export import export

    r = check(a.file, bg=a.bg)
    if r.doc is None or r.analysis is None:
        print(format_text(r), file=sys.stderr)
        return 1
    if r.status == "FAIL" and not a.force:
        print(format_text(r), file=sys.stderr)
        print("\nrefusing to export a FAIL logo (use --force to override)", file=sys.stderr)
        return 1
    res = export(r, a.out, name=a.name, bg=a.bg, app_bg=a.app_bg)
    print(f"exported {len(res['files'])} files to {res['out']} ({r.file}: {r.score}/100 {r.status})")
    for f in res["files"]:
        print(f"  {f}")
    for n in res["notes"]:
        print(f"note: {n}")
    return 0


def cmd_history(a) -> int:
    if a.restore:
        if not a.out:
            print("--restore needs -o FILE", file=sys.stderr)
            return 2
        p = history.restore(a.name, a.restore, a.out, a.history_dir)
        print(f"restored {a.restore} → {p}")
        return 0
    print(history.table(a.name, a.history_dir))
    return 0


def cmd_outline(a) -> int:
    from .outline import OutlineError, outline

    try:
        svg, notes = outline(SvgDoc.load(a.file), a.font)
    except (OutlineError, SvgError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    Path(a.out).write_text(svg, encoding="utf-8")
    for n in notes:
        print(n)
    print(f"wrote {a.out}")
    return 0


def cmd_render(a) -> int:
    from PIL import Image

    doc = SvgDoc.load(a.file)
    img = render.render(doc, a.size)
    if a.bg and (h := normalize_color(a.bg)):
        back = Image.new("RGBA", img.size, hex_to_rgb(h) + (255,))
        back.alpha_composite(img)
        img = back
    img.save(a.out)
    print(f"{a.out} ({img.width}×{img.height}, {render.select()})")
    return 0


def cmd_doctor(a) -> int:
    found = render.available_backends()
    print(f"varness {__version__}")
    print("renderers: " + (", ".join(found) if found else "NONE — pip install resvg-py"))
    if found:
        print(f"selected:  {render.select()}")
    try:
        import fontTools  # noqa: F401

        fonts = "fontTools ok"
        try:
            import uharfbuzz  # noqa: F401

            fonts += " + uharfbuzz (kerning)"
        except ImportError:
            fonts += " (pip install uharfbuzz for full kerning)"
    except ImportError:
        fonts = "missing — `varness outline` needs: pip install 'varness[fonts]'"
    print(f"outlining: {fonts}")
    return 0 if found else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="varness", description="Render-in-the-loop harness for SVG logos.")
    p.add_argument("--version", action="version", version=f"varness {__version__}")
    p.add_argument("--renderer", help="resvg-py | cairosvg | rsvg-convert | resvg | inkscape")
    p.add_argument("--history-dir", default=history.DEFAULT_ROOT, help="where --track stores revisions")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="lint + pixel metrics + score (optionally sheet and history)")
    c.add_argument("files", nargs="+")
    c.add_argument("--json", action="store_true")
    c.add_argument("--sheet", metavar="PNG", help="also write a contact sheet")
    c.add_argument("--track", metavar="NAME", help="record this revision in the history log")
    c.add_argument("--note", help="note stored with the tracked revision")
    c.add_argument("--bg", help="brand background colour to test contrast against")
    c.add_argument("--strict", action="store_true", help="exit 1 unless every file is ship-ready")
    c.add_argument("-v", "--verbose", action="store_true", help="show INFO findings too")
    c.set_defaults(fn=cmd_check)

    s = sub.add_parser("sheet", help="contact sheet PNG: sizes, backgrounds, mono, context, diagnostics")
    s.add_argument("file")
    s.add_argument("-o", "--out", default="sheet.png")
    s.add_argument("--bg")
    s.set_defaults(fn=cmd_sheet)

    cp = sub.add_parser("compare", help="rank candidates side by side and flag near-duplicates")
    cp.add_argument("files", nargs="+")
    cp.add_argument("-o", "--out", default="compare.png")
    cp.add_argument("--json", action="store_true")
    cp.add_argument("--bg")
    cp.add_argument("--similar", type=float, default=0.8, help="silhouette IoU above which two concepts are flagged")
    cp.set_defaults(fn=cmd_compare)

    e = sub.add_parser("export", help="production kit: clean/mono SVG, PNGs, favicon.ico, PWA icons")
    e.add_argument("file")
    e.add_argument("-o", "--out", default="dist")
    e.add_argument("--name", default="logo")
    e.add_argument("--bg", help="brand colour (contrast checks, sheet)")
    e.add_argument("--app-bg", help="tile colour for apple-touch/maskable icons (default: --bg or white)")
    e.add_argument("--force", action="store_true", help="export even if the logo FAILs")
    e.set_defaults(fn=cmd_export)

    h = sub.add_parser("history", help="show or restore tracked revisions")
    h.add_argument("name")
    h.add_argument("--restore", metavar="VER")
    h.add_argument("-o", "--out")
    h.set_defaults(fn=cmd_history)

    o = sub.add_parser("outline", help="convert <text> to paths with a real font")
    o.add_argument("file")
    o.add_argument("-o", "--out", required=True)
    o.add_argument("--font", help="font file (.ttf/.otf); default: fc-match on font-family")
    o.set_defaults(fn=cmd_outline)

    r = sub.add_parser("render", help="render one PNG")
    r.add_argument("file")
    r.add_argument("--size", type=int, default=512, help="longest side in px")
    r.add_argument("-o", "--out", default="render.png")
    r.add_argument("--bg")
    r.set_defaults(fn=cmd_render)

    d = sub.add_parser("doctor", help="show available renderers and optional features")
    d.set_defaults(fn=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.renderer:
            render.select(args.renderer)
        return args.fn(args)
    except render.RenderError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
