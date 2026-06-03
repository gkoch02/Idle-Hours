#!/usr/bin/env python3
"""Generate the committed high-resolution cyanotype "photogram" plate used by
the ``anna_atkins`` render theme.

Anna Atkins's *Photographs of British Algae: Cyanotype Impressions* (1843) was
the first book illustrated with photographic images: each plate is a contact
photogram of a pressed alga laid on cyanotype paper — a ghostly white silhouette
on a deep Prussian-blue ground, captioned in her own white handwriting.

The Idle Hours appliance ships a **continuous-tone** rendering of such a plate
(an original work in the cyanotype idiom — the historical scans live behind
museum image hosts that the build environment cannot reach, and the point of the
committed asset is to exercise the render-time *dithering* path, which needs real
tonal content rather than flat fills). ``render_quote.dither_image_to_palette``
Floyd–Steinberg-dithers this PNG down to the six Spectra-6 inks at render time,
so the deep blues break into blue/black stipple, the feathered specimen edges
melt into a blue+white "sky-blue" haze, and the bright cores stay white — the
authentic cyanotype look reproduced on a 6-ink eInk panel.

Run ``python3 scripts/generate_anna_atkins_plate.py`` to (re)produce
``idle_hours/assets/anna_atkins_cyanotype.png``. Deterministic (seeded), so a
re-run is byte-stable.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "idle_hours" / "assets" / "anna_atkins_cyanotype.png"
W, H = 800, 480
SS = 2  # supersample factor; work at 1600x960 then downscale for smooth tone.
SEED = 0x1843  # Atkins's publication year — deterministic re-renders.


def _prussian_ground(w: int, h: int, rng: random.Random) -> Image.Image:
    """Deep Prussian-blue ground with a soft edge vignette and low-frequency
    exposure mottle, built as continuous-tone RGB so the dither has gradients
    to work with."""
    base = (22, 52, 112)      # mid Prussian blue
    edge = (7, 22, 58)        # darker toward the plate edges (exposure falloff)
    img = Image.new("RGB", (w, h))
    px = img.load()
    cx, cy = w / 2, h / 2
    maxd = math.hypot(cx, cy)
    # Low-frequency mottle: sum a few broad sinusoids with random phase so the
    # wash reads as unevenly-coated sensitised paper rather than a flat fill.
    waves = [(rng.uniform(0.6, 1.8) / w, rng.uniform(0.6, 1.8) / h,
              rng.uniform(0, math.tau), rng.uniform(6, 16)) for _ in range(4)]
    for y in range(h):
        for x in range(w):
            d = math.hypot(x - cx, y - cy) / maxd          # 0 centre .. 1 corner
            v = d ** 1.4
            mott = 0.0
            for fx, fy, ph, amp in waves:
                mott += amp * math.sin(x * fx * math.tau + ph) * math.sin(y * fy * math.tau + ph)
            r = int(base[0] * (1 - v) + edge[0] * v + mott * 0.4)
            g = int(base[1] * (1 - v) + edge[1] * v + mott * 0.6)
            b = int(base[2] * (1 - v) + edge[2] * v + mott)
            px[x, y] = (max(0, min(60, r)), max(0, min(90, g)), max(0, min(170, b)))
    return img


def _frond(draw: ImageDraw.ImageDraw, rng: random.Random, ox: float, oy: float,
           length: float, angle: float, scale: float, branches: int) -> None:
    """Paint one feathery alga onto an L-mode intensity layer (white=specimen).

    A curved main stipe with many tapering, gently-curling filaments — the
    silhouette of a delicate red/brown seaweed such as *Ptilota* or
    *Cystoseira*. Tone is built by overlapping soft dabs; the caller blurs the
    whole layer afterwards for the photogram edge."""
    # Sample the main stipe as a slowly-curving path.
    pts = []
    x, y, a = ox, oy, angle
    steps = int(length)
    for i in range(steps):
        a += rng.uniform(-0.02, 0.02)
        x += math.cos(a)
        y += math.sin(a)
        pts.append((x, y, i / steps))
    # Stipe itself (thicker at the base, tapering up).
    for (px, py, t) in pts:
        r = max(1.0, (1 - t) * 4.0 * scale + 1.0)
        draw.ellipse((px - r, py - r, px + r, py + r), fill=int(190 - 40 * t))
    # Filaments branching off both sides.
    for _ in range(branches):
        bi = rng.randint(2, max(3, steps - 2))
        bx, by, t = pts[bi]
        side = rng.choice((-1, 1))
        ba = angle + side * rng.uniform(0.5, 1.2)
        blen = (1 - t) * length * rng.uniform(0.25, 0.6) + 6
        curl = rng.uniform(-0.06, 0.06)
        fx, fy, fa = bx, by, ba
        n = int(blen)
        for j in range(n):
            fa += curl + rng.uniform(-0.03, 0.03)
            fx += math.cos(fa)
            fy += math.sin(fa)
            rr = max(0.6, (1 - j / max(1, n)) * 2.4 * scale)
            val = int(210 - 70 * (j / max(1, n)))
            draw.ellipse((fx - rr, fy - rr, fx + rr, fy + rr), fill=val)


def main() -> int:
    rng = random.Random(SEED)
    w, h = W * SS, H * SS
    ground = _prussian_ground(w, h, rng)

    spec = Image.new("L", (w, h), 0)
    sdraw = ImageDraw.Draw(spec)

    # A large hero frond sweeping up the left margin, a broad specimen arcing
    # across the bottom, and a small sprig top-right — composed so the centred
    # quote panel leaves all three visible around its edges.
    _frond(sdraw, rng, ox=150 * SS, oy=430 * SS, length=300 * SS, angle=-math.pi / 2.1, scale=1.4, branches=46)
    _frond(sdraw, rng, ox=120 * SS, oy=360 * SS, length=170 * SS, angle=-1.15, scale=1.0, branches=24)
    _frond(sdraw, rng, ox=560 * SS, oy=470 * SS, length=240 * SS, angle=-1.4, scale=1.2, branches=34)
    _frond(sdraw, rng, ox=690 * SS, oy=70 * SS, length=120 * SS, angle=1.7, scale=0.9, branches=18)

    # Feather the specimen for the soft contact-print edge, then keep a sharper
    # core on top so the filaments don't dissolve entirely.
    soft = spec.filter(ImageFilter.GaussianBlur(radius=4 * SS))
    core = spec.filter(ImageFilter.GaussianBlur(radius=1.2 * SS))
    spec = Image.eval(Image.blend(soft, core, 0.55), lambda v: min(255, int(v * 1.25)))

    # Composite: lift the ground toward white by the specimen intensity.
    out = ground.copy()
    op = out.load()
    sp = spec.load()
    for y in range(h):
        for x in range(w):
            a = sp[x, y] / 255.0
            if a <= 0.01:
                continue
            r, g, b = op[x, y]
            op[x, y] = (
                int(r + (255 - r) * a),
                int(g + (255 - g) * a),
                int(b + (255 - b) * a),
            )

    out = out.resize((W, H), Image.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT, optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
