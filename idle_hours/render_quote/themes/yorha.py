"""The ``yorha`` theme: the YoRHa system menu, Intel › Archives, from *NieR: Automata*.

Design notes: docs/themes.md § yorha
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw, ImageFilter

from .._paths import EBGARAMOND_BOLD, EBGARAMOND_REGULAR, META_FONT_BOLD_CANDIDATES, META_FONT_CANDIDATES
from ..fonts import load_font
from ..furniture import _clock_hour12, _paint_placed, _place_quote, _row_digest, fallback_title
from ..palette import (
    _PANEL_INKS,
    SPECTRA6,
    SPECTRA6_PALETTE,
    BAYER_4x4,
    _dither_calibrated,
    gray_pixel_access,
    pixel_access,
    snap_image_to_palette,
)
from ..primitives import _shift_no_wrap
from ..spec import FrameSpec
from ..text import draw_tracked, fit_text_to_width
from ._shared import _lumon_hover_boxes

_YORHA_SEED = 0x594F5248              # YORH
_YORHA_INKS = ("white", "yellow", "black")
_YORHA_DOT_PITCH = 16
_YORHA_HATCH_PITCH = 9
_YORHA_HEADER_RECT = (0, 18, 800, 54)
_YORHA_TABS = ("MAP", "QUESTS", "ITEMS", "WEAPONS", "SKILLS", "INTEL", "SYSTEM")
_YORHA_MENU_RECT = (30, 76, 226, 388)
_YORHA_POD_CENTRE = (96, 424)
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


def _yorha_cap_baseline(font, top: float, bottom: float) -> int:
    """The baseline that centres a caps label's ink between ``top`` and
    ``bottom``. EB Garamond's ascent carries accent room above the caps, so a
    top-anchored label sits low in its row."""
    cap = -font.getbbox("H", anchor="ls")[1]
    return round((top + bottom + cap) / 2)


def _yorha_menu_rows() -> list:
    x0, y0, x1, y1 = _YORHA_MENU_RECT
    step = (y1 - y0) // 12
    return [(x0, y0 + i * step, x1, y0 + i * step + step - 4) for i in range(12)]


def _yorha_scene() -> Image.Image:
    """The sheet, the panels, the shadows and the Pod — everything the hour
    and the quote do not touch — dithered and ruled. Painted once per
    process."""
    key = (_yorha_paint_ground, _yorha_paint_panels, _yorha_paint_pod_tone, _yorha_paint_rules, _yorha_paint_pod)
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
    """Pod 042's shadow on the sheet, soft and well below it: the unit
    hovers. The Pod itself is drawn crisp after the dither
    (``_yorha_paint_pod``)."""
    size = scene.size
    cx, cy = _YORHA_POD_CENTRE
    shadow = Image.new("L", size, 0)
    ImageDraw.Draw(shadow).ellipse((cx - 44, cy + 40, cx + 46, cy + 50), fill=255)
    shadow = shadow.filter(ImageFilter.GaussianBlur(4)).point(lambda v: int(v * 0.65))
    scene.paste(Image.new("RGB", size, _yorha_cream(0.18, 0.55)), (0, 0), shadow)
    shadow.close()


def _yorha_pod_faces() -> dict:
    """Pod 042 in side view, facing the pane, seen a little from above: the
    long side, the top, the front end, and the two arms folded under."""
    cx, cy = _YORHA_POD_CENTRE
    left, right, top, foot = cx - 46, cx + 34, cy - 12, cy + 16
    dx, dy = 8, -7                                # the box's depth, receding up and right
    return {
        "top": [(left, top), (right, top), (right + dx, top + dy), (left + dx, top + dy)],
        "side": [(left, top), (right, top), (right, foot), (left + 5, foot), (left, foot - 5)],
        "front": [(right, top), (right + dx, top + dy), (right + dx, foot + dy), (right, foot)],
        "arms": [((cx - 12, foot), (cx - 22, foot + 7), (cx - 30, foot + 10)),
                 ((cx + 12, foot), (cx + 2, foot + 7), (cx - 6, foot + 10))],
    }


def _yorha_stipple_polygon(image: Image.Image, points, black_rank: int, yellow_rank: int) -> None:
    """Fill a polygon on the 4x4 Bayer tile: ranks under ``black_rank`` black,
    under ``yellow_rank`` yellow, the rest white."""
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs) + 1, max(ys) + 1
    mask = Image.new("1", (x1 - x0, y1 - y0), 0)
    ImageDraw.Draw(mask).polygon([(x - x0, y - y0) for x, y in points], fill=1)
    mp = gray_pixel_access(mask)
    px = pixel_access(image)
    width, height = image.size
    black, yellow, white = SPECTRA6["black"], SPECTRA6["yellow"], SPECTRA6["white"]
    for y in range(max(0, y0), min(height, y1)):
        row = BAYER_4x4[y % 4]
        for x in range(max(0, x0), min(width, x1)):
            if mp[x - x0, y - y0]:
                rank = row[x % 4]
                px[x, y] = black if rank < black_rank else yellow if rank < yellow_rank else white
    mask.close()


def _yorha_paint_pod(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """Pod 042, crisp: a white keyline off the sheet, the faces stippled by
    the upper-left light (top white, side cream, front shaded), black edges,
    panel seams, the front port, the folded arms, and the unit's legend."""
    black, white = SPECTRA6["black"], SPECTRA6["white"]
    faces = _yorha_pod_faces()
    hull = Image.new("L", image.size, 0)
    hd = ImageDraw.Draw(hull)
    for name in ("top", "side", "front"):
        hd.polygon(faces[name], fill=255)
    for arm in faces["arms"]:
        hd.line(arm, fill=255, width=3)
        hd.rectangle((arm[-1][0] - 4, arm[-1][1] - 2, arm[-1][0] + 1, arm[-1][1] + 3), fill=255)
    halo = hull.filter(ImageFilter.MaxFilter(5))
    image.paste(Image.new("RGB", image.size, white), (0, 0), halo)
    for m in (hull, halo):
        m.close()
    # The arms first: they hang behind the hull's foot.
    for arm in faces["arms"]:
        draw.line(arm, fill=black, width=2, joint="curve")
        hx, hy = arm[-1]
        draw.rectangle((hx - 4, hy - 2, hx + 1, hy + 3), fill=black)
    _yorha_stipple_polygon(image, faces["top"], 0, 0)
    _yorha_stipple_polygon(image, faces["side"], 0, 3)
    _yorha_stipple_polygon(image, faces["front"], 3, 10)
    for name in ("top", "side", "front"):
        draw.polygon(faces[name], outline=black)
    # Seams: the side's split line and two panel joints, a vent on the rear.
    (left, top), (right, _t), *_ = faces["side"]
    foot = faces["side"][2][1]
    mid = (top + foot) // 2 + 2
    draw.line((left + 1, mid, right - 1, mid), fill=black, width=1)
    for x in (left + 24, right - 20):
        draw.line((x, top + 1, x, mid), fill=black, width=1)
    for i in range(3):
        draw.line((left + 6, top + 4 + i * 3, left + 18, top + 4 + i * 3), fill=black, width=1)
    # The port in the front end, a dark square with a glint.
    (fx0, fy0), (fx1, fy1) = faces["front"][0], faces["front"][1]
    draw.polygon([(fx0 + 2, fy0 + 4), (fx1 - 2, fy1 + 6), (fx1 - 2, fy1 + 15), (fx0 + 2, fy0 + 13)], fill=black)
    draw.point((fx0 + 4, fy0 + 6), fill=white)
    # The legend on its own tag: a crisp panel face with a black head band.
    label = _yorha_font(13, "Bold")
    tag_x0, tag_x1 = faces["front"][1][0] + 14, _YORHA_MENU_RECT[2]
    tag_y0, tag_y1 = top - 10, top + 10
    _yorha_fill_panel(image, (tag_x0, tag_y0, tag_x1, tag_y1))
    draw.rectangle((tag_x0, tag_y0, tag_x1, tag_y1), outline=black, width=1)
    draw.rectangle((tag_x0, tag_y0, tag_x0 + 3, tag_y1), fill=black)
    baseline = _yorha_cap_baseline(label, tag_y0, tag_y1)
    draw_tracked(draw, (tag_x0 + 10, baseline - label.getmetrics()[0]), "POD 042", label, black, tracking=2)


def _yorha_paint_rules(image: Image.Image) -> None:
    """After the dither: the panel faces, the dot grid, the pane's and rows'
    hairlines with their corner ticks, the tab bar with the crest, and the
    Pod."""
    for rect in _yorha_panel_rects():
        _yorha_fill_panel(image, rect)
    draw = ImageDraw.Draw(image)
    black = SPECTRA6["black"]
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
    _yorha_paint_pod(image, draw)


def _yorha_paint_tab_bar(draw: ImageDraw.ImageDraw, open_tab: str) -> None:
    """The black tab bar with ``open_tab`` open, and the crest with the unit."""
    black, white = SPECTRA6["black"], SPECTRA6["white"]
    draw.rectangle(_YORHA_HEADER_RECT, fill=black)
    font = _yorha_font(15, "Regular")
    top, bottom = _YORHA_HEADER_RECT[1] + 6, _YORHA_HEADER_RECT[3] - 6
    baseline = _yorha_cap_baseline(font, top, bottom)
    tab_x: float = 30
    for tab in _YORHA_TABS:
        tw = draw.textlength(tab, font=font)
        if tab == open_tab:
            draw.rectangle((tab_x - 8, top, tab_x + tw + 8, bottom), fill=white)
        draw.text((tab_x, baseline), tab, font=font, fill=black if tab == open_tab else white, anchor="ls")
        tab_x += tw + 26
    # The crest: a ring with its wing bars, and the unit beside it.
    cx, cy = 752, (_YORHA_HEADER_RECT[1] + _YORHA_HEADER_RECT[3]) // 2
    draw.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), outline=white, width=2)
    draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=white)
    for i in range(3):
        draw.line((cx - 14 - i * 5, cy - 4 + i * 4, cx - 24 - i * 5, cy - 4 + i * 4), fill=white, width=1)
        draw.line((cx + 14 + i * 5, cy - 4 + i * 4, cx + 24 + i * 5, cy - 4 + i * 4), fill=white, width=1)
    small = _yorha_font(14, "Regular")
    unit_top = _yorha_cap_baseline(small, cy - 10, cy + 10) - small.getmetrics()[0]
    draw_tracked(draw, (cx - 48, unit_top), "UNIT 2B", small, white, tracking=2, anchor_right=True)


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
        draw.text((x0 + 22, _yorha_cap_baseline(font, y0, y1)), f"ARCHIVE {i + 1:02d}", font=font,
                  fill=white if active else black, anchor="ls")


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


def _yorha_phrase_boxes(draw: ImageDraw.ImageDraw, placed) -> list:
    """The matched phrase's boxes: ``_lumon_hover_boxes``' runs, trimmed to
    the phrase face's ascender top and descender foot with an even margin.
    The line-height box ``lumon`` uses carries EB Garamond's accent room above
    the ascenders, which left the bar a third too tall and top-heavy."""
    bold = next((font for *_, font, is_bold, _w, _lh in placed if is_bold), None)
    if bold is None:
        return []
    _l, ink_top, _r, ink_foot = bold.getbbox("hp", anchor="la")
    size = getattr(bold, "size", 20)
    pad_y, pad_x = max(2, round(size * 0.09)), max(3, round(size * 0.14))
    boxes = []
    for x0, y, x1, _y1 in _lumon_hover_boxes(draw, placed):
        line_top = y + 2                          # the run's line top, before lumon's own margin
        boxes.append((x0 + 3 - pad_x, line_top + ink_top - pad_y, x1 - 2 + pad_x, line_top + ink_foot + pad_y))
    return boxes


def _yorha_paint_quote(draw: ImageDraw.ImageDraw, placed) -> None:
    """Black EB Garamond; the matched phrase white, knocked out of a black
    box per run — the selected item."""
    black, white = SPECTRA6["black"], SPECTRA6["white"]
    for box in _yorha_phrase_boxes(draw, placed):
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
    """The YoRHa archives with the hour's entry open (see docs/themes.md)."""
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
# The sleep frame: the archive asks to sleep (System › Sleep Mode, Yes chosen).
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
        draw.text((x0 + 22, _yorha_cap_baseline(font, y0, y1)), _YORHA_SLEEP_MENU[i], font=font,
                  fill=white if active else black, anchor="ls")


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
        draw.text((rx0 + 40, _yorha_cap_baseline(option, ry0, ry1)), label, font=option,
                  fill=white if active else black, anchor="ls")


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
