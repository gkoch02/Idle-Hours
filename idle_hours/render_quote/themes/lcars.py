"""The ``lcars`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .._paths import META_FONT_BOLD_CANDIDATES
from ..fonts import load_font, theme_font_candidates
from ..palette import SPECTRA6, BAYER_4x4, pixel_access
from ..spec import BorderSpec

# R+B+W 3-way Bayer cuts on ``BAYER_4x4`` (cells below the first → red, below
# the second → blue, the rest → white). Lavender is 5/5/6; lilac 4/4/8 is
# paler, with a heavier white lift.
_LCARS_LAVENDER_CUTS = (5, 10)
_LCARS_LILAC_CUTS = (4, 8)


def _lcars_paint_rbw_block(pixels, left: int, top: int, right: int, bot: int,
                           sentinel, cuts: tuple[int, int]) -> None:
    """3-way Bayer post-pass of ``sentinel`` pixels to red / blue / white at
    ``cuts`` (``_LCARS_LAVENDER_CUTS`` or ``_LCARS_LILAC_CUTS``). ``sentinel``
    must be off-palette (``(1, 1, 1)``). Bbox-scoped so neighbouring blocks in
    other sentinels stay untouched."""
    ink_red = SPECTRA6["red"]
    ink_blue = SPECTRA6["blue"]
    ink_white = SPECTRA6["white"]
    red_cut, blue_cut = cuts
    for py in range(top, bot + 1):
        row = BAYER_4x4[py % 4]
        for px in range(left, right + 1):
            if pixels[px, py] == sentinel:
                cell = row[px % 4]
                if cell < red_cut:
                    pixels[px, py] = ink_red
                elif cell < blue_cut:
                    pixels[px, py] = ink_blue
                else:
                    pixels[px, py] = ink_white


def _lcars_post_pass_tangerine(pixels, left: int, top: int, right: int, bot: int,
                               sentinel_red) -> None:
    """Bbox-scoped R+Y biased Bayer: ~3/8 yellow on red. Threshold and
    phase match ``draw_deco_border``'s final pass and ``_draw_text_body``'s
    ``deco`` branch, so all three land on one tangerine. Only touches
    ``sentinel_red`` pixels."""
    yellow = SPECTRA6["yellow"]
    threshold = 6  # round(0.375 * 16)
    for y in range(top, bot + 1):
        row = BAYER_4x4[y % 4]
        for x in range(left, right + 1):
            if row[x % 4] < threshold and pixels[x, y] == sentinel_red:
                pixels[x, y] = yellow


def _lcars_post_pass_coral(pixels, left: int, top: int, right: int, bot: int,
                           sentinel_red) -> None:
    """Bbox-scoped R+W 50/50 checkerboard (coral). Only touches
    ``sentinel_red`` pixels, so solid red elsewhere stays saturated."""
    white = SPECTRA6["white"]
    for py in range(top, bot + 1):
        for px in range(left, right + 1):
            if (px + py) & 1 and pixels[px, py] == sentinel_red:
                pixels[px, py] = white


def draw_lcars_border(image: Image.Image, colors: dict) -> None:
    """Paint a Michael Okuda LCARS interface frame: an L of chrome down the
    left edge and along the top and bottom, rounded where it wraps each
    canvas corner, with a stack of coloured rail blocks and an "LCARS"
    wordmark.

    * **Bars and elbows.** ``T`` (44 px at 800×480) is both the bar
      thickness and the rail width. The top bar (y = 0..T-1) is split into
      a tangerine segment and a lavender one with a small black gap; the
      bottom bar is one tangerine ribbon. Each corner is an annular
      quarter-circle elbow: outer radius ``R_out``, inner radius
      ``R_in = R_out - T``, common centre ``(R_out, R_out)`` (mirrored at
      the bottom), so the chrome has uniform thickness T.
    * **Tangerine.** Spectra 6 has no orange. The chrome is painted in
      ``ornament_dark`` (red) and ~3/8 of it flipped to yellow on
      ``BAYER_4x4`` (cells < 6), as ``draw_deco_border`` does; a 50/50 mix
      reads as washed-out amber. Bbox-scoped, so the body is untouched.
    * **Seven rail blocks** between the elbows, plain rectangles within the
      rail column, separated by black gaps: lavender, yellow, coral, lilac,
      red, coral, blue, with uneven heights. Lavender / lilac are 3-ink
      R+B+W stipples and coral is R+W 1:1 (sentinel + bbox post-pass, see
      ``spectra6_color_recipes.md``).
    * **Block labels**: short fixed numeric codes in black, right-aligned
      in each block.
    * **"LCARS" wordmark** right-aligned in the top bar's lavender
      segment, and a **"STARDATE" callout** in the bottom bar, both black
      in the ornament face (Antonio Bold).

    The top bar spans the y = 14..29 ``DEBUG MODE`` band, so in debug mode
    the yellow label sits on the chrome (reduced contrast, still legible;
    production has no label). ``lcars`` has no ``_DEBUG_LABEL_RIGHT_INSET``
    entry.

    The rail column is x = 0..T-1 (0..43); the widest body (``dense``,
    ``max_width`` 680) starts at x = 60, so rail and text never meet.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size

    # Chrome is painted in ``ornament_dark`` (red) as a sentinel; the
    # tangerine / coral post-passes convert it. Labels on the blocks are
    # black, the Okudagram contrast.
    sentinel_red = colors["ornament_dark"]
    label_ink_on_block = SPECTRA6["black"]

    # --- Geometry ---
    # Every constant scales with the canvas: ``/api/preview`` calls this at
    # sizes down to ``PREVIEW_MIN_*`` = 80×60, and fixed native constants
    # would invert PIL bboxes (``rail_top > rail_bot``) and 500 the
    # endpoint. Below scale 0.5 the chrome is sub-pixel, so paint nothing.
    scale = min(width / 800.0, height / 480.0)
    if scale < 0.5:
        return
    # ``T`` is both bar thickness and rail width; the annular elbow needs
    # them equal so R_out − R_in matches both. ``R_out`` sets how rounded
    # the canvas-corner curve is.
    T = max(8, int(round(44 * scale)))
    bar_thickness = T
    rail_width = T
    R_out = max(16, int(round(72 * scale)))   # outer elbow radius
    R_in = R_out - T                           # derived
    # Rail blocks are plain rectangles confined to the rail column, so they
    # read as flush sidebar segments rather than floating pill buttons.
    block_right = rail_width - 1

    top_bar_y1 = 0
    top_bar_y2 = bar_thickness - 1
    bottom_bar_y2 = height - 1
    bottom_bar_y1 = bottom_bar_y2 - bar_thickness + 1

    page_bg = colors.get("page_bg", SPECTRA6["black"])
    lavender_sentinel = (1, 1, 1)

    # ===========================================================
    # Layer 1: paint top/bottom bars + rail straight runs
    # ===========================================================
    # The straight runs start at ``R_out``: x, y ∈ [0, R_out) is the
    # elbow's footprint, painted in Layer 2. The top bar is two segments
    # with a ~6 px black divider.
    segment_gap = max(2, int(round(6 * scale)))
    top_bar_left = R_out
    top_bar_right = width - 1
    top_bar_inner_w = top_bar_right - top_bar_left + 1
    seg1_w = int(top_bar_inner_w * 0.55)
    seg1_left = top_bar_left
    seg1_right = seg1_left + seg1_w - 1
    seg2_left = seg1_right + 1 + segment_gap
    seg2_right = top_bar_right
    # First (tangerine) segment of the top bar.
    draw.rectangle(
        (seg1_left, top_bar_y1, seg1_right, top_bar_y2),
        fill=sentinel_red,
    )
    # Second (lavender) segment of the top bar.
    draw.rectangle(
        (seg2_left, top_bar_y1, seg2_right, top_bar_y2),
        fill=lavender_sentinel,
    )
    # Bottom bar: one tangerine ribbon from R_out, clear of the elbow; the
    # STARDATE callout gives it weight.
    draw.rectangle(
        (R_out, bottom_bar_y1, width - 1, bottom_bar_y2),
        fill=sentinel_red,
    )
    # No uniform rail strip: the straight rail between the elbows is only
    # the stacked blocks, with black gaps as separators. A tangerine strip
    # under them would swallow any warm block.

    # ===========================================================
    # Layer 2: annular-quadrant elbows (BOTH outer + inner rounded)
    # ===========================================================
    # Each elbow is the annulus between two concentric quarter-circles
    # centred at (R_out, R_out) (top elbow): the outer arc (radius R_out)
    # rounds the canvas corner, the inner arc (radius R_in = R_out − T)
    # rounds the page-interior side.
    #
    # Paint the outer-disc quadrant in the sentinel, then carve the inner
    # one in page_bg. For the top-left quadrant the pieslice angles run
    # 180° → 270°.
    # Top elbow:
    draw.pieslice(
        (0, 0, 2 * R_out - 1, 2 * R_out - 1),
        start=180, end=270,
        fill=sentinel_red,
    )
    if R_in > 0:
        draw.pieslice(
            (T, T, 2 * R_out - T - 1, 2 * R_out - T - 1),
            start=180, end=270,
            fill=page_bg,
        )
    # Bottom elbow, mirrored: centre (R_out, height - R_out), angles
    # 90° → 180°.
    bottom_disc_y1 = height - 2 * R_out
    bottom_disc_y2 = height - 1
    draw.pieslice(
        (0, bottom_disc_y1, 2 * R_out - 1, bottom_disc_y2),
        start=90, end=180,
        fill=sentinel_red,
    )
    if R_in > 0:
        draw.pieslice(
            (T, bottom_disc_y1 + T, 2 * R_out - T - 1, bottom_disc_y2 - T),
            start=90, end=180,
            fill=page_bg,
        )

    # ===========================================================
    # Layer 2: rail blocks between the two elbows
    # ===========================================================
    # Seven blocks; the stippled tones are off the native palette and need
    # sentinel paint + bbox post-pass, hence the ``_lcars_paint_*`` helpers.
    # The rail's straight section runs y ∈ [R_out, height − R_out − 1],
    # with a 3 px gutter at each end so the end blocks don't merge into the
    # elbow arcs.
    rail_gutter = max(1, int(round(3 * scale)))
    rail_top = R_out + rail_gutter
    rail_bot = height - R_out - rail_gutter - 1
    rail_height = rail_bot - rail_top + 1
    block_gap = max(1, int(round(3 * scale)))
    # ``block_specs`` is (kind, label, proportion of height); the
    # proportions sum to 1.0 and vary on purpose, as LCARS block heights
    # did. Labels stay at 3-5 chars: the block is only ~rail_width wide
    # and a longer code clips at the left edge.
    # No tangerine / peach blocks: they share R+Y pixels with the chrome
    # and vanish into it. The mix is pastel stipples (lavender, lilac,
    # coral) plus native red / yellow / blue (critical / advisory /
    # informational in LCARS convention).
    block_specs = [
        ("lavender", "40-27", 0.14),
        ("yellow",   "65-54", 0.16),
        ("coral",    "97-56", 0.13),
        ("lilac",    "76-54", 0.16),
        ("red",      "22-43", 0.13),
        ("coral",    "57-65", 0.15),
        ("blue",     "18-82", 0.13),
    ]
    assert abs(sum(p for _, _, p in block_specs) - 1.0) < 1e-6
    available_v = rail_height - block_gap * (len(block_specs) - 1)
    pixels = pixel_access(image)
    blocks: list[tuple[int, int, int, int, str]] = []
    cursor_y = rail_top
    for kind, label, prop in block_specs:
        bh = int(round(available_v * prop))
        top = cursor_y
        bot = cursor_y + bh - 1
        left = 0
        right = block_right
        # Native-ink blocks fill directly; stippled ones paint a sentinel
        # and convert it with a per-block bbox post-pass.
        if kind == "coral":
            draw.rectangle((left, top, right, bot), fill=sentinel_red)
            _lcars_post_pass_coral(pixels, left, top, right, bot, sentinel_red)
        elif kind == "lavender":
            draw.rectangle((left, top, right, bot), fill=lavender_sentinel)
            _lcars_paint_rbw_block(pixels, left, top, right, bot, lavender_sentinel, _LCARS_LAVENDER_CUTS)
        elif kind == "lilac":
            draw.rectangle((left, top, right, bot), fill=lavender_sentinel)
            _lcars_paint_rbw_block(pixels, left, top, right, bot, lavender_sentinel, _LCARS_LILAC_CUTS)
        elif kind == "yellow":
            draw.rectangle((left, top, right, bot), fill=SPECTRA6["yellow"])
        elif kind == "red":
            # Solid red is unambiguous here: the tangerine chrome is
            # separated from this block by a gap and the elbow geometry.
            draw.rectangle((left, top, right, bot), fill=SPECTRA6["red"])
        elif kind == "blue":
            draw.rectangle((left, top, right, bot), fill=SPECTRA6["blue"])
        blocks.append((left, top, right, bot, label))
        cursor_y += bh + block_gap

    # ===========================================================
    # Layer 3: convert the chrome sentinels to tangerine + lavender
    # ===========================================================
    # Convert the chrome's sentinel red (top-bar left segment, bottom
    # bar, both elbows) to tangerine in two sweeps over the chrome's y
    # extent; the rail blocks lie outside both sweeps. The lavender
    # top-bar segment uses another sentinel and gets its own pass.
    # Top region: covers the top bar + the entire top elbow annulus.
    _lcars_post_pass_tangerine(pixels, 0, top_bar_y1, width - 1, R_out - 1, sentinel_red)
    # Bottom region: covers the bottom bar + the entire bottom elbow.
    _lcars_post_pass_tangerine(pixels, 0, height - R_out, width - 1, bottom_bar_y2, sentinel_red)
    # Lavender segment of the top bar.
    _lcars_paint_rbw_block(pixels, seg2_left, top_bar_y1, seg2_right, top_bar_y2, lavender_sentinel,
                           _LCARS_LAVENDER_CUTS)

    # ===========================================================
    # Layer 4: black labels centred inside each block
    # ===========================================================
    block_label_font = load_font(META_FONT_BOLD_CANDIDATES, max(6, int(round(10 * scale))))
    label_pad_right = 4   # inset from the block's right edge
    for left, top, right, bot, label in blocks:
        baseline_bbox = draw.textbbox((0, 0), label, font=block_label_font)
        label_w = baseline_bbox[2] - baseline_bbox[0]
        label_h = baseline_bbox[3] - baseline_bbox[1]
        # Right-align inside the block.
        label_x = right - label_pad_right - label_w - baseline_bbox[0]
        label_y = top + (bot - top - label_h) // 2 - baseline_bbox[1]
        draw.text(
            (label_x, label_y),
            label,
            font=block_label_font,
            fill=label_ink_on_block,
        )

    # ===========================================================
    # Layer 5: large "LCARS" wordmark in the top bar
    # ===========================================================
    # Right-aligned inside the top bar's lavender segment, black on
    # lavender, sized to most of the bar height.
    wordmark_font = load_font(theme_font_candidates("lcars", "ornament"), max(10, int(round(26 * scale))))
    wordmark_text = "LCARS"
    wordmark_bbox = draw.textbbox((0, 0), wordmark_text, font=wordmark_font)
    wordmark_w = wordmark_bbox[2] - wordmark_bbox[0]
    wordmark_h = wordmark_bbox[3] - wordmark_bbox[1]
    wordmark_x = width - 16 - wordmark_w
    wordmark_y = top_bar_y1 + (bar_thickness - wordmark_h) // 2 - wordmark_bbox[1]
    draw.text(
        (wordmark_x, wordmark_y),
        wordmark_text,
        font=wordmark_font,
        fill=label_ink_on_block,
    )

    # ===========================================================
    # Layer 6: bottom-right "STARDATE" callout
    # ===========================================================
    # A secondary heading at the bottom right (the reference wallpaper's
    # "DATA NODE 188"), black on the tangerine bottom bar, smaller than
    # the wordmark so the string fits the bar.
    stardate_font = load_font(theme_font_candidates("lcars", "ornament"), max(7, int(round(14 * scale))))
    stardate_text = "STARDATE 47988.1"
    sd_bbox = draw.textbbox((0, 0), stardate_text, font=stardate_font)
    sd_w = sd_bbox[2] - sd_bbox[0]
    sd_h = sd_bbox[3] - sd_bbox[1]
    sd_x = width - 16 - sd_w
    sd_y = bottom_bar_y1 + (bar_thickness - sd_h) // 2 - sd_bbox[1]
    draw.text(
        (sd_x, sd_y),
        stardate_text,
        font=stardate_font,
        fill=label_ink_on_block,
    )


SPEC = BorderSpec(
    themes=("lcars",),
    paint=draw_lcars_border,
)
