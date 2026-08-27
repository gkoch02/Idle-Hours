#!/usr/bin/env python3
"""One-time art generator for ``idle_hours/assets/daguerreotype_plate.png`` —
the continuous-tone monochrome landscape the ``daguerreotype`` theme dithers
to the white/black sub-palette at render time (with Atkinson error diffusion,
the method the theme exists to introduce).

The plate is an *original work in the daguerreotype idiom* rather than a scan,
for the same reasons ``generate_anna_atkins_plate.py`` documents: the point of
the asset is to exercise the render-time dithering path, which needs real
continuous-tone content — swap a genuine scan in at the same path and it
dithers identically. The subject is a still river landscape (a valley lake
under a bright sky, wooded banks, one great tree), because a procedural
portrait reads crude where a procedural landscape reads pastoral — the
anna_atkins precedent again.

What is deliberately NOT baked in: the oval mat crop, the edge vignette and
the R+G tarnish ring all stay render-time (`render_daguerreotype_frame`), so
the committed plate remains a clean rectangular photograph and the case
furniture can be tuned without regenerating art.

Deterministic: a fixed SEED drives every random element, so re-runs are
byte-stable.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "idle_hours" / "assets" / "daguerreotype_plate.png"
W, H = 560, 480
SS = 2  # supersample factor; smooth tone survives the downscale
SEED = 1851  # the daguerreotype's great decade

HORIZON = 0.52  # sky/far-ridge boundary, fraction of height
LAKE_TOP = 0.60
LAKE_BOTTOM = 0.80


def _ridge(rng: random.Random, width: int, base: float, roughness: float) -> list[float]:
    """A gently rolling ridge line: summed low-frequency sines + jitter."""
    phases = [rng.uniform(0, 2 * math.pi) for _ in range(3)]
    amps = [roughness * f for f in (1.0, 0.55, 0.3)]
    waves = [width / d for d in (2.3, 4.7, 9.1)]
    return [
        base + sum(a * math.sin(x / wl + p) for a, wl, p in zip(amps, waves, phases))
        for x in range(width)
    ]


def _tree(draw: ImageDraw.ImageDraw, rng: random.Random, x: float, y: float,
          angle: float, length: float, width: int, tone: int) -> None:
    """A recursive winter tree: trunk forking into thinning branches."""
    if length < 8 or width < 1:
        return
    ex = x + math.cos(angle) * length
    ey = y - math.sin(angle) * length
    draw.line([(x, y), (ex, ey)], fill=tone, width=width)
    for _ in range(2 if length > 30 else 3):
        spread = rng.uniform(0.25, 0.65) * rng.choice((-1, 1))
        _tree(draw, rng, ex, ey, angle + spread, length * rng.uniform(0.6, 0.75),
              max(1, width - 1), tone)


def main() -> None:
    rng = random.Random(SEED)
    w, h = W * SS, H * SS
    img = Image.new("L", (w, h))
    px = img.load()

    horizon = int(h * HORIZON)
    lake_top, lake_bottom = int(h * LAKE_TOP), int(h * LAKE_BOTTOM)

    # Sky: bright at the zenith, hazing gently toward the horizon.
    for y in range(h):
        if y < horizon:
            tone = 236 - 26 * (y / horizon)
        elif y < lake_top:
            tone = 150  # placeholder; ridges paint over this band
        elif y < lake_bottom:
            t = (y - lake_top) / (lake_bottom - lake_top)
            tone = 205 - 55 * t  # the lake mirrors the sky, dimmed
        else:
            tone = 78  # foreground bank
        for x in range(w):
            px[x, y] = int(tone)

    draw = ImageDraw.Draw(img)

    # Clouds: a few soft bright masses, blurred into the sky later.
    for _ in range(7):
        cx = rng.uniform(0.05, 0.95) * w
        cy = rng.uniform(0.06, 0.6) * horizon
        rx = rng.uniform(0.09, 0.22) * w
        ry = rx * rng.uniform(0.25, 0.4)
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=246)

    # Two ridges walking back into haze — atmospheric perspective is what
    # makes the dithered plate read as a photograph rather than a diagram.
    far = _ridge(rng, w, h * 0.47, h * 0.02)
    near = _ridge(rng, w, h * 0.545, h * 0.028)
    for x in range(w):
        for y in range(int(far[x]), lake_top):
            px[x, y] = 168
        for y in range(int(near[x]), lake_top):
            px[x, y] = 122
    # The ridges reflect into the lake head, faintly.
    for x in range(w):
        depth = int((lake_top - near[x]) * 0.55)
        for y in range(lake_top, min(lake_top + depth, lake_bottom)):
            px[x, y] = max(96, px[x, y] - 38)

    # Horizontal lake streaks: still water carries the sky in bands.
    for _ in range(26):
        sy = rng.randint(lake_top + 6 * SS, lake_bottom - 4 * SS)
        sx = rng.randint(0, w // 2)
        ln = rng.randint(w // 10, w // 3)
        draw.line([(sx, sy), (min(w - 1, sx + ln), sy)],
                  fill=min(235, px[min(w - 1, sx), sy] + 26), width=SS)

    # Foreground bank texture: coarse dark grass strokes.
    for _ in range(700):
        gx = rng.randint(0, w - 1)
        gy = rng.randint(lake_bottom, h - 1)
        ln = rng.randint(2 * SS, 6 * SS)
        draw.line([(gx, gy), (gx + rng.randint(-2, 2), gy - ln)],
                  fill=rng.choice((58, 66, 92)), width=1)

    # The great tree, dark against the sky on the right bank: a heavy forked
    # trunk under a massed canopy — soft overlapping ellipses, not foliage
    # detail, because the Atkinson pass supplies the texture.
    base_x, base_y = w * 0.78, lake_bottom + (h - lake_bottom) * 0.45
    _tree(draw, rng, base_x, base_y, math.pi / 2, h * 0.13, 8 * SS, 44)
    crown_cy = base_y - h * 0.30
    for _ in range(12):
        cx = base_x + rng.uniform(-0.11, 0.11) * w
        cy = crown_cy + rng.uniform(-0.07, 0.05) * h
        rx = rng.uniform(0.045, 0.09) * w
        ry = rx * rng.uniform(0.5, 0.75)
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=rng.choice((58, 70, 84)))

    img = img.filter(ImageFilter.GaussianBlur(SS * 1.1))
    img = img.resize((W, H), Image.Resampling.LANCZOS)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
