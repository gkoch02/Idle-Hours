"""The ``letter`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from .._paths import BASE_DIR
from ..palette import SPECTRA6, BAYER_4x4, _load_dithered_plate
from ..spec import BorderSpec

# Fixed seed for the letter theme's aged-paper texture, so re-renders stay
# byte-identical.
_LETTER_PAPER_SEED = 0x1E77E2


def _letter_paint_aged_paper(image: Image.Image, width: int, height: int, page_bg,
                             cream_light, sepia_a, sepia_b, rng: random.Random) -> None:
    """Synthesised aged-paper Layer 0 — the graceful fallback for ``letter``
    when the committed ``letter_aged_paper.png`` plate is missing.

    Two textures, every pixel an ink so palette-snap is a no-op. Deliberately
    subtle: it should read as old paper, not compete with the handwriting.

      (a) Uneven cream tan: yellow-wash density modulated by an edge
          vignette, a low-amplitude mottle (precomputed per-row / per-column
          sine tables, no per-pixel trig) and a fine grain jitter. Centre
          ≈9% yellow, corners ≈14%.
      (b) Foxing: seeded R+G sepia spots biased toward the edges.

    The creases and wax seal are painted by ``draw_letter_border`` after this
    returns.
    """
    if page_bg is None:
        return
    pixels = image.load()
    col = [math.sin(x * 0.013) + 0.6 * math.sin(x * 0.031 + 1.7) for x in range(width)]
    row_mottle = [math.sin(y * 0.015 + 0.5) + 0.6 * math.sin(y * 0.029 + 2.3) for y in range(height)]
    half_w = max(1.0, width * 0.5)
    half_h = max(1.0, height * 0.5)
    for y in range(height):
        brow = BAYER_4x4[y & 3]
        ry = row_mottle[y]
        edge_y = 1.0 - min(y, height - 1 - y) / half_h
        for x in range(width):
            if pixels[x, y] != page_bg:
                continue
            edge_x = 1.0 - min(x, width - 1 - x) / half_w
            edge = edge_x if edge_x > edge_y else edge_y
            mottle = (col[x] + ry) * 0.5
            grain = (((x * 131 + y * 57) % 17) - 8) / 8.0
            density = 0.085 + 0.05 * (edge * edge) + 0.02 * mottle + 0.02 * grain
            if brow[x & 3] < density * 16:
                pixels[x, y] = cream_light

    # (b) Foxing: each spot a 2x2 or 3x3 R/G checkerboard so it carries a
    # balanced pair and averages to rust-brown (a circular mask leaves
    # imbalanced plus-shapes that read as lone red or green specks).
    n_spots = max(10, (width * height) // 9000)
    for _ in range(n_spots):
        fx = int(rng.triangular(0, width - 1, rng.choice((0, width - 1))))
        fy = int(rng.triangular(0, height - 1, rng.choice((0, height - 1))))
        spot_w = rng.choice((2, 2, 3))
        for dy in range(spot_w):
            for dx in range(spot_w):
                px, py = fx + dx, fy + dy
                if 0 <= px < width and 0 <= py < height and pixels[px, py] in (page_bg, cream_light):
                    pixels[px, py] = sepia_a if (px + py) & 1 else sepia_b


def draw_letter_border(image: Image.Image, colors: dict,
                       clear_rect: tuple[int, int, int, int] | None = None) -> None:
    """Wax-sealed letter decoration: aged, lightly-crumpled paper ground +
    fold/crumple creases + a pressed oxblood / maroon wax seal in the
    bottom-right corner.

    Everything stays in the margins and paints before the text, so the
    creases sit behind the glyphs as real folds do and the quote block never
    reaches the seal's corner. Layers, bottom to top:

    * **Layer 0 — aged paper.** ``letter_aged_paper.png`` dithered to
      white/yellow/red/green (W+Y cream, R+G foxing), so palette-snap is a
      no-op; ``_letter_paint_aged_paper`` synthesises it when the asset is
      missing.
    * **Writing-area knockout** — with ``clear_rect``, the body rect is reset
      to clean cream with a feathered edge, so foxing doesn't speckle the
      thin script strokes.
    * **Crumple creases** — two dotted fold creases at the thirds, plus (in
      the fallback path only) a few soft tonal wrinkles. Painted only on bare
      paper; the body text overpaints them.
    * **The wax seal** (bottom-right) — an oxblood dome lit from the upper
      left: a scalloped rim (two summed sinusoids), a Bayer ramp anchored on
      R+K maroon (red on the lit shoulder, white for coral gloss, black
      climbing toward the rim), a stippled cast shadow, a specular hotspot, a
      ring of shaded beads and a recessed hourglass emblem, plus a few
      spatter flecks. It sits clear of the attribution and the y=14-29 debug
      band, so ``letter`` needs no ``_DEBUG_LABEL_RIGHT_INSET`` entry.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    page_bg = colors.get("page_bg")
    ink = colors["text"]
    wax_red = colors["accent"]
    maroon_dark = SPECTRA6["black"]
    cream_light = SPECTRA6["yellow"]

    sepia_a = SPECTRA6["red"]
    sepia_b = SPECTRA6["green"]
    rng = random.Random(_LETTER_PAPER_SEED)

    # ---- Layer 0: aged paper ------------------------------------------
    # Committed plate dithered to W/Y/R/G, or the synthesised fallback when
    # the asset is unavailable (stripped install). Both yield pure Spectra-6.
    # The creases and seal paint over either.
    plate = _load_dithered_plate(LETTER_PLATE, width, height, palette=_AGED_PAPER_PALETTE)
    if plate is not None:
        image.paste(plate, (0, 0))
    else:
        _letter_paint_aged_paper(image, width, height, page_bg, cream_light, sepia_a, sepia_b, rng)
    pixels = image.load()

    # ---- Body-text writing area: clean cream knockout -----------------
    # The plate's foxing speckle around the thin Dancing Script strokes reads
    # as blur, so with ``clear_rect`` the rect is reset to clean cream (white
    # + light yellow stipple), feathered so it blends into the foxed margins.
    if clear_rect is not None and page_bg is not None:
        cx0, cy0, cx1, cy1 = clear_rect
        feather = 16
        for py in range(max(0, cy0), min(height - 1, cy1) + 1):
            for px in range(max(0, cx0), min(width - 1, cx1) + 1):
                edge_d = min(px - cx0, cx1 - px, py - cy0, cy1 - py)
                # Feathered ring: clean with probability rising inward.
                if edge_d < feather and ((px * 131 + py * 57) % 16) / 16.0 >= edge_d / feather:
                    continue
                # ~1/16 yellow (≈6%), matching the plate's pale-cream centre,
                # so only the removed foxing distinguishes the area.
                pixels[px, py] = cream_light if BAYER_4x4[py & 3][px & 3] == 0 else page_bg

    # ---- Crumple creases ----------------------------------------------
    # Two dotted black fold creases at the thirds, plus soft tonal wrinkles
    # (a cream ridge with a white highlight) that read as light catching the
    # sheet rather than as scratches. Painted only on bare paper / cream.
    paper_tones = (page_bg, cream_light)
    margin = 26
    crease_step = 4
    for frac in (1, 2):
        cy = (height * frac) // 3
        if cy + 1 >= height:
            continue
        for x in range(margin, width - margin, crease_step):
            if pixels[x, cy] in paper_tones:
                pixels[x, cy] = ink
            vx = x + crease_step // 2
            if vx < width - margin and (x // crease_step) & 1 and pixels[vx, cy + 1] in paper_tones:
                pixels[vx, cy + 1] = ink

    # Soft tonal wrinkles, fallback path only: over the plate's W+Y stipple a
    # solid cream ridge reads as a hard bright streak.
    if page_bg is not None and plate is None:
        for _ in range(5):
            wx = rng.randint(60, max(61, width - 60))
            wy = rng.randint(50, max(51, height - 50))
            angle = rng.uniform(0.0, math.pi)
            length = rng.randint(50, 130)
            dxu, dyu = math.cos(angle), math.sin(angle)
            nxp, nyp = -dyu, dxu  # unit perpendicular → highlight side
            for s in range(length):
                px = int(wx + (s - length // 2) * dxu)
                py = int(wy + (s - length // 2) * dyu)
                if 0 <= px < width and 0 <= py < height and pixels[px, py] in paper_tones:
                    pixels[px, py] = cream_light
                hx, hy = int(px + nxp), int(py + nyp)
                if 0 <= hx < width and 0 <= hy < height and pixels[hx, hy] in paper_tones:
                    pixels[hx, hy] = page_bg

    # ---- Wax seal (bottom-right) -------------------------------------
    # Scale the seal to the canvas so preview thumbnails get a proportional
    # seal.
    base_r = max(10, min(40, int(min(width, height) * 0.085)))
    scx = width - base_r - 32
    scy = height - base_r - 38
    if scx <= base_r or scy <= base_r:
        # Too small to seat a seal; the paper and creases carry the theme.
        return

    # Depth model: a glossy dome lit from the upper-left — coral highlight,
    # red body, R+K maroon core shadow — plus a cast shadow and a specular
    # hotspot.
    highlight_ink = SPECTRA6["white"]  # R+W coral at <100% density; pure gloss at 100%
    light_dx, light_dy = -0.7071, -0.7071  # light from the upper-left

    # (0) Clean cream bed behind the seal, so foxing doesn't show as noise
    # around the bead. Cream and plate are both W+Y, so only the foxing is
    # removed; the rim ring thins it out gradually so no edge shows.
    if page_bg is not None:
        knock_r = base_r * 1.7
        feather = knock_r * 0.78
        kx0 = max(0, int(scx - knock_r))
        kx1 = min(width - 1, int(scx + knock_r))
        ky0 = max(0, int(scy - knock_r))
        ky1 = min(height - 1, int(scy + knock_r))
        for py in range(ky0, ky1 + 1):
            for px in range(kx0, kx1 + 1):
                d = math.hypot(px - scx, py - scy)
                if d > knock_r:
                    continue
                if d > feather:
                    # Rim: thin the foxing out toward the edge.
                    if pixels[px, py] in (sepia_a, sepia_b):
                        keep = (knock_r - d) / (knock_r - feather)  # 1 at feather → 0 at rim
                        if ((px * 131 + py * 57) % 16) / 16.0 < keep:
                            pixels[px, py] = page_bg
                    continue
                # ~1/16 yellow, as in the writing-area knockout.
                pixels[px, py] = cream_light if BAYER_4x4[py & 3][px & 3] == 0 else page_bg

    # (1) Soft cast shadow, offset down-right and fading to its rim. Drawn
    # before the seal so only the lower-right crescent survives.
    # ``page_bg is None`` guards the sentinel-render test path.
    if page_bg is not None:
        shadow_dx = max(3, base_r // 9)
        shadow_dy = max(4, base_r // 7)
        shx, shy = scx + shadow_dx, scy + shadow_dy
        shadow_r = base_r * 1.06
        sx0 = max(0, int(shx - shadow_r))
        sy0 = max(0, int(shy - shadow_r))
        sx1 = min(width - 1, int(shx + shadow_r))
        sy1 = min(height - 1, int(shy + shadow_r))
        # Fall on all four paper inks, including the plate's R/G foxing, so
        # foxing specks don't poke through the shadow.
        paper_inks = (page_bg, cream_light, sepia_a, sepia_b)
        for py in range(sy0, sy1 + 1):
            for px in range(sx0, sx1 + 1):
                if pixels[px, py] not in paper_inks:
                    continue
                d = math.hypot(px - shx, py - shy)
                if d >= shadow_r:
                    continue
                density = 0.6 * (1.0 - d / shadow_r)
                if BAYER_4x4[py & 3][px & 3] < density * 16:
                    pixels[px, py] = maroon_dark

    # (2) Irregular pressed-wax rim: sum of two sinusoids around the circle.
    seal_pts = []
    steps = 72
    for i in range(steps):
        theta = (i / steps) * 2 * math.pi
        wobble = 1.0 + 0.05 * math.sin(theta * 5) + 0.035 * math.sin(theta * 8 + 1.3)
        r = base_r * wobble
        seal_pts.append((scx + r * math.cos(theta), scy + r * math.sin(theta)))
    draw.polygon(seal_pts, fill=wax_red)

    # Seal bbox for the per-pixel shading pass below.
    rim = base_r + 4
    bx0 = max(0, scx - rim)
    by0 = max(0, scy - rim)
    bx1 = min(width - 1, scx + rim)
    by1 = min(height - 1, scy + rim)

    # (3) Dome shading. ``t`` is the shadow amount (0 lit, 1 deepest): a
    # directional term plus rim darkening on the shadow side only, so the
    # lit shoulder stays bright to the edge. ``t`` is Bayer-dithered into a
    # ramp anchored on R+K maroon: white for coral gloss at the highlight,
    # black density climbing past 50% toward the rim. The base ink between
    # dithered pixels stays ``wax_red``.
    for py in range(by0, by1 + 1):
        for px in range(bx0, bx1 + 1):
            if pixels[px, py] != wax_red:
                continue
            nx = (px - scx) / base_r
            ny = (py - scy) / base_r
            directional = nx * light_dx + ny * light_dy  # +lit … -shadow
            r2 = nx * nx + ny * ny
            t = 0.5 - 0.5 * max(-1.0, min(1.0, directional / 1.05))
            if t > 0.5:  # shadow side: deepen toward the rim
                t += 0.20 * max(0.0, r2 - 0.45)
            else:        # lit side: only a whisper of edge falloff
                t += 0.06 * max(0.0, r2 - 0.55)
            t = max(0.0, min(1.0, t))
            cell = BAYER_4x4[py & 3][px & 3]
            if t < 0.25:
                # Lit shoulder: white dithered into red for a coral gloss,
                # brightest at the terminator-free highlight.
                density = (0.25 - t) / 0.25 * 0.5
                if cell < density * 16:
                    pixels[px, py] = highlight_ink
            else:
                # Body → core shadow: ~35% black below the highlight, ~50%
                # (true maroon) at mid-tone, up to ~90% at the rim.
                density = min(0.9, 0.35 + (t - 0.25) * 0.733)
                if cell < density * 16:
                    pixels[px, py] = maroon_dark

    # (4) Specular hotspot — solid white where the dome faces the light,
    # for the wet-wax sheen the coral dither alone can't give.
    spec_x = scx + int(-0.42 * base_r)
    spec_y = scy + int(-0.42 * base_r)
    spec_r = max(1, base_r // 14)
    draw.ellipse(
        (spec_x - spec_r, spec_y - spec_r, spec_x + spec_r, spec_y + spec_r),
        fill=highlight_ink,
    )

    # (5) Beaded rim: signet beading just inside the edge. Each bead is a
    # maroon dot with a 1 px coral highlight on its lit side, so the ring
    # catches the dome's light rather than reading as a flat dotted circle.
    bead_r = base_r * 0.82
    n_beads = 18
    for i in range(n_beads):
        theta = (i / n_beads) * 2 * math.pi
        bxp = scx + bead_r * math.cos(theta)
        byp = scy + bead_r * math.sin(theta)
        lit = (math.cos(theta) * light_dx + math.sin(theta) * light_dy) > 0
        draw.ellipse((bxp - 1, byp - 1, bxp + 1, byp + 1), fill=maroon_dark)
        if lit:
            hx, hy = int(bxp + light_dx), int(byp + light_dy)
            if bx0 <= hx <= bx1 and by0 <= hy <= by1:
                pixels[hx, hy] = highlight_ink

    # (6) Recessed hourglass emblem (the time motif). Each groove is a
    # maroon stroke over a coral highlight offset down-right onto the far
    # inner wall, so it reads as engraved into the wax.
    eh = base_r * 0.5   # half-height of the hourglass
    ew = base_r * 0.32  # half-width at the flared ends
    top_y = scy - eh
    bot_y = scy + eh
    upper = [(scx - ew, top_y), (scx + ew, top_y), (scx, scy)]
    lower = [(scx - ew, bot_y), (scx + ew, bot_y), (scx, scy)]
    cap_top = ((scx - ew - 1, top_y), (scx + ew + 1, top_y))
    cap_bot = ((scx - ew - 1, bot_y), (scx + ew + 1, bot_y))
    # Highlight pass first (offset +1,+1), then the maroon groove on top,
    # leaving a coral sliver on the lower-right of every stroke.
    for offset, colour in ((1, highlight_ink), (0, maroon_dark)):
        draw.line([(x + offset, y + offset) for x, y in upper] + [(upper[0][0] + offset, upper[0][1] + offset)], fill=colour, width=2)
        draw.line([(x + offset, y + offset) for x, y in lower] + [(lower[0][0] + offset, lower[0][1] + offset)], fill=colour, width=2)
        draw.line((cap_top[0][0] + offset, cap_top[0][1] + offset, cap_top[1][0] + offset, cap_top[1][1] + offset), fill=colour, width=2)
        draw.line((cap_bot[0][0] + offset, cap_bot[0][1] + offset, cap_bot[1][0] + offset, cap_bot[1][1] + offset), fill=colour, width=2)

    # (7) A couple of stray wax flecks beside the seal — drip character,
    # each with a 1 px maroon shadow so it sits on the page like the bead.
    for fx, fy, fr in (
        (scx - base_r - 6, scy + base_r - 4, 2),
        (scx + base_r - 2, scy - base_r + 8, 1),
    ):
        if 0 <= fx - fr and fx + fr < width and 0 <= fy - fr and fy + fr < height:
            sxp, syp = fx + 1, fy + 2
            if page_bg is not None and 0 <= sxp < width and 0 <= syp < height:
                if pixels[sxp, syp] in (page_bg, cream_light, sepia_a, sepia_b):
                    pixels[sxp, syp] = maroon_dark
            draw.ellipse((fx - fr, fy - fr, fx + fr, fy + fr), fill=wax_red)
            # Tone the fleck toward oxblood so it matches the shaded seal.
            for py in range(max(0, fy - fr), min(height - 1, fy + fr) + 1):
                for px in range(max(0, fx - fr), min(width - 1, fx + fr) + 1):
                    if pixels[px, py] == wax_red and (px + py) & 1:
                        pixels[px, py] = maroon_dark

# The letter plate dithers to white/yellow/red/green (W+Y cream, R+G foxing).
# Black is excluded so error diffusion can't fleck clean paper (the creases
# and seal supply their own), and blue so foxing can't drift cool.
LETTER_PLATE = BASE_DIR / "assets" / "letter_aged_paper.png"
_AGED_PAPER_PALETTE = [SPECTRA6["white"], SPECTRA6["yellow"], SPECTRA6["red"], SPECTRA6["green"]]


SPEC = BorderSpec(
    themes=("letter",),
    paint=draw_letter_border,
    # The painter pastes the dithered aged-paper plate, knocks the writing
    # area back to clean cream (no foxing) so the thin Dancing Script body
    # doesn't blur against the plate's speckle, then paints creases and the
    # wax seal on top. The generous pad leaves clean margin round the text
    # even after the 16 px feathered edge, with no drawn frame.
    clear_rect_pad=(26, 18, 18),
)
