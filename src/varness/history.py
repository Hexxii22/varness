"""Version log for the refine loop: every checked revision is kept with its report."""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from .report import Report

DEFAULT_ROOT = ".varness/history"


def _dir(name: str, root: str | Path = DEFAULT_ROOT) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "logo"
    return Path(root) / safe


def _best(index: list[dict]) -> dict:
    """Highest score; ties go to the newer revision (position, not the version string)."""
    return max(enumerate(index), key=lambda p: (p[1]["score"], p[0]))[1]


def load_index(name: str, root: str | Path = DEFAULT_ROOT) -> list[dict]:
    p = _dir(name, root) / "index.json"
    return json.loads(p.read_text()) if p.exists() else []


def record(name: str, svg_path: str | Path, report: Report, note: str = "", root: str | Path = DEFAULT_ROOT) -> dict:
    """Store this revision (skips if identical to the last one). Returns the entry plus deltas."""
    d = _dir(name, root)
    d.mkdir(parents=True, exist_ok=True)
    index = load_index(name, root)
    prev = index[-1] if index else None
    if prev and prev["sha"] == report.sha:
        entry = dict(prev, duplicate=True)
    else:
        version = f"v{len(index) + 1:03d}"
        shutil.copyfile(svg_path, d / f"{version}.svg")
        (d / f"{version}.json").write_text(json.dumps(report.to_dict(), indent=2))
        entry = {
            "version": version, "sha": report.sha, "score": report.score, "status": report.status,
            "categories": report.categories, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "issues": [f.code for f in report.findings if f.level != "INFO"], "note": note,
        }
        index.append(entry)
        (d / "index.json").write_text(json.dumps(index, indent=2))
    entry = dict(entry)
    entry["prev"] = prev
    entry["best"] = _best(index)
    return entry


def describe(entry: dict) -> str:
    v, s = entry["version"], entry["score"]
    if entry.get("duplicate"):
        return f"history: unchanged since {v} ({s}/100)"
    parts = [f"history: {v} = {s}/100"]
    prev = entry["prev"]
    if prev:
        parts.append(f"{s - prev['score']:+d} vs {prev['version']}")
        fixed = sorted(set(prev["issues"]) - set(entry["issues"]))
        new = sorted(set(entry["issues"]) - set(prev["issues"]))
        if fixed:
            parts.append("fixed: " + ", ".join(fixed))
        if new:
            parts.append("NEW: " + ", ".join(new))
    best = entry["best"]
    if best["score"] > s:
        parts.append(f"best is {best['version']} ({best['score']}) — regression; restore with "
                     f"`varness history <name> --restore {best['version']} -o <file>`")
    return " · ".join(parts)


def table(name: str, root: str | Path = DEFAULT_ROOT) -> str:
    index = load_index(name, root)
    if not index:
        return f"no history for {name!r} (run `varness check file.svg --track {name}`)"
    best = _best(index)["version"]
    lines = [f"{'ver':<6}{'score':>6}  {'status':<6} {'time':<20} issues"]
    for e in index:
        mark = " *" if e["version"] == best else ""
        lines.append(f"{e['version']:<6}{e['score']:>6}  {e['status']:<6} {e['time']:<20} "
                     f"{', '.join(e['issues']) or '-'}{mark}" + (f"   # {e['note']}" if e.get("note") else ""))
    lines.append(f"(* best) files in {_dir(name, root)}")
    return "\n".join(lines)


def restore(name: str, version: str, dest: str | Path, root: str | Path = DEFAULT_ROOT) -> Path:
    src = _dir(name, root) / f"{version}.svg"
    if not src.exists():
        raise FileNotFoundError(f"{src} does not exist")
    shutil.copyfile(src, dest)
    return Path(dest)
