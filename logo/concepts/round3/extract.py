"""Bake the chosen glyph outlines and skeletons into glyphs.json (so builds don't need the fonts).

Fonts (all SIL Open Font License, fetched with `npm pack @fontsource/<name>`):
  Kaushan Script (Pablo Impallari), Instrument Serif (Instrument), Dancing Script (Pablo Impallari).
Usage: python logo/concepts/round3/extract.py <dir with unpacked @fontsource packages>
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from glyph_skeleton import glyph_skeleton  # noqa: E402

GLYPHS = {
    "kaushan-V": ("fontsource-kaushan-script-5.3.0/package/files/kaushan-script-latin-400-normal.woff2", "V", 15),
    "instrument-v": ("fontsource-instrument-serif-5.3.0/package/files/instrument-serif-latin-400-italic.woff2", "v", 15),
    "dancing-V": ("fontsource-dancing-script-5.3.0/package/files/dancing-script-latin-700-normal.woff2", "V", 15),
}

if __name__ == "__main__":
    root = Path(sys.argv[1])
    out = {}
    for key, (rel, ch, err) in GLYPHS.items():
        sk = glyph_skeleton(str(root / rel), ch, (0, 0, 1000, 1000), max_err=err)
        out[key] = {"source": rel.split("/")[0], "char": ch, "max_err": err, "d": sk.d,
                    "nodes": sk.nodes, "handles": sk.handles, "box": sk.box}
        print(key, len(sk.nodes), "nodes", len(sk.handles), "handles")
    (Path(__file__).parent / "glyphs.json").write_text(json.dumps(out, indent=1))
