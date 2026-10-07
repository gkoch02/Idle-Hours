"""The ``yorha`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw, ImageFilter

from .._paths import EBGARAMOND_BOLD, EBGARAMOND_REGULAR, META_FONT_BOLD_CANDIDATES, META_FONT_CANDIDATES
from ..fonts import load_font
from ..furniture import _clock_hour12, _paint_placed, _place_quote, _row_digest, fallback_title
from ..palette import _PANEL_INKS, SPECTRA6, SPECTRA6_PALETTE, BAYER_4x4, _dither_calibrated, pixel_access, snap_image_to_palette
from ..primitives import _shade_silhouette, _shift_no_wrap
from ..spec import FrameSpec
from ..text import draw_tracked, fit_text_to_width
from ._shared import _lumon_hover_boxes

# ---------------------------------------------------------------------------
# yorha — *NieR: Automata* (2017): the YoRHa system menu, Intel › Archives
# ---------------------------------------------------------------------------
# The pause menu's Intel › Archives: a cream sheet hatched and dotted over
# the blurred city, a dark tab bar, a boxed menu with the selected row
# inverted, a content pane, and Pod 042. Full design notes: docs/themes.md
# (``yorha``).
#
# The sheet (vignette, blurred city silhouettes, diagonal hatch, the panels'
# soft shadows) and the Pod (``_shade_silhouette`` under the upper-left light) are
# painted in continuous tone and Floyd–Steinberg dithered to white, yellow and
# black (``_dither_calibrated``). Panel faces, hairlines, corner ticks, dot
# grid, tab bar, crest and type go on after the dither.
#
# The hour is the open entry: ARCHIVE 01..12, the hour's row inverted with a
# white pointer and the pane's counter reading ``NN / 12``. The quote is EB
# Garamond (the closest open face to the game's UI serif), the matched phrase
# knocked out white of a black box, the game's selected-item mark. Pinned
# across the minutes; the matched phrase carries the minute. One glitch sliver
# at the pane's foot is seeded from the quote. Composed at 800x480 and
# NEAREST-downsampled otherwise (the ``metro`` convention).
# ---------------------------------------------------------------------------
_YORHA_SEED = 0x594F5248              # YORH
_YORHA_INKS = ("white", "yellow", "black")
_YORHA_DOT_PITCH = 16
_YORHA_HATCH_PITCH = 9
_YORHA_HEADER_RECT = (0, 18, 800, 54)
_YORHA_TABS = ("MAP", "QUESTS", "ITEMS", "WEAPONS", "SKILLS", "INTEL", "SYSTEM")
_YORHA_MENU_RECT = (30, 76, 226, 388)
_YORHA_POD_CENTRE = (112, 428)
_YORHA_PANE_RECT = (254, 76, 770, 448)
_YORHA_QUOTE_RECT = (272, 134, 752, 398)
_YORHA_BYLINE_Y = 416
_YORHA_SCENE: dict = {}


def _yorha_cream(y: float, k: float = 0.0) -> tuple[int, int, int]:
    """A calibrated mix: white with ``y`` of yellow and ``k`` of black."""
    w, yel, blk = (_PANEL_INKS[n] for n in ("white", "yellow", "black"))
    r, g, bl = (round(a * (1 - y - k) + b * y + c * k) for a, b, c in zip(w, yel, blk, strict=True))
    return r, g, bl


def _yorha_font(size: int, weight: str = "Regular"):
    """EB Garamond: the two static cuts, with the lighter labels on Regular
    and the emphasised ones on Bold."""
    file = EBGARAMOND_BOLD if weight in ("SemiBold", "Bold") else EBGARAMOND_REGULAR
    return load_font([file, *META_FONT_CANDIDATES], size=size)


def _yorha_menu_rows() -> list:
    x0, y0, x1, y1 = _YORHA_MENU_RECT
    step = (y1 - y0) // 12
    return [(x0, y0 + i * step, x1, y0 + i * step + step - 4) for i in range(12)]


def _yorha_scene() -> Image.Image:
    """The sheet, the panels, the shadows and the Pod — everything the hour
    and the quote do not touch — dithered and ruled. Painted once per
    process."""
    key = (_yorha_paint_ground, _yorha_paint_panels, _yorha_paint_pod_tone, _yorha_paint_rules)
    cached = _YORHA_SCENE.get("frame")
    if cached is not None and cached[0] == key:
        return cached[1]
    size = (800, 480)
    scene = Image.new("RGB", size, _yorha_cream(0.25))
    _yorha_paint_ground(scene)
    _yorha_paint_panels(scene)
    _yorha_paint_pod_tone(scene)
    image = _dither_calibrated(scene, _YORHA_INKS)
    _yorha_paint_rules(image)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)       # the tab bar's type is antialiased
    _YORHA_SCENE["frame"] = (key, image)
    return image


def _yorha_paint_ground(scene: Image.Image) -> None:
    """The cream sheet in tone: a vignette, the blurred city along the foot,
    and the diagonal hatch."""
    size = scene.size
    width, height = size
    vignette = Image.new("L", (width // 4, height // 4), 0)
    vp = pixel_access(vignette)
    cx, cy = vignette.size[0] / 2.0, vignette.size[1] / 2.0
    rmax = math.hypot(cx, cy)
    for y in range(vignette.size[1]):
        for x in range(vignette.size[0]):
            t = (math.hypot(x + 0.5 - cx, y + 0.5 - cy) / rmax) ** 2.6
            vp[x, y] = int(255 * min(1.0, t * 0.5))
    vignette = vignette.resize(size, Image.Resampling.BICUBIC)
    scene.paste(Image.new("RGB", size, _yorha_cream(0.22, 0.42)), (0, 0), vignette)
    # The city: blurred silhouettes along the foot, the world behind the menu.
    rng = random.Random(_YORHA_SEED + 1)
    city = Image.new("L", size, 0)
    cd = ImageDraw.Draw(city)
    x = -20
    while x < width + 20:
        w = rng.randint(24, 70)
        h = rng.randint(30, 110)
        cd.rectangle((x, height - h, x + w, height + 20), fill=rng.randint(120, 220))
        x += w + rng.randint(4, 18)
    city = city.filter(ImageFilter.GaussianBlur(9)).point(lambda v: int(v * 0.55))
    scene.paste(Image.new("RGB", size, _yorha_cream(0.18, 0.62)), (0, 0), city)
    # The hatch: fine diagonals, a shade darker, that dither to faint dashes.
    hatch = Image.new("L", size, 0)
    hd = ImageDraw.Draw(hatch)
    for d in range(-height, width + height, _YORHA_HATCH_PITCH):
        hd.line((d, 0, d + height, height), fill=255, width=1)
    scene.paste(Image.new("RGB", size, _yorha_cream(0.30, 0.16)), (0, 0), hatch.point(lambda v: int(v * 0.55)))
    for m in (vignette, city, hatch):
        m.close()


def _yorha_panel_rects() -> list:
    return [_YORHA_PANE_RECT, *_yorha_menu_rows()]


def _yorha_paint_panels(scene: Image.Image) -> None:
    """The pane and the menu rows in tone: their soft shadows on the sheet,
    and a lighter cream under them (the fill itself is laid crisp after the
    dither — error diffusion worms at a light density, and a page should
    not)."""
    size = scene.size
    panels = Image.new("L", size, 0)
    pd = ImageDraw.Draw(panels)
    for rect in _yorha_panel_rects():
        pd.rectangle(rect, fill=255)
    shadow = _shift_no_wrap(panels, 4, 5).filter(ImageFilter.GaussianBlur(4)).point(lambda v: int(v * 0.7))
    scene.paste(Image.new("RGB", size, _yorha_cream(0.20, 0.5)), (0, 0), shadow)
    scene.paste(Image.new("RGB", size, _yorha_cream(0.12)), (0, 0), panels)
    panels.close()
    shadow.close()


def _yorha_fill_panel(image: Image.Image, rect) -> None:
    """A panel's face: white with a yellow eighth on the 4x4 Bayer tile."""
    x0, y0, x1, y1 = rect
    px = pixel_access(image)
    white, yellow = SPECTRA6["white"], SPECTRA6["yellow"]
    for y in range(y0, y1 + 1):
        row = BAYER_4x4[y % 4]
        for x in range(x0, x1 + 1):
            px[x, y] = yellow if row[x % 4] < 2 else white


def _yorha_paint_pod_tone(scene: Image.Image) -> None:
    """Pod 042 in tone: a capsule hull shaded under the upper-left light,
    its face plate, its fins, and its shadow on the sheet."""
    size = scene.size
    cx, cy = _YORHA_POD_CENTRE
    shadow = Image.new("L", size, 0)
    ImageDraw.Draw(shadow).ellipse((cx - 52, cy + 30, cx + 56, cy + 44), fill=255)
    shadow = shadow.filter(ImageFilter.GaussianBlur(5)).point(lambda v: int(v * 0.6))
    scene.paste(Image.new("RGB", size, _yorha_cream(0.18, 0.55)), (0, 0), shadow)
    hull = Image.new("L", size, 0)
    hd = ImageDraw.Draw(hull)
    hd.rounded_rectangle((cx - 58, cy - 20, cx + 38, cy + 20), radius=20, fill=255)
    hd.polygon([(cx - 40, cy - 20), (cx - 18, cy - 40), (cx, cy - 20)], fill=255)          # the dorsal fin
    hd.polygon([(cx - 48, cy + 18), (cx - 64, cy + 34), (cx - 26, cy + 20)], fill=255)     # the ventral fin
    body = _shade_silhouette(hull, _yorha_cream(0.12, 0.16), _yorha_cream(0.06, 0.0), _yorha_cream(0.16, 0.58),
                         offset=6, blur=4)
    scene.paste(body, (0, 0), hull)
    face = Image.new("L", size, 0)
    ImageDraw.Draw(face).rounded_rectangle((cx + 16, cy - 15, cx + 46, cy + 15), radius=7, fill=255)
    plate = _shade_silhouette(face, _yorha_cream(0.10, 0.70), _yorha_cream(0.08, 0.34), _yorha_cream(0.12, 0.92),
                          offset=3, blur=2)
    scene.paste(plate, (0, 0), face)
    for m in (shadow, hull, body, face, plate):
        m.close()


def _yorha_paint_rules(image: Image.Image) -> None:
    """After the dither: the dot grid, the pane's and rows' hairlines with
    their corner ticks, the tab bar with the crest, and the Pod's lens,
    antenna and legend."""
    for rect in _yorha_panel_rects():
        _yorha_fill_panel(image, rect)
    draw = ImageDraw.Draw(image)
    black, white = SPECTRA6["black"], SPECTRA6["white"]
    width, height = image.size
    px = pixel_access(image)
    p = _YORHA_DOT_PITCH
    for y in range(p // 2, height, p):
        for x in range(p // 2, width, p):
            if px[x, y] != black:
                px[x, y] = black
    for rect in (_YORHA_PANE_RECT, *_yorha_menu_rows()):
        x0, y0, x1, y1 = rect
        draw.rectangle(rect, outline=black, width=1)
        for (x, y), (dx, dy) in (((x0, y0), (1, 1)), ((x1, y0), (-1, 1)), ((x0, y1), (1, -1)), ((x1, y1), (-1, -1))):
            draw.line((x, y, x + 5 * dx, y), fill=black, width=2)
            draw.line((x, y, x, y + 5 * dy), fill=black, width=2)
    _yorha_paint_tab_bar(draw, "INTEL")
    # The Pod's silhouette, lens, antenna and legend.
    pxc, pyc = _YORHA_POD_CENTRE
    draw.rounded_rectangle((pxc - 58, pyc - 20, pxc + 38, pyc + 20), radius=20, outline=black, width=1)
    draw.polygon([(pxc - 40, pyc - 20), (pxc - 18, pyc - 40), (pxc, pyc - 20)], outline=black)
    draw.polygon([(pxc - 48, pyc + 18), (pxc - 64, pyc + 34), (pxc - 26, pyc + 20)], outline=black)
    draw.rounded_rectangle((pxc + 16, pyc - 15, pxc + 46, pyc + 15), radius=7, outline=black, width=1)
    draw.ellipse((pxc + 24, pyc - 8, pxc + 40, pyc + 8), fill=black)
    draw.ellipse((pxc + 28, pyc - 5, pxc + 32, pyc - 1), fill=white)
    draw.line((pxc - 18, pyc - 40, pxc - 18, pyc - 54), fill=black, width=1)
    draw.ellipse((pxc - 20, pyc - 58, pxc - 16, pyc - 54), fill=black)
    draw.text((pxc + 56, pyc - 7), "POD 042", font=_yorha_font(13, "Bold"), fill=black, stroke_width=2,
              stroke_fill=white)


def _yorha_paint_tab_bar(draw: ImageDraw.ImageDraw, open_tab: str) -> None:
    """The black tab bar with ``open_tab`` open, and the crest with the unit."""
    black, white = SPECTRA6["black"], SPECTRA6["white"]
    draw.rectangle(_YORHA_HEADER_RECT, fill=black)
    font = _yorha_font(15, "Regular")
    tab_x: float = 30
    for tab in _YORHA_TABS:
        tw = draw.textlength(tab, font=font)
        if tab == open_tab:
            draw.rectangle((tab_x - 8, _YORHA_HEADER_RECT[1] + 6, tab_x + tw + 8, _YORHA_HEADER_RECT[3] - 6), fill=white)
            draw.text((tab_x, _YORHA_HEADER_RECT[1] + 8), tab, font=font, fill=black)
        else:
            draw.text((tab_x, _YORHA_HEADER_RECT[1] + 8), tab, font=font, fill=white)
        tab_x += tw + 26
    # The crest: a ring with its wing bars, and the unit beside it.
    cx, cy = 752, (_YORHA_HEADER_RECT[1] + _YORHA_HEADER_RECT[3]) // 2
    draw.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), outline=white, width=2)
    draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=white)
    for i in range(3):
        draw.line((cx - 14 - i * 5, cy - 4 + i * 4, cx - 24 - i * 5, cy - 4 + i * 4), fill=white, width=1)
        draw.line((cx + 14 + i * 5, cy - 4 + i * 4, cx + 24 + i * 5, cy - 4 + i * 4), fill=white, width=1)
    small = _yorha_font(14, "Regular")
    draw_tracked(draw, (cx - 48, cy - 8), "UNIT 2B", small, white, tracking=2, anchor_right=True)


def _yorha_paint_menu(draw: ImageDraw.ImageDraw, hour: int) -> None:
    """The twelve archive rows' labels; the hour's row inverted."""
    black, white = SPECTRA6["black"], SPECTRA6["white"]
    font = _yorha_font(16, "Regular")
    for i, (x0, y0, x1, y1) in enumerate(_yorha_menu_rows()):
        active = (i + 1) == hour
        if active:
            draw.rectangle((x0, y0, x1, y1), fill=black)
            draw.polygon([(x1 - 16, y0 + 7), (x1 - 8, (y0 + y1) / 2), (x1 - 16, y1 - 7)], fill=white)
        else:
            draw.rectangle((x0 + 8, (y0 + y1) / 2 - 3, x0 + 14, (y0 + y1) / 2 + 3), outline=black, width=1)
        draw.text((x0 + 22, y0 + 3), f"ARCHIVE {i + 1:02d}", font=font, fill=white if active else black)


def _yorha_paint_pane(draw: ImageDraw.ImageDraw, hour: int, quote_row: dict) -> None:
    """The open entry's head: the title over a rule, the counter."""
    black = SPECTRA6["black"]
    x0, y0, x1, y1 = _YORHA_PANE_RECT
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "").strip() or "Untitled"
    font, text = fit_text_to_width(draw, title, [EBGARAMOND_BOLD, *META_FONT_BOLD_CANDIDATES], 22, x1 - x0 - 120, floor=15)
    draw.text((x0 + 18, y0 + 14), text, font=font, fill=black)
    counter = f"{hour:02d} / 12"
    small = _yorha_font(15, "Regular")
    draw.text((x1 - 18 - draw.textlength(counter, font=small), y0 + 18), counter, font=small, fill=black)
    draw.line((x0 + 18, y0 + 46, x1 - 18, y0 + 46), fill=black, width=1)


def _yorha_layout(draw: ImageDraw.ImageDraw, quote_row: dict):
    return _place_quote(draw, quote_row, _YORHA_QUOTE_RECT, theme="yorha",
                        font_max=34, font_min=18, line_height_mult=1.34)


def _yorha_paint_quote(draw: ImageDraw.ImageDraw, placed) -> None:
    """Black EB Garamond; the matched phrase white, knocked out of a black
    box per run — the selected item."""
    black, white = SPECTRA6["black"], SPECTRA6["white"]
    for box in _lumon_hover_boxes(draw, placed):
        draw.rectangle(box, fill=black)
    _paint_placed(draw, placed, black, white)


def _yorha_paint_byline(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    author = (quote_row.get("author") or "").strip()
    if not author:
        return
    x0 = _YORHA_QUOTE_RECT[0]
    font, text = fit_text_to_width(draw, author, [EBGARAMOND_REGULAR, *META_FONT_CANDIDATES], 18,
                                   _YORHA_QUOTE_RECT[2] - x0, floor=13)
    draw.text((x0, _YORHA_BYLINE_Y), text, font=font, fill=SPECTRA6["black"])


def _yorha_paint_glitch(image: Image.Image, quote_row: dict) -> None:
    """One sliver of the pane's foot shifted sideways — the game's tic."""
    rng = random.Random(_YORHA_SEED ^ _row_digest(quote_row))
    x0, y0, x1, y1 = _YORHA_PANE_RECT
    y = rng.randint(y1 - 60, y1 - 12)
    h = rng.randint(2, 4)
    shift = rng.choice((-6, -4, 4, 6))
    band = image.crop((x0 + 1, y, x1, y + h))
    image.paste(band, (x0 + 1 + shift, y))
    band.close()


def render_yorha_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The YoRHa archives with the hour's entry open (see the section
    comment above)."""
    hour = _clock_hour12(time_str)
    image = _yorha_scene().copy()
    draw = ImageDraw.Draw(image)
    _yorha_paint_menu(draw, hour)
    _yorha_paint_pane(draw, hour, quote_row)
    _yorha_paint_quote(draw, _yorha_layout(draw, quote_row))
    _yorha_paint_byline(draw, quote_row)
    _yorha_paint_glitch(image, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


# ---------------------------------------------------------------------------
# The sleep frame: the archive asks to sleep. The same sheet, panels and Pod,
# the tab bar turned to SYSTEM, the menu's SLEEP MODE row selected, and the
# pane holding the game's confirmation dialog with Yes chosen, under Pod 042's
# proposal. No glitch sliver: a resting unit, not a damaged one.
# ---------------------------------------------------------------------------
_YORHA_SLEEP_MENU = ("SAVE", "LOAD", "SETTINGS", "CONTROLS", "SOUND", "SCREEN", "NETWORK",
                     "UNIT DATA", "BACKUP", "SLEEP MODE", "TITLE SCREEN", "CREDITS")
_YORHA_SLEEP_SELECTED = _YORHA_SLEEP_MENU.index("SLEEP MODE")
_YORHA_SLEEP_DIALOG_RECT = (300, 146, 724, 326)
_YORHA_SLEEP_PROMPT = "Enter sleep mode?"
_YORHA_SLEEP_POD_LINES = ("Proposal: Unit 2B enter sleep mode.", "The archive will be kept until morning.")


def _yorha_paint_sleep_menu(draw: ImageDraw.ImageDraw) -> None:
    """The System menu's rows in the archive's style; SLEEP MODE inverted."""
    black, white = SPECTRA6["black"], SPECTRA6["white"]
    font = _yorha_font(16, "Regular")
    for i, (x0, y0, x1, y1) in enumerate(_yorha_menu_rows()):
        active = i == _YORHA_SLEEP_SELECTED
        if active:
            draw.rectangle((x0, y0, x1, y1), fill=black)
            draw.polygon([(x1 - 16, y0 + 7), (x1 - 8, (y0 + y1) / 2), (x1 - 16, y1 - 7)], fill=white)
        else:
            draw.rectangle((x0 + 8, (y0 + y1) / 2 - 3, x0 + 14, (y0 + y1) / 2 + 3), outline=black, width=1)
        draw.text((x0 + 22, y0 + 3), _YORHA_SLEEP_MENU[i], font=font, fill=white if active else black)


def _yorha_paint_sleep_head(draw: ImageDraw.ImageDraw) -> None:
    """The pane's head: SYSTEM › SLEEP MODE over a rule, STANDBY at the right."""
    black = SPECTRA6["black"]
    x0, y0, x1, _y1 = _YORHA_PANE_RECT
    draw.text((x0 + 18, y0 + 14), "System › Sleep Mode", font=_yorha_font(22, "Bold"), fill=black)
    small = _yorha_font(15, "Regular")
    draw_tracked(draw, (x1 - 18, y0 + 18), "STANDBY", small, black, tracking=2, anchor_right=True)
    draw.line((x0 + 18, y0 + 46, x1 - 18, y0 + 46), fill=black, width=1)


def _yorha_sleep_option_rows() -> list:
    """The dialog's two option rows, Yes then No."""
    x0, _y0, x1, y1 = _YORHA_SLEEP_DIALOG_RECT
    return [(x0 + 40, y1 - 92, x1 - 40, y1 - 58), (x0 + 40, y1 - 48, x1 - 40, y1 - 14)]


def _yorha_paint_sleep_dialog(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """The confirmation dialog: a hard stippled shadow, the panel face, the
    black bands top and foot, the prompt, and Yes selected over No."""
    black, white = SPECTRA6["black"], SPECTRA6["white"]
    x0, y0, x1, y1 = _YORHA_SLEEP_DIALOG_RECT
    px = pixel_access(image)
    for y in range(y0 + 7, y1 + 8):
        row = BAYER_4x4[y % 4]
        for x in range(x0 + 7, x1 + 8):
            if (x > x1 or y > y1) and row[x % 4] < 8:
                px[x, y] = black
    _yorha_fill_panel(image, _YORHA_SLEEP_DIALOG_RECT)
    draw.rectangle(_YORHA_SLEEP_DIALOG_RECT, outline=black, width=1)
    draw.rectangle((x0, y0, x1, y0 + 5), fill=black)
    draw.rectangle((x0, y1 - 3, x1, y1), fill=black)
    for (x, y), (dx, dy) in (((x0, y0), (1, 1)), ((x1, y0), (-1, 1)), ((x0, y1), (1, -1)), ((x1, y1), (-1, -1))):
        draw.line((x - 4 * dx, y, x + 10 * dx, y), fill=black, width=2)
        draw.line((x, y - 4 * dy, x, y + 10 * dy), fill=black, width=2)
    prompt = _yorha_font(30, "Regular")
    tw = draw.textlength(_YORHA_SLEEP_PROMPT, font=prompt)
    draw.text(((x0 + x1 - tw) / 2, y0 + 22), _YORHA_SLEEP_PROMPT, font=prompt, fill=black)
    draw.line((x0 + 40, y0 + 70, x1 - 40, y0 + 70), fill=black, width=1)
    option = _yorha_font(22, "Regular")
    for label, (rx0, ry0, rx1, ry1), active in zip(("Yes", "No"), _yorha_sleep_option_rows(), (True, False),
                                                   strict=True):
        cy = (ry0 + ry1) / 2
        if active:
            draw.rectangle((rx0, ry0, rx1, ry1), fill=black)
            draw.polygon([(rx0 + 12, ry0 + 9), (rx0 + 22, cy), (rx0 + 12, ry1 - 9)], fill=white)
        else:
            draw.rectangle((rx0, ry0, rx1, ry1), outline=black, width=1)
            draw.rectangle((rx0 + 13, cy - 4, rx0 + 21, cy + 4), outline=black, width=1)
        draw.text((rx0 + 40, cy), label, font=option, fill=white if active else black, anchor="lm")


def _yorha_paint_sleep_pod_line(draw: ImageDraw.ImageDraw) -> None:
    """Pod 042's proposal under the dialog, as the game sets its lines."""
    black = SPECTRA6["black"]
    x0, _y0, x1, _y1 = _YORHA_PANE_RECT
    y = _YORHA_SLEEP_DIALOG_RECT[3] + 30
    label = _yorha_font(15, "Bold")
    draw_tracked(draw, (x0 + 18, y + 4), "POD 042", label, black, tracking=2)
    draw.line((x0 + 18, y + 26, x0 + 110, y + 26), fill=black, width=1)
    body = _yorha_font(21, "Regular")
    for i, line in enumerate(_YORHA_SLEEP_POD_LINES):
        draw.text((x0 + 128, y + i * 30), line, font=body, fill=black)


def render_yorha_sleep(time_str: str, width: int, height: int) -> Image.Image:
    """The quiet-hours frame: the System menu with SLEEP MODE selected and
    the confirmation dialog answered Yes, under Pod 042's proposal.

    The quote frame's sheet, panels, Pod and crest, with the tab bar turned
    to SYSTEM. ``time_str`` is unused: nothing on the frame tells the time.
    """
    del time_str
    image = _yorha_scene().copy()
    draw = ImageDraw.Draw(image)
    _yorha_paint_tab_bar(draw, "SYSTEM")
    _yorha_paint_sleep_menu(draw)
    _yorha_paint_sleep_head(draw)
    _yorha_paint_sleep_dialog(image, draw)
    _yorha_paint_sleep_pod_line(draw)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("yorha",), render=render_yorha_frame, sleep=render_yorha_sleep)
