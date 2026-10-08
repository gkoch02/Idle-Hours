"""The ``chrono`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random
from typing import Any

from PIL import Image, ImageChops, ImageDraw

from ..fonts import _font_ascent, load_font, normalize_dashes, theme_font_candidates
from ..furniture import _fit_from_title
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_4x4, BAYER_8x8, gray_pixel_access, pixel_access, snap_image_to_palette
from ..primitives import _bayer_threshold_field, _fill_swatch_stipple, _soft_ellipse_mask, paint_neon_mask
from ..spec import FrameSpec

# ─── chrono (16-bit SNES JRPG dialogue) ──────────────────────────────────────
#
# The 16-bit counterpart to questline's 8-bit scene (Final Fantasy VI /
# Chrono Trigger era): a gradient twilight sky, the translucent-blue gradient
# dialogue window with a rounded border, and a portrait sub-window. Pixelify
# Sans gives the matched phrase a real Bold weight on top of the yellow
# accent. HH:MM is never shown — the matched phrase carries the time.

# Portrait motif — an ornate hourglass (a drawn face reads as crude on six
# inks). Each material carries a multi-tone shading ramp so brass, glass and
# sand read as lit volumes. Sculpted at a low logical resolution into a
# tone-indexed 'L' image (`_chrono_build_hourglass`), then upscaled and
# dither-mapped to Spectra-6 tones.
#
# Tone index → fill rule. "solid" = one ink; "mix2"/"mix3" = ordered-Bayer
# dithers (the recipes in spectra6_color_recipes.md): cream/gold/bronze brass
# (Y+W / Y / R+Y), amber sand (R+Y at varying density), sky-tint glass (B+W).
_CHRONO_ART_TONES = {
    1: ("solid", SPECTRA6["black"]),                          # outline
    2: ("mix2", SPECTRA6["yellow"], SPECTRA6["white"], 0.55),  # brass highlight (cream)
    3: ("solid", SPECTRA6["yellow"]),                         # brass mid (gold)
    4: ("mix2", SPECTRA6["red"], SPECTRA6["yellow"], 0.25),    # brass shadow (bronze)
    5: ("mix2", SPECTRA6["yellow"], SPECTRA6["white"], 0.6),   # sand highlight (pale)
    6: ("mix2", SPECTRA6["red"], SPECTRA6["yellow"], 0.38),    # sand mid (amber)
    7: ("mix2", SPECTRA6["red"], SPECTRA6["yellow"], 0.20),    # sand shadow (deep amber)
    8: ("mix2", SPECTRA6["blue"], SPECTRA6["white"], 0.55),    # glass tint (sky)
    9: ("solid", SPECTRA6["white"]),                          # specular highlight
}
_CHRONO_ART_SIZE = (56, 72)  # logical pixels before upscale
_CHRONO_ART_SCALE = 2        # → 112×144 px on the panel

_CHRONO_SKY_BOTTOM = 256
_CHRONO_WINDOW = (28, 256, 772, 458)
_CHRONO_PORTRAIT = (32, 222, 180, 394)


def _chrono_tone_color(idx: int, x: int, y: int):
    """Resolve an art tone index to its Spectra-6 (possibly dithered) colour."""
    # A tagged tuple whose shape depends on its kind, unpacked per branch below.
    rule: tuple[Any, ...] = _CHRONO_ART_TONES[idx]
    kind = rule[0]
    if kind == "solid":
        return rule[1]
    if kind == "mix2":
        _, dark, light, density = rule
        return light if BAYER_4x4[y % 4][x % 4] < round(density * 16) else dark
    _, ink_a, ink_b, ink_c, da, db = rule
    cell = BAYER_4x4[y % 4][x % 4]
    return ink_a if cell < round(da * 16) else (ink_b if cell < round((da + db) * 16) else ink_c)


def _chrono_build_hourglass(run_out: bool = False) -> Image.Image:
    """Sculpt an ornate hourglass as a tone-indexed ('L') logical image.

    ``run_out`` empties the upper bulb into a full mound below, for the sleep
    frame: the glass is drawn as usual, then the sand is moved and the bulb
    outlines restored, so the default sculpt is untouched.

    A brass frame (capped top/bottom with finials + two shaded side posts), two
    sky-tinted glass bulbs with specular streaks, and amber sand — draining from
    a dished surface in the upper bulb, through the neck as a thin stream, onto a
    mound in the lower bulb. Light from the upper-left (cream highlights up-left,
    bronze / deep-amber shadows down-right). The caller upscales + dither-maps.
    """
    lw, lh = _CHRONO_ART_SIZE
    img = Image.new("L", (lw, lh), 0)
    d = ImageDraw.Draw(img)
    K = 1
    top_bulb = [(14, 9), (42, 9), (31, 37), (25, 37)]
    bot_bulb = [(25, 37), (31, 37), (42, 63), (14, 63)]
    # Glass bulbs (sky tint).
    d.polygon(top_bulb, fill=8)
    d.polygon(bot_bulb, fill=8)
    # Sand: dished surface in the upper bulb, a mound in the lower, a thin stream.
    d.polygon([(20, 22), (36, 22), (31, 37), (25, 37)], fill=6)
    d.line((20, 22, 28, 25), fill=7, width=1)
    d.line((36, 22, 28, 25), fill=7, width=1)
    d.line((22, 23, 34, 23), fill=5, width=1)
    d.polygon([(14, 63), (42, 63), (28, 48)], fill=6)
    d.line((28, 48, 15, 62), fill=5, width=1)
    d.line((29, 49, 41, 62), fill=7, width=1)
    d.line((28, 37, 28, 48), fill=6, width=1)
    d.point((28, 41), fill=5)
    d.point((28, 45), fill=5)
    # Glass specular streaks (upper-left of each bulb).
    d.line((19, 13, 23, 21), fill=9, width=1)
    d.point((20, 23), fill=9)
    d.line((20, 41, 22, 46), fill=9, width=1)
    # Glass outline.
    d.polygon(top_bulb, outline=K)
    d.polygon(bot_bulb, outline=K)
    # Brass side posts (cream highlight left, bronze shadow right).
    for px0, px1 in ((8, 12), (44, 48)):
        d.rectangle((px0, 8, px1, 64), fill=3, outline=K)
        d.line((px0 + 1, 9, px0 + 1, 63), fill=2, width=1)
        d.line((px1 - 1, 9, px1 - 1, 63), fill=4, width=1)
    # Brass caps (cream highlight top, bronze shadow bottom) + finials.
    for cy0, cy1 in ((3, 9), (63, 69)):
        d.rectangle((4, cy0, 52, cy1), fill=3, outline=K)
        d.line((5, cy0 + 1, 51, cy0 + 1), fill=2, width=1)
        d.line((5, cy1 - 1, 51, cy1 - 1), fill=4, width=1)
    d.rectangle((25, 0, 31, 3), fill=3, outline=K)
    d.rectangle((25, 69, 31, 71), fill=3, outline=K)
    if run_out:
        # Empty glass above (keeping its specular streak), no stream through
        # the neck, and every grain in a full mound below.
        d.polygon([(20, 22), (36, 22), (31, 37), (25, 37)], fill=8)
        d.line((20, 22, 36, 22), fill=8, width=1)
        d.line((28, 37, 28, 48), fill=8, width=1)
        d.polygon([(15, 62), (41, 62), (35, 50), (28, 43), (21, 50)], fill=6)
        d.line((28, 43, 16, 61), fill=5, width=1)
        d.line((29, 44, 40, 61), fill=7, width=1)
        d.line((19, 13, 23, 21), fill=9, width=1)
        d.polygon(top_bulb, outline=K)
        d.polygon(bot_bulb, outline=K)
    return img


def _chrono_paint_hourglass(image: Image.Image, ox: int, oy: int, run_out: bool = False) -> None:
    """Upscale the logical hourglass and paint it at (ox, oy), dither-mapping tones.

    The dither is sampled at absolute panel coordinates so the synthesised
    brass / sand / glass tones share a continuous Bayer phase with the frame.
    """
    big = _chrono_build_hourglass(run_out).resize(
        (_CHRONO_ART_SIZE[0] * _CHRONO_ART_SCALE, _CHRONO_ART_SIZE[1] * _CHRONO_ART_SCALE),
        Image.Resampling.NEAREST,
    )
    bw, bh = big.size
    src = gray_pixel_access(big)
    dst = pixel_access(image)
    width, height = image.size
    for y in range(bh):
        gy = oy + y
        if gy < 0 or gy >= height:
            continue
        for x in range(bw):
            idx = src[x, y]
            if not idx:
                continue
            gx = ox + x
            if 0 <= gx < width:
                dst[gx, gy] = _chrono_tone_color(idx, gx, gy)
_CHRONO_STAR_SEED = 0xC470


def _chrono_fill_poly(image: Image.Image, points, dark, light, density: float) -> None:
    """Fill a polygon with a Bayer two-ink stipple (for navy mountain silhouettes)."""
    w, h = image.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    bbox = mask.getbbox()
    if bbox is None:
        return
    x0, y0, x1, y1 = bbox
    px = pixel_access(image)
    mx = pixel_access(mask)
    threshold = round(density * 16)
    for y in range(y0, y1):
        for x in range(x0, x1):
            if mx[x, y]:
                px[x, y] = light if BAYER_4x4[y % 4][x % 4] < threshold else dark


def _chrono_paint_sky(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """Gradient twilight sky: deep navy at the zenith fading to a hazy horizon,
    with deterministic stars, a pale moon, and a two-range mountain silhouette.

    A per-row Bayer density ramp: black density falls from the zenith to
    mid-sky, then white density rises toward the horizon (haze).
    """
    width = image.size[0]
    BLUE = SPECTRA6["blue"]
    BLACK = SPECTRA6["black"]
    WHITE = SPECTRA6["white"]
    px = pixel_access(image)
    bottom = _CHRONO_SKY_BOTTOM
    # Clip the PixelAccess writes to the image height: `bottom` anchors the
    # ramp, but /api/preview renders canvases as short as ~60 px.
    for y in range(min(bottom, image.size[1])):
        if y < 130:
            # Zenith → mid: navy fading to pure blue (black density 0.42 → 0).
            d = 0.42 * (1 - y / 130)
            light, dark = BLACK, BLUE
        else:
            # Mid → horizon: pure blue gaining a haze of white (0 → 0.38).
            d = 0.38 * ((y - 130) / (bottom - 130))
            light, dark = WHITE, BLUE
        threshold = round(d * 16)
        row = BAYER_4x4[y % 4]
        for x in range(width):
            px[x, y] = light if row[x % 4] < threshold else dark
    # Stars — deterministic white specks in the upper sky, clear of the moon.
    rng = random.Random(_CHRONO_STAR_SEED)
    moon_cx, moon_cy, moon_r = 648, 72, 30
    for _ in range(70):
        sx = rng.randint(6, width - 6)
        sy = rng.randint(8, 150)
        if (sx - moon_cx) ** 2 + (sy - moon_cy) ** 2 < (moon_r + 14) ** 2:
            continue
        draw.point((sx, sy), fill=WHITE)
        if rng.random() < 0.22:  # a few brighter 2×2 stars
            draw.rectangle((sx, sy, sx + 1, sy + 1), fill=WHITE)
    # Distant mountain ranges (back lighter, front navy) for parallax depth.
    # Peaks are offsets above ``bottom`` (the horizon) so they follow it if
    # the sky height changes.
    draw.polygon(
        [(0, bottom), (0, bottom - 86), (150, bottom - 46), (320, bottom - 100),
         (520, bottom - 52), (700, bottom - 96), (width, bottom - 58), (width, bottom)],
        fill=BLUE,
    )
    _chrono_fill_poly(
        image,
        [(0, bottom), (0, bottom - 34), (180, bottom - 72), (360, bottom - 26),
         (560, bottom - 70), (760, bottom - 28), (width, bottom - 56), (width, bottom)],
        dark=BLUE, light=BLACK, density=0.5,
    )
    # Pale moon with a couple of faint navy craters.
    draw.ellipse((moon_cx - moon_r, moon_cy - moon_r, moon_cx + moon_r, moon_cy + moon_r), fill=WHITE)
    for (cx, cy, cr) in ((moon_cx - 8, moon_cy - 6, 5), (moon_cx + 9, moon_cy + 7, 4), (moon_cx + 2, moon_cy - 11, 3)):
        _fill_swatch_stipple(image, (cx - cr, cy - cr, cx + cr, cy + cr), dark=WHITE, light=BLUE, light_density=0.5)


def _chrono_window_fill(image: Image.Image, rect: tuple[int, int, int, int], radius: int) -> None:
    """Translucent-blue gradient window fill, clipped to a rounded rectangle.

    Painted on a private tile (top navy → bottom blue with a faint sky-blue
    sheen) and pasted through a rounded-rectangle mask, so the corners read as
    the soft rounded FF-window silhouette rather than a hard rectangle.
    """
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    BLUE = SPECTRA6["blue"]
    BLACK = SPECTRA6["black"]
    WHITE = SPECTRA6["white"]
    tile = Image.new("RGB", (w, h), BLUE)
    tpx = pixel_access(tile)
    for j in range(h):
        frac = j / max(1, h - 1)
        if frac < 0.5:
            d = 0.5 * (1 - frac / 0.5)  # navy top → blue mid
            light, dark = BLACK, BLUE
        else:
            d = 0.16 * ((frac - 0.5) / 0.5)  # faint sky-blue sheen toward the foot
            light, dark = WHITE, BLUE
        threshold = round(d * 16)
        row = BAYER_4x4[j % 4]
        for i in range(w):
            tpx[i, j] = light if row[i % 4] < threshold else dark
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    image.paste(tile, (x0, y0), mask)


def _chrono_window_border(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], radius: int) -> None:
    """White rounded double border with small yellow corner accents (FF window)."""
    WHITE = SPECTRA6["white"]
    YELLOW = SPECTRA6["yellow"]
    x0, y0, x1, y1 = rect
    draw.rounded_rectangle(rect, radius=radius, outline=WHITE, width=3)
    draw.rounded_rectangle((x0 + 6, y0 + 6, x1 - 6, y1 - 6), radius=max(2, radius - 4), outline=WHITE, width=1)
    # Small yellow accent ticks just inside each corner.
    for (cx, cy) in ((x0 + 12, y0 + 12), (x1 - 13, y0 + 12), (x0 + 12, y1 - 13), (x1 - 13, y1 - 13)):
        draw.rectangle((cx, cy, cx + 2, cy + 2), fill=YELLOW)


def _chrono_paint_portrait(image: Image.Image, draw: ImageDraw.ImageDraw, run_out: bool = False) -> None:
    """Portrait sub-window (a smaller FF window) holding the shaded hourglass."""
    rect = _CHRONO_PORTRAIT
    _chrono_window_fill(image, rect, radius=14)
    _chrono_window_border(draw, rect, radius=14)
    art_w = _CHRONO_ART_SIZE[0] * _CHRONO_ART_SCALE
    art_h = _CHRONO_ART_SIZE[1] * _CHRONO_ART_SCALE
    cx = (rect[0] + rect[2]) // 2
    cy = (rect[1] + rect[3]) // 2
    _chrono_paint_hourglass(image, cx - art_w // 2, cy - art_h // 2, run_out)


def _chrono_paint_dialogue(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict, rect: tuple[int, int, int, int]) -> None:
    """Speaker-name header + the quote as left-aligned dialogue.

    Author name (uppercased, truncated) as a white Pixelify Sans Bold header
    line, then the quote body below with the matched time-phrase in yellow
    Pixelify Sans Bold — a real weight step, not just a recolour.
    """
    WHITE = SPECTRA6["white"]
    YELLOW = SPECTRA6["yellow"]
    x0, y0, x1, y1 = rect
    box_w = x1 - x0
    # Speaker-name header.
    author = (quote_row.get("author") or "").strip()
    name = (author or "NARRATOR").upper()
    name_font = load_font(theme_font_candidates("chrono", "quote_bold"), size=19)
    while name and draw.textlength(name, font=name_font) > box_w:
        name = name[:-1]
    nb = draw.textbbox((0, 0), name, font=name_font)
    draw.text((x0 - nb[0], y0 - nb[1]), name, font=name_font, fill=WHITE)
    body_top = y0 + (nb[3] - nb[1]) + 8

    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    matched = quote_row.get("matched_text") or ""
    quote_font, quote_font_bold, wrapped_quote, line_height, _ = fit_quote(
        draw, display_quote, matched, box_w, y1 - body_top,
        font_max=54, font_min=14, line_height_mult=1.32, theme="chrono",
    )
    body_ascent = _font_ascent(quote_font)
    y = body_top
    for line in wrapped_quote:
        start = 0
        while start < len(line) and line[start][0].strip() == "":
            start += 1
        end = len(line)
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        x: float = x0
        for chunk, is_bold in line[start:end]:
            font = quote_font_bold if is_bold else quote_font
            chunk_y = y + (body_ascent - _font_ascent(font))
            draw.text((x, chunk_y), chunk, font=font, fill=YELLOW if is_bold else WHITE)
            bbox = draw.textbbox((0, 0), chunk, font=font)
            x += bbox[2] - bbox[0]
        y += line_height


def _chrono_paint_arrow(draw: ImageDraw.ImageDraw) -> None:
    """Yellow ▼ continue arrow in the window's bottom-right."""
    YELLOW = SPECTRA6["yellow"]
    x1, y1 = _CHRONO_WINDOW[2], _CHRONO_WINDOW[3]
    cx, cy = x1 - 30, y1 - 24
    draw.polygon([(cx - 8, cy - 6), (cx + 8, cy - 6), (cx, cy + 7)], fill=YELLOW)


def _chrono_paint_footer(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """'— from {Title} —' in white along the window's bottom inner margin."""
    font = load_font(theme_font_candidates("chrono", "quote_regular"), size=12)
    text = _fit_from_title(draw, quote_row, font, (_CHRONO_WINDOW[2] - _CHRONO_WINDOW[0]) - 140)
    if text is None:
        return
    bbox = draw.textbbox((0, 0), text, font=font)
    cx = (_CHRONO_WINDOW[0] + _CHRONO_WINDOW[2]) // 2 + 50  # nudge clear of the portrait
    fx = cx - (bbox[2] - bbox[0]) // 2 - bbox[0]
    fy = _CHRONO_WINDOW[3] - 18 - bbox[1]
    # Solid white: a sky-blue B+W dither averages too close to the blue window
    # fill to stay legible at this size.
    draw.text((fx, fy), text, font=font, fill=SPECTRA6["white"])


def render_chrono_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """16-bit SNES JRPG dialogue scene (see the module section comment above).

    ``time_str`` is unused (the matched phrase carries the time); kept for
    dispatch-signature uniformity.
    """
    del time_str  # see docstring; deliberately unused.
    image = Image.new("RGB", (width, height), color=SPECTRA6["blue"])
    draw = ImageDraw.Draw(image)
    _chrono_paint_sky(image, draw)
    _chrono_window_fill(image, _CHRONO_WINDOW, radius=18)
    _chrono_window_border(draw, _CHRONO_WINDOW, radius=18)
    _chrono_paint_portrait(image, draw)
    # Dialogue text sits right of the portrait, inside the window.
    px1 = _CHRONO_PORTRAIT[2]
    _chrono_paint_dialogue(image, draw, quote_row, (px1 + 16, _CHRONO_WINDOW[1] + 14, _CHRONO_WINDOW[2] - 24, _CHRONO_WINDOW[3] - 30))
    _chrono_paint_arrow(draw)
    _chrono_paint_footer(image, draw, quote_row)
    return snap_image_to_palette(image, SPECTRA6_PALETTE)


# ─── chrono sleep frame: the End of Time ─────────────────────────────────────
#
# Chrono Trigger's hub between eras: one lamppost burning on a stone platform
# in a dark void. The portrait hourglass has run out, which is the frame's
# whole joke for a clock that has stopped for the night; the narrator promises
# the gates open again at dawn, so it reads as resting rather than ended.
# No figure: the lamp alone carries the scene.
_CHRONO_SLEEP_ROW = {
    "author": "Narrator",
    "display_quote": "You have reached the End of Time. Rest here, traveller; the gates open again at dawn.",
    "matched_text": "dawn",
    "title": "The End of Time",
}
_CHRONO_LAMP_X = 520
_CHRONO_LAMP_HEAD = (_CHRONO_LAMP_X - 14, 62, _CHRONO_LAMP_X + 14, 90)
_CHRONO_PLATFORM = (360, 188, 680, 232)
_CHRONO_VOID_SEED = 0xE0D
_CHRONO_VOID_HAZE = 0.2   # blue density at the platform's horizon
_CHRONO_POOL_CAP = 115    # peak lamplight density on the platform, out of 255 (~45%)


def _chrono_paint_void(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """Black void with a faint blue haze rising toward the platform, and a
    seeded scatter of drifting white motes."""
    px = pixel_access(image)
    width = image.size[0]
    for y in range(min(_CHRONO_SKY_BOTTOM, image.size[1])):
        # BAYER_8x8 for a smooth ramp: the 4x4 tile's 16 levels band visibly.
        threshold = max(0.0, (y - 60) / (_CHRONO_SKY_BOTTOM - 60)) * _CHRONO_VOID_HAZE * 64
        row = BAYER_8x8[y % 8]
        for x in range(width):
            if row[x % 8] < threshold:
                px[x, y] = SPECTRA6["blue"]
    rng = random.Random(_CHRONO_VOID_SEED)
    for _ in range(40):
        draw.point((rng.randint(5, width - 5), rng.randint(5, 180)), fill=SPECTRA6["white"])


def _chrono_paint_platform(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """The stone platform the lamp stands on: a navy-stippled disc, rimmed white,
    with a pool of lamplight stippled across its far half."""
    x0, y0, x1, y1 = _CHRONO_PLATFORM
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    _chrono_fill_poly(image, [(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in
                              (i * math.pi / 36 for i in range(72))],
                      dark=SPECTRA6["blue"], light=SPECTRA6["black"], density=0.45)
    # The pool is a stippled density field, densest under the lamp, clipped to
    # the platform. Not a core-less ``paint_neon_mask``: that paints only the
    # halo *around* its mask, which left a hollow ring spilling into the void.
    pool_box = (_CHRONO_LAMP_X - 80, y0 + 2, _CHRONO_LAMP_X + 80, y0 + 30)
    density = _soft_ellipse_mask(image.size, pool_box, blur=8).point(lambda v: v * _CHRONO_POOL_CAP // 255)
    lit = ImageChops.subtract(density, _bayer_threshold_field(image.size)).point(lambda v: 255 if v else 0)
    platform = Image.new("L", image.size, 0)
    ImageDraw.Draw(platform).ellipse(_CHRONO_PLATFORM, fill=255)
    lit = ImageChops.multiply(lit, platform)
    image.paste(SPECTRA6["yellow"], (0, 0), lit)
    for mask in (density, lit, platform):
        mask.close()
    draw.ellipse(_CHRONO_PLATFORM, outline=SPECTRA6["white"], width=2)


def _chrono_paint_lamppost(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """The lamppost: a yellow lantern blooming into the void, then the post,
    cap and base drawn black with white keylines over the glow."""
    black, white, yellow = SPECTRA6["black"], SPECTRA6["white"], SPECTRA6["yellow"]
    lantern = Image.new("L", image.size, 0)
    ImageDraw.Draw(lantern).rectangle(_CHRONO_LAMP_HEAD, fill=255)
    paint_neon_mask(image, lantern, yellow, yellow, radius=46, gamma=1.1, cap=0.55,
                    ground=frozenset({black, SPECTRA6["blue"]}))
    lantern.close()
    cx = _CHRONO_LAMP_X
    hx0, hy0, hx1, hy1 = _CHRONO_LAMP_HEAD
    base_y = (_CHRONO_PLATFORM[1] + _CHRONO_PLATFORM[3]) // 2
    draw.rectangle((cx - 4, hy1 + 4, cx + 4, base_y - 4), fill=black, outline=white)
    draw.rectangle((cx - 12, base_y - 6, cx + 12, base_y + 4), fill=black, outline=white)
    draw.polygon([(hx0 - 6, hy0), (hx1 + 6, hy0), (hx1 - 2, hy0 - 18), (hx0 + 2, hy0 - 18)], fill=black, outline=white)
    draw.rectangle(_CHRONO_LAMP_HEAD, outline=white)
    draw.line((cx, hy0, cx, hy1), fill=black, width=2)
    draw.line((hx0, (hy0 + hy1) // 2, hx1, (hy0 + hy1) // 2), fill=black, width=2)
    draw.polygon([(hx0 - 4, hy1), (hx1 + 4, hy1), (hx1 - 4, hy1 + 8), (hx0 + 4, hy1 + 8)], fill=black, outline=white)


def render_chrono_sleep(time_str: str, width: int, height: int) -> Image.Image:
    """The sleep frame: the End of Time (see the section comment above).

    Composed at the canonical 800×480 and NEAREST-downsampled, so a preview
    thumbnail shows the whole scene. ``time_str`` is unused: the run-out
    hourglass is the only time surface, and it never changes.
    """
    del time_str
    image = Image.new("RGB", (800, 480), color=SPECTRA6["black"])
    draw = ImageDraw.Draw(image)
    _chrono_paint_void(image, draw)
    _chrono_paint_platform(image, draw)
    _chrono_paint_lamppost(image, draw)
    _chrono_window_fill(image, _CHRONO_WINDOW, radius=18)
    _chrono_window_border(draw, _CHRONO_WINDOW, radius=18)
    _chrono_paint_portrait(image, draw, run_out=True)
    row = dict(_CHRONO_SLEEP_ROW)
    _chrono_paint_dialogue(image, draw, row, (_CHRONO_PORTRAIT[2] + 16, _CHRONO_WINDOW[1] + 14,
                                              _CHRONO_WINDOW[2] - 24, _CHRONO_WINDOW[3] - 30))
    _chrono_paint_arrow(draw)
    _chrono_paint_footer(image, draw, row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("chrono",), render=render_chrono_frame, sleep=render_chrono_sleep)
