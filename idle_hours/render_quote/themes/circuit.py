"""The ``circuit`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .._paths import META_FONT_CANDIDATES, SPACEMONO_REGULAR
from ..fonts import load_font
from ..palette import SPECTRA6, pixel_access
from ..spec import BorderSpec

# Copper-trace routes for ``draw_circuit_border``: polylines of (x_frac,
# y_frac) waypoints, stroked in gold with ``joint="curve"`` corners (the
# teardrop bends of a PCB autorouter). They hug the perimeter margins (the
# body block is knocked out via ``clear_rect``) and stay clear of the
# y=14-29 DEBUG-banner band.
_CIRCUIT_TRACES: tuple[tuple[tuple[float, float], ...], ...] = (
    # Top bus — left-to-right across the top margin with a centred jog.
    ((0.06, 0.10), (0.40, 0.10), (0.46, 0.16)),
    ((0.55, 0.16), (0.61, 0.10), (0.86, 0.10)),
    # Left rail down the side margin with two right-angle branches inward.
    ((0.05, 0.16), (0.05, 0.55), (0.12, 0.62)),
    ((0.05, 0.34), (0.11, 0.34)),
    # Right rail down the side margin.
    ((0.95, 0.18), (0.95, 0.60), (0.88, 0.67)),
    ((0.95, 0.42), (0.89, 0.42)),
    # Bottom bus across the bottom margin with a 45° jog.
    ((0.09, 0.90), (0.42, 0.90), (0.48, 0.84)),
    ((0.58, 0.84), (0.64, 0.90), (0.92, 0.90)),
    # Two short diagonal traces for visual variety.
    ((0.15, 0.21), (0.21, 0.27), (0.21, 0.40)),
    ((0.85, 0.24), (0.79, 0.30), (0.79, 0.45)),
)
# Silkscreen reference designators (text, x_frac, y_frac) beside the routed
# pads. The crystal "Y1" is drawn separately as a component outline — the
# quartz oscillator, the literal clock element on a real board.
_CIRCUIT_DESIGNATORS: tuple[tuple[str, float, float], ...] = (
    ("R1", 0.40, 0.10),
    ("R2", 0.61, 0.10),
    ("C1", 0.05, 0.55),
    ("C4", 0.95, 0.60),
    ("U1", 0.21, 0.40),
    ("D2", 0.79, 0.45),
)


def draw_circuit_border(
    image: Image.Image,
    colors: dict,
    clear_rect: tuple[int, int, int, int] | None = None,
) -> None:
    """Paint a printed-circuit-board (PCB) composition around the quote.

    The clock as if etched onto the board that drives the panel. Layers,
    deepest → shallowest:

    * **Layer 0 — forest soldermask wash.** Half the green ``page_bg`` pixels
      flipped to black on the ``(x + y) & 1`` checkerboard: G+K 1:1 reads as
      FR-4 bottle-green and keeps ``circuit`` distinct from ``atomic``'s mint.
      Idempotent (only green pixels flip), which matters because ``render``
      calls every border painter twice.
    * **Copper traces** (gold) from ``_CIRCUIT_TRACES``.
    * **Plated pads** at every trace endpoint — gold ring, dark drill.
    * **Mounting holes** in the four corners, inset 28 px. The top-right one
      overlaps the DEBUG-banner band, hence ``circuit``'s
      ``_DEBUG_LABEL_RIGHT_INSET`` entry.
    * **Y1 crystal** in the bottom-left margin.
    * **Silkscreen designators** (white) plus an ``IDLE HOURS · REV 2.0``
      legend bottom-right.

    With ``clear_rect`` the body region is reset to clean soldermask and
    framed with a white silkscreen component outline and a pin-1 marker.
    """
    width, height = image.size
    page_bg = colors.get("page_bg")
    gold = colors.get("accent", SPECTRA6["yellow"])
    silk = colors.get("text", SPECTRA6["white"])
    green_ink = SPECTRA6["green"]
    black_ink = SPECTRA6["black"]
    pixels = pixel_access(image)
    draw = ImageDraw.Draw(image)

    # ------------------------------------------------------------------
    # Layer 0 — forest soldermask wash (G+K 1:1 over the flat-green ground).
    if page_bg == green_ink:
        for y in range(height):
            row_odd = y & 1
            for x in range(width):
                if ((x & 1) ^ row_odd) and pixels[x, y] == green_ink:
                    pixels[x, y] = black_ink

    trace_w = max(2, round(width / 320))
    pad_r = max(3, round(width / 130))

    def _pad(px: int, py: int, r_out: int = pad_r) -> None:
        r_in = max(1, r_out - 3)
        draw.ellipse((px - r_out, py - r_out, px + r_out, py + r_out), fill=gold)
        draw.ellipse((px - r_in, py - r_in, px + r_in, py + r_in), fill=black_ink)

    # ------------------------------------------------------------------
    # Copper traces + pads at their endpoints.
    for route in _CIRCUIT_TRACES:
        pts = [(round(fx * width), round(fy * height)) for fx, fy in route]
        if len(pts) >= 2:
            draw.line(pts, fill=gold, width=trace_w, joint="curve")
        for px, py in (pts[0], pts[-1]):
            _pad(px, py)

    # ------------------------------------------------------------------
    # Corner mounting holes — white keep-out ring around a dark drill.
    mount_inset = 28
    mount_r = max(5, round(width / 62))
    for mx, my in (
        (mount_inset, mount_inset),
        (width - 1 - mount_inset, mount_inset),
        (mount_inset, height - 1 - mount_inset),
        (width - 1 - mount_inset, height - 1 - mount_inset),
    ):
        draw.ellipse((mx - mount_r, my - mount_r, mx + mount_r, my + mount_r), outline=silk, width=2)
        drill = max(2, mount_r - 4)
        draw.ellipse((mx - drill, my - drill, mx + drill, my + drill), fill=black_ink)

    # ------------------------------------------------------------------
    # Silkscreen designators (white) beside the routed pads.
    label_font = load_font([SPACEMONO_REGULAR, *META_FONT_CANDIDATES], size=max(9, round(width / 72)))
    for text, fx, fy in _CIRCUIT_DESIGNATORS:
        lx = round(fx * width) + pad_r + 3
        ly = round(fy * height) - pad_r - 2
        draw.text((lx, ly), text, font=label_font, fill=silk)

    # ------------------------------------------------------------------
    # Y1 quartz crystal in the bottom-left margin — component outline,
    # two pads, and a label. The literal clock element on the board.
    can_cx = round(0.22 * width)
    can_cy = round(0.92 * height)
    can_hw = max(12, round(width / 40))
    can_hh = max(5, round(height / 64))
    draw.rounded_rectangle(
        (can_cx - can_hw, can_cy - can_hh, can_cx + can_hw, can_cy + can_hh),
        radius=3, outline=silk, width=2,
    )
    _pad(can_cx - can_hw, can_cy + can_hh + 3, r_out=max(3, pad_r - 1))
    _pad(can_cx + can_hw, can_cy + can_hh + 3, r_out=max(3, pad_r - 1))
    draw.text((can_cx + can_hw + 6, can_cy - can_hh), "Y1", font=label_font, fill=silk)

    # Board legend, bottom-right silkscreen.
    legend = "IDLE HOURS · REV 2.0"
    legend_bb = draw.textbbox((0, 0), legend, font=label_font)
    legend_w = legend_bb[2] - legend_bb[0]
    draw.text((width - mount_inset - legend_w, round(0.945 * height)), legend, font=label_font, fill=silk)

    # ------------------------------------------------------------------
    # Body-text knockout — clean forest board + white silkscreen outline.
    if clear_rect is None or page_bg is None:
        return
    cx0, cy0, cx1, cy1 = clear_rect
    cx0 = max(0, cx0)
    cy0 = max(0, cy0)
    cx1 = min(width - 1, cx1)
    cy1 = min(height - 1, cy1)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    # Reset to clean soldermask, wiping anything routed across the body.
    for py in range(cy0, cy1 + 1):
        row_odd = py & 1
        for px in range(cx0, cx1 + 1):
            pixels[px, py] = black_ink if ((px & 1) ^ row_odd) else green_ink
    # Silkscreen "component outline" framing the populated area + pin-1 dot.
    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=6, outline=silk, width=1)
    draw.rectangle((cx0 - 1, cy0 - 1, cx0 + 3, cy0 + 3), fill=silk)


SPEC = BorderSpec(
    themes=("circuit",),
    paint=draw_circuit_border,
    # The painter routes copper, pads and silkscreen across the board, then
    # knocks the body region back to clean forest soldermask and frames it
    # with a 1 px white silkscreen outline and a pin-1 corner dot; the pad
    # keeps that outline (and the dot just outside the top-left corner)
    # clear of the first and last text lines.
    clear_rect_pad=(16, 10, 10),
    # past the TR mounting hole's keep-out ring (leftmost
    # x=width-42) plus a 4 px gap
    debug_label_inset=46,
    # The look is the composite of two paints (issue #361).
    paints_twice=True,
)
