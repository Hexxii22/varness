# Logo craft for SVG authors

Short, practical notes for writing logo geometry by hand. Read the section you need.

## What makes a mark work

- **One idea.** A mark communicates one thing. If you need a paragraph to explain it, simplify.
- **Distinctive silhouette.** Fill it solid black: is it still recognisable and different from the obvious
  competitor marks? The sheet's mono row is this test.
- **Scales down.** It must read at 16–32px. Detail that only appears at 512px is decoration, not design.
- **Works in one colour.** Colour supports the form; it must never be the only thing separating parts.
- **Appropriate.** Tone matches the brief (a bank and a kids' game want different geometry and weight).

## Construction

- Canvas `0 0 512 512`; 64-unit cells; place key points on multiples of 16 (8 if you must).
- Circles: `M cx-r cy a r r 0 1 0 2r 0 a r r 0 1 0 -2r 0 Z` (two half arcs); use the same `r` family across
  the mark (e.g. 32 / 64 / 128) for coherence.
- Rounded rectangle path: `M x+r y H x+w-r A r r 0 0 1 x+w y+r V y+h-r A r r 0 0 1 x+w-r y+h H x+r
  A r r 0 0 1 x y+h-r V y+r A r r 0 0 1 x+r y Z`.
- Holes: put inner sub-paths in the same `<path>` with `fill-rule="evenodd"` (or wind them opposite).
- Point on a circle at angle θ (degrees, clockwise from 3 o'clock in SVG): `(cx + r·cos θ, cy + r·sin θ)`.
- Repeated parts: draw one, then `<use href="#petal" transform="rotate(72 256 256)"/>` — or write each
  rotated copy as its own path if the file must avoid `<use>`.
- Diagonal strokes of constant thickness t between two points: offset both ends by the normal
  `n = (dy, -dx)/len · t/2`; compute, don't eyeball.
- Keep stroke weights consistent: pick one or two weights (e.g. 48 and 24) and use them everywhere.

## Optical corrections (what the numbers cannot see)

- Round and pointed shapes look smaller than squares of the same height: let circles overshoot the
  baseline/cap line by ~2–3% and points by ~4–6%.
- Horizontal strokes look heavier than vertical ones of the same width: make horizontals ~5–10% thinner.
- Geometric centre ≠ visual centre: triangles and play-buttons need a nudge toward their heavy side;
  stacked shapes look better slightly above true centre.
- Where two curves meet a straight, make the transition tangent; visible kinks read as mistakes at large sizes.
- Inner corners fill in at small sizes: add ink traps (small notches) or widen the gap where strokes meet.

## Colour

- Start in black. Add colour only after the mono version works.
- 1 primary + at most 1–2 accents. Check lightness, not just hue: the sheet's greyscale tile must keep
  the structure (`similar-lightness` warns when it doesn't).
- Main colour ≥ 3:1 contrast on its intended background. Dark marks need a reversed (white) version on dark
  UIs — `varness export` writes it.
- Avoid pure `#000`/`#fff` as brand colours unless intended; near-black navy/charcoal reads richer.
- Gradients: only as an optional treatment over a mark that already works flat.

## Type (wordmarks)

- Choose from installed fonts (`fc-list : family`), or the user's brand font file. Match personality:
  geometric sans (Inter, Poppins, Montserrat) = modern/tech; humanist sans = friendly; serif = heritage/editorial;
  slab = sturdy; mono = developer.
- Outline with `varness outline`, then refine: tighten spacing for display sizes (`letter-spacing` −1…−3% of
  font size), check awkward pairs (AV, To, LT), consider custom touches on one letter only.
- Lockup: the symbol's height usually matches cap height or x-height + ascender; gap between symbol and
  wordmark ≈ the width of one stem to one letter.

## Clichés to avoid unless the brief demands them

Swooshes and orbit rings, generic globes, lightbulbs for "ideas", gears for "engineering", chat bubbles for
"communication", shields for "security", leaves for "eco", abstract connected dots for "network/AI",
sparkles for "AI", random gradient blobs, a plain initial in a circle with no twist, mountain + sun.
If the first idea is one of these, treat it as a starting point and find the twist.

## Critique checklist (use on the sheet)

1. Squint / 16px tile: is the silhouette still clear and unique?
2. Mono row: does anything disappear or merge?
3. Dark row: does it need the reversed variant? Is the accent still visible?
4. Overlay: red (thin), blue (closing gaps), orange (colour-only edges) — any left?
5. Balance: does it sit centred and stable, or tip/float?
6. Consistency: one stroke-weight family, one radius family, angles from a small set (0/30/45/60/90).
7. Brief: does it say the one thing it should say, for this audience?
