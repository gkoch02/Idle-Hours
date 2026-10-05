"""Painting primitives shared by the themes: blooms, relief, hatching, height fields, flow strokes,
noise fields, stipples and silhouettes.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .fonts import _font_ascent, normalize_dashes
from .layout import fit_quote, strip_underscore_emphasis
from .palette import SPECTRA6, BAYER_4x4, BAYER_8x8, gray_pixel_access, pixel_access


def paint_neon_mask(
    image: Image.Image,
    mask: Image.Image,
    core,
    glow,
    *,
    radius: int = 5,
    gamma: float = 2.4,
    cap: float = 0.5,
    ground=None,
    tile=BAYER_4x4,
    glow_minor=None,
    glow_minor_share: float = 0.0,
    core_minor=None,
    core_minor_share: float = 0.0,
) -> None:
    """Paint a glyph/shape mask as a lit neon tube: solid ``core`` strokes
    wrapped in a ``glow`` bloom stippled onto the surrounding ground.

    Other synthesised tones mix two inks at a **constant** density; a bloom
    is one ink at a *falling* density. The halo is the mask blurred
    (``ImageFilter.GaussianBlur``) and read back as a per-pixel Bayer
    **density**, so the eye integrates a gradient out of a binary field.

    Tuning:

    * ``radius`` must stay TIGHT — comparable to the stroke width. A wide blur
      of a dense text line is a solid rectangle and reads as a coloured box.
    * ``gamma`` > 1 pulls the mid-tones down so the bloom decays over ~6-10 px
      instead of plateauing and cutting off at a visible edge.
    * ``cap`` keeps the densest ring below solid, so the halo always shows
      stipple texture; a saturated ring reads as a painted outline.

    ``mask`` must be an ``"L"`` image the same size as ``image`` (shared
    coordinates). Work is confined to the mask bbox grown by the blur pad.
    ``core=None`` paints only the halo.

    ``ground`` optionally restricts the halo to pixels currently holding one
    of those colours, so a later glow can't eat earlier cores or decoration.

    **Synthesised glows.** When the panel lacks the glow colour (``bakelite``'s
    amber), ``glow_minor`` / ``glow_minor_share`` mix a second ink at a
    constant ratio: the lit pixels are tile ranks ``0..n-1`` and the lowest
    ``glow_minor_share`` of that run take the minor ink, so density carries
    the glow and the ratio the hue, steady down the whole falloff.
    ``core_minor`` does the same for the stroke. The ratio must ride the
    density's own read — a second read of the same Bayer tile is perfectly
    correlated with the first, and keying the ratio on it makes the halo
    change hue as it fades (``pride`` uses the same rank partition).

    ``tile`` selects the ordered matrix: 4x4 suits a solid glow; a *split*
    glow wants ``BAYER_8x8``, because a short lit run can't hold a fraction
    accurately.
    """
    bbox = mask.getbbox()
    if bbox is None:
        return
    width, height = image.size
    pad = max(2, int(radius * 3))
    x0 = max(0, bbox[0] - pad)
    y0 = max(0, bbox[1] - pad)
    x1 = min(width, bbox[2] + pad)
    y1 = min(height, bbox[3] + pad)
    if x1 <= x0 or y1 <= y0:
        return
    halo = mask.filter(ImageFilter.GaussianBlur(radius))
    px = pixel_access(image)
    mp = gray_pixel_access(mask)
    hp = gray_pixel_access(halo)
    size = len(tile)
    levels = size * size
    core_cut = levels * core_minor_share
    for y in range(y0, y1):
        row = tile[y % size]
        for x in range(x0, x1):
            rank = row[x % size]
            if mp[x, y] > 128:
                if core is not None:
                    px[x, y] = core_minor if core_minor is not None and rank < core_cut else core
                continue
            level = hp[x, y] / 255.0
            if level <= 0.02:
                continue
            lit = min(cap, level ** gamma) * levels
            if rank < lit and (ground is None or px[x, y] in ground):
                px[x, y] = glow_minor if glow_minor is not None and rank < lit * glow_minor_share else glow


def wrap_quote_into_masks(draw, size, quote_row: dict, rect, *, theme: str,
                         font_max: int = 34, font_min: int = 15,
                         line_height_mult: float = 1.4,
                         align: str = "center") -> tuple[Image.Image, Image.Image, int]:
    """Lay a quote out into two ``"L"`` masks — prose and matched phrase — and
    return them with the block's bottom y.

    The shared front half of every *lit* frame (``izakaya``, ``abyssal``,
    ``bakelite``): a bloom needs its mask before anything is painted, and the
    prose and the time phrase need separate masks so each takes its own
    colour and falloff. One shared mask gives the phrase the prose's glow;
    blooming per *chunk* double-exposes where two halos meet in a line. The
    caller makes its own ``paint_neon_mask`` calls.

    Lines are centred with leading/trailing whitespace chunks trimmed, and
    chunks are baseline-aligned via ``_font_ascent`` so the bold phrase sits
    on the prose's line even when the faces' ascents differ.

    ``align="left"`` flushes lines to the rect's left edge (``observation``'s
    ragged-right transcript).
    """
    x0, y0, x1, y1 = rect
    box_w, box_h = x1 - x0, y1 - y0
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    quote_font, quote_font_bold, wrapped, line_height, _ = fit_quote(
        draw, display_quote, quote_row.get("matched_text") or "", box_w, box_h,
        font_max=font_max, font_min=font_min, line_height_mult=line_height_mult, theme=theme,
    )
    prose = Image.new("L", size, 0)
    hot = Image.new("L", size, 0)
    prose_draw, hot_draw = ImageDraw.Draw(prose), ImageDraw.Draw(hot)

    y = y0 + max(0, (box_h - len(wrapped) * line_height) // 2)
    body_ascent = _font_ascent(quote_font)
    for line in wrapped:
        start, end = 0, len(line)
        while start < end and line[start][0].strip() == "":
            start += 1
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        segment = line[start:end]
        width_px = sum(draw.textbbox((0, 0), c, font=quote_font_bold if b else quote_font)[2]
                       for c, b in segment)
        x = x0 if align == "left" else x0 + max(0, (box_w - width_px) // 2)
        for chunk, is_bold in segment:
            font = quote_font_bold if is_bold else quote_font
            target = hot_draw if is_bold else prose_draw
            target.text((x, y + (body_ascent - _font_ascent(font))), chunk, font=font, fill=255)
            x += draw.textbbox((0, 0), chunk, font=font)[2]
        y += line_height
    return prose, hot, y


def paint_hatched_tone(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    tone,
    angle_deg: float,
    spacing: float,
    ink,
    *,
    ground=None,
    phase: float = 0.0,
    max_duty: float = 0.85,
    gamma: float = 1.0,
) -> None:
    """Paint continuous tone as line-work — the engraver's alternative to the
    pixel stipple.

    Modulates the **weight** of a parallel line family under a tone field, at
    constant pitch, so the grey reads as *drawing* — intaglio's tone
    mechanism. Keep the pitch constant: tone-varying spacing reads as
    scanlines with noise.

    ``tone`` is a callable ``(x, y) -> float`` in 0..1 in panel coordinates.
    Per pixel, ``u = -x*sin(a) + y*cos(a) + phase``; the pixel takes ``ink``
    when its distance to the nearest line centre is under half the pitch
    times the duty ``min(max_duty, tone**gamma)``. Continuous coordinates
    give any angle even weight.

    Cross-hatching is a second call at a second angle with a shadows-only
    tone (``max(0, t - 0.5) * 2``), as an engraver adds the second family.

    ``max_duty`` is the analogue of ``paint_neon_mask``'s ``cap``: even tone
    1.0 shows paper between the lines, or the hatch collapses to a flat fill.
    ``ground`` restricts painting to pixels holding one of those colours.

    Keep ``spacing >= 4`` and the angle off 0/45/90 degrees, or the family
    beats against the pixel lattice into thick-thin banding.
    """
    a = math.radians(angle_deg)
    sin_a, cos_a = math.sin(a), math.cos(a)
    x0, y0, x1, y1 = rect
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(image.size[0], x1), min(image.size[1], y1)
    px = pixel_access(image)
    half = 0.5 * spacing
    for y in range(y0, y1):
        for x in range(x0, x1):
            t = tone(x, y)
            if t <= 0.0:
                continue
            duty = min(max_duty, t ** gamma if gamma != 1.0 else t)
            u = -x * sin_a + y * cos_a + phase
            delta = abs(u - round(u / spacing) * spacing)
            if delta < half * duty and (ground is None or px[x, y] in ground):
                px[x, y] = ink


def paint_relief_mask(
    image: Image.Image,
    mask: Image.Image,
    *,
    highlight,
    shadow,
    face=None,
    face_minor=None,
    face_minor_share: float = 0.0,
    radius: int = 3,
    strength: float = 4.0,
    cap: float = 0.65,
    ground=None,
    tile=BAYER_8x8,
    shade_face: bool = True,
    contact=None,
    contact_cut: int = 55,
) -> None:
    """Paint a glyph/shape mask as a *raised* (or sunken) surface lit from the
    upper left — the inverse of ``paint_neon_mask``: light falling ON the mask
    instead of radiating from it.

    ``shade_face=True`` (default) lights the mask's own surface — right for
    *large* shapes (a bead, a bolt head). ``False`` confines the lighting to
    the *exterior* — solid face, rim light outside the upper-left edge, core
    shadow outside the lower-right — which thin letterforms need: shading a
    2-3 px stroke's own face leaves no face, and the glyph decays to a grey
    ghost.

    The blurred mask is read as a height field; its gradient against the
    upper-left house light (as ``vitrail`` / ``kanagawa`` use) decides which
    side of each edge is lit: faces toward the light take ``highlight`` at a
    density proportional to slope, faces away take ``shadow``. ``radius`` is
    the die's fillet, ``strength`` the relief depth, and ``cap`` keeps even
    the steepest face stippled (a saturated face reads as an outline).

    ``face`` optionally fills the interior first, with ``face_minor`` /
    ``face_minor_share`` mixing a second ink on the tile's own rank read (the
    ``paint_neon_mask`` split-band rule). ``face=None`` for shapes an earlier
    pass already filled.

    ``contact`` optionally lays a solid ring of that ink in the exterior band
    where the halo is at least ``contact_cut``, *under* the directional pass —
    the ambient-occlusion crease round a raised form. Lambert alone gives
    near-zero shading on the edges lying along the light direction, and on a
    mottled ground the letterform bleeds into the plate there. The highlight
    paints over the ring afterwards. Raising ``contact_cut`` narrows it;
    ``contact=None`` (default) disables it.

    **Set ``contact_cut`` from the halo profile of a *stroke*, not of a large
    shape.** One pixel outside a 3 px stem a radius-2 halo is ~93 and two
    pixels out ~57, versus ~150 just outside a broad edge; a cut tuned on a
    broad edge (96) creases a glyph nowhere, silently. The default suits a
    radius-2 blur on body text.

    Swap ``highlight`` and ``shadow`` for deboss. ``ground`` restricts
    *exterior* writes (contact ring included) so relief never eats
    neighbouring decoration; interior pixels belong to the mask.
    """
    bbox = mask.getbbox()
    if bbox is None:
        return
    width, height = image.size
    pad = max(2, radius * 3)
    x0 = max(1, bbox[0] - pad)
    y0 = max(1, bbox[1] - pad)
    x1 = min(width - 1, bbox[2] + pad)
    y1 = min(height - 1, bbox[3] + pad)
    if x1 <= x0 or y1 <= y0:
        return
    halo = mask.filter(ImageFilter.GaussianBlur(radius))
    px = pixel_access(image)
    mp = gray_pixel_access(mask)
    hp = gray_pixel_access(halo)
    size = len(tile)
    levels = size * size
    face_cut = levels * face_minor_share
    inv = 1.0 / 510.0  # central difference over 2 px of an 8-bit field
    for y in range(y0, y1):
        row = tile[y % size]
        for x in range(x0, x1):
            rank = row[x % size]
            inside = mp[x, y] > 128
            if inside and face is not None:
                px[x, y] = face_minor if face_minor is not None and rank < face_cut else face
            if inside and not shade_face:
                continue
            exterior_ok = inside or ground is None or px[x, y] in ground
            if contact is not None and not inside and exterior_ok and hp[x, y] >= contact_cut:
                px[x, y] = contact
            gx = (hp[x + 1, y] - hp[x - 1, y]) * inv
            gy = (hp[x, y + 1] - hp[x, y - 1]) * inv
            shade = (gx + gy) * 0.7071  # Lambert term against upper-left light
            lit = min(cap, abs(shade) * strength) * levels
            if rank >= lit:
                continue
            if not exterior_ok:
                continue
            px[x, y] = highlight if shade > 0 else shadow


# Sobel slopes for ``shade_height_field``, read as +d/dx and +d/dy. The Y
# weights look upside down and the X weights do not, because
# ``ImageFilter.Kernel`` applies its rows in reverse order but its columns as
# written — fenced by ``TestShadeHeightField``, since a flipped sign silently
# moves the light to the wrong corner. ``scale=2`` reports a unit ramp as 4
# grey levels: quarter-level slope resolution keeps a soft dome from
# terracing, at the cost of clipping slopes steeper than 32 levels per pixel.
_SOBEL_X = ImageFilter.Kernel((3, 3), (-1, 0, 1, -2, 0, 2, -1, 0, 1), scale=2, offset=128)
_SOBEL_Y = ImageFilter.Kernel((3, 3), (1, 2, 1, 0, 0, 0, -1, -2, -1), scale=2, offset=128)
_HEIGHT_FIELD_LUTS: dict = {}


def _height_field_lut(light, relief: float, ambient: float, diffuse: float,
                      specular: float, shininess: float) -> bytes:
    """A 65536-entry ``(gx << 8 | gy) → tone`` table: Blinn-Phong for every
    slope pair the two Sobel images can report. Memoised per parameter set so
    the per-pixel pass is a plain table lookup."""
    key = (tuple(light), relief, ambient, diffuse, specular, shininess)
    cached = _HEIGHT_FIELD_LUTS.get(key)
    if cached is not None:
        return cached
    lx, ly, lz = light
    norm = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / norm, ly / norm, lz / norm
    hx, hy, hz = lx, ly, lz + 1.0                       # Blinn half-vector, viewer on +z
    hn = math.sqrt(hx * hx + hy * hy + hz * hz)
    hx, hy, hz = hx / hn, hy / hn, hz / hn
    out = bytearray(65536)
    for a in range(256):
        nx = -(a - 128) * relief
        for b in range(256):
            ny = -(b - 128) * relief
            inv = 1.0 / math.sqrt(nx * nx + ny * ny + 1.0)
            ndl = (nx * lx + ny * ly + lz) * inv
            ndh = (nx * hx + ny * hy + hz) * inv
            tone = ambient + diffuse * max(0.0, ndl)
            if ndh > 0.0:
                tone += specular * ndh ** shininess
            out[a << 8 | b] = max(0, min(255, int(tone * 255 + 0.5)))
    table = bytes(out)
    _HEIGHT_FIELD_LUTS[key] = table
    return table


def shade_height_field(
    height: Image.Image,
    *,
    light=(-0.55, -0.62, 0.56),
    relief: float = 0.025,
    ambient: float = 0.1,
    diffuse: float = 0.85,
    specular: float = 0.7,
    shininess: float = 28.0,
) -> Image.Image:
    """Render an ``"L"`` height field as a lit continuous-tone surface.

    A *3-D render* rather than a stipple rule (the eighth tone axis in
    ``docs/spectra6_color_recipes.md``): every pixel gets a normal, is shaded
    Blinn-Phong under one light, and the result stays continuous tone for
    error diffusion to carry onto the inks — an airbrush, which is what
    ``biomech``'s smooth gradients and specular glints need.

    Unlike ``paint_relief_mask`` (lights a flat mask's blurred edge and
    writes ink per pixel in Python), this takes a caller-built height field
    (blurred shapes unioned with ``ImageChops.lighter``, carved with
    ``subtract``) and returns *tone*, leaving inks to
    ``dither_image_to_palette``. The per-pixel work is C-speed: two 3x3 Sobel
    ``ImageFilter.Kernel`` passes (``offset=128`` keeps the sign) and one
    lookup into a memoised 65536-entry table.

    ``light`` is screen-space (x right, y down, z toward the viewer), upper
    left by convention. ``relief`` converts height per pixel into normal tilt,
    per Sobel level (four per unit slope); a field blurred at radius *r* peaks
    near ``255/(2r)``, so the default turns a radius-5 dome through most of a
    hemisphere. A flat pixel shades to ``ambient + diffuse * lz`` — mid-grey,
    not black; darkening recesses (multiply by the height) is the caller's
    choice.
    """
    gx = height.filter(_SOBEL_X).tobytes()
    gy = height.filter(_SOBEL_Y).tobytes()
    lut = _height_field_lut(tuple(light), relief, ambient, diffuse, specular, shininess)
    tone = bytes(lut[a << 8 | b] for a, b in zip(gx, gy))
    return Image.frombytes("L", height.size, tone)


def _flow_stroke_hash(cx: int, cy: int, salt: int) -> float:
    """Deterministic 0..1 value per stroke cell — ``_bakelite_grain``'s hash
    with a ``salt`` term so multiple passes over one canvas decorrelate."""
    h = (cx * 0x1F1F1F1F) ^ (cy * 0x2545F491) ^ (salt * 0x9E3779B9)
    h = ((h ^ (h >> 13)) * 0x27D4EB2D) & 0xFFFFFFFF
    return ((h ^ (h >> 15)) & 0xFFFF) / 65535.0


def paint_flow_strokes(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    direction,
    ink_at,
    *,
    cell: int = 11,
    length: int = 18,
    width: int = 2,
    steps: int = 3,
    ground=None,
    salt: int = 0,
) -> None:
    """The painterly pass: short streamline strokes advected through a
    caller-supplied direction field, each stroke a single ink chosen at its
    origin.

    Fakes *facture* at stroke scale where the stipples fake tone at pixel
    scale: partial coverage of blue strokes over black reads as brushed night
    water because the marks are long (15-25 px) and coherent enough to read
    direction at panel distance. That needs field wavelengths well above the
    placement pitch (>= 80 px against a 10-13 px ``cell`` in ``nocturne``);
    a faster-turning field shreds the strokes back into noise.

    One candidate per ``cell x cell`` square inside ``rect``; the origin is
    jittered by an integer position hash (never ``random`` — frames must
    re-render byte-identically), and the same hash is passed to
    ``ink_at(x, y, r)`` as ``r``. ``ink_at`` returning ``None`` skips the
    stroke — that is how the caller carries density and tone. Each stroke is
    integrated along the field in ``steps`` segments of ``length/steps``, so
    it bends with the field.

    Strokes render through a scratch mask and land only on ``ground`` pixels
    (the ``paint_neon_mask`` discipline), so a pass never eats earlier cores
    or text. ``salt`` decorrelates multiple passes on one canvas.
    """
    x0, y0, x1, y1 = rect
    scratch = Image.new("L", image.size, 0)
    scratch_draw = ImageDraw.Draw(scratch)
    sp = pixel_access(scratch)
    px = pixel_access(image)
    w, h = image.size
    seg = max(1.0, length / steps)
    for cy in range(y0, y1, cell):
        for cx in range(x0, x1, cell):
            r = _flow_stroke_hash(cx, cy, salt)
            jx = _flow_stroke_hash(cx, cy, salt ^ 0x5BD1E995)
            jy = _flow_stroke_hash(cx, cy, salt ^ 0x85EBCA6B)
            ox = cx + jx * cell
            oy = cy + jy * cell
            ink = ink_at(int(ox), int(oy), r)
            if ink is None:
                continue
            points = [(ox, oy)]
            sx, sy = ox, oy
            reach = seg * (0.6 + 0.4 * r)
            for _ in range(steps):
                ang = direction(sx, sy)
                sx += math.cos(ang) * reach
                sy += math.sin(ang) * reach
                points.append((sx, sy))
            scratch_draw.line(points, fill=255, width=width)
            bx0 = max(0, int(min(p[0] for p in points)) - width)
            by0 = max(0, int(min(p[1] for p in points)) - width)
            bx1 = min(w - 1, int(max(p[0] for p in points)) + width)
            by1 = min(h - 1, int(max(p[1] for p in points)) + width)
            for yy in range(by0, by1 + 1):
                for xx in range(bx0, bx1 + 1):
                    if sp[xx, yy] == 0:
                        continue
                    if ground is None or px[xx, yy] in ground:
                        px[xx, yy] = ink
                    sp[xx, yy] = 0


def position_noise(x: int, y: int) -> int:
    """A 0..255 positional hash — white noise, deterministic per pixel.

    A sparse wash thresholds this rather than a Bayer rank: at 3-9% density an
    ordered tile lays a visible dot lattice, where a hash scatter reads as
    paper fibre. (``bakelite``'s "hash reads as sandpaper" warning is about
    mid-density fields.) For a whole-canvas field use :func:`_white_noise`,
    the C-speed equivalent.
    """
    h = (x * 374761393 + y * 668265263) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return (h ^ (h >> 16)) & 0xFF


def _fill_swatch_stipple(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    dark: tuple[int, int, int],
    light: tuple[int, int, int],
    light_density: float,
) -> None:
    """Paint a rectangle with the Bayer stipple ``draw_text_dithered``
    applies to glyph masks; the three density branches mirror that function
    so the swatch shows the recipe a theme would actually paint.
    """
    x0, y0, x1, y1 = rect
    # Clip to image bounds: ``PixelAccess`` raises on out-of-range writes,
    # and a rect may sit partly or fully off-canvas (the diags swatch band in
    # a web-preview thumbnail).
    w, h = image.size
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(w, x1)
    y1 = min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return
    px = pixel_access(image)
    if light_density <= 0.25:
        for y in range(y0, y1):
            for x in range(x0, x1):
                px[x, y] = light if (x % 2 == 0 and y % 2 == 0) else dark
    elif light_density >= 0.5:
        for y in range(y0, y1):
            for x in range(x0, x1):
                px[x, y] = dark if (x + y) % 2 == 0 else light
    else:
        threshold = round(light_density * 16)
        for y in range(y0, y1):
            for x in range(x0, x1):
                px[x, y] = light if BAYER_4x4[y % 4][x % 4] < threshold else dark


def _fill_swatch_stipple_3way(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    ink_a: tuple[int, int, int],
    ink_b: tuple[int, int, int],
    ink_c: tuple[int, int, int],
    density_a: float,
    density_b: float,
) -> None:
    """Paint a rectangular region with a 3-ink Bayer stipple.

    Partitions the 4×4 Bayer tile by two thresholds: cells below
    ``round(density_a * 16)`` get ``ink_a``, below
    ``round((density_a + density_b) * 16)`` get ``ink_b``, the rest ``ink_c``.
    See the "Three-ink recipes" section of ``spectra6_color_recipes.md``.
    Clips to image bounds like ``_fill_swatch_stipple``.
    """
    x0, y0, x1, y1 = rect
    w, h = image.size
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(w, x1)
    y1 = min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return
    threshold_a = round(density_a * 16)
    threshold_b = round((density_a + density_b) * 16)
    px = pixel_access(image)
    for y in range(y0, y1):
        for x in range(x0, x1):
            cell = BAYER_4x4[y % 4][x % 4]
            if cell < threshold_a:
                px[x, y] = ink_a
            elif cell < threshold_b:
                px[x, y] = ink_b
            else:
                px[x, y] = ink_c


def _white_noise(width: int, height: int, seed: int) -> Image.Image:
    """A deterministic ``L`` field of uniform noise, one byte per pixel.

    For an *aperiodic* scatter: a small Bayer gate paints diagonal
    pinstripes that read as corduroy on the panel inks (invisible in an RGB
    preview). :func:`position_noise` has the right character but is a
    Python call per pixel, far too slow for a whole canvas. ``Random.randbytes``
    is the same white noise from a seeded C generator, so the frame stays
    byte-identical across processes (``hash()`` would not: it is
    PYTHONHASHSEED-salted), and compositing uses C-speed ``point`` LUTs and
    ``paste`` masks.
    """
    return Image.frombytes("L", (width, height), random.Random(seed).randbytes(width * height))


def _smooth_noise(size, cells, seed: int) -> Image.Image:
    """Seeded value noise: a coarse grid of white noise, bicubic-upsampled.
    ``cells`` is the grid's (columns, rows), so an unequal pair stretches the
    noise into streaks."""
    return _white_noise(cells[0], cells[1], seed).resize(size, Image.Resampling.BICUBIC)


def _bayer_threshold_field(size) -> Image.Image:
    """``BAYER_8x8`` tiled across ``size`` as an ``"L"`` image of rank
    thresholds (``rank * 4 + 2``), so a density map can be stippled with one
    C-speed compare: ``ImageChops.subtract(density, field)`` is non-zero
    exactly where the density beats the cell's rank."""
    width, height = size
    rows = [bytes(BAYER_8x8[r][x % 8] * 4 + 2 for x in range(width)) for r in range(8)]
    return Image.frombytes("L", size, b"".join(rows[y % 8] for y in range(height)))


def _lerp_stops(stops, y: float):
    """The colour at ``y`` on a ``[(y, rgb), ...]`` gradient sorted on ``y``,
    linearly interpolated; before the first stop it holds the first colour,
    past the last it holds the last."""
    for (y0, c0), (y1, c1) in zip(stops, stops[1:]):
        if y <= y1:
            t = 0.0 if y1 == y0 else max(0.0, (y - y0) / (y1 - y0))
            return tuple(round(a + (b - a) * t) for a, b in zip(c0, c1))
    return stops[-1][1]


def _halo_paste(image: Image.Image, mask: Image.Image, fill, halo: int = 5) -> None:
    """Paste ``fill`` through ``mask`` over a black halo grown from it, so
    text floats on a busy scene without a panel hiding it. ``fill=None``
    lays the halo alone (for a mask whose ink is painted separately)."""
    hard = mask.point(lambda v: 255 if v > 110 else 0)
    image.paste(SPECTRA6["black"], (0, 0), hard.filter(ImageFilter.MaxFilter(halo)))
    if fill is not None:
        image.paste(fill, (0, 0), hard)


def _soft_ellipse_mask(size, box, blur: int) -> Image.Image:
    """An ``L`` mask of the ellipse ``box``, Gaussian-feathered by ``blur``:
    a pool of light or shadow to composite through."""
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse(box, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(blur))


def _shift_no_wrap(img: Image.Image, dx: int, dy: int) -> Image.Image:
    """Translate without wrap-around (``ImageChops.offset`` wraps)."""
    out = Image.new(img.mode, img.size, 0)
    out.paste(img, (dx, dy))
    return out


def _shade_silhouette(mask: Image.Image, base, light, dark, *, offset: int = 10, blur: int = 7) -> Image.Image:
    """Model a silhouette under an upper-left light.

    Where the shape meets its own down-right shift it has an exposed upper-left
    edge — the lit rim; where it meets its up-left shift, the lower-right core
    shadow. Both are blurred so the modelling rolls round the form."""
    m = mask.filter(ImageFilter.GaussianBlur(1))
    lit = ImageChops.subtract(m, _shift_no_wrap(m, offset, offset)).filter(ImageFilter.GaussianBlur(blur))
    shadow = ImageChops.subtract(m, _shift_no_wrap(m, -offset, -offset)).filter(ImageFilter.GaussianBlur(blur))
    img = Image.new("RGB", mask.size, base)
    img = Image.composite(Image.new("RGB", mask.size, light), img, lit)
    return Image.composite(Image.new("RGB", mask.size, dark), img, shadow)


def _catmull_rom(points, closed: bool = True, samples: int = 10) -> list:
    """Catmull-Rom through ``points`` — organic silhouettes rather than the
    hard polygon corners a figure made of ``ImageDraw`` primitives gets."""
    pts = list(points)
    n = len(pts)
    out = []
    for i in (range(n) if closed else range(n - 1)):
        p0 = pts[(i - 1) % n] if closed else pts[max(i - 1, 0)]
        p1, p2 = pts[i], pts[(i + 1) % n]
        p3 = pts[(i + 2) % n] if closed else pts[min(i + 2, n - 1)]
        for k in range(samples):
            t = k / samples
            t2, t3 = t * t, t * t * t
            out.append(tuple(
                0.5 * (2 * p1[j] + (p2[j] - p0[j]) * t
                       + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                       + (3 * p1[j] - p0[j] - 3 * p2[j] + p3[j]) * t3)
                for j in (0, 1)
            ))
    if not closed:
        out.append(tuple(pts[-1]))
    return out


# ---- craquelure --------------------------------------------------------------

def paint_craquelure(
    image: Image.Image,
    region: Image.Image,
    *,
    seed: int,
    cell=(21, 13),
    jitter: float = 0.36,
    drop: float = 0.2,
    diagonal: float = 0.14,
    continuity: int = 5,
    dark=None,
    light=None,
    light_share: float = 0.15,
    keep_out: Image.Image | None = None,
    keep_out_pad: int = 2,
) -> Image.Image:
    """Craze a painted surface with an aged-varnish crack network.

    The net is a *graph* (connected by construction, unlike a thresholded noise
    field): a lattice of ``cell``-spaced vertices, each nudged by up to
    ``jitter`` of a cell, whose right and down edges are polylines bowed at the
    midpoint. ``drop`` of the edges are left out so islands merge into larger
    blocks; ``diagonal`` of the cells gain a corner-to-corner split so the net
    does not read as a grid.

    Along the net, ``continuity`` of every 8 pixels are painted (positional
    hash), so fissures read as fine and broken. A crack pixel takes ``dark`` on
    light paint and ``light`` where the paint is already ``dark``, but only
    ``light_share`` of those open, since full strength would read as a white
    net laid over the black.

    ``region`` (``"L"``) confines the net to the painted surface; ``keep_out``
    (``"L"``) is dilated by ``keep_out_pad`` and never cracked. Returns the
    crack mask. Deterministic for a given ``seed``.
    """
    dark = SPECTRA6["black"] if dark is None else dark
    light = SPECTRA6["white"] if light is None else light
    width, height = image.size
    rng = random.Random(seed)
    cw, ch = cell
    cols, rows = width // cw + 2, height // ch + 2
    verts = {}
    for j in range(rows):
        for i in range(cols):
            verts[i, j] = (i * cw + rng.uniform(-jitter, jitter) * cw,
                           j * ch + rng.uniform(-jitter, jitter) * ch)
    net = Image.new("L", image.size, 0)
    nd = ImageDraw.Draw(net)

    def crack(p, q, bow: float) -> None:
        mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
        dx, dy = q[0] - p[0], q[1] - p[1]
        mx, my = mx - dy * bow, my + dx * bow
        nd.line([(round(p[0]), round(p[1])), (round(mx), round(my)), (round(q[0]), round(q[1]))],
                fill=255, width=1)

    for j in range(rows):
        for i in range(cols):
            p = verts[i, j]
            # Draw every random number whether or not the edge is kept, so one
            # edge's fate never shifts the stream for the rest of the net.
            for di, dj in ((1, 0), (0, 1)):
                keep, bow = rng.random() >= drop, rng.uniform(-0.16, 0.16)
                q = verts.get((i + di, j + dj))
                if keep and q is not None:
                    crack(p, q, bow)
            split, flip, bow = rng.random() < diagonal, rng.random() < 0.5, rng.uniform(-0.1, 0.1)
            if split and (i + 1, j + 1) in verts:
                a, b = ((i, j), (i + 1, j + 1)) if flip else ((i + 1, j), (i, j + 1))
                crack(verts[a], verts[b], bow)

    guard = None
    if keep_out is not None:
        guard = pixel_access(keep_out.filter(ImageFilter.MaxFilter(2 * keep_out_pad + 1)))
    painted = Image.new("L", image.size, 0)
    px, rp, np_, pp = pixel_access(image), pixel_access(region), pixel_access(net), pixel_access(painted)
    bbox = net.getbbox()
    if bbox is None:
        return painted
    for y in range(bbox[1], bbox[3]):
        for x in range(bbox[0], bbox[2]):
            if not np_[x, y] or not rp[x, y] or (guard is not None and guard[x, y]):
                continue
            h = position_noise(x, y)
            if h % 8 >= continuity:
                continue
            if px[x, y] == dark:
                if (h >> 3) % 64 < light_share * 64:
                    px[x, y] = light
                    pp[x, y] = 255
            else:
                px[x, y] = dark
                pp[x, y] = 255
    net.close()
    return painted
