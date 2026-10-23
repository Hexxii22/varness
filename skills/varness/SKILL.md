---
name: varness
description: Design, refine, audit and export SVG logos, icons, favicons, app icons, monograms and wordmarks with a render-in-the-loop harness. Use whenever the user asks to create or improve a logo/brand mark/icon as SVG, check whether an SVG logo works at small sizes or in one colour, compare logo concepts, or produce a favicon/app-icon kit from an SVG.
---

# varness — render-in-the-loop logo design

**Core rule: never present an SVG you have not rendered and looked at.** You write SVG blind;
`varness` renders it, measures it in pixels and draws a contact sheet you then *read as an image*.
The numbers catch technical defects. Your eyes judge the idea. Both are required.

## 0. Setup (once)

```bash
varness doctor        # renderers + optional font outlining
```
If the command is missing: `pip install "git+https://github.com/hexxii22/varness"` (or `pip install -e .`
inside a checkout), or run `scripts/varness` next to this file (needs `pip install numpy pillow resvg-py`).
For wordmarks also: `pip install fonttools uharfbuzz`.

## 1. Brief

Ask at most five questions, or infer and *state* your assumptions:
name · what it does · audience · three personality words · constraints (existing colours, things to avoid)
· where it must work (favicon, app icon, print, embroidery, dark UI) · mark type if the user has one in mind.

## 2. Concepts — different ideas, not variations

Write 3–5 SVGs in `logo/concepts/`, each from a **different** direction, e.g.
lettermark/monogram · abstract geometric · pictorial metaphor · negative-space trick · wordmark/combination.
Give each a one-sentence rationale tied to the brief. Follow the authoring rules below.

```bash
varness compare logo/concepts/*.svg -o logo/concepts/compare.png
```
Read `compare.png`. Drop FAILs. If a pair is reported **too similar**, replace one with a genuinely new idea.
Critique each concept in a line: memorable? distinctive in its category? appropriate? survives 1 colour and 16px?

If the user is present: show `compare.png`, the rationales and your recommendation, then stop and ask which
direction to develop. If you work autonomously: pick by brief fit first, score second.

## 3. Refine loop

```bash
varness check logo/logo.svg --track <brand> --note "what changed" --sheet logo/sheet.png
```
1. Read `logo/sheet.png` (light/dark rows, 32px×4 and 16px×8 zooms, mono, context, diagnostics overlay).
2. Fix every FAIL, then every WARN. Each finding carries a concrete fix (units, viewBox, translate).
3. Then fix what numbers miss: optical balance, uneven stroke weights, awkward curves, cramped gaps, tangents.
4. Edit, re-run, re-read. The history line tells you what improved and flags regressions
   (`varness history <brand>`; `--restore vNNN -o file` to go back).

Stop when the report says **ship-ready** *and* the sheet looks right at every size. Cap at ~8 rounds;
if you are stuck, the concept is wrong — go back to step 2 rather than polishing.

## 4. Wordmarks and lockups

You cannot draw good letterforms freehand. Write real type, then outline it:
```bash
fc-list : family | sort -u | head -50          # what is installed
# <text x="..." y="..." font-family="Inter" font-weight="700" font-size="160" text-anchor="middle"
#       letter-spacing="-4" fill="#14213d">brand</text>
varness outline lockup-src.svg -o lockup.svg [--font path/to/Font.ttf]
varness check lockup.svg --sheet lockup-sheet.png
```
Lockups (wide canvases) are judged by **height**: "32px" means 32px tall.
Keep `lockup-src.svg` (with `<text>`) as the editable source; ship the outlined file.

## 5. Export

```bash
varness export logo/logo.svg -o logo/dist --name <brand> [--app-bg "#hex"]
```
Produces cleaned master + black/white SVGs, PNG 16–1024, `favicon.ico` (16/32/48), Apple/PWA/maskable icons,
`site.webmanifest`, `head-snippet.html`, `sheet.png`, `report.json`. It refuses a FAIL logo unless `--force`.
Report the files and show the final sheet.

## SVG authoring rules

- Marks: `viewBox="0 0 512 512"`, integer coordinates, think in an 8×8 grid of 64-unit cells.
  Lockups: keep the height at 512 (e.g. `0 0 1600 512`).
- Use `path`, `rect`, `circle`, `ellipse`, `polygon` with flat `fill`. No `<text>` (outline it), `<image>`,
  filters, masks, scripts, external references. Strokes are fine while exploring; prefer fills for the master.
- 1–3 colours. Design in one colour first; colour is the last layer, never the only thing separating parts.
- Minimum stroke/detail **and** gap: 16 units (1px at 32px). Aim for 24–32 if the mark must work as a favicon.
- Negative space must be real: holes via `fill-rule="evenodd"` sub-paths, not white shapes on top.
- Padding 6–10% of the canvas; centre the bounding box; nudge asymmetric shapes optically.
- Build geometry deliberately: compute arc endpoints (`x = cx + r·cosθ`, `y = cy + r·sinθ`), reuse coordinates,
  mirror halves, rotate repeated parts with `transform="rotate(a 256 256)"`. Round to ≤1 decimal.
- Prefer `varness build spec.json -o logo.svg` (needs `pip install 'varness[build]'`) over hand-written paths for
  rings, arcs, cut-outs, rounded corners and radial repeats: it computes exact curves and real boolean holes.
  Shapes: `circle [cx,cy,r]`, `ring [cx,cy,R,r]`, `arc [cx,cy,R,r,a0,a1]` (0° = 12 o'clock, clockwise, radial ends),
  `rect [x,y,w,h]`, `polygon [[x,y] or {"polar":[r,angle],"about":[x,y]},…]` (polar points: only r snaps), `ngon [cx,cy,R,n]` (+`star`, `rot`); `"r"` rounds polygon corners.
  Ops: `union`/`subtract`/`intersect` lists (`subtract` cuts the rest out of the first). Modifiers on any shape:
  `translate`, `rotate`, `mirror "x"|"y"`, `repeat n`. Set `"snap": 8` to be warned about off-grid values.
  Spec: `{"snap": 8, "layers": [{"fill": "#hex", "shape": {...}}]}`; see `examples/badge/badge.json`.
- Check composition on the sheet with `--grid thirds|golden|keyline|radial:N` (default `8x8`).
- More craft (construction, optical corrections, colour, type, clichés to avoid): `references/craft.md`.

## Findings cheat-sheet

| code | meaning | typical fix |
|---|---|---|
| live-text / raster-image / external-ref / script | not a self-contained vector master | outline text, redraw as paths, inline |
| dangling-ref / no-viewbox / renders-blank | broken file | define ids, add viewBox, check fills/transforms |
| use-cycle / use-chain | recursive or deeply chained `<use>` (renderers recurse per hop) | reference the base shape directly |
| thin-at-64 / thin-at-32 | strokes/details below 1px at that size | thicken to the unit value in the fix |
| gaps-close-at-32 / busy-at-16 | counters and gaps fill in | open gaps, drop detail, make a favicon variant |
| underfilled / touches-edge / off-center | canvas framing | use the suggested viewBox / translate (verified to clear the finding; for clipped art it frames the whole drawing) |
| visual-weight | centre of mass far from centre | optical nudge; judge on the sheet |
| needs-color / white-knockout | mark only works in colour / fake holes | separate parts with gaps; cut real holes |
| similar-lightness / low-contrast-* | colours collapse in greyscale or on a background | change lightness, not just hue |
| complex-paths / many-elements / intricate-outline | too detailed | fewer, bolder shapes |

## What the score is (and is not)

`score` (0–100) is a **technical gate** over five categories: integrity, scalability, composition, colour,
simplicity. It cannot judge originality, meaning or brand fit; a plain letter in a circle can score 99.
Never trade the idea for points. Use `--json` when you need the raw metrics.
