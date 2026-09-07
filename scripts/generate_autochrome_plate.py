#!/usr/bin/env python3
"""One-time art generator for ``idle_hours/assets/autochrome_garden.png`` — the
continuous-tone colour photograph the ``autochrome`` theme dithers to the FULL
six-ink Spectra-6 palette at render time.

Autochrome Lumiere (1907-1930s) was the first practical colour process: a glass
plate carried a mosaic of potato-starch grains dyed orange-red, green and
blue-violet, and the emulsion behind it was exposed and developed through that
random colour filter. The image you see is therefore not continuous colour at
all — it is a **stochastic mosaic of three coloured grains** that the eye
integrates at viewing distance. A Floyd-Steinberg dither to six inks is the
same object, which is why this theme exists: the panel is not approximating
autochrome, it is doing what autochrome did.

The plate is an *original work in the idiom* rather than a scan, for the same
reasons ``generate_anna_atkins_plate.py`` and ``generate_daguerreotype_plate.py``
document — the point of the asset is to exercise the render-time dithering
path, which needs real continuous-tone content. Drop a genuine scan in at the
same path and it dithers identically.

**The subject is a garden, and the palette is muted on purpose.** Both choices
are forced by measurement rather than taste:

* A garden is *the* canonical autochrome subject — the long exposures (the
  grain layer costs 2-3 stops, so 30-60x a mono plate) suited static subjects,
  and colour was the whole point, so the Lumieres, Etienne Clementel and Albert
  Kahn's operators all shot flower beds obsessively. It also happens to put all
  six inks on the page honestly: sky blue, foliage green, poppy red, bloom
  yellow, path white, shadow black.
* Saturation is held low and the key held high because that is what survives a
  six-ink dither. Measured on the real primitive, a saturated source quantises
  to a chunky blue/red/green mosaic that reads as colour bars at 800x480, while
  a soft desaturated one breaks into a fine grain with white carrying the tone.
  Autochrome's own tonal character — pastel, high-key, soft-focus, warm-biased
  — is the one photographic register that dithers *well* on these inks, so the
  period style and the hardware constraint point the same way.

What is deliberately NOT baked in: the passe-partout binding tape, the paper
mask and the caption card all stay render-time (``render_autochrome_frame``),
so the committed plate remains a clean rectangular photograph and the mount can
be retuned without regenerating art.

Deterministic: a fixed SEED drives every random element, so re-runs are
byte-stable.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "idle_hours" / "assets" / "autochrome_garden.png"
W, H = 800, 480
SS = 3            # supersample factor; smooth tone survives the downscale
SEED = 1907       # the year Lumiere put autochrome plates on sale

HORIZON = 0.40    # sky / tree-line boundary, fraction of height
BEDS_TOP = 0.52   # where the flower beds begin
NEAR_BEDS = 0.61  # where the near border takes over from the lawn


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]


def _ridge(rng: random.Random, width: int, base: float, roughness: float) -> list[float]:
    """A soft rolling tree line: summed low-frequency sines."""
    phases = [rng.uniform(0, 2 * math.pi) for _ in range(3)]
    amps = [roughness * f for f in (1.0, 0.5, 0.28)]
    waves = [width / d for d in (2.1, 5.3, 11.7)]
    return [
        base + sum(a * math.sin(x / wl + p) for a, wl, p in zip(amps, waves, phases))
        for x in range(width)
    ]


def _soft_layer(size: tuple[int, int], paint, blur: float) -> Image.Image:
    """Draw ``paint`` onto a fresh 8-bit mask and blur it.

    Every mass in this plate goes down as a blurred *mask* rather than as a
    filled shape, and that is the whole difference between a photograph and a
    poster once the dither runs. A hard-edged ellipse of near-white quantises to
    a solid white blob with a visible rim; the same ellipse as a soft mask
    modulates the sky underneath it, so error diffusion has a gradient to break
    up and the eye reads cloud. The first cut of this generator composited hard
    shapes and blurred once at the end, and the result read as confetti over
    stripes.
    """
    mask = Image.new("L", size, 0)
    paint(ImageDraw.Draw(mask))
    return mask.filter(ImageFilter.GaussianBlur(blur))


def _drift_centres(rng: random.Random, count: int, y0: float, y1: float,
                   w: int, h: int, x0: float = -0.05, x1: float = 1.05
                   ) -> list[tuple[float, float, float]]:
    """Anchor points for bloom masses: a border is planted in drifts, and a
    uniform scatter of single heads dissolves into noise under the dither.

    ``x0`` / ``x1`` bias the drifts across the frame. The theme's caption card
    covers the right third of the panel, so the blooms — the whole reason the
    subject is a garden — are planted where they will be seen.
    """
    return [
        (rng.uniform(x0, x1) * w, rng.uniform(y0, y1) * h,
         rng.uniform(0.06, 0.15) * w)
        for _ in range(count)
    ]


def main() -> None:
    rng = random.Random(SEED)
    w, h = W * SS, H * SS
    img = Image.new("RGB", (w, h))
    px = img.load()

    horizon = int(h * HORIZON)
    beds_top = int(h * BEDS_TOP)

    # --- Sky: a pale summer sky hazing to near-white at the tree line.
    # Atmospheric perspective is what makes a dithered plate read as a
    # photograph rather than a diagram, so the gradient is the first thing in.
    sky_top = (86, 132, 198)
    sky_low = (192, 212, 222)
    for y in range(beds_top):
        tone = _lerp(sky_top, sky_low, (y / horizon) ** 0.7)
        for x in range(w):
            px[x, y] = tone

    # --- Clouds, as a soft mask brightening the sky rather than as filled
    # shapes. Each is a cluster of small overlapping ellipses so the silhouette
    # is lumpy before the blur rounds it; a single large ellipse blurs into a
    # lens flare.
    def _clouds(d: ImageDraw.ImageDraw) -> None:
        for _ in range(5):
            cx = rng.uniform(0.0, 1.0) * w
            cy = rng.uniform(0.10, 0.66) * horizon
            span = rng.uniform(0.07, 0.15) * w
            for _ in range(rng.randint(5, 9)):
                bx = cx + rng.uniform(-span, span)
                by = cy + rng.uniform(-span, span) * 0.28
                r = span * rng.uniform(0.22, 0.44)
                d.ellipse((bx - r, by - r * 0.7, bx + r, by + r * 0.7),
                          fill=rng.randint(150, 215))
    cloud = _soft_layer((w, h), _clouds, blur=SS * 11)
    # Cap the lift so a cloud never blows to paper white: a blown highlight
    # dithers to a solid patch with a hard rim, which is the artefact that made
    # the first plate read as a blob pasted on a gradient.
    img.paste(Image.new("RGB", (w, h), (236, 238, 236)), (0, 0),
              cloud.point(lambda v: int(v * 0.62)))

    # --- Two tree lines walking back into haze, laid as soft masks so the
    # horizon is a transition rather than a drawn line.
    far = _ridge(rng, w, horizon - h * 0.02, h * 0.014)
    near = _ridge(rng, w, horizon + h * 0.045, h * 0.024)

    def _band(line: list[float]):
        def paint(d: ImageDraw.ImageDraw) -> None:
            d.polygon([(0, h), *[(x, line[x]) for x in range(w)], (w - 1, h)], fill=255)
        return paint

    img.paste(Image.new("RGB", (w, h), (126, 152, 122)), (0, 0),
              _soft_layer((w, h), _band(far), blur=SS * 5))
    img.paste(Image.new("RGB", (w, h), (80, 112, 72)), (0, 0),
              _soft_layer((w, h), _band(near), blur=SS * 4))

    # --- Lawn and beds: a green field darkening gently toward the viewer,
    # feathered into the tree line's foot rather than butted against it.
    lawn_far = (124, 150, 86)
    lawn_near = (84, 112, 60)
    lawn = Image.new("RGB", (w, h))
    lp = lawn.load()
    for y in range(h):
        tone = _lerp(lawn_far, lawn_near, max(0.0, (y - beds_top) / (h - beds_top)))
        for x in range(w):
            lp[x, y] = tone

    def _lawn_mask(d: ImageDraw.ImageDraw) -> None:
        d.rectangle((0, beds_top, w, h), fill=255)
    img.paste(lawn, (0, 0), _soft_layer((w, h), _lawn_mask, blur=SS * 6))

    # --- Sunlight and cloud shadow drifting across the lawn. A flat green
    # field gives error diffusion nothing to break up and dithers to uniform
    # noise; broad low-frequency modulation is what the eye reads as ground.
    # It replaces an earlier gravel walk, which was a flat pale wedge floating
    # in the middle distance rather than a path receding through one.
    def _sunlight(d: ImageDraw.ImageDraw) -> None:
        for _ in range(9):
            cx = rng.uniform(-0.1, 1.1) * w
            cy = rng.uniform(BEDS_TOP, 1.0) * h
            rx = rng.uniform(0.16, 0.38) * w
            ry = rx * rng.uniform(0.12, 0.26)
            d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=rng.randint(120, 210))
    img.paste(Image.new("RGB", (w, h), (172, 190, 128)), (0, 0),
              _soft_layer((w, h), _sunlight, blur=SS * 14))

    def _shade(d: ImageDraw.ImageDraw) -> None:
        for _ in range(7):
            cx = rng.uniform(-0.1, 1.1) * w
            cy = rng.uniform(BEDS_TOP + 0.04, 1.0) * h
            rx = rng.uniform(0.13, 0.30) * w
            ry = rx * rng.uniform(0.14, 0.30)
            d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=rng.randint(90, 165))
    img.paste(Image.new("RGB", (w, h), (74, 100, 62)), (0, 0),
              _soft_layer((w, h), _shade, blur=SS * 16))

    # --- Flower beds. Poppy red and bloom yellow are the two inks the garden
    # exists to put on the page, so they are massed into drifts and laid as soft
    # layers: a scatter of single heads dissolves under the dither, where a
    # drift holds its colour.
    def _heads(centres, radius: float, jitter: float):
        def paint(d: ImageDraw.ImageDraw) -> None:
            for cx, cy, spread in centres:
                for _ in range(rng.randint(14, 26)):
                    bx = cx + rng.gauss(0, spread * 0.5)
                    by = cy + rng.gauss(0, spread * jitter)
                    r = radius * rng.uniform(0.7, 1.5)
                    d.ellipse((bx - r, by - r * 0.85, bx + r, by + r * 0.85),
                              fill=rng.randint(170, 255))
        return paint

    far_beds = _drift_centres(rng, 5, BEDS_TOP + 0.02, NEAR_BEDS - 0.03, w, h, -0.05, 0.72)
    near_beds = _drift_centres(rng, 8, NEAR_BEDS + 0.04, 0.94, w, h, -0.05, 0.62)
    img.paste(Image.new("RGB", (w, h), (190, 106, 86)), (0, 0),
              _soft_layer((w, h), _heads(near_beds, h * 0.022, 0.22), blur=SS * 3))
    img.paste(Image.new("RGB", (w, h), (226, 212, 140)), (0, 0),
              _soft_layer((w, h), _heads(far_beds, h * 0.010, 0.16), blur=SS * 3))
    img.paste(Image.new("RGB", (w, h), (232, 226, 204)), (0, 0),
              _soft_layer((w, h), _heads(_drift_centres(rng, 3, 0.70, 0.92, w, h, 0.02, 0.55),
                                         h * 0.011, 0.18), blur=SS * 3))

    # Foreground foliage: a dark soft mass anchoring the bottom edge, so the
    # frame closes on shadow rather than running off in mid-tone.
    def _foliage(d: ImageDraw.ImageDraw) -> None:
        for _ in range(260):
            gx = rng.uniform(-0.02, 1.02) * w
            gy = rng.uniform(0.88, 1.04) * h
            r = rng.uniform(0.012, 0.035) * w
            d.ellipse((gx - r, gy - r, gx + r, gy + r), fill=rng.randint(120, 235))
    img.paste(Image.new("RGB", (w, h), (60, 88, 54)), (0, 0),
              _soft_layer((w, h), _foliage, blur=SS * 4))

    # --- The autochrome cast. Two passes, both period-accurate and both
    # measured against the dither: lift the key (the plates are famously bright
    # and low-contrast because the grain layer scatters light), then bias warm
    # (the orange-red starch grains dominate the eye's response, which is why
    # autochromes skew pink-ochre rather than neutral).
    lifted = img.point(lambda v: int(round(30 + v * 0.86)))
    r, g, b = lifted.split()
    lifted = Image.merge("RGB", (
        r.point(lambda v: min(255, int(round(v * 1.04 + 3)))),
        g,
        b.point(lambda v: int(round(v * 0.99))),
    ))

    # Soft focus: an autochrome is diffused by its own grain layer, and the
    # softness is also what lets error diffusion find smooth gradients to break
    # up instead of hard edges to ring around.
    out = lifted.filter(ImageFilter.GaussianBlur(SS * 1.2))
    out = out.resize((W, H), Image.Resampling.LANCZOS)
    out = out.filter(ImageFilter.GaussianBlur(0.8))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
