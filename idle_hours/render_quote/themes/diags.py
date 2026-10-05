"""The ``diags`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .._paths import META_FONT_BOLD_CANDIDATES, META_FONT_CANDIDATES
from ..fonts import load_font, theme_font_candidates
from ..layout import choose_layout
from ..palette import SPECTRA6, SPECTRA6_PALETTE, snap_image_to_palette
from ..primitives import _fill_swatch_stipple, _fill_swatch_stipple_3way
from ..spec import FrameSpec
from ..theme_tables import THEMES

# Two-ink stipple recipes from spectra6_color_recipes.md, as (display name,
# dark ink, light ink, light density, short label); the order drives the
# two-row swatch band of the diagnostic frame. The band mirrors the *whole*
# catalogue (``test_swatch_list_has_every_documented_recipe``), so a swatch
# means the recipe is documented, not that a theme paints it. The order is
# hue grouping only; reordering would just churn the diags golden fixture.
# ``sage`` follows the doc's "above 50%, swap dark/light and pass the
# complementary density" rule. Three-ink mixes are in
# ``_DIAGS_TRIPLE_SWATCHES`` below.
_DIAGS_SYNTH_SWATCHES: list[tuple[str, tuple[int, int, int], tuple[int, int, int], float, str]] = [
    # Row 1 — reds / oranges / violets / sepia / cream
    ("tangerine", SPECTRA6["red"],    SPECTRA6["yellow"], 0.375, "R+Y 5:3"),
    ("candlelit", SPECTRA6["red"],    SPECTRA6["white"],  0.25,  "R+W 3:1"),
    ("coral",     SPECTRA6["red"],    SPECTRA6["white"],  0.5,   "R+W 1:1"),
    ("amber",     SPECTRA6["red"],    SPECTRA6["yellow"], 0.5,   "R+Y 1:1"),
    ("violet",    SPECTRA6["red"],    SPECTRA6["blue"],   0.5,   "R+B 1:1"),
    ("maroon",    SPECTRA6["red"],    SPECTRA6["black"],  0.5,   "R+K 1:1"),
    ("sepia",     SPECTRA6["red"],    SPECTRA6["green"],  0.5,   "R+G 1:1"),
    ("cream",     SPECTRA6["yellow"], SPECTRA6["white"],  0.5,   "Y+W 1:1"),
    # Row 2 — greens / blues / neutrals
    ("mint",      SPECTRA6["green"],  SPECTRA6["white"],  0.5,   "G+W 1:1"),
    ("sage",      SPECTRA6["white"],  SPECTRA6["green"],  0.25,  "W+G 3:1"),
    ("olive",     SPECTRA6["yellow"], SPECTRA6["green"],  0.5,   "Y+G 1:1"),
    ("lime",      SPECTRA6["yellow"], SPECTRA6["green"],  0.375, "Y+G 5:3"),
    ("forest",    SPECTRA6["green"],  SPECTRA6["black"],  0.5,   "G+K 1:1"),
    ("cyan",      SPECTRA6["green"],  SPECTRA6["blue"],   0.5,   "G+B 1:1"),
    ("teal",      SPECTRA6["green"],  SPECTRA6["blue"],   0.375, "G+B 5:3"),
    ("sky",       SPECTRA6["blue"],   SPECTRA6["white"],  0.5,   "B+W 1:1"),
    ("navy",      SPECTRA6["blue"],   SPECTRA6["black"],  0.5,   "B+K 1:1"),
    ("gray",      SPECTRA6["black"],  SPECTRA6["white"],  0.5,   "K+W 1:1"),
]

# Swatches in the first row of the diags two-ink band: the 18 recipes split
# 8 / 10 so per-swatch widths stay readable.
_DIAGS_SYNTH_ROW1_COUNT = 8

_DIAGS_SPECTRA6_SWATCHES: list[tuple[str, tuple[int, int, int], str]] = [
    ("white",  SPECTRA6["white"],  "#FFFFFF"),
    ("black",  SPECTRA6["black"],  "#000000"),
    ("red",    SPECTRA6["red"],    "#FF0000"),
    ("yellow", SPECTRA6["yellow"], "#FFFF00"),
    ("blue",   SPECTRA6["blue"],   "#0000FF"),
    ("green",  SPECTRA6["green"],  "#00FF00"),
]


def _diags_system_info() -> dict[str, str]:
    """Return host / IP / uptime strings for the diagnostic frame.

    Each lookup is wrapped so a misconfigured environment (no network,
    non-Linux host, restricted /proc) still renders; a missing field shows
    ``"—"``.

    The IP comes from a UDP "connect" to a public address, which sends no
    packet but pins the kernel's chosen source address — the primary
    outbound IP — with ``socket.gethostbyname`` as the fallback.
    """
    import socket

    info: dict[str, str] = {"host": "—", "ip": "—", "uptime": "—"}
    try:
        host = socket.gethostname()
        if host:
            info["host"] = host
    except Exception:
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 53))
            info["ip"] = sock.getsockname()[0]
        finally:
            sock.close()
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
            if ip and ip != "127.0.0.1":
                info["ip"] = ip
        except Exception:
            pass
    try:
        with open("/proc/uptime", "r") as fh:
            seconds = int(float(fh.read().split()[0]))
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        if days:
            info["uptime"] = f"{days}d {hours}h {minutes}m"
        elif hours:
            info["uptime"] = f"{hours}h {minutes}m"
        else:
            info["uptime"] = f"{minutes}m"
    except Exception:
        pass
    return info



# Three-ink stipple recipes from ``spectra6_color_recipes.md`` ("Three-ink
# recipes"), as (display name, ink_a, ink_b, ink_c, density_a, density_b,
# short label); the third density is implicit. Shown in two rows of 6 below
# the two-ink band, to check on the panel whether each reads as its pastel.
_DIAGS_TRIPLE_SWATCHES: list[
    tuple[str, tuple[int, int, int], tuple[int, int, int], tuple[int, int, int], float, float, str]
] = [
    # Pastels (3rd ink = white)
    ("light orange", SPECTRA6["red"],    SPECTRA6["yellow"], SPECTRA6["white"], 0.40,    0.40,    "R+Y+W 40/40/20"),
    ("salmon",       SPECTRA6["red"],    SPECTRA6["yellow"], SPECTRA6["white"], 1 / 3,   1 / 3,   "R+Y+W 1:1:1"),
    ("peach",        SPECTRA6["red"],    SPECTRA6["yellow"], SPECTRA6["white"], 0.30,    0.50,    "R+Y+W 30/50/20"),
    ("lavender",     SPECTRA6["red"],    SPECTRA6["blue"],   SPECTRA6["white"], 1 / 3,   1 / 3,   "R+B+W 1:1:1"),
    ("lilac",        SPECTRA6["red"],    SPECTRA6["blue"],   SPECTRA6["white"], 0.25,    0.25,    "R+B+W 25/25/50"),
    ("seafoam",      SPECTRA6["green"],  SPECTRA6["blue"],   SPECTRA6["white"], 0.40,    0.30,    "G+B+W 40/30/30"),
    # Pastels continued + deep tones (3rd ink = white or black) + chromatic (no W/K)
    ("khaki",        SPECTRA6["yellow"], SPECTRA6["green"],  SPECTRA6["white"], 0.40,    0.30,    "Y+G+W 40/30/30"),
    ("beige",        SPECTRA6["red"],    SPECTRA6["yellow"], SPECTRA6["white"], 0.25,    0.25,    "R+Y+W 25/25/50"),
    ("plum",         SPECTRA6["red"],    SPECTRA6["blue"],   SPECTRA6["black"], 1 / 3,   1 / 3,   "R+B+K 1:1:1"),
    ("print sepia",  SPECTRA6["red"],    SPECTRA6["yellow"], SPECTRA6["black"], 0.40,    0.40,    "R+Y+K 40/40/20"),
    ("burnt orange", SPECTRA6["red"],    SPECTRA6["yellow"], SPECTRA6["green"], 0.50,    0.40,    "R+Y+G 50/40/10"),
    ("forest-teal",  SPECTRA6["green"],  SPECTRA6["blue"],   SPECTRA6["yellow"], 0.40,   0.40,    "G+B+Y 40/40/20"),
]

_DIAGS_TRIPLE_ROW1_COUNT = 6


def render_diags_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Render the diagnostic frame for the ``diags`` theme.

    Replaces the literary layout with a status panel: a large clock, picker
    metrics (bucket / layout / quality / ID / matched phrase), the native
    palette, and the two- and three-ink stipple recipes. For on-panel
    calibration and for confirming the picker chose what you'd expect.
    """
    colors = THEMES["diags"]
    image = Image.new("RGB", (width, height), color=colors["page_bg"])
    draw = ImageDraw.Draw(image)

    INSET = 12
    PAD_X = 22

    # Outer frame
    draw.rectangle((INSET, INSET, width - INSET - 1, height - INSET - 1), outline=colors["text"], width=1)

    # Header bar
    header_font = load_font(META_FONT_BOLD_CANDIDATES, size=14)
    header = "IDLE HOURS · DIAGS"
    draw.text((PAD_X, INSET + 8), header, font=header_font, fill=colors["accent"])
    rule_y = INSET + 32
    draw.line((PAD_X, rule_y, width - PAD_X, rule_y), fill=colors["text"])

    # ----- Top section: big clock + status grid -----
    clock_font = load_font(theme_font_candidates("diags", "quote_bold"), size=88)
    # Shown verbatim, malformed or not: this is the diagnostic panel. Only a
    # missing time needs a stand-in, since there is nothing to show.
    clock_text = time_str or "--:--"
    clock_bbox = draw.textbbox((0, 0), clock_text, font=clock_font)
    clock_w = clock_bbox[2] - clock_bbox[0]
    clock_x = PAD_X
    clock_y = rule_y + 10
    draw.text((clock_x - clock_bbox[0], clock_y - clock_bbox[1]), clock_text, font=clock_font, fill=colors["text"])

    # Status table — right of the clock
    field_key_font = load_font(META_FONT_BOLD_CANDIDATES, size=12)
    field_val_font = load_font(META_FONT_CANDIDATES, size=12)
    fields_x = clock_x + clock_w + 36
    key_col_w = 92
    f_y = clock_y + 6
    LINE_H = 17

    layout_name = choose_layout(quote_row.get("display_quote") or "")
    bucket = quote_row.get("bucket") or "—"
    resolved = quote_row.get("resolved_bucket") or bucket
    quality = quote_row.get("quality_score")
    source_id = quote_row.get("source_id")
    line_number = quote_row.get("line_number")
    matched = (quote_row.get("matched_text") or "—").replace("\n", " ").strip()
    fallback = quote_row.get("used_fallback")

    if resolved and bucket and resolved != bucket and fallback:
        bucket_display = f"{bucket} → {resolved}"
    else:
        bucket_display = resolved or bucket

    if source_id and line_number is not None:
        id_display = f"{source_id}:{line_number}"
    elif source_id:
        id_display = str(source_id)
    else:
        id_display = "—"

    fields = [
        ("BUCKET", bucket_display),
        ("LAYOUT", layout_name),
        ("QUALITY", "—" if quality is None else str(quality)),
        ("FALLBACK", "yes" if fallback else "no"),
        ("ID", id_display),
        ("MATCHED", matched if len(matched) <= 36 else matched[:34] + "…"),
    ]
    for key, val in fields:
        draw.text((fields_x, f_y), key, font=field_key_font, fill=colors["accent"])
        draw.text((fields_x + key_col_w, f_y), val, font=field_val_font, fill=colors["text"])
        f_y += LINE_H

    # ----- System info strip (host / ip / uptime) -----
    # Sits between the status table (ends ~y=162) and the palette swatches
    # (start y=192).
    sys_info = _diags_system_info()
    sys_label_font = load_font(META_FONT_BOLD_CANDIDATES, size=11)
    sys_val_font = load_font(META_FONT_CANDIDATES, size=11)
    sys_y = 170
    sys_entries = [
        ("HOST", sys_info["host"]),
        ("IP", sys_info["ip"]),
        ("UPTIME", sys_info["uptime"]),
    ]
    # Distribute the three entries evenly across the inner width.
    avail_strip_w = width - 2 * PAD_X
    slot_w = avail_strip_w // len(sys_entries)
    for i, (key, val) in enumerate(sys_entries):
        slot_x = PAD_X + i * slot_w
        draw.text((slot_x, sys_y), key, font=sys_label_font, fill=colors["accent"])
        key_bb = draw.textbbox((0, 0), key, font=sys_label_font)
        key_w = key_bb[2] - key_bb[0]
        draw.text((slot_x + key_w + 8, sys_y), val, font=sys_val_font, fill=colors["text"])

    # ----- Middle section: Spectra 6 swatches -----
    section_font = load_font(META_FONT_BOLD_CANDIDATES, size=12)
    label_bold = load_font(META_FONT_BOLD_CANDIDATES, size=10)
    label_reg = load_font(META_FONT_CANDIDATES, size=10)

    s1_y = 186
    draw.text((PAD_X, s1_y), "SPECTRA 6 NATIVE PALETTE", font=section_font, fill=colors["accent"])

    sw_top = s1_y + 14
    sw_h = 36
    sw_gap = 6
    sw_count = len(_DIAGS_SPECTRA6_SWATCHES)
    avail_w = width - 2 * PAD_X
    sw_w = (avail_w - (sw_count - 1) * sw_gap) // sw_count
    for i, (name, rgb, hex_code) in enumerate(_DIAGS_SPECTRA6_SWATCHES):
        x0 = PAD_X + i * (sw_w + sw_gap)
        x1 = x0 + sw_w
        y1 = sw_top + sw_h
        draw.rectangle((x0, sw_top, x1, y1), fill=rgb, outline=colors["text"], width=1)
        # Contrasting label: white on black / blue / red, black otherwise.
        is_dark_fill = rgb in (SPECTRA6["black"], SPECTRA6["blue"], SPECTRA6["red"])
        label_fill = SPECTRA6["white"] if is_dark_fill else SPECTRA6["black"]
        draw.text((x0 + 5, sw_top + 4), name.upper(), font=label_bold, fill=label_fill)
        draw.text((x0 + 5, sw_top + 18), hex_code, font=label_reg, fill=label_fill)

    # ----- Synth bands -----
    # Two-ink: 18 recipes in 2 rows (8 + 10). Three-ink: 12 recipes in 2 rows
    # (6 + 6). All four rows share the per-swatch geometry; only the column
    # count and the painter change. Labels are a bold name plus a faded
    # recipe, two 9 pt lines.
    label_bold_9 = load_font(META_FONT_BOLD_CANDIDATES, size=9)
    label_reg_9 = load_font(META_FONT_CANDIDATES, size=9)
    sw2_color_h = 22
    sw2_label_h = 22
    sw2_row_h = sw2_color_h + sw2_label_h
    sw2_row_gap = 3
    sw2_gap = 5

    def _paint_synth_row(row_top: int, entries: list, painter) -> None:
        n = len(entries)
        row_w = (avail_w - (n - 1) * sw2_gap) // n
        if row_w <= 0:
            # Canvas too narrow for the swatch grid (small /api/preview
            # thumbnail) — skip rather than feed PIL an inverted rectangle.
            return
        for col_idx, entry in enumerate(entries):
            x0 = PAD_X + col_idx * (row_w + sw2_gap)
            x1 = x0 + row_w
            color_y1 = row_top + sw2_color_h
            # Paint the stipple inset by 1 so the outline stays visible.
            painter(entry, (x0 + 1, row_top + 1, x1, color_y1))
            draw.rectangle((x0, row_top, x1, color_y1), outline=colors["text"], width=1)
            name = entry[0]
            recipe = entry[-1]
            draw.text((x0, color_y1 + 2), name, font=label_bold_9, fill=colors["text"])
            draw.text((x0, color_y1 + 12), recipe, font=label_reg_9, fill=colors["subtle"])

    def _two_ink_painter(entry, rect):
        _name, dark, light, density, _recipe = entry
        _fill_swatch_stipple(image, rect, dark, light, density)

    def _three_ink_painter(entry, rect):
        _name, ink_a, ink_b, ink_c, density_a, density_b, _recipe = entry
        _fill_swatch_stipple_3way(image, rect, ink_a, ink_b, ink_c, density_a, density_b)

    # ----- Two-ink synth band -----
    s2_y = sw_top + sw_h + 8
    draw.text((PAD_X, s2_y), "SYNTHESISED (2-INK STIPPLE)", font=section_font, fill=colors["accent"])
    sw2_top = s2_y + 14
    sw2_row1 = _DIAGS_SYNTH_SWATCHES[:_DIAGS_SYNTH_ROW1_COUNT]
    sw2_row2 = _DIAGS_SYNTH_SWATCHES[_DIAGS_SYNTH_ROW1_COUNT:]
    _paint_synth_row(sw2_top, sw2_row1, _two_ink_painter)
    _paint_synth_row(sw2_top + sw2_row_h + sw2_row_gap, sw2_row2, _two_ink_painter)

    # ----- Three-ink synth band -----
    sw2_band_end = sw2_top + 2 * sw2_row_h + sw2_row_gap
    s3_y = sw2_band_end + 6
    draw.text((PAD_X, s3_y), "SYNTHESISED (3-INK STIPPLE)", font=section_font, fill=colors["accent"])
    sw3_top = s3_y + 14
    sw3_row1 = _DIAGS_TRIPLE_SWATCHES[:_DIAGS_TRIPLE_ROW1_COUNT]
    sw3_row2 = _DIAGS_TRIPLE_SWATCHES[_DIAGS_TRIPLE_ROW1_COUNT:]
    _paint_synth_row(sw3_top, sw3_row1, _three_ink_painter)
    _paint_synth_row(sw3_top + sw2_row_h + sw2_row_gap, sw3_row2, _three_ink_painter)

    return snap_image_to_palette(image, SPECTRA6_PALETTE)


SPEC = FrameSpec(themes=("diags",), render=render_diags_frame)
