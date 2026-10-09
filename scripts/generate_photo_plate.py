#!/usr/bin/env python3
"""One-time art generator for ``idle_hours/assets/photo_coast.png`` — the
picture the ``photo`` theme shows when the operator has not pointed it at one
of their own (or the one they named cannot be read).

It used to borrow ``autochrome``'s garden, so with nothing configured the two
themes showed the same meadow and read as one theme in the rotation. This
plate is a different picture on purpose, and different in kind as well as in
subject: ``autochrome`` is a soft, warm, pastel 1907 transparency, while this
is a holiday snapshot — a bright coast at midday, a lighthouse on the
headland, sea and sand. Blue and yellow carry it where the garden is green and
red, so the two frames are told apart at a glance across a room.

It is an *original work in the idiom* rather than a photograph, for the
reasons ``generate_autochrome_plate.py`` documents, and it follows that
script's one rule for surviving a six-ink dither: every mass goes down as a
blurred mask, the chroma is held in the band ``photo``'s conditioning targets
(it is not conditioned at render time, so it has to arrive there), and the
key is high enough for white to carry the tone.

The composition leaves the right-hand sky and sea quiet, because
``_photo_card_rect`` places the caption card over the quietest region; the
lighthouse and the headland sit on the left where the card will not go.

Deterministic: a fixed SEED drives every random element, so re-runs are
byte-stable.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "idle_hours" / "assets" / "photo_coast.png"
W, H = 800, 480
SS = 3            # supersample factor; smooth tone survives the downscale
SEED = 1859       # the year the Longships light was lit

HORIZON = 0.47    # sea meets sky, fraction of height
SHORE = 0.70      # where the surf breaks on the beach


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]


def _soft_layer(size: tuple[int, int], paint, blur: float) -> Image.Image:
    """Draw ``paint`` onto a fresh 8-bit mask and blur it (see the autochrome
    generator: a hard shape dithers to a blob with a rim, a soft mask to a
    picture)."""
    mask = Image.new("L", size, 0)
    paint(ImageDraw.Draw(mask))
    return mask.filter(ImageFilter.GaussianBlur(blur))


def _gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int],
              y0: int, y1: int, power: float = 1.0) -> Image.Image:
    w, h = size
    column = Image.new("RGB", (1, h))
    cp = column.load()
    for y in range(h):
        cp[0, y] = _lerp(top, bottom, ((y - y0) / max(1, y1 - y0)) ** power if y > y0 else 0.0)
    return column.resize((w, h))


def main() -> None:
    rng = random.Random(SEED)
    w, h = W * SS, H * SS
    horizon = int(h * HORIZON)
    shore = int(h * SHORE)

    # --- Sky: a clear midday blue, paling toward the horizon haze.
    img = _gradient((w, h), (104, 150, 206), (206, 220, 228), 0, horizon, power=0.8)

    # A few fair-weather clouds, kept small and high so the sky stays the
    # quiet region the caption card is meant to find.
    def _clouds(d: ImageDraw.ImageDraw) -> None:
        for cx, cy, span in ((0.18, 0.12, 0.09), (0.47, 0.22, 0.06), (0.86, 0.09, 0.05)):
            for _ in range(rng.randint(6, 9)):
                bx = (cx + rng.uniform(-span, span)) * w
                by = (cy + rng.uniform(-span, span) * 0.25) * h
                r = span * w * rng.uniform(0.25, 0.45)
                d.ellipse((bx - r, by - r * 0.6, bx + r, by + r * 0.6), fill=rng.randint(150, 220))
    img.paste(Image.new("RGB", (w, h), (238, 240, 238)), (0, 0),
              _soft_layer((w, h), _clouds, blur=SS * 9).point(lambda v: int(v * 0.7)))

    # --- Sea: deeper blue at the horizon line, lightening and greening toward
    # the shallows, laid as a soft band so the horizon is a transition.
    sea = _gradient((w, h), (62, 104, 150), (120, 168, 170), horizon, shore, power=1.3)

    def _sea_mask(d: ImageDraw.ImageDraw) -> None:
        d.rectangle((0, horizon, w, h), fill=255)
    img.paste(sea, (0, 0), _soft_layer((w, h), _sea_mask, blur=SS * 1.5))

    # Sun glitter: broken horizontal streaks, brightest under the sun's side.
    def _glitter(d: ImageDraw.ImageDraw) -> None:
        for _ in range(220):
            y = rng.uniform(horizon + h * 0.02, shore - h * 0.02)
            x = rng.gauss(0.62, 0.16) * w
            length = rng.uniform(0.01, 0.05) * w * (1.0 + (y - horizon) / (shore - horizon))
            d.line((x - length, y, x + length, y), fill=rng.randint(120, 230), width=SS)
    img.paste(Image.new("RGB", (w, h), (228, 234, 232)), (0, 0),
              _soft_layer((w, h), _glitter, blur=SS * 1.2))

    # --- The headland: a grassy cliff rising from the left edge, its face a
    # darker rock band, sloping down into the sea at about a third across.
    def _cliff_line(x: float) -> float:
        t = x / (0.40 * w)
        if t >= 1.0:
            return float(horizon + h * 0.02)
        return horizon - h * 0.16 * (1 - t ** 2.2) + h * 0.006 * math.sin(x / (w * 0.03))

    def _headland(d: ImageDraw.ImageDraw) -> None:
        d.polygon([(0, shore), *[(x, _cliff_line(x)) for x in range(0, int(0.40 * w), SS)],
                   (int(0.40 * w), horizon + h * 0.02), (int(0.47 * w), shore)], fill=255)
    img.paste(Image.new("RGB", (w, h), (104, 130, 82)), (0, 0),
              _soft_layer((w, h), _headland, blur=SS * 2))

    # The cliff face: warm sandstone under the turf, streaked by weathering
    # (vertical strokes at varying tone) and darkening toward the waterline,
    # so it reads as rock rather than as a flat grey slab.
    def _rock_face(d: ImageDraw.ImageDraw) -> None:
        pts = [(x, _cliff_line(x) + h * 0.05) for x in range(0, int(0.40 * w), SS)]
        d.polygon([(0, shore), *pts, (int(0.40 * w), horizon + h * 0.06), (int(0.47 * w), shore)],
                  fill=255)
    face = _soft_layer((w, h), _rock_face, blur=SS * 3)
    rock = _gradient((w, h), (156, 138, 116), (92, 84, 80), horizon - int(h * 0.12), shore)
    rp = ImageDraw.Draw(rock)
    for _ in range(90):
        x = rng.uniform(0, 0.46) * w
        y0 = rng.uniform(HORIZON - 0.12, SHORE - 0.06) * h
        tone = rng.randint(70, 150)
        rp.line((x, y0, x + rng.uniform(-SS * 4, SS * 4), y0 + rng.uniform(0.04, 0.12) * h),
                fill=(tone, int(tone * 0.92), int(tone * 0.84)), width=rng.randint(SS * 2, SS * 6))
    rock = rock.filter(ImageFilter.GaussianBlur(SS * 2.5))
    img.paste(rock, (0, 0), face)

    # --- The lighthouse: a white tower with one red band and a dark lantern,
    # small enough to be part of the view rather than its subject.
    lx = 0.17 * w
    base = _cliff_line(lx) + SS * 2
    top = base - h * 0.17

    def _tower(d: ImageDraw.ImageDraw) -> None:
        d.polygon([(lx - w * 0.016, base), (lx - w * 0.011, top),
                   (lx + w * 0.011, top), (lx + w * 0.016, base)], fill=255)
    img.paste(Image.new("RGB", (w, h), (236, 234, 226)), (0, 0),
              _soft_layer((w, h), _tower, blur=SS * 0.8))

    def _band(d: ImageDraw.ImageDraw) -> None:
        y0, y1 = top + (base - top) * 0.38, top + (base - top) * 0.58
        d.rectangle((lx - w * 0.016, y0, lx + w * 0.016, y1), fill=255)
    band = _soft_layer((w, h), _band, blur=SS * 0.8)
    band = Image.composite(band, Image.new("L", (w, h), 0), _soft_layer((w, h), _tower, blur=SS * 0.8))
    img.paste(Image.new("RGB", (w, h), (178, 72, 58)), (0, 0), band)

    def _lantern(d: ImageDraw.ImageDraw) -> None:
        d.rectangle((lx - w * 0.009, top - h * 0.035, lx + w * 0.009, top), fill=255)
        d.polygon([(lx - w * 0.013, top - h * 0.035), (lx, top - h * 0.055),
                   (lx + w * 0.013, top - h * 0.035)], fill=255)
    img.paste(Image.new("RGB", (w, h), (52, 54, 58)), (0, 0),
              _soft_layer((w, h), _lantern, blur=SS * 0.8))

    # --- Surf: a broken white line where the waves break, and the wet sand
    # behind it reflecting the sky.
    def _surf(d: ImageDraw.ImageDraw) -> None:
        for _ in range(140):
            x = rng.uniform(0.30, 1.02) * w
            y = shore + rng.gauss(0, h * 0.008)
            d.ellipse((x - w * 0.03, y - SS * 3, x + w * 0.03, y + SS * 3), fill=rng.randint(170, 255))
    img.paste(Image.new("RGB", (w, h), (236, 238, 234)), (0, 0),
              _soft_layer((w, h), _surf, blur=SS * 2))

    # --- Beach: warm dry sand toward the viewer, a darker wet band at the
    # waterline, and broad dune shadow so the dither has tone to break up.
    sand = _gradient((w, h), (176, 168, 140), (226, 204, 150), shore, h, power=0.7)

    def _beach(d: ImageDraw.ImageDraw) -> None:
        d.polygon([(int(0.30 * w), shore + h * 0.012), (w, shore + h * 0.012), (w, h), (0, h),
                   (0, shore + h * 0.05)], fill=255)
    img.paste(sand, (0, 0), _soft_layer((w, h), _beach, blur=SS * 3))

    def _ripples(d: ImageDraw.ImageDraw) -> None:
        for _ in range(10):
            cx = rng.uniform(-0.1, 1.1) * w
            cy = rng.uniform(SHORE + 0.08, 1.0) * h
            rx = rng.uniform(0.15, 0.32) * w
            d.ellipse((cx - rx, cy - rx * 0.08, cx + rx, cy + rx * 0.08), fill=rng.randint(90, 170))
    img.paste(Image.new("RGB", (w, h), (196, 176, 128)), (0, 0),
              _soft_layer((w, h), _ripples, blur=SS * 10))

    # Rocks at the foot of the headland: low, flat boulders in a few tones,
    # each with a lit top, so the corner closes on shadow without blobs.
    for tone_rgb, count in (((84, 80, 78), 9), ((120, 110, 98), 7)):
        def _rocks(d: ImageDraw.ImageDraw, count: int = count) -> None:
            for _ in range(count):
                x = rng.uniform(0.0, 0.34) * w
                y = rng.uniform(SHORE + 0.01, 0.80) * h
                r = rng.uniform(0.02, 0.045) * w
                d.ellipse((x - r, y - r * 0.35, x + r, y + r * 0.35), fill=rng.randint(200, 255))
        img.paste(Image.new("RGB", (w, h), tone_rgb), (0, 0),
                  _soft_layer((w, h), _rocks, blur=SS * 2.5))

    # A mild snapshot finish: a slight lift and a touch of softness, so error
    # diffusion has gradients rather than edges to work on.
    out = img.point(lambda v: int(round(14 + v * 0.93)))
    out = out.filter(ImageFilter.GaussianBlur(SS * 0.9))
    out = out.resize((W, H), Image.Resampling.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
