"""The ``autochrome`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .._paths import META_FONT_BOLD_CANDIDATES
from ..fonts import load_font, normalize_dashes, theme_font_candidates
from ..furniture import draw_centred_styled_lines, draw_truncated_centred_byline, paint_mount_card
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, _load_dithered_plate, snap_image_to_palette
from ..spec import FrameSpec
from ._shared import _AUTOCHROME_PALETTE, AUTOCHROME_PLATE, _autochrome_paint_garden_fallback

# ---------------------------------------------------------------------------
# autochrome — a colour photograph, in the panel's own idiom
#
# Autochrome Lumière plates were a stochastic mosaic of dyed starch grains
# the eye integrates — the same object as a dither to six inks. Full design
# notes: docs/themes.md (``autochrome``).
#
# The only plate dithered against the full six-ink palette: the other plate
# themes restrict the candidates so diffusion cannot scatter chroma into
# their ground, but here the chroma is the subject. The source is muted and
# high-key on purpose: a saturated source quantises to chunky colour bars,
# while a soft desaturated one breaks into fine grain. The committed garden
# (``scripts/generate_autochrome_plate.py``) puts all six inks on the page;
# ``TestAutochromePlate`` checks every ink is present and none but white
# dominates.
#
# The mount is a passe-partout of black binding tape; the quote sits on a
# cream card on a black shadow ledge (``paint_mount_card``). The matched
# phrase is solid red: the nearest solid ink to the dominant orange-red
# grain, and a two-ink stipple at caption size shreds a serif.
#
# A photograph carries no clock: ``time_str`` is del-asserted. Composed at
# 800x480 and NEAREST-downsampled otherwise (the ``metro`` convention).
_AUTOCHROME_TAPE = 13                       # passe-partout binding tape, px
_AUTOCHROME_CORNER = 7                      # extra reach where tape strips overlap
_AUTOCHROME_CARD = (458, 56, 770, 424)      # the caption card
_AUTOCHROME_LEDGE = 3                       # the card's drop shadow


def _autochrome_paint_plate(image: Image.Image) -> None:
    """The photograph: the committed garden, Floyd-Steinberg-dithered against
    all six inks, full bleed."""
    plate = _load_dithered_plate(AUTOCHROME_PLATE, 800, 480, palette=_AUTOCHROME_PALETTE)
    if plate is None:
        _autochrome_paint_garden_fallback(image)
        return
    image.paste(plate, (0, 0))


def _autochrome_paint_tape(draw: ImageDraw.ImageDraw) -> None:
    """The passe-partout: black gummed tape binding the glass sandwich, with a
    hairline of light at the paper mask's edge just inside it. The corners
    are thicker where the four strips overlap, which reads as tape rather
    than as a drawn frame.
    """
    black, white = SPECTRA6["black"], SPECTRA6["white"]
    t = _AUTOCHROME_TAPE
    draw.rectangle((0, 0, 799, t - 1), fill=black)
    draw.rectangle((0, 480 - t, 799, 479), fill=black)
    draw.rectangle((0, 0, t - 1, 479), fill=black)
    draw.rectangle((800 - t, 0, 799, 479), fill=black)
    c = t + _AUTOCHROME_CORNER
    for x0, y0 in ((0, 0), (800 - c, 0), (0, 480 - c), (800 - c, 480 - c)):
        draw.rectangle((x0, y0, x0 + c - 1, y0 + c - 1), fill=black)
    draw.rectangle((t, t, 799 - t, 479 - t), outline=white, width=1)


def _autochrome_paint_card(image: Image.Image, draw: ImageDraw.ImageDraw,
                           quote_row: dict) -> None:
    """The caption card: cream stock on a shadow ledge, carrying the quote in
    Libre Caslon with the matched phrase in the studio's red ink."""
    x0, y0, x1, y1 = _AUTOCHROME_CARD
    black, red = SPECTRA6["black"], SPECTRA6["red"]
    paint_mount_card(image, draw, _AUTOCHROME_CARD, ledge=_AUTOCHROME_LEDGE)

    # Mount chrome: the process name letterspaced with plain spaces under a
    # hairline rule, in the metadata sans.
    draw.text(((x0 + x1) // 2, y0 + 18), " ".join("AUTOCHROME"),
              font=load_font(META_FONT_BOLD_CANDIDATES, size=10), fill=black, anchor="ms")
    draw.line((x0 + 34, y0 + 26, x1 - 34, y0 + 26), fill=black, width=1)

    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    quote_font, quote_font_bold, wrapped, line_height, _ = fit_quote(
        draw, display_quote, quote_row.get("matched_text") or "",
        x1 - x0 - 36, y1 - y0 - 92, font_max=26, font_min=13,
        line_height_mult=1.34, theme="autochrome",
    )
    draw_centred_styled_lines(
        draw, wrapped, x0=x0, x1=x1, top=y0 + 46, line_height=line_height,
        regular=quote_font, bold=quote_font_bold, fill=black, accent=red,
    )
    draw_truncated_centred_byline(
        draw, quote_row, centre=(x0 + x1) // 2, baseline=y1 - 18,
        max_width=x1 - x0 - 30, fill=black,
        font=load_font(theme_font_candidates("autochrome", "quote_regular"), size=13),
    )


def render_autochrome_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """An autochrome plate in its passe-partout (see the section comment)."""
    del time_str  # a photograph carries no clock; see the section comment.
    image = Image.new("RGB", (800, 480), color=SPECTRA6["white"])
    _autochrome_paint_plate(image)
    draw = ImageDraw.Draw(image)
    _autochrome_paint_tape(draw)
    _autochrome_paint_card(image, draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("autochrome",), render=render_autochrome_frame)
