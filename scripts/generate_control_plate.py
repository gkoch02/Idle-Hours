#!/usr/bin/env python3
"""Generate the committed continuous-tone board-formed concrete plate used by
the ``control`` render theme's plinth.

The plinth was first synthesised at render time as a hash-jittered ordered
stipple (``render_quote._control_paint_concrete_stipple``) — the ``bakelite``
moulding recipe, which reads as cast stone at a glance but has no *structure*:
real board-formed concrete carries the grain of the timber shuttering it was
poured against, a slight tonal step between one formwork panel and the next,
horizontal pour lines where one lift met the one below, and a scatter of
aggregate pits and lime specks. This script bakes all of that as a
**continuous-tone** greyscale sheet, and ``render_quote.dither_image_to_palette``
Floyd–Steinberg-dithers it to white+black at render time, so the plinth breaks
into an organic stipple whose local density tracks the concrete's tone — the
same render-time-plate capability ``grimdark``'s gunmetal and ``letter``'s aged
paper use. The stipple stays in ``_control_paint_concrete_stipple`` as the
graceful fallback when the asset is missing.

The mean luminance sits in the light-mid greys (L≈150, about 40% black after
dithering) so the slab reads as a lit concrete wall, darkening toward the
bottom edge as a wall does below eye level; the black wayfinding sign painted
over it needs that band to stay lighter than itself.

Run ``python3 scripts/generate_control_plate.py`` to (re)produce
``idle_hours/assets/control_concrete.png``. Deterministic (seeded), so a re-run
is byte-stable.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "idle_hours" / "assets" / "control_concrete.png"
W, H = 800, 88          # the plinth band: y = 392..480 of the 800x480 panel
SS = 2                  # supersample factor; work at 1600x176 then downscale
SEED = 0xC0B7
PANEL_SEAMS = (200, 400, 600)   # formwork panel joints, matching the frame's seams
POUR_LINES = (0.34, 0.68)       # horizontal lift joints as fractions of the height


def _ground(w: int, h: int, rng: random.Random) -> Image.Image:
    """Lit concrete: a light-mid base, darker toward the foot, with a tonal step
    per formwork panel and low-frequency mottle from uneven curing."""
    base, foot = 166.0, 138.0
    panel_offsets = []
    for _ in range(len(PANEL_SEAMS) + 1):
        panel_offsets.append(rng.uniform(-7, 7))
    waves = [(rng.uniform(1.5, 3.5) / w, rng.uniform(0.8, 2.2) / h, rng.uniform(0, math.tau))
             for _ in range(3)]
    img = Image.new("L", (w, h))
    px = img.load()
    seams = [s * SS for s in PANEL_SEAMS]
    for y in range(h):
        t = y / max(1, h - 1)
        row_base = base + (foot - base) * (t ** 1.4)
        for x in range(w):
            panel = sum(1 for s in seams if x >= s)
            v = row_base + panel_offsets[panel]
            for fx, fy, ph in waves:
                v += 6.0 * math.sin(math.tau * (fx * x + fy * y) + ph)
            # Seam recess: a soft shadow either side of each panel joint.
            for s in seams:
                d = abs(x - s)
                if d < 6 * SS:
                    v -= 18.0 * (1 - d / (6 * SS))
            px[x, y] = max(0, min(255, int(round(v))))
    return img


def _board_grain(img: Image.Image, rng: random.Random) -> None:
    """Horizontal timber grain from the shuttering: fine streaks whose
    brightness wanders along their length, plus the two lift joints."""
    w, h = img.size
    px = img.load()
    for y in range(h):
        amp = rng.uniform(2.0, 7.0)
        freq = rng.uniform(0.004, 0.012)
        phase = rng.uniform(0, math.tau)
        for x in range(w):
            v = px[x, y] + amp * math.sin(math.tau * freq * x + phase) * math.sin(y * 0.9)
            px[x, y] = max(0, min(255, int(round(v))))
    draw = ImageDraw.Draw(img)
    for frac in POUR_LINES:
        yy = int(frac * h)
        # A dark joint with a lighter lip just above it, the way one lift's
        # top edge catches light over the shadow of the next pour.
        draw.line([(0, yy - SS), (w, yy - SS)], fill=min(255, int(px[0, yy] + 14)), width=SS)
        draw.line([(0, yy), (w, yy)], fill=max(0, int(px[0, yy] - 52)), width=SS)


def _aggregate(img: Image.Image, rng: random.Random) -> None:
    """Pits where aggregate sat at the face, and pale lime specks."""
    w, h = img.size
    draw = ImageDraw.Draw(img)
    for _ in range(190):
        r = rng.uniform(0.6, 2.2) * SS
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        dark = max(0, int(rng.uniform(55, 95)))
        draw.ellipse((x - r, y - r, x + r, y + r), fill=dark)
    for _ in range(110):
        r = rng.uniform(0.4, 1.3) * SS
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=min(255, int(rng.uniform(190, 220))))


def main() -> int:
    rng = random.Random(SEED)
    w, h = W * SS, H * SS
    img = _ground(w, h, rng)
    _board_grain(img, rng)
    _aggregate(img, rng)
    img = img.filter(ImageFilter.GaussianBlur(0.6 * SS))
    out = img.convert("RGB").resize((W, H), Image.Resampling.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT, optimize=True)
    print(f"wrote {OUT} ({W}x{H})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
