#!/usr/bin/env python3
"""Generate the committed continuous-tone weathered-metal plate used by the
``grimdark`` render theme.

Grimdark's bulkhead used to be synthesised at render time by stippling sparse
white into the black ground (``render_quote._grimdark_paint_mottle``) — a cheap
K+W charcoal that reads as flat halftone up close. This script bakes a real
**continuous-tone** gunmetal sheet instead: a dark charcoal base with an edge
vignette, low-frequency exposure mottle, seeded oxidation blotches (lighter
scuffs + darker grime), and a few faint diagonal scratches.
``render_quote.dither_image_to_palette`` Floyd–Steinberg-dithers this PNG down
to white+black at render time, so the bulkhead breaks into an organic
white-on-black stipple whose local density tracks the metal's tone — scuffed
plate brightens, grime and shadow deepen toward void — far closer to real
weathered armour plate than the uniform ordered stipple it replaces. The
synthesised stipple stays in ``_grimdark_paint_mottle`` as a graceful fallback
when the asset is missing.

The mean luminance is kept deliberately low so the white-dither density reads as
dark gunmetal, not silver — only scuffs and the brightest mottle peaks lift far
from the void.

Run ``python3 scripts/generate_grimdark_plate.py`` to (re)produce
``idle_hours/assets/grimdark_gunmetal.png``. Deterministic (seeded), so a re-run
is byte-stable.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "idle_hours" / "assets" / "grimdark_gunmetal.png"
W, H = 800, 480
SS = 2  # supersample factor; work at 1600x960 then downscale for smooth tone.
SEED = 0x28E7  # deterministic re-renders.


def _gunmetal_ground(w: int, h: int, rng: random.Random) -> Image.Image:
    """Dark charcoal ground with an edge vignette and low-frequency exposure
    mottle, built as continuous-tone greyscale (R=G=B) so the dither has smooth
    gradients to break into a white/black stipple."""
    base = 58       # mid-charcoal at the centre
    edge = 26       # darker toward the plate edges (a vignetted bulkhead)
    img = Image.new("L", (w, h))
    px = img.load()
    cx, cy = w / 2, h / 2
    maxd = math.hypot(cx, cy)
    # A few broad sinusoids with random phase so the sheet reads as unevenly
    # lit rolled steel rather than a flat fill.
    waves = [(rng.uniform(0.5, 1.6) / w, rng.uniform(0.5, 1.6) / h,
              rng.uniform(0, math.tau), rng.uniform(6, 14)) for _ in range(4)]
    for y in range(h):
        for x in range(w):
            d = math.hypot(x - cx, y - cy) / maxd          # 0 centre .. 1 corner
            v = d ** 1.3
            mott = 0.0
            for fx, fy, ph, amp in waves:
                mott += amp * math.sin(x * fx * math.tau + ph) * math.sin(y * fy * math.tau + ph)
            tone = base * (1 - v) + edge * v + mott * 0.5
            px[x, y] = max(0, min(120, int(tone)))
    return img


def _blotches(img: Image.Image, rng: random.Random) -> None:
    """Seeded oxidation / weathering patches: soft radial discs that either
    lighten (scuffed, exposed metal) or darken (grime, shadow). Drawn onto the
    greyscale ground with additive/subtractive blending so they read as patina
    rather than hard spots."""
    w, h = img.size
    px = img.load()
    n = max(10, (w * h) // (9000 * SS * SS) * SS * SS)
    for _ in range(n):
        bx = rng.randint(0, w - 1)
        by = rng.randint(0, h - 1)
        br = rng.randint(40 * SS // 2, 130 * SS // 2)
        # ~1/3 darken (grime), the rest lighten (scuff). Scuffs are stronger so
        # the eye reads bright metal where the plate has been rubbed.
        darken = rng.random() < 0.34
        peak = rng.uniform(14, 30) if not darken else rng.uniform(10, 22)
        br2 = br * br
        x0, x1 = max(0, bx - br), min(w - 1, bx + br)
        y0, y1 = max(0, by - br), min(h - 1, by + br)
        for y in range(y0, y1 + 1):
            dy = y - by
            for x in range(x0, x1 + 1):
                dx = x - bx
                d2 = dx * dx + dy * dy
                if d2 > br2:
                    continue
                falloff = 1.0 - (d2 ** 0.5) / br
                delta = peak * falloff * falloff
                v = px[x, y]
                px[x, y] = max(0, min(150, int(v - delta if darken else v + delta)))


def _scratches(img: Image.Image, rng: random.Random) -> None:
    """A handful of faint long diagonal scratches — the bright hairlines a
    worked metal surface accumulates. Drawn onto a separate layer and blurred so
    they read as soft gleams rather than crisp pen lines, then screened in."""
    w, h = img.size
    layer = Image.new("L", (w, h), 0)
    ld = ImageDraw.Draw(layer)
    for _ in range(rng.randint(6, 10)):
        x0 = rng.randint(0, w - 1)
        y0 = rng.randint(0, h - 1)
        angle = rng.uniform(-0.6, 0.6) + rng.choice((0.0, math.pi / 2))
        length = rng.randint(120 * SS // 2, 360 * SS // 2)
        x1 = x0 + int(math.cos(angle) * length)
        y1 = y0 + int(math.sin(angle) * length)
        ld.line((x0, y0, x1, y1), fill=rng.randint(40, 80), width=max(1, SS // 2))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=1.4 * SS))
    base = img.load()
    sp = layer.load()
    for y in range(h):
        for x in range(w):
            s = sp[x, y]
            if s:
                base[x, y] = min(150, base[x, y] + s // 2)


def main() -> int:
    rng = random.Random(SEED)
    w, h = W * SS, H * SS
    img = _gunmetal_ground(w, h, rng)
    _blotches(img, rng)
    _scratches(img, rng)
    out = img.convert("RGB").resize((W, H), Image.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT, optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
