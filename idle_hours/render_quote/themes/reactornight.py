"""The ``reactornight`` theme: Nightdraft's Reactor Night instrument panel, with the quote in its nixie tube.

Design notes: docs/themes.md § reactornight
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .._paths import JOST_VARIABLE, META_FONT_BOLD_CANDIDATES, META_FONT_CANDIDATES, SHARETECHMONO_REGULAR
from ..fonts import load_font
from ..furniture import _clock_hh_mm, _clock_hour12, fallback_title
from ..palette import _PANEL_INKS, SPECTRA6, SPECTRA6_PALETTE, _dither_calibrated, snap_image_to_palette
from ..primitives import _fill_swatch_stipple, paint_neon_mask, wrap_quote_into_masks
from ..spec import FrameSpec
from ..text import draw_tracked, fit_text_to_width, tracked_width

_REACTORNIGHT_MARGIN = 24
_REACTORNIGHT_LEGENDS = ("RUNNING", "MORNING", "AFTERNOON", "EVENING", "NIGHT", "STANDBY")
_REACTORNIGHT_LAMP_TOP, _REACTORNIGHT_LAMP_H, _REACTORNIGHT_LAMP_GAP = 60, 30, 8
_REACTORNIGHT_BEZEL = (24, 104, 776, 398)
_REACTORNIGHT_GLASS = (30, 110, 770, 392)
_REACTORNIGHT_TUBE_X = (52, 748)
_REACTORNIGHT_DIVIDER_Y = 210
_REACTORNIGHT_QUOTE_RECT = (52, 222, 748, 380)
_REACTORNIGHT_PLATE = (24, 414, 776, 448)
# The ground and the bezel as fractions of the way from the white ink to the
# black: graphite, and the bezel's lighter ring round the tube.
_REACTORNIGHT_GROUND = 0.93
_REACTORNIGHT_BEZEL_TONE = 0.80
_REACTORNIGHT_SCENE: dict = {}
_REACTORNIGHT_SLEEP_ROW: dict[str, str] = {
    "display_quote": "The fan is off and the house is cooling. The tube stays dark until morning.",
    "matched_text": "until morning",
    "author": "Nightdraft",
    "title": "Standby",
}


def _reactornight_tone(t: float) -> tuple[int, int, int]:
    """A grey ``t`` of the way from the white ink to the black ink."""
    r, g, b = (round(w + (k - w) * t) for w, k in zip(_PANEL_INKS["white"], _PANEL_INKS["black"], strict=True))
    return r, g, b


def _reactornight_label(size: int, weight: str = "Bold"):
    return load_font([(JOST_VARIABLE, weight), *META_FONT_BOLD_CANDIDATES], size=size)


def _reactornight_mono(size: int):
    return load_font([SHARETECHMONO_REGULAR, *META_FONT_CANDIDATES], size=size)


def _reactornight_lamp_rects() -> list[tuple[int, int, int, int]]:
    n = len(_REACTORNIGHT_LEGENDS)
    left, right = _REACTORNIGHT_MARGIN, 800 - _REACTORNIGHT_MARGIN
    w = (right - left - (n - 1) * _REACTORNIGHT_LAMP_GAP) / n
    rects = []
    for i in range(n):
        x0 = round(left + i * (w + _REACTORNIGHT_LAMP_GAP))
        rects.append((x0, _REACTORNIGHT_LAMP_TOP, round(x0 + w), _REACTORNIGHT_LAMP_TOP + _REACTORNIGHT_LAMP_H))
    return rects


def _reactornight_daypart(hour24: int) -> str:
    """The daypart lamp lit for a 24-hour clock hour: morning from five,
    afternoon from noon, evening from five, night from nine."""
    if 5 <= hour24 < 12:
        return "MORNING"
    if 12 <= hour24 < 17:
        return "AFTERNOON"
    if 17 <= hour24 < 21:
        return "EVENING"
    return "NIGHT"


def _reactornight_paint_brass(image: Image.Image, rect, radius: int, width: int = 2) -> None:
    """A brass rim: a ring ``width`` px wide round ``rect``, aged brass as a
    yellow and black half stipple."""
    ring = Image.new("L", image.size, 0)
    ImageDraw.Draw(ring).rounded_rectangle(rect, radius=radius, outline=255, width=width)
    brass = image.copy()
    _fill_swatch_stipple(brass, ring.getbbox() or (0, 0, 0, 0), SPECTRA6["black"], SPECTRA6["yellow"], 0.5)
    image.paste(brass, (0, 0), ring)
    ring.close()
    brass.close()


def _reactornight_scene() -> Image.Image:
    """The graphite panel, the bezel and the tube's black glass, dithered;
    painted once per process."""
    cached = _REACTORNIGHT_SCENE.get("frame")
    if cached is not None:
        return cached
    size = (800, 480)
    scene = Image.new("RGB", size, _reactornight_tone(_REACTORNIGHT_GROUND))
    draw = ImageDraw.Draw(scene)
    x0, y0, x1, y1 = _REACTORNIGHT_BEZEL
    draw.rounded_rectangle((x0 + 2, y0 + 4, x1 + 2, y1 + 4), radius=11, fill=_PANEL_INKS["black"])
    draw.rounded_rectangle(_REACTORNIGHT_BEZEL, radius=11, fill=_reactornight_tone(_REACTORNIGHT_BEZEL_TONE))
    draw.rounded_rectangle((x0, y0, x1, y0 + 14), radius=11, fill=_reactornight_tone(_REACTORNIGHT_BEZEL_TONE - 0.08))
    image = _dither_calibrated(scene, ("white", "black"))
    # After the dither, in solid ink: the glass is tube-black throughout.
    ImageDraw.Draw(image).rounded_rectangle(_REACTORNIGHT_GLASS, radius=7, fill=SPECTRA6["black"])
    scene.close()
    _REACTORNIGHT_SCENE["frame"] = image
    return image


def _reactornight_paint_header(draw: ImageDraw.ImageDraw, image: Image.Image) -> None:
    """"LITERARY CLOCK" engraved at the left, the UNIT 01 plate at the right."""
    white = SPECTRA6["white"]
    draw_tracked(draw, (_REACTORNIGHT_MARGIN, 24), "LITERARY CLOCK", _reactornight_label(16), white, tracking=4)
    font = _reactornight_label(10, "Medium")
    text = "UNIT 01"
    w = tracked_width(draw, text, font, tracking=2) + 24
    x1 = 800 - _REACTORNIGHT_MARGIN
    rect = (round(x1 - w), 22, x1, 46)
    draw.rounded_rectangle(rect, radius=3, fill=SPECTRA6["black"])
    _reactornight_paint_brass(image, rect, 3)
    draw_tracked(draw, (rect[0] + 12, 28), text, font, white, tracking=2)


def _reactornight_paint_lamps(image: Image.Image, lit: dict[str, str]) -> None:
    """The annunciator: each lamp a cell behind brass. A lamp named in
    ``lit`` is filled with that ink, its legend in white (black on yellow);
    the rest are dark cells with their legends still readable."""
    draw = ImageDraw.Draw(image)
    font = _reactornight_label(11)
    for rect, legend in zip(_reactornight_lamp_rects(), _REACTORNIGHT_LEGENDS, strict=True):
        ink = lit.get(legend)
        draw.rounded_rectangle(rect, radius=5, fill=SPECTRA6[ink] if ink else SPECTRA6["black"])
        _reactornight_paint_brass(image, rect, 5)
        fg = SPECTRA6["black"] if ink == "yellow" else SPECTRA6["white"]
        tw = tracked_width(draw, legend, font, tracking=2)
        draw_tracked(draw, ((rect[0] + rect[2] - tw) / 2, rect[1] + 8), legend, font, fg, tracking=2)


def _reactornight_paint_tube(image: Image.Image, hour: str, volume: str, line: str) -> None:
    """The tube's printed channel names and divider, and its readouts lit:
    the hour over as many unlit "8"s as it has digits (a sparse green
    stipple, an undriven cathode), and the book and line at the right. The
    readouts' cores are white with a share of green, in a green bloom: the
    panel's green ink alone is too dark to read as lit on the black glass."""
    draw = ImageDraw.Draw(image)
    white, green, black = SPECTRA6["white"], SPECTRA6["green"], SPECTRA6["black"]
    left, right = _REACTORNIGHT_TUBE_X
    label = _reactornight_label(10, "Medium")
    draw_tracked(draw, (left, 124), "HOUR", label, white, tracking=2.5)
    draw_tracked(draw, (right, 124), "VOLUME", label, white, tracking=2.5, anchor_right=True)
    draw.line((left, _REACTORNIGHT_DIVIDER_Y, right, _REACTORNIGHT_DIVIDER_Y), fill=green, width=1)
    hero = _reactornight_mono(68)
    ghost = Image.new("L", image.size, 0)
    ImageDraw.Draw(ghost).text((left, 132), "8" * len(hour), font=hero, fill=255)
    unlit = image.copy()
    _fill_swatch_stipple(unlit, ghost.getbbox() or (0, 0, 0, 0), black, green, 0.5)
    image.paste(unlit, (0, 0), ghost.point(lambda v: 255 if v > 128 else 0))
    unlit.close()
    ghost.close()
    mask = Image.new("L", image.size, 0)
    md = ImageDraw.Draw(mask)
    md.text((left, 132), hour, font=hero, fill=255)
    md.text((left + draw.textlength(hour, font=hero) + 10, 170), "/12", font=_reactornight_mono(22), fill=255)
    big, small = _reactornight_mono(36), _reactornight_mono(17)
    md.text((right - draw.textlength(volume, font=big), 140), volume, font=big, fill=255)
    md.text((right - draw.textlength(line, font=small), 182), line, font=small, fill=255)
    paint_neon_mask(image, mask, white, green, radius=3, gamma=1.6, cap=0.55, ground=(black,),
                    core_minor=green, core_minor_share=0.3)
    mask.close()


def _reactornight_paint_quote(image: Image.Image, quote_row: dict) -> None:
    """The quote in the tube, flush left: white cores in a green bloom, the
    phrase in amber, the panel's time channel."""
    draw = ImageDraw.Draw(image)
    prose, hot, _ = wrap_quote_into_masks(draw, image.size, quote_row, _REACTORNIGHT_QUOTE_RECT, theme="reactornight",
                                          font_max=30, font_min=15, line_height_mult=1.32, align="left")
    black, green = SPECTRA6["black"], SPECTRA6["green"]
    paint_neon_mask(image, prose, SPECTRA6["white"], green, radius=2, gamma=1.8, cap=0.4, ground=(black,))
    paint_neon_mask(image, hot, SPECTRA6["yellow"], green, radius=2.5, gamma=1.5, cap=0.5, ground=(black,))
    prose.close()
    hot.close()


def _reactornight_byline(quote_row: dict) -> str:
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "").strip()
    return "  —  ".join(p.upper() for p in (author, title) if p) or "PROJECT GUTENBERG"


def _reactornight_paint_plate(image: Image.Image, text: str, *, lit: bool) -> None:
    """The verdict plate under the tube: lit green with the byline in white,
    or a dark cell."""
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = _REACTORNIGHT_PLATE
    draw.rounded_rectangle(_REACTORNIGHT_PLATE, radius=6, fill=SPECTRA6["green"] if lit else SPECTRA6["black"])
    _reactornight_paint_brass(image, _REACTORNIGHT_PLATE, 6)
    candidates = [(JOST_VARIABLE, "Bold"), *META_FONT_BOLD_CANDIDATES]
    font, fitted = fit_text_to_width(draw, text, candidates, 13, x1 - x0 - 48, floor=11, tracking=2)
    tw = tracked_width(draw, fitted, font, tracking=2)
    draw_tracked(draw, ((x0 + x1 - tw) / 2, y0 + 9), fitted, font, SPECTRA6["white"], tracking=2)


def _reactornight_finish(image: Image.Image, width: int, height: int) -> Image.Image:
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


def render_reactornight_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Nightdraft's Reactor Night panel: RUNNING and the hour's daypart lit,
    the hour, the book and its line in the tube's readouts, the quote in the
    tube and the byline on the lit plate (see docs/themes.md)."""
    hour24, _minute = _clock_hh_mm(time_str)
    image = _reactornight_scene().copy()
    draw = ImageDraw.Draw(image)
    _reactornight_paint_header(draw, image)
    _reactornight_paint_lamps(image, {"RUNNING": "green", _reactornight_daypart(hour24): "yellow"})
    source = str(quote_row.get("source_id") or "").strip()
    line = quote_row.get("line_number")
    _reactornight_paint_tube(image, str(_clock_hour12(time_str)), f"#{source}" if source else "-----",
                             f"LINE {line}" if line not in (None, "") else "LINE ----")
    _reactornight_paint_quote(image, quote_row)
    _reactornight_paint_plate(image, _reactornight_byline(quote_row), lit=True)
    return _reactornight_finish(image, width, height)


def render_reactornight_sleep(time_str: str, width: int, height: int) -> Image.Image:
    """The quiet-hours frame: the fan stopped and the panel on standby.
    RUNNING dark, NIGHT and STANDBY lit, the readouts dashed, and the plate
    a dark cell. ``time_str`` is unused: nothing on the frame tells the time."""
    del time_str
    image = _reactornight_scene().copy()
    draw = ImageDraw.Draw(image)
    _reactornight_paint_header(draw, image)
    _reactornight_paint_lamps(image, {"NIGHT": "yellow", "STANDBY": "red"})
    _reactornight_paint_tube(image, "--", "-----", "LINE ----")
    _reactornight_paint_quote(image, _REACTORNIGHT_SLEEP_ROW)
    _reactornight_paint_plate(image, "STANDBY  —  RESUMES AT DAWN", lit=False)
    return _reactornight_finish(image, width, height)


SPEC = FrameSpec(themes=("reactornight",), render=render_reactornight_frame, sleep=render_reactornight_sleep)
