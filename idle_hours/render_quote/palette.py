"""The Spectra 6 inks, ordered-dither tables, palette snapping and plate dithering.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from PIL import Image

if TYPE_CHECKING:
    from PIL._imaging import PixelAccess


def pixel_access(image: Image.Image) -> PixelAccess:
    """``image.load()``, with the ``None`` its type allows ruled out.

    Pillow types ``load()`` as ``PixelAccess | None``. It returns ``None`` only
    for an image whose decoder has nothing to hand back, never for one built in
    memory, which is every image the renderer indexes pixel by pixel. Going
    through here keeps the type checker honest without an ``assert`` at each of
    the ~200 sites (issue #350).
    """
    pixels = image.load()
    if pixels is None:  # pragma: no cover - not reachable for in-memory images
        raise ValueError(f"{image!r} has no pixel access")
    return pixels


class GrayPixels(Protocol):
    """Pixel access to a one-band image: every pixel is an ``int``."""

    def __getitem__(self, xy: tuple[int, int], /) -> int: ...

    def __setitem__(self, xy: tuple[int, int], value: int, /) -> None: ...


class RGBPixels(Protocol):
    """Pixel access to an RGB(A) image: every pixel is a tuple of ints."""

    def __getitem__(self, xy: tuple[int, int], /) -> tuple[int, ...]: ...

    def __setitem__(self, xy: tuple[int, int], value: tuple[int, ...], /) -> None: ...


def gray_pixel_access(image: Image.Image) -> GrayPixels:
    """``pixel_access`` for an ``"1"`` or ``"L"`` mask, typed as ints.

    Pillow cannot say from the type which mode an image has, so it types a
    pixel as ``float | tuple[int, ...]``. The mode check here is what makes
    the narrower type true.
    """
    if image.mode not in ("1", "L"):
        raise ValueError(f"expected a one-band image, got mode {image.mode!r}")
    return cast("GrayPixels", pixel_access(image))


def rgb_pixel_access(image: Image.Image) -> RGBPixels:
    """``pixel_access`` for an ``"RGB"`` or ``"RGBA"`` image, typed as int tuples."""
    if image.mode not in ("RGB", "RGBA"):
        raise ValueError(f"expected an RGB image, got mode {image.mode!r}")
    return cast("RGBPixels", pixel_access(image))


DEFAULT_WIDTH = 800
DEFAULT_HEIGHT = 480
SPECTRA6 = {
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "red": (255, 0, 0),
    "yellow": (255, 255, 0),
    "blue": (0, 0, 255),
    "green": (0, 255, 0),
}
SPECTRA6_PALETTE = list(SPECTRA6.values())
# Canonical 4×4 ordered Bayer matrix (values 0..15), shared by
# ``draw_text_dithered`` and ``draw_deco_border`` so text and ornament land on
# the same pattern. A pixel is painted ``light`` when
# ``BAYER_4x4[y % 4][x % 4] < threshold``; threshold = round(density * 16).
BAYER_4x4: tuple[tuple[int, ...], ...] = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)
# The 8x8 ordered Bayer tile, derived from the 4x4 by the standard recursive
# construction so the two can't drift. 65 density levels instead of 17: use it
# for smooth gradients (at 4x4 a gradient quantises into visible contour bands)
# and for exact two-ink ratios (3/8 is 24/64; 4x4 only offers 6/16).
BAYER_8x8: tuple[tuple[int, ...], ...] = tuple(
    tuple(
        4 * BAYER_4x4[y % 4][x % 4] + ((0, 2), (3, 1))[y // 4][x // 4]
        for x in range(8)
    )
    for y in range(8)
)


def snap_image_to_palette(image: Image.Image, palette: list[tuple[int, int, int]]) -> Image.Image:
    snapped = Image.new("RGB", image.size)
    src = rgb_pixel_access(image)
    dst = pixel_access(snapped)
    # Frames carry only a handful of distinct colours, so memoise the
    # nearest-colour lookup per source pixel. Byte-identical output.
    cache: dict = {}
    for y in range(image.height):
        for x in range(image.width):
            pixel = src[x, y]
            nearest = cache.get(pixel)
            if nearest is None:
                nearest = min(
                    palette,
                    key=lambda c: (pixel[0] - c[0]) ** 2 + (pixel[1] - c[1]) ** 2 + (pixel[2] - c[2]) ** 2,
                )
                cache[pixel] = nearest
            dst[x, y] = nearest
    return snapped

# ---------------------------------------------------------------------------
# Render-time image dithering to the Spectra-6 palette.
#
# A committed continuous-tone PNG (a theme's plate) dithered down to the inks
# at render time, for photographic tonal fidelity. The plates themselves, and
# each one's sub-palette, belong to their themes.
# ---------------------------------------------------------------------------

# Dithered results are deterministic per (source, size, method) and re-used
# across the 144-frame contact sheet and the golden suite, so memoise them.
_DITHER_CACHE: dict = {}


def dither_image_to_palette(
    image: Image.Image,
    palette: list[tuple[int, int, int]],
    method: str = "floyd-steinberg",
) -> Image.Image:
    """Quantise a continuous-tone RGB image to ``palette`` with dithering,
    so gradients survive as a stipple the eye averages back into the tone.

    ``method``:

    * ``"floyd-steinberg"`` (default) — Pillow's C-speed ``Image.quantize``
      error diffusion: the soft organic stipple photographic plates want.
    * ``"ordered"`` — a deterministic 4×4 Bayer dither: a stable, tileable
      cross-hatch instead of content-dependent noise.
    * ``"atkinson"`` — Atkinson diffusion, which passes on only 6/8 of the
      error and *discards* the rest, so highlights blow toward paper and
      shadows crush toward ink: the high-key look of a daguerreotype (and
      what that theme's mechanism test measures). Pure Python, so reserve it
      for plates memoised through ``_load_dithered_plate``.

    Output is pure on-palette RGB, so a later ``snap_image_to_palette`` is a
    no-op on these pixels.
    """
    if not palette:
        raise ValueError("palette must contain at least one colour")
    src = image.convert("RGB")
    if method == "floyd-steinberg":
        pal_img = Image.new("P", (1, 1))
        flat: list[int] = []
        for colour in palette:
            flat.extend(colour)
        # Pad the 256-entry palette with the first ink, so quantize only maps
        # to colours in ``palette`` (0,0,0 padding would inject black).
        while len(flat) < 768:
            flat.extend(palette[0])
        pal_img.putpalette(flat[:768])
        quantised = src.quantize(palette=pal_img, dither=Image.Dither.FLOYDSTEINBERG)
        return quantised.convert("RGB")
    if method == "ordered":
        out = Image.new("RGB", src.size)
        sp = rgb_pixel_access(src)
        op = pixel_access(out)
        # Bayer cell values 0..15 → a signed bias in roughly [-0.5, +0.5] of an
        # ink step, scaled to 8-bit. ``amp`` controls the dither strength.
        amp = 64
        cache: dict = {}
        w, h = src.size
        for y in range(h):
            brow = BAYER_4x4[y & 3]
            for x in range(w):
                bias = (brow[x & 3] / 15.0 - 0.5) * amp
                r, g, b = sp[x, y]
                key = (int(r + bias), int(g + bias), int(b + bias))
                nearest = cache.get(key)
                if nearest is None:
                    pr, pg, pb = key
                    nearest = min(
                        palette,
                        key=lambda c: (pr - c[0]) ** 2 + (pg - c[1]) ** 2 + (pb - c[2]) ** 2,
                    )
                    cache[key] = nearest
                op[x, y] = nearest
        return out
    if method == "atkinson":
        out = Image.new("RGB", src.size)
        sp = rgb_pixel_access(src)
        op = pixel_access(out)
        w, h = src.size
        # Three rolling error rows (y, y+1, y+2) — Atkinson's kernel reaches
        # two rows down, one further than Floyd-Steinberg's.
        cur = [[0.0, 0.0, 0.0] for _ in range(w)]
        nxt = [[0.0, 0.0, 0.0] for _ in range(w)]
        after = [[0.0, 0.0, 0.0] for _ in range(w)]
        for y in range(h):
            for x in range(w):
                r, g, b = sp[x, y]
                err = cur[x]
                vr, vg, vb = r + err[0], g + err[1], b + err[2]
                nearest = min(
                    palette,
                    key=lambda c: (vr - c[0]) ** 2 + (vg - c[1]) ** 2 + (vb - c[2]) ** 2,
                )
                op[x, y] = nearest
                # An eighth to each of six neighbours; the remaining quarter is
                # dropped on purpose — that loss IS the Atkinson look.
                er = (vr - nearest[0]) / 8.0
                eg = (vg - nearest[1]) / 8.0
                eb = (vb - nearest[2]) / 8.0
                for tx, row in ((x + 1, cur), (x + 2, cur), (x - 1, nxt),
                                (x, nxt), (x + 1, nxt), (x, after)):
                    if 0 <= tx < w:
                        cell = row[tx]
                        cell[0] += er
                        cell[1] += eg
                        cell[2] += eb
            cur, nxt, after = nxt, after, cur
            for cell in after:
                cell[0] = cell[1] = cell[2] = 0.0
        return out
    raise ValueError(f"unknown dither method: {method!r}")


def _load_dithered_plate(path: Path, width: int, height: int, method: str = "floyd-steinberg",
                         palette: list[tuple[int, int, int]] | None = None,
                         focus: tuple[float, float] | None = None) -> Image.Image | None:
    """Open a committed plate PNG, resize it, and dither it to ``palette``
    (default the full Spectra-6 set), memoised. Returns ``None`` if the asset
    is missing or unreadable, so a stripped install degrades to a plain
    ground.

    With ``focus`` (x, y fractions, 0..1) the plate is scaled to *cover* the
    box and the overflow cropped about that point, for a window whose aspect
    differs from the plate's; without it the plate is stretched to fit.
    """
    pal = palette if palette is not None else SPECTRA6_PALETTE
    key = (str(path), width, height, method, tuple(pal), focus)
    cached = _DITHER_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        with Image.open(path) as raw:
            rgb = raw.convert("RGB")
            if focus is None:
                resized = rgb.resize((width, height), Image.Resampling.LANCZOS)
            else:
                scale = max(width / rgb.width, height / rgb.height)
                sw, sh = max(width, round(rgb.width * scale)), max(height, round(rgb.height * scale))
                left = round((sw - width) * min(1.0, max(0.0, focus[0])))
                top = round((sh - height) * min(1.0, max(0.0, focus[1])))
                resized = rgb.resize((sw, sh), Image.Resampling.LANCZOS).crop(
                    (left, top, left + width, top + height))
    except (OSError, ValueError):
        return None
    dithered = dither_image_to_palette(resized, pal, method=method)
    _DITHER_CACHE[key] = dithered
    return dithered

# The panel's measured inks — CLAUDE.md's calibration table. A scene painted
# in this space and quantised by ``_dither_calibrated`` is re-labelled with the
# nominal ``SPECTRA6`` values afterwards, so the dither decides in the space the
# eye actually sees. Shared by expedition, hades, beksinski, goya, lumon, dsky,
# oblivion and yorha.
_PANEL_INKS = {
    "white": (185, 199, 201),
    "black": (31, 34, 38),
    "red": (98, 32, 30),
    "yellow": (193, 187, 30),
    "blue": (35, 63, 142),
    "green": (53, 86, 58),
}


def _dither_calibrated(scene: Image.Image, inks) -> Image.Image:
    """Floyd–Steinberg ``scene`` against the *calibrated* colours of ``inks``,
    then re-label the chosen indices with the nominal inks.

    ``quantize(palette=…)`` maps every pixel to an index into the palette
    image it is handed; replacing that image's palette with the nominal
    values afterwards is a pure re-labelling, so the dither's decisions are
    made in the measured space and its output is on-palette RGB.
    """
    measured: list[int] = []
    nominal: list[int] = []
    for name in inks:
        measured.extend(_PANEL_INKS[name])
        nominal.extend(SPECTRA6[name])
    while len(measured) < 768:
        measured.extend(_PANEL_INKS[inks[0]])
        nominal.extend(SPECTRA6[inks[0]])
    palette = Image.new("P", (1, 1))
    palette.putpalette(measured[:768])
    quantised = scene.convert("RGB").quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
    quantised.putpalette(nominal[:768])
    return quantised.convert("RGB")
