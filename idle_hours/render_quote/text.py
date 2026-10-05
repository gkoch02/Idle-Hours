"""Drawing text: plain, faux-grey and dithered inks, chroma shifts, tracked text and the literary body.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .fonts import load_font
from .layout import _bold_stroke_for_theme
from .palette import SPECTRA6, BAYER_4x4
from .theme_tables import _THEMES_WITHOUT_ORNAMENT_MARKS


def draw_text(draw, xy, text, font, fill):
    draw.text(xy, text, font=font, fill=fill)


def draw_faux_gray_text(image: Image.Image, xy, text, font, dark=(0, 0, 0), light=(255, 255, 255), pattern_offset=(0, 0)):
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text(xy, text, font=font, fill=255)
    # Scan only the glyph bbox; pixels outside it are zero in the mask.
    bbox = mask.getbbox()
    if bbox is None:
        return
    x0, y0, x1, y1 = bbox
    px = image.load()
    mx = mask.load()
    ox, oy = pattern_offset
    for y in range(y0, y1):
        for x in range(x0, x1):
            if mx[x, y]:
                px[x, y] = dark if ((x + ox) + (y + oy)) % 2 == 0 else light


def draw_faux_3way_text(
    image: Image.Image,
    xy,
    text,
    font,
    ink_a,
    ink_b,
    ink_c,
    density_a: float,
    density_b: float,
    pattern_offset=(0, 0),
):
    """Paint ``text`` as a three-ink Bayer stipple.

    Partitions the 4×4 Bayer tile by two thresholds: cells below
    ``round(density_a*16)`` get ``ink_a``, below
    ``round((density_a + density_b)*16)`` ``ink_b``, the rest ``ink_c`` —
    the same partition as ``_fill_swatch_stipple_3way``, so text and the
    ``diags`` reference swatch share one hue. Used by ``chanbara``'s quote
    marks (burnt orange, R+Y+G 50/40/10).
    """
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text(xy, text, font=font, fill=255)
    # Bound the scan to the inked glyph region (see draw_faux_gray_text).
    bbox = mask.getbbox()
    if bbox is None:
        return
    bx0, by0, bx1, by1 = bbox
    px = image.load()
    mx = mask.load()
    ox, oy = pattern_offset
    threshold_a = round(density_a * 16)
    threshold_b = round((density_a + density_b) * 16)
    for y in range(by0, by1):
        for x in range(bx0, bx1):
            if mx[x, y]:
                tile = BAYER_4x4[(y + oy) % 4][(x + ox) % 4]
                if tile < threshold_a:
                    px[x, y] = ink_a
                elif tile < threshold_b:
                    px[x, y] = ink_b
                else:
                    px[x, y] = ink_c


def _paint_ornament_mark(image, xy, text, font, theme: str, colors: dict, pattern_offset=(0, 0)) -> None:
    """Dispatch the oversized opening / closing quote-mark painter.

    Most themes paint via ``draw_faux_gray_text`` (a 50/50 checkerboard of
    ``ornament_dark`` / ``ornament_light``). ``chanbara`` uses a three-ink
    burnt-orange stipple (R+Y+G 50/40/10) so the marks read as weathered
    rust-orange rather than solid fire-engine red.
    """
    if theme in _THEMES_WITHOUT_ORNAMENT_MARKS:
        # The marks paint OUTSIDE the body rect, on the stippled paper, where
        # even a page_bg glyph would punch a ghost hole in the wash.
        return
    if theme == "chanbara":
        draw_faux_3way_text(
            image,
            xy,
            text,
            font=font,
            ink_a=SPECTRA6["red"],
            ink_b=SPECTRA6["yellow"],
            ink_c=SPECTRA6["green"],
            density_a=0.50,
            density_b=0.40,
            pattern_offset=pattern_offset,
        )
        return
    draw_faux_gray_text(
        image,
        xy,
        text,
        font=font,
        dark=colors["ornament_dark"],
        light=colors["ornament_light"],
        pattern_offset=pattern_offset,
    )


def draw_text_dithered(image: Image.Image, xy, text, font, dark, light, pattern_offset=(0, 0), light_density: float = 0.5, stroke_width: int = 0):
    """Paint ``text`` as a ``dark``/``light`` Bayer stipple within its bbox.

    Like ``draw_faux_gray_text`` but bbox-limited, which matters because body
    paths call it once per word chunk. Uses the same
    ``((x + ox) + (y + oy)) % 2`` checkerboard so the two paths interleave
    cleanly when a theme uses both.

    ``light_density`` picks the pattern:

    * ``0.5`` (default) — 50/50 checkerboard.
    * ``0.25`` — one ``light`` pixel per 2×2 tile (the ``draw_atomic_border``
      ground pattern).
    * Anything in ``(0.25, 0.5)`` — 4×4 ordered Bayer, ``light`` when
      ``BAYER_4x4[y % 4][x % 4] < round(light_density * 16)``. ``deco`` uses
      0.375 for a red-biased tangerine. The 0.25 and 0.5 branches must stay
      byte-identical for their existing callers.

    The mask is thresholded at ≥128, not every nonzero pixel: antialiased
    edge pixels painted at full ink would grow a 1 px halo that survives
    ``snap_image_to_palette`` as a hot fringe. ≥128 reproduces the silhouette
    plain ``draw.text`` + palette snap produces, so small text doesn't thicken.

    ``stroke_width`` is forwarded to the mask draw as a faux bold (``glacier``
    uses 1 px, since Iceland has no Bold); the bbox is padded by it so the
    thickened rim never clips.
    """
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox(xy, text, font=font, stroke_width=stroke_width)
    x0, y0, x1, y1 = bbox
    # Pad by a pixel for glyph stems that sit on the bbox edge, then clamp.
    pad = 1 + stroke_width
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(image.width, x1 + pad)
    y1 = min(image.height, y1 + pad)
    if x1 <= x0 or y1 <= y0:
        return
    region_w = x1 - x0
    region_h = y1 - y0
    mask = Image.new("L", (region_w, region_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text((xy[0] - x0, xy[1] - y0), text, font=font, fill=255, stroke_width=stroke_width, stroke_fill=255)
    px = image.load()
    mx = mask.load()
    ox, oy = pattern_offset
    if light_density <= 0.25:
        # Sparse 1-in-4: light only where both axes are even in the
        # offset frame, so one light pixel per 2×2 tile (25% light).
        for y in range(region_h):
            ay = y + y0
            for x in range(region_w):
                if mx[x, y] >= 128:
                    ax = x + x0
                    px[ax, ay] = light if ((ax + ox) % 2 == 0 and (ay + oy) % 2 == 0) else dark
    elif light_density >= 0.5:
        for y in range(region_h):
            ay = y + y0
            for x in range(region_w):
                if mx[x, y] >= 128:
                    ax = x + x0
                    px[ax, ay] = dark if ((ax + ox) + (ay + oy)) % 2 == 0 else light
    else:
        # 4×4 ordered Bayer for intermediate densities (deco's 0.375).
        threshold = round(light_density * 16)
        for y in range(region_h):
            ay = y + y0
            for x in range(region_w):
                if mx[x, y] >= 128:
                    ax = x + x0
                    px[ax, ay] = light if BAYER_4x4[(ay + oy) % 4][(ax + ox) % 4] < threshold else dark



def draw_text_chroma_shift(
    image: Image.Image,
    xy,
    text: str,
    font,
    *,
    core=None,
    left=None,
    right=None,
    offset: int = 2,
    ground=None,
) -> None:
    """Paint ``text`` with its colour channels separated, as bled composite video.

    Synthesises a *defect* rather than a colour: the red and blue records of
    an analogue signal drifting out of registration.

    The pass order is load-bearing: the two chroma ghosts go down first at
    opposite horizontal offsets, then the core covers the middle, leaving a
    red fringe on one edge and a blue on the other. Core-first would put
    colour *over* the letterform and read as a coloured outline.

    Unlike ``pulp``'s misregistration (two plates offset one way — a printing
    fault), the separation here is symmetric about the glyph: a signal
    splitting, not a sheet slipping.

    ``ground`` restricts the ghosts to the inks they may overwrite, so a later
    line's fringe cannot eat an earlier line's core (as in
    ``paint_neon_mask``).
    """
    x, y = int(xy[0]), int(xy[1])
    if not text.strip():
        return
    box = font.getbbox(text)
    pad = offset + 2
    w = box[2] - box[0] + 2 * pad
    h = box[3] - box[1] + 2 * pad
    if w <= 0 or h <= 0:
        return
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((pad - box[0], pad - box[1]), text, font=font, fill=255)
    mp = mask.load()
    px = image.load()
    width, height = image.size
    base_x, base_y = x + box[0] - pad, y + box[1] - pad

    for ink, dx in ((left, -offset), (right, offset)):
        if ink is None:
            continue
        for my in range(h):
            iy = base_y + my
            if not 0 <= iy < height:
                continue
            for mx in range(w):
                if mp[mx, my] <= 128:
                    continue
                ix = base_x + mx + dx
                if 0 <= ix < width and (ground is None or px[ix, iy] in ground):
                    px[ix, iy] = ink
    if core is not None:
        for my in range(h):
            iy = base_y + my
            if not 0 <= iy < height:
                continue
            for mx in range(w):
                if mp[mx, my] > 128:
                    ix = base_x + mx
                    if 0 <= ix < width:
                        px[ix, iy] = core
    mask.close()


def _draw_text_body(image: Image.Image, draw, xy, text, font, fill, theme: str):
    """Draw body / attribution text, rerouting per-theme fills to stipples.

    Only the listed (theme, fill) pairs are stippled; everything else is a
    solid ``draw.text``. Most reroutes treat a THEMES slot as a *sentinel* —
    the slot names a native ink and this seam paints the synthesised mix:

    * ``nightvision`` — green body → G+W 1:1 mint; yellow phrase → Y+G
      5/8:3/8 lime.
    * ``grimoire`` — red phrase → B+W sky blue (matches its quote marks).
    * ``gothic`` — red phrase → R+Y 1:1 amber; ``betweenus_dark`` — yellow
      phrase → the same amber.
    * ``deco`` / ``grimdark`` — red phrase → R+Y 5/8:3/8 tangerine (deco's
      matches ``draw_deco_border``'s post-pass threshold).
    * ``blueprint`` / ``scholar`` — red phrase → R+K maroon; ``mucha`` /
      ``fillmore`` — red body → R+K maroon.
    * ``illuminated`` / ``risograph`` — blue phrase → R+B violet.
    * ``bauhaus`` — blue phrase → B+K navy.
    * ``glacier`` — green phrase → G+B 5/8:3/8 teal plus a faux-bold stroke.
    * ``herbarium`` — green phrase → G+K forest green; ``mucha`` — green
      phrase → G+B cyan.
    * ``firmament`` — yellow phrase → Y+W cream; ``anna_atkins`` — yellow
      phrase → B+W sky blue, and every glyph gets a black halo first.

    Border ornaments paint outside this seam, so they keep solid inks.
    """
    if theme == "anna_atkins" and text.strip():
        # anna_atkins draws text straight on the dithered plate, so stamp a
        # thin black outline behind each glyph first; the real glyph is drawn
        # on top by the branches below, inside the black ring.
        draw.text(xy, text, font=font, fill=SPECTRA6["black"], stroke_width=2, stroke_fill=SPECTRA6["black"])
    if theme == "nightvision" and fill == SPECTRA6["green"]:
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["white"])
    elif theme == "grimoire" and fill == SPECTRA6["red"]:
        # Sky blue (B+W 1:1), the recipe this theme's quote marks use, so the
        # phrase and ornaments share one moon-silver register. The red
        # ``accent`` is a sentinel and is never painted — hence ``dark=blue``
        # rather than ``dark=fill`` — which keeps the phrase clear of the
        # border's red pentagrams and sigils. (Solid white left it
        # undifferentiated from the body; a 3/4-red mix read dim.)
        draw_text_dithered(image, xy, text, font, dark=SPECTRA6["blue"], light=SPECTRA6["white"])
    elif theme == "gothic" and fill == SPECTRA6["red"]:
        # Amber (R+Y 1:1): warm candle-flame on black, clear of the red
        # border ornaments.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["yellow"])
    elif theme == "deco" and fill == SPECTRA6["red"]:
        # 3/8 yellow on 5/8 red on BAYER_4x4; must match
        # ``draw_deco_border``'s post-pass threshold so phrase and border
        # share one tangerine.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["yellow"], light_density=0.375)
    elif theme in ("blueprint", "scholar") and fill == SPECTRA6["red"]:
        # Maroon (R+K 1:1): blueprint's red pencil pressed hard, scholar's
        # aged red-lead annotation. Border marks stay solid red.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["black"])
    elif theme == "illuminated" and fill == SPECTRA6["blue"]:
        # Violet (R+B 1:1) — Tyrian purple, in the same register as the
        # border's R+B+K plum cabochons. The red body never hits this branch.
        draw_text_dithered(image, xy, text, font, dark=SPECTRA6["red"], light=SPECTRA6["blue"])
    elif theme == "glacier" and fill == SPECTRA6["green"]:
        # Teal (G+B 5/8:3/8, Bayer threshold 6/16). 50/50 cyan read too close
        # to the blue body and solid green read muddy; the green bias pulls
        # the phrase off the body while staying cool. Plus a
        # ``stroke_width=1`` faux bold, since Iceland ships only Regular and
        # hue alone doesn't carry the differentiation.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["blue"], light_density=0.375, stroke_width=_bold_stroke_for_theme(theme))
    elif theme == "risograph" and fill == SPECTRA6["blue"]:
        # Violet (R+B 1:1) — the riso red-over-blue overprint. Keeps the
        # theme's no-black invariant by construction.
        draw_text_dithered(image, xy, text, font, dark=SPECTRA6["red"], light=fill)
    elif theme == "bauhaus" and fill == SPECTRA6["blue"]:
        # Navy (B+K 1:1), a deeper variant of the border's solid blue square
        # so all three primaries still show solid in the border.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["black"])
    elif theme == "nightvision" and fill == SPECTRA6["yellow"]:
        # Lime (Y+G 5/8:3/8, density 0.375): yellow-biased because a 50/50
        # Y+G reads washed-out olive — the HUD readout glow.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["green"], light_density=0.375)
    elif theme == "herbarium" and fill == SPECTRA6["green"]:
        # Forest green (G+K 1:1, the recipes doc's dark green): pressed plant
        # material against the cream ground, distinct from the border's Y+G
        # olive leaf.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["black"])
    elif theme in ("mucha", "fillmore") and fill == SPECTRA6["red"]:
        # Maroon (R+K 1:1). Both themes keep the red sentinel in ``text`` so
        # every body path hits this seam:
        #
        # * ``mucha`` — a synthesised body colour, the oxblood of period
        #   poster lettering; its green phrase lands on cyan below.
        # * ``fillmore`` — tames the fatiguing red-on-yellow body, as red ink
        #   darkened on yellow stock. The blue phrase and blob primaries stay
        #   solid, so all six inks still appear.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["black"])
    elif theme == "mucha" and fill == SPECTRA6["green"]:
        # Cyan (G+B 1:1): a cool accent against the warm maroon body.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["blue"])
    elif theme == "firmament" and fill == SPECTRA6["yellow"]:
        # Cream (Y+W 1:1): gilt constellation labels on the navy ground.
        # The white body falls through to the ``else`` branch.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["white"])
    elif theme == "grimdark" and fill == SPECTRA6["red"]:
        # Forge amber (R+Y 5/8:3/8 on BAYER_4x4, as ``deco``): molten metal on
        # the bulkhead, tied to the gold trim. 50/50 would read washed-out
        # because yellow out-luminates red.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["yellow"], light_density=0.375)
    elif theme == "anna_atkins" and fill == SPECTRA6["yellow"]:
        # Yellow sentinel → B+W sky blue (the ``glacier`` recipe): a ghostly
        # cyanotype element distinct from the crisp white body. The yellow
        # shows literally only in the debug banner, outside this seam.
        draw_text_dithered(image, xy, text, font, dark=SPECTRA6["blue"], light=SPECTRA6["white"])
    elif theme == "betweenus_dark" and fill == SPECTRA6["yellow"]:
        # Yellow sentinel → R+Y 1:1 amber, the apricot the app's dark
        # ``want`` (#DFA07C) lands on. On black the mix's brightness is the
        # point; the recipes doc's washed-out caveat is about white grounds.
        draw_text_dithered(image, xy, text, font, dark=SPECTRA6["red"], light=SPECTRA6["yellow"])
    else:
        draw.text(xy, text, font=font, fill=fill)


def tracked_width(draw, text: str, font, *, tracking: float) -> float:
    """Width of ``text`` as ``draw_tracked`` will paint it: per-glyph advances
    plus ``tracking`` between glyphs. A per-glyph sum, not ``textlength`` of the
    whole string, because the glyph-by-glyph draw drops kerning."""
    if not text:
        return 0.0
    return sum(draw.textlength(ch, font=font) for ch in text) + tracking * (len(text) - 1)


def draw_tracked(draw, xy, text: str, font, fill, *, tracking: float, anchor_right: bool = False) -> float:
    """Letterspaced caps — an instrument panel's silkscreened legend, a
    wayfinding sign, a banknote masthead. Returns the run's width.

    PIL has no tracking, so the string is stepped a glyph at a time. Works
    against an ``"L"`` bloom mask as readily as against the image. With
    ``anchor_right`` the run ends at ``xy[0]`` instead of starting there.
    """
    x, y = xy
    width = tracked_width(draw, text, font, tracking=tracking)
    if anchor_right:
        x -= width
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return width


def fit_text_to_width(draw, text: str, candidates, size: int, max_width: float, *,
                      floor: int, tracking: float = 0):
    """Shrink a chrome string until it fits, then ellipsise at the floor.

    Returns ``(font, text)``. The floor keeps the string readable across a
    room; below it the value is truncated with an ellipsis instead of shrunk
    further. Measured the way it will be painted: as one kerned run when
    ``tracking`` is 0, glyph by glyph (via ``tracked_width``) otherwise.
    """
    def measure(candidate: str, font) -> float:
        if tracking:
            return tracked_width(draw, candidate, font, tracking=tracking)
        return draw.textlength(candidate, font=font)

    while size > floor:
        font = load_font(candidates, size=size)
        if measure(text, font) <= max_width:
            return font, text
        size -= 2
    font = load_font(candidates, size=floor)
    while len(text) > 1 and measure(text, font) > max_width:
        text = text[:-2].rstrip(" ,.;:") + "…"
    return font, text
