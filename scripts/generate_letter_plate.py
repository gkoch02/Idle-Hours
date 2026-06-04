#!/usr/bin/env python3
"""Generate the committed continuous-tone aged-paper plate used by the
``letter`` render theme.

The ``letter`` theme presents a quote as intimate antique correspondence on a
foxed cream sheet. Its aged-paper Layer 0 used to be synthesised at render time
from a sine-table cream wash + edge vignette + R+G foxing stipple
(``render_quote._letter_paint_aged_paper``). This script bakes a real
**continuous-tone** sheet instead: a warm cream base, an edge-weighted tan
vignette, a low-frequency fibrous mottle, and seeded reddish-brown foxing blobs.
``render_quote.dither_image_to_palette`` Floyd–Steinberg-dithers this PNG to
white/yellow/red/green at render time — the cream body breaks into a W+Y
stipple, and the browned foxing regions naturally mix R+G into the documented
sepia recipe — giving the photographic tonal depth of real aged rag paper that
the flat stipple can only approximate. The synthesised texture stays in
``_letter_paint_aged_paper`` as a graceful fallback when the asset is missing.

Foxing is kept localised and warm (reddish-brown blobs) so that error diffusion
mixes red+green only where the paper has actually browned; the clean cream
regions stay W+Y and green never bleeds into them. The crumple creases and the
wax seal are painted by the theme as primitives on top, so they are
deliberately NOT baked into the plate.

Run ``python3 scripts/generate_letter_plate.py`` to (re)produce
``idle_hours/assets/letter_aged_paper.png``. Deterministic (seeded), so a re-run
is byte-stable.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "idle_hours" / "assets" / "letter_aged_paper.png"
W, H = 800, 480
SS = 2  # supersample factor; work at 1600x960 then downscale for smooth tone.
SEED = 0xF0E6  # cream base colour as a mnemonic; deterministic re-renders.


def _paper_ground(w: int, h: int, rng: random.Random) -> Image.Image:
    """Warm cream ground with an edge-weighted tan vignette and a low-frequency
    fibrous mottle, built as continuous-tone RGB so the dither has gradients to
    break into a white↔cream↔tan stipple."""
    centre = (244, 236, 210)   # bright warm cream at the middle of the sheet
    edge = (214, 196, 150)     # deeper tan toward the margins (where paper ages)
    img = Image.new("RGB", (w, h))
    px = img.load()
    cx, cy = w / 2, h / 2
    maxd = math.hypot(cx, cy)
    waves = [(rng.uniform(0.5, 1.7) / w, rng.uniform(0.5, 1.7) / h,
              rng.uniform(0, math.tau), rng.uniform(4, 10)) for _ in range(4)]
    for y in range(h):
        for x in range(w):
            d = math.hypot(x - cx, y - cy) / maxd          # 0 centre .. 1 corner
            v = d ** 1.5
            mott = 0.0
            for fx, fy, ph, amp in waves:
                mott += amp * math.sin(x * fx * math.tau + ph) * math.sin(y * fy * math.tau + ph)
            r = centre[0] * (1 - v) + edge[0] * v + mott * 0.8
            g = centre[1] * (1 - v) + edge[1] * v + mott * 0.7
            b = centre[2] * (1 - v) + edge[2] * v + mott * 0.5
            px[x, y] = (max(150, min(255, int(r))),
                        max(140, min(255, int(g))),
                        max(110, min(255, int(b))))
    return img


def _foxing(img: Image.Image, rng: random.Random) -> None:
    """Seeded reddish-brown foxing blobs — the rust-coloured age spots old rag
    paper develops as iron impurities oxidise. Each is a soft radial stain that
    darkens and warms the paper toward sepia; drawn onto a separate layer,
    blurred, and multiplied in so the spots read as stains soaked into the fibre
    rather than painted-on dots. Biased toward the edges where foxing
    concentrates."""
    w, h = img.size
    stain = Image.new("L", (w, h), 0)
    sd = ImageDraw.Draw(stain)
    n = rng.randint(60, 90)
    for _ in range(n):
        fx = int(rng.triangular(0, w - 1, rng.choice((0, w - 1))))
        fy = int(rng.triangular(0, h - 1, rng.choice((0, h - 1))))
        fr = rng.randint(3 * SS, 14 * SS)
        strength = rng.randint(40, 120)
        sd.ellipse((fx - fr, fy - fr, fx + fr, fy + fr), fill=strength)
    stain = stain.filter(ImageFilter.GaussianBlur(radius=2.5 * SS))
    px = img.load()
    sp = stain.load()
    # Sepia direction: pull green and (more) blue down, leave red high → warm
    # rust-brown. Scaled by the stain mask so clean paper is untouched.
    for y in range(h):
        for x in range(w):
            s = sp[x, y]
            if not s:
                continue
            a = min(1.0, s / 160.0)
            r, g, b = px[x, y]
            px[x, y] = (
                max(120, int(r - 35 * a)),
                max(90, int(g - 70 * a)),
                max(60, int(b - 95 * a)),
            )


def main() -> int:
    rng = random.Random(SEED)
    w, h = W * SS, H * SS
    img = _paper_ground(w, h, rng)
    _foxing(img, rng)
    out = img.resize((W, H), Image.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT, optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
