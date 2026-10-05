"""The ``chanbara`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..palette import SPECTRA6


def draw_chanbara_border(image: Image.Image, colors: dict) -> None:
    """Paint a samurai-cinema title-card surround: large off-canvas
    rising-sun disc with a red-to-maroon radial edge gradient, plus a
    small maroon artist's-chop seal in the top-left corner.

    * **Rising-sun disc**: a filled ``colors["accent"]`` (red) circle,
      centre ``(width + 30, height + 30)``, radius 220; PIL clips the
      off-canvas part, leaving an arc through the bottom-right quadrant.
      A radial post-pass then flips half the red pixels in the outer
      40 px shell to black on ``(x+y)&1`` parity (R+K 1:1 maroon), so the
      disc darkens from vermilion to oxblood at the rim. White text reads
      on both. Pinned bottom-right so the top-right stays clear of the
      ``DEBUG MODE`` banner.
    * **Artist's chop seal**: a 28×36 px red rectangle at ``(24, 24)``,
      maroon-post-passed the same way (an aged hanko). Its white "ichi"
      stroke is painted *after* the post-pass so it stays solid.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    accent_color = colors["accent"]
    light_color = colors.get("ornament_light", SPECTRA6["white"])

    # Large rising-sun disc anchored off-canvas in the bottom-right; only
    # its upper-left arc lands on the canvas.
    sun_cx = width + 30
    sun_cy = height + 30
    sun_radius = 220
    draw.ellipse(
        (sun_cx - sun_radius, sun_cy - sun_radius,
         sun_cx + sun_radius, sun_cy + sun_radius),
        fill=accent_color,
    )

    # Radial maroon post-pass on the disc's outer 40 px shell, restricted
    # to the BR quadrant (the only place the disc paints). Squared
    # distances avoid a sqrt() per pixel.
    sentinel_red = SPECTRA6["red"]
    maroon_dark = SPECTRA6["black"]
    pixels = image.load()
    inner_r_sq = (sun_radius - 40) * (sun_radius - 40)
    outer_r_sq = sun_radius * sun_radius
    quad_x0 = width // 2
    quad_y0 = height // 2
    for py in range(quad_y0, height):
        dy = py - sun_cy
        dy_sq = dy * dy
        for px in range(quad_x0, width):
            dx = px - sun_cx
            d_sq = dx * dx + dy_sq
            if inner_r_sq <= d_sq <= outer_r_sq:
                if (px + py) & 1 == 0 and pixels[px, py] == sentinel_red:
                    pixels[px, py] = maroon_dark

    # Artist's chop seal: a red rectangle, sentinel for the post-pass below.
    chop_left = 24
    chop_top = 24
    chop_w = 28
    chop_h = 36
    chop_right = chop_left + chop_w
    chop_bottom = chop_top + chop_h
    draw.rectangle(
        (chop_left, chop_top, chop_right, chop_bottom),
        fill=accent_color,
    )

    # Maroon post-pass on the chop seal's bbox (the disc-rim recipe),
    # clipped to the image bounds for small preview canvases.
    for py in range(chop_top, min(chop_bottom + 1, height)):
        for px in range(chop_left, min(chop_right + 1, width)):
            if (px + py) & 1 == 0 and pixels[px, py] == sentinel_red:
                pixels[px, py] = maroon_dark

    # White "ichi" stroke through the chop's centre, painted after the
    # post-pass so it lands solid; inset 5 px from each side so it reads
    # as a mark, not a bisection.
    stroke_y = chop_top + chop_h // 2
    draw.line(
        [(chop_left + 5, stroke_y), (chop_right - 5, stroke_y)],
        fill=light_color,
        width=2,
    )

    # Vertical brush-tick column in the left margin, the signature / date
    # column a samurai-cinema poster runs beside the seal: five uneven
    # sumi strokes, red sentinel then maroon post-pass to match the chop.
    # At x≈14-40, y≈196-280: below the oversized opening quote mark
    # (y≈20-140), and left of the body (dense layout starts at x≥60).
    tick_cx = chop_left + chop_w // 2
    tick_specs = ((196, 11), (212, 9), (228, 12), (244, 8), (260, 10))
    for ty, half in tick_specs:
        draw.line([(tick_cx - half, ty), (tick_cx + half, ty)], fill=sentinel_red, width=2)
    # Ink-spatter flecks trailing off the lowest ticks (same sentinel).
    for fx, fy in ((tick_cx + 15, 266), (tick_cx - 13, 272), (tick_cx + 6, 278)):
        draw.ellipse((fx - 1, fy - 1, fx + 1, fy + 1), fill=sentinel_red)
    # Maroon post-pass over the brush-tick column bbox (x±18, y 188-282).
    col_x0 = max(0, tick_cx - 18)
    col_x1 = min(width - 1, tick_cx + 18)
    for py in range(188, min(283, height)):
        for px in range(col_x0, col_x1 + 1):
            if (px + py) & 1 == 0 and pixels[px, py] == sentinel_red:
                pixels[px, py] = maroon_dark
