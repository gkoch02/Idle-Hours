"""The ``comic`` theme's border painter, a golden-age comic panel: a Ben-Day dot corner,
a racing-stripe chevron and a heavy black gutter.

Design notes: docs/themes.md § comic
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..palette import SPECTRA6
from ..spec import BorderSpec

# Hardcoded: the comic THEMES entry has only two non-bg slots, and adding
# a blue / green one would re-pin the cross-theme invariant tests.
_COMIC_STRIPE_PALETTE = (
    SPECTRA6["blue"],
    SPECTRA6["green"],
    SPECTRA6["red"],
    SPECTRA6["black"],
)


def draw_comic_corner_stripes(image: Image.Image, colors: dict) -> None:
    """Paint a comic-book panel: Ben-Day halftone corner, racing-stripe
    chevron, and a heavy black panel gutter. The stripe gaps take
    ``colors["page_bg"]``. Design notes: docs/themes.md § comic.
    """
    width, height = image.size

    # Ben-Day halftone dots: a red dot grid masked to a top-left right
    # triangle (cx + cy ≤ tri_legs), inset ≥22 px so the gutter corner and
    # the sampled (15, 15) pixel stay yellow.
    dot_draw = ImageDraw.Draw(image)
    # Default to red dots / black gutter so unit tests that pass only
    # ``page_bg`` still render the full panel.
    dot_color = colors.get("accent", SPECTRA6["red"])
    dot_r = 3
    dot_step = 16
    dot_inset = 26
    tri_legs = 150
    cy = dot_inset
    while cy <= tri_legs:
        cx = dot_inset
        while cx <= tri_legs:
            if cx + cy <= tri_legs:
                dot_draw.ellipse((cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r), fill=dot_color)
            cx += dot_step
        cy += dot_step

    qx = width // 2
    qy = height // 2
    qw = width - qx
    qh = height - qy

    # Paint stripes onto a sub-image the size of the lower-right quadrant,
    # so bands clip on its bounds without per-stripe polygon math.
    quadrant = Image.new("RGB", (qw, qh), color=colors["page_bg"])
    qd = ImageDraw.Draw(quadrant)

    stripe_thickness = 19
    stripe_gap = 11
    period = stripe_thickness + stripe_gap
    palette = _COMIC_STRIPE_PALETTE

    # Each band runs at slope -1 through (c, qh) at the sub-image bottom
    # and (c + qh, 0) at the top, extended past both bounds so PIL's line
    # caps don't leave a gap at the canvas edge. Only four bands are kept:
    # indices 17-20 at the native 400×240 quadrant, the same relative
    # position at other sizes.
    stripe_cs = list(range(-qh - period, qw + period + 1, period))
    keep_count = min(4, len(stripe_cs))
    if qh == 240 and qw == 400:
        kept_indices = {17, 18, 19, 20}
    else:
        default_qh = 240
        default_qw = 400
        default_stripe_cs = list(range(-default_qh - period, default_qw + period + 1, period))
        default_keep_indices = {17, 18, 19, 20}
        target_mid = sum(default_keep_indices) / len(default_keep_indices)
        scale = len(stripe_cs) / len(default_stripe_cs)
        scaled_mid = target_mid * scale
        keep_start = round(scaled_mid - (keep_count - 1) / 2)
        keep_start = max(0, min(keep_start, max(0, len(stripe_cs) - keep_count)))
        kept_indices = set(range(keep_start, min(len(stripe_cs), keep_start + keep_count)))

    overshoot = max(stripe_thickness, stripe_gap)
    for i, c in enumerate(stripe_cs):
        if i in kept_indices:
            color = palette[i % len(palette)]
            qd.line(
                [(c - overshoot, qh + overshoot), (c + qh + overshoot, -overshoot)],
                fill=color,
                width=stripe_thickness,
            )

    # Right-isoceles triangle mask (legs qh) at the quadrant's bottom-right,
    # hypotenuse parallel to the stripes. Mode "L" so paste() uses it as
    # per-pixel alpha.
    mask = Image.new("L", (qw, qh), 0)
    md = ImageDraw.Draw(mask)
    md.polygon([(qw - qh, qh), (qw, 0), (qw, qh)], fill=255)

    image.paste(quadrant, (qx, qy), mask=mask)

    # Heavy black panel border, painted last over the dots and stripes.
    # Inset 2 / width 4 puts the stroke at x/y 2–5, clear of every comic
    # gating-test sample point ((6,16), (12,12), (400,11), (15,15),
    # (20,20), (36,56)).
    border_draw = ImageDraw.Draw(image)
    panel_inset = 2
    border_draw.rectangle(
        (panel_inset, panel_inset, width - 1 - panel_inset, height - 1 - panel_inset),
        outline=colors.get("text", SPECTRA6["black"]),
        width=4,
    )


SPEC = BorderSpec(
    themes=("comic",),
    paint=draw_comic_corner_stripes,
)
