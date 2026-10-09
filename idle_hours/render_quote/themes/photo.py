"""The ``photo`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import collections
import math
import os
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from idle_hours.path_resolution import PHOTO_PATH_ENV, resolve_input_path

from .._paths import BASE_DIR
from ..fonts import load_font, normalize_dashes, theme_font_candidates
from ..furniture import _row_digest, draw_centred_styled_lines, draw_truncated_centred_byline, paint_mount_card
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import (
    SPECTRA6,
    SPECTRA6_PALETTE,
    BAYER_8x8,
    _load_dithered_plate,
    dither_image_to_palette,
    gray_pixel_access,
    pixel_access,
    snap_image_to_palette,
)
from ..primitives import _flow_stroke_hash
from ..spec import FrameSpec

# ---------------------------------------------------------------------------
# photo — the operator's own picture (``IDLE_HOURS_PHOTO_PATH``), conditioned,
# dithered to six inks and captioned on a card placed where it covers least.
# Every failure degrades to the bundled plate. Design notes: docs/themes.md § photo.

# The picture shown when nothing is configured or the configured source
# cannot be read: a coast with a lighthouse (scripts/generate_photo_plate.py).
# It is deliberately not ``autochrome``'s garden, which this theme borrowed
# until the two read as one theme in the rotation. Dithered against all six
# inks, like an operator's photograph.
PHOTO_PLATE = BASE_DIR / "assets" / "photo_coast.png"

# Extensions attempted from a directory listing: an allowlist, because probing
# every file with Image.open is slow and a wider attack surface.
_PHOTO_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"})

# Bounded: a directory can hold thousands of files and each decoded 800x480
# frame is ~1.1 MB. The key includes caller-controlled geometry, so an
# unbounded cache would let /api/preview clients retain memory per size.
_PHOTO_CACHE: "collections.OrderedDict[tuple, tuple[Image.Image, tuple[int, int, int, int]]]" = (
    collections.OrderedDict())
_PHOTO_CACHE_MAX = 6
# Decode cap: a 56 MP PNG costs ~212 MiB of RSS (~3.8 MiB per megapixel), so
# 40 MP bounds a non-draftable decode at ~150 MiB, which a 512 MB Pi survives
# alongside the main loop. JPEGs are drafted down first (see ``_photo_open``).
_PHOTO_MAX_PIXELS = 40_000_000
# Warnings latch per resolved source so a stale path does not write a line per
# render (SD-card wear) — the ``pick_quote._DEGRADED_WARNED`` pattern.
_PHOTO_WARNED: set = set()

# Conditioning targets, read off the shipped ``autochrome`` plate (chroma
# 0.163, mean luminance 0.671, spread 0.142), which dithers to a fine grain
# with white carrying the tone. They are ceilings: a gentler photograph is
# left alone.
#
# Chroma is ``(max - min) / 255`` per pixel, NOT HSV saturation, and that is
# load-bearing: ``ImageEnhance.Color`` blends toward grey, so it scales this
# quantity linearly and ``target / measured`` lands in one pass. HSV
# saturation is a ratio, and the same factor badly undershoots on dark colours.
_PHOTO_TARGET_CHROMA = 0.18
_PHOTO_TARGET_MEAN = 0.63
_PHOTO_SPREAD_CEILING = 0.22     # only compress contrast well above the reference
_PHOTO_MIN_CONTRAST = 0.75       # ...and never flatten it
_PHOTO_MEAN_TOLERANCE = 0.06
# A dark photograph is lifted only this far, and by a gamma curve rather than
# an offset. 0.63 is a high-key autochrome's brightness; forcing a deliberately
# dark scene up to it erases the scene, and doing it with an offset raises the
# black point so nothing in the frame stays dark (a forest at ~0.26 came out
# with its deepest shadow at 36% grey). Gamma pins 0 and 255 and moves the
# mid-tones, so shadows keep their structure.
_PHOTO_LIFT_TARGET = 0.50
_PHOTO_SOFT_FOCUS = 0.6

# How much a tonally-unusual region costs relative to a detailed one. At 0.5
# a smooth bright subject is about as expensive to cover as moderate
# texture, which is the balance that keeps the card off a sun without
# driving it onto foliage.
_PHOTO_SALIENCE_WEIGHT = 0.5
# How much the single worst cell under a candidate counts alongside its mean.
_PHOTO_PEAK_WEIGHT = 0.5

_PHOTO_CARD_W, _PHOTO_CARD_H = 312, 368
_PHOTO_CARD_MARGIN = 34
# Candidate card anchors, in the order ties are broken. Right-hand positions
# come first because a caption on the right is the conventional reading order
# for a picture-plus-text plate, so an image with no quiet region at all still
# lands somewhere deliberate.
_PHOTO_CARD_ANCHORS = ((1, 0.5), (0, 0.5), (1, 0.0), (0, 0.0), (1, 1.0), (0, 1.0))


def _photo_source() -> str | None:
    """The configured photo file or directory, or ``None``.

    Read per render rather than captured at import: ``run_clock`` exports the
    variable during ``main``, after this module is already imported by the
    in-process peek path, and a test that sets it must not have to reload the
    module.
    """
    value = os.environ.get(PHOTO_PATH_ENV, "").strip()
    return value or None


def _photo_warn_once(key: str, message: str) -> None:
    if key not in _PHOTO_WARNED:
        _PHOTO_WARNED.add(key)
        print(f"photo theme: {message}", file=sys.stderr)


def _photo_candidates(source: str) -> list[Path]:
    """Resolve the configured source to a list of candidate image files.

    A file yields itself (whatever its extension — the operator named it
    explicitly, so honour that); a directory yields its sorted image-suffixed
    entries. Sorted so the digest-driven pick is stable across filesystems,
    whose directory order is not.
    """
    path = resolve_input_path(source, BASE_DIR)
    try:
        if path.is_file():
            return [path]
        if path.is_dir():
            return sorted(p for p in path.iterdir()
                          if p.is_file() and p.suffix.lower() in _PHOTO_SUFFIXES)
    except OSError:
        return []
    return []


def _photo_for_row(quote_row: dict) -> Path | None:
    """Pick this render's photograph.

    A directory rotates with the *quote* rather than with the clock, which is
    the cadence the appliance already moves at — and it keeps the frame
    deterministic for a given row, which run_clock's "quote unchanged, skip the
    redraw" dedup depends on.
    """
    source = _photo_source()
    if source is None:
        return None
    candidates = _photo_candidates(source)
    if not candidates:
        _photo_warn_once(f"empty:{source}",
                         f"{source!r} holds no readable image; using the bundled plate")
        return None
    return candidates[_row_digest(quote_row) % len(candidates)]


def _photo_measure(image: Image.Image) -> tuple[float, float, float]:
    """Mean chroma, mean luminance and luminance spread, each 0..1.

    Measured on a thumbnail: the numbers only steer a global correction, and
    walking every pixel of a 12-megapixel phone photo to compute them would
    cost more than the render. See ``_PHOTO_TARGET_CHROMA`` for why chroma is
    ``max - min`` rather than HSV saturation.
    """
    small = image.resize((64, 40), Image.Resampling.BILINEAR)
    pixels = small.width * small.height
    bands = small.split()
    lightest = ImageChops.lighter(ImageChops.lighter(bands[0], bands[1]), bands[2])
    darkest = ImageChops.darker(ImageChops.darker(bands[0], bands[1]), bands[2])
    chroma_hist = ImageChops.subtract(lightest, darkest).histogram()
    chroma = sum(i * n for i, n in enumerate(chroma_hist)) / pixels / 255.0
    value_hist = lightest.histogram()
    mean = sum(i * n for i, n in enumerate(value_hist)) / pixels / 255.0
    variance = sum(n * ((i / 255.0) - mean) ** 2 for i, n in enumerate(value_hist)) / pixels
    return chroma, mean, math.sqrt(variance)


def _photo_lift(image: Image.Image, target: float) -> Image.Image:
    """Raise a dark photograph's mean to ``target`` with a gamma curve.

    The exponent is solved on the lightest-channel histogram, the same
    quantity ``_photo_measure`` reports, so it lands rather than undershooting
    the way ``log(target) / log(mean)`` does on a spread of tones. The same
    curve on every channel maps each pixel's lightest channel through it too,
    which is what makes the histogram the right thing to solve on.
    """
    small = image.resize((64, 40), Image.Resampling.BILINEAR)
    bands = small.split()
    hist = ImageChops.lighter(ImageChops.lighter(bands[0], bands[1]), bands[2]).histogram()
    pixels = small.width * small.height

    def mean_at(gamma: float) -> float:
        return sum(n * (i / 255.0) ** gamma for i, n in enumerate(hist) if n) / pixels

    low, high = 0.1, 1.0   # mean_at falls as gamma rises
    for _ in range(24):
        mid = (low + high) / 2
        if mean_at(mid) > target:
            low = mid
        else:
            high = mid
    gamma = (low + high) / 2
    lut = [round(255 * (v / 255.0) ** gamma) for v in range(256)]
    return image.point(lut * 3)


def _photo_cap_chroma(image: Image.Image) -> Image.Image:
    chroma, _, _ = _photo_measure(image)
    if chroma > _PHOTO_TARGET_CHROMA:
        return ImageEnhance.Color(image).enhance(_PHOTO_TARGET_CHROMA / chroma)
    return image


def _photo_condition(image: Image.Image) -> Image.Image:
    """Pull an arbitrary photograph into the band that dithers to grain.

    The brightness target is decided from the source before anything moves it
    (the chroma correction makes a saturated photo measure dark). Order is
    chroma, then lift, then levels; levels never adds a positive offset, which
    would raise the black point. Chroma and contrast only ever reduce. Design
    notes: ``docs/themes.md`` § photo.
    """
    _, source_mean, _ = _photo_measure(image)
    if source_mean > _PHOTO_TARGET_MEAN + _PHOTO_MEAN_TOLERANCE:
        target = _PHOTO_TARGET_MEAN
    elif source_mean < _PHOTO_LIFT_TARGET - _PHOTO_MEAN_TOLERANCE:
        target = _PHOTO_LIFT_TARGET
    else:
        target = source_mean
    out = _photo_cap_chroma(image)
    for _ in range(3):
        _, mean, _ = _photo_measure(out)
        if mean >= target - _PHOTO_MEAN_TOLERANCE / 2:
            break
        out = _photo_cap_chroma(_photo_lift(out, target))
    _, mean, spread = _photo_measure(out)
    scale = 1.0
    if spread > _PHOTO_SPREAD_CEILING:
        scale = max(_PHOTO_MIN_CONTRAST, _PHOTO_SPREAD_CEILING / spread)
    dest = target if mean > target + _PHOTO_MEAN_TOLERANCE / 2 else mean
    if scale < 1.0 or dest != mean:
        offset = (dest - mean * scale) * 255.0
        if offset > 0:
            # Compressing contrast around the mean would add ``offset`` to
            # black too, undoing the lift's one guarantee on a high-contrast
            # night scene. Scale toward black instead and win the mean back
            # with the black-pinned gamma lift.
            out = out.point(lambda v, s=scale: int(round(v * s)))
            out = _photo_cap_chroma(_photo_lift(out, dest))
        else:
            out = out.point(lambda v, s=scale, o=offset: max(0, min(255, int(round(v * s + o)))))
    return out.filter(ImageFilter.GaussianBlur(_PHOTO_SOFT_FOCUS))


def _photo_cover_crop(image: Image.Image, width: int, height: int) -> Image.Image:
    """Scale to cover the panel and centre-crop the overflow.

    Cover rather than fit: letterboxing an operator's photo would paint bars
    the panel has no good colour for, and a picture frame shows a picture.
    """
    src_w, src_h = image.size
    scale = max(width / src_w, height / src_h)
    scaled = image.resize((max(width, int(round(src_w * scale))),
                           max(height, int(round(src_h * scale)))),
                          Image.Resampling.LANCZOS)
    left = (scaled.width - width) // 2
    top = (scaled.height - height) // 2
    return scaled.crop((left, top, left + width, top + height))


def _photo_open(path: Path, width: int, height: int) -> Image.Image | None:
    """Open, orient, crop and condition an operator's photograph.

    Handles EXIF rotation, palette / CMYK / alpha modes and a size bound; any
    failure returns ``None`` and the caller falls back to the bundled plate.

    **Draft first, then cap, then decode.** ``Image.open`` is lazy, so both
    checks run before any pixel is materialised. ``draft`` lets the JPEG
    decoder scale down during the DCT pass (a no-op for other formats), so a
    48 MP phone JPEG is under the cap once drafted. The cap then rejects what
    draft could not shrink: Pillow's own bomb guard only raises above ~179 MP,
    and a large PNG well under that can OOM the render child on a 512 MB Pi
    before it reaches the fallback.
    """
    try:
        with Image.open(path) as raw:
            # Ask for twice the target box so the LANCZOS cover-crop still has
            # resampling headroom; draft only ever overshoots upward.
            raw.draft("RGB", (width * 2, height * 2))
            pixels = raw.width * raw.height
            if pixels > _PHOTO_MAX_PIXELS:
                _photo_warn_once(
                    f"toobig:{path}",
                    f"{path} is {pixels / 1e6:.0f} MP after draft, over the "
                    f"{_PHOTO_MAX_PIXELS / 1e6:.0f} MP decode cap; using the bundled plate",
                )
                return None
            raw.load()
            oriented = ImageOps.exif_transpose(raw) or raw
            rgb = oriented.convert("RGB")
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        _photo_warn_once(f"open:{path}", f"cannot read {path}: {exc!r}; using the bundled plate")
        return None
    return _photo_condition(_photo_cover_crop(rgb, width, height))


def photo_source_stamp(quote_row: dict) -> tuple | None:
    """A hashable stamp for the photograph this row would render, or ``None``.

    Public for the curator UI's ``/api/preview`` cache, whose key (theme,
    time, quote identity, corpus stamps) does not move when the operator swaps
    the file, and which answers before ``_photo_frame_for``'s mtime-aware
    cache is consulted. The stamp resolves the row's own photograph, so a
    directory whose membership changed is covered too.
    """
    path = _photo_for_row(quote_row)
    if path is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        # Still distinguishes one missing path from another, and from a
        # readable one — which is all the cache key needs.
        return (str(path), None, None)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _photo_frame_for(quote_row: dict, width: int, height: int) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """The dithered background and the card rectangle chosen for it.

    Returned together because placement is measured on the continuous-tone
    image, before dithering. Don't measure the dithered plate: a dither turns
    smooth regions into high-edge-energy stipple, inverting the score so the
    card lands on the part of the picture worth keeping.

    Falls back to the bundled coast plate (``PHOTO_PLATE``) when nothing is configured
    or the source cannot be read, so the theme always renders and, with the
    environment variable unset, is byte-deterministic (it has a golden
    fixture).
    """
    path = _photo_for_row(quote_row)
    key: tuple | None = None
    if path is not None:
        try:
            stat = path.stat()
            key = (str(path), stat.st_mtime_ns, stat.st_size, width, height)
        except OSError:
            key = None
        if key is not None:
            cached = _PHOTO_CACHE.get(key)
            if cached is not None:
                _PHOTO_CACHE.move_to_end(key)
                return cached
        conditioned = _photo_open(path, width, height)
        if conditioned is not None:
            result = (dither_image_to_palette(conditioned, SPECTRA6_PALETTE),
                      _photo_card_rect(conditioned, width, height))
            if key is not None:
                _PHOTO_CACHE[key] = result
                while len(_PHOTO_CACHE) > _PHOTO_CACHE_MAX:
                    _PHOTO_CACHE.popitem(last=False)
            return result
    return _photo_fallback_frame(width, height)


def _photo_fallback_frame(width: int, height: int) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """The bundled coast plate, measured for card placement the same way an
    operator's photograph is - off the continuous-tone source, not the
    dithered plate."""
    plate = _load_dithered_plate(PHOTO_PLATE, width, height, palette=SPECTRA6_PALETTE)
    try:
        with Image.open(PHOTO_PLATE) as raw:
            source = raw.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        source = None
    if plate is None:
        plate = Image.new("RGB", (width, height), SPECTRA6["white"])
        _photo_paint_coast_fallback(plate)
    rect = _photo_card_rect(source if source is not None else plate, width, height)
    return plate, rect


def _photo_paint_coast_fallback(image: Image.Image) -> None:
    """A stripped install still gets a coast-shaped colour picture: sky
    paling to the horizon, a blue sea, a white surf line and yellow sand, as
    ``BAYER_8x8`` density ramps, with a dark headland on the left so the card
    still has a quiet side to find."""
    px = pixel_access(image)
    width, height = image.size
    white, black, blue, green, yellow = (
        SPECTRA6[c] for c in ("white", "black", "blue", "green", "yellow"))
    horizon, shore = int(height * 0.47), int(height * 0.70)
    for y in range(height):
        row = BAYER_8x8[y % 8]
        for x in range(width):
            if y < horizon:
                density, ink, ground = 0.40 * (1.0 - y / horizon) ** 0.8, blue, white
            elif y < shore - 3:
                density, ink, ground = 0.38 + 0.20 * (shore - y) / (shore - horizon), blue, white
                if _flow_stroke_hash(x // 6, y, 5) < 0.06:
                    ink = white
            elif y < shore + 3:
                density, ink, ground = 0.0, black, white
            else:
                density, ink, ground = 0.42, yellow, white
            cliff = horizon - (height * 0.16) * max(0.0, 1.0 - (x / (width * 0.40)) ** 2.2)
            if x < width * 0.42 and cliff <= y < shore:
                density, ink, ground = 0.55, black, green
            px[x, y] = ink if row[x % 8] < 64 * density else ground


def _photo_cost_map(image: Image.Image, cols: int = 20, rows: int = 12) -> list[list[float]]:
    """Per-cell cost of covering that part of the picture.

    Two terms, because either alone picks a bad spot:

    * **Detail** — mean edge energy. Flat sky, wall and shadow are cheap to
      cover; foliage, a horizon or a face is not.
    * **Salience** — distance of the cell's luminance from the frame's mean.
      A smooth bright subject (a sun, a lit face, a window) has little edge
      energy inside it, so detail alone would put the card on it.

    Both are computed on the continuous-tone image (see ``_photo_frame_for``).
    """
    grey = image.convert("L")
    detail = grey.filter(ImageFilter.FIND_EDGES).resize((cols, rows), Image.Resampling.BOX)
    coarse = grey.resize((cols, rows), Image.Resampling.BOX)
    dpx, cpx = gray_pixel_access(detail), gray_pixel_access(coarse)
    cells = [[cpx[c, r] for c in range(cols)] for r in range(rows)]
    mean = sum(sum(row) for row in cells) / (cols * rows)
    return [
        [dpx[c, r] / 255.0 + _PHOTO_SALIENCE_WEIGHT * abs(cells[r][c] - mean) / 255.0
         for c in range(cols)]
        for r in range(rows)
    ]


def _photo_card_rect(image: Image.Image, width: int, height: int) -> tuple[int, int, int, int]:
    """Place the caption card over the quietest candidate region."""
    card_w = max(1, min(_PHOTO_CARD_W, width - 2 * _PHOTO_CARD_MARGIN))
    card_h = max(1, min(_PHOTO_CARD_H, height - 2 * _PHOTO_CARD_MARGIN))
    detail = _photo_cost_map(image)
    rows, cols = len(detail), len(detail[0])
    best, best_score = None, None
    for side, vertical in _PHOTO_CARD_ANCHORS:
        x0 = _PHOTO_CARD_MARGIN if side == 0 else width - _PHOTO_CARD_MARGIN - card_w
        y0 = int(round(_PHOTO_CARD_MARGIN + vertical * (height - 2 * _PHOTO_CARD_MARGIN - card_h)))
        x0 = max(0, min(width - card_w, x0))
        y0 = max(0, min(height - card_h, y0))
        c0, c1 = int(x0 / width * cols), max(int(x0 / width * cols) + 1, int((x0 + card_w) / width * cols))
        r0, r1 = int(y0 / height * rows), max(int(y0 / height * rows) + 1, int((y0 + card_h) / height * rows))
        cells = [detail[r][c] for r in range(r0, min(r1, rows)) for c in range(c0, min(c1, cols))]
        # Mean plus a share of the worst cell: across a 312x368 card the mean
        # dilutes a small face on an empty lawn to nothing, while the peak asks
        # whether this position clips anything important.
        score = (sum(cells) / len(cells) + _PHOTO_PEAK_WEIGHT * max(cells)) if cells else 0.0
        if best_score is None or score < best_score - 1e-9:
            best, best_score = (x0, y0), score
    x0, y0 = best if best is not None else (_PHOTO_CARD_MARGIN, _PHOTO_CARD_MARGIN)
    return (x0, y0, x0 + card_w, y0 + card_h)


def _photo_paint_card(image: Image.Image, draw: ImageDraw.ImageDraw,
                      rect: tuple[int, int, int, int], quote_row: dict) -> None:
    """The caption card: the shared cream mount, keylined at 2 px because an
    arbitrary photograph may be pale right up against the card's edge."""
    x0, y0, x1, y1 = rect
    black, red = SPECTRA6["black"], SPECTRA6["red"]
    paint_mount_card(image, draw, rect, ledge=3, outline_width=2)

    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    quote_font, quote_font_bold, wrapped, line_height, _ = fit_quote(
        draw, display_quote, quote_row.get("matched_text") or "",
        x1 - x0 - 40, y1 - y0 - 74, font_max=26, font_min=12,
        line_height_mult=1.34, theme="photo",
    )
    block_h = len(wrapped) * line_height
    draw_centred_styled_lines(
        draw, wrapped, x0=x0, x1=x1,
        top=y0 + max(24, ((y1 - y0) - 34 - block_h) // 2),
        line_height=line_height, regular=quote_font, bold=quote_font_bold,
        fill=black, accent=red,
    )
    draw_truncated_centred_byline(
        draw, quote_row, centre=(x0 + x1) // 2, baseline=y1 - 16,
        max_width=x1 - x0 - 30, fill=black,
        font=load_font(theme_font_candidates("photo", "quote_regular"), size=13),
    )


def render_photo_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The operator's photograph with the quote on a card (see the section
    comment).

    Composed at 800x480 and NEAREST-downsampled otherwise (the ``metro``
    convention), not re-laid out per size: the card's minimum size exceeds a
    thumbnail canvas, and a preview should show what the panel will show.
    """
    del time_str  # a photograph carries no clock; the daguerreotype rule.
    plate, rect = _photo_frame_for(quote_row, 800, 480)
    image = plate.copy()
    draw = ImageDraw.Draw(image)
    _photo_paint_card(image, draw, rect, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("photo",), render=render_photo_frame)
