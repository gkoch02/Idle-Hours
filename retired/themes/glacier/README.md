# `glacier` (retired)

Retired from the rotation, the renderer and the live docs. Everything the theme was is kept in this folder so it can be restored as it was; see [`../../README.md`](../../README.md) for how.

## README row

| `glacier`     | <img src="idle_hours/assets/previews/glacier.png" width="240" alt="glacier theme preview">         | white       | blue  | green  | Iceland (techno display) | Icy / aurora panel        |

## Design notes (from `docs/themes.md`)

  - `glacier` (white/blue/green, Iceland geometric techno display face — Cyreal, OFL) — the first theme to pair a blue body with a green accent; the cool gradient reads as blue body → teal matched phrase → sky-blue ornament highlights on the frost-crystal border.

    **Accent.** The matched-phrase green is rerouted in `_draw_text_body` to a 5/8:3/8 G+B teal stipple — green-biased via Bayer threshold 6/16, the same luminance-bias pattern `nightvision`'s lime and `deco`'s tangerine use to lift a matched phrase off a same-axis body colour.

    **Frost-edge wash.** Inside a thin blue outer rule at inset 14, `draw_glacier_border` gathers a sparse sky-blue frost in the ≤44 px clear margins above and below the type area, painted as a gradient Bayer threshold (peak ~5/16 at the frame edge fading linearly to bare at the inner lip) that only flips *white* ground pixels to blue. The ground reads as ice creeping across a windowpane while the blue body text (which never starts before y=72) stays fully legible. It is skipped on non-white grounds so the unit-test sentinel render is unaffected.

    **Corner sprays.** Each of the four frost-crystal sprays fans a blue horizontal + vertical splinter, two intermediate blue splinters filling the 45° fan, and the longest green-tipped diagonal splinter with two tiny dendrite barbs feathering off it the way real hoar-frost grows side-arms, anchored by a small blue hub dot. The diagonal splinter's (and its barbs') green pixels are post-pass-flipped to white on a 50/50 `(x+y)&1` checkerboard inside each cluster's bbox (the documented sky-blue two-ink recipe), so green+white averages at panel distance into a sunlight-on-ice highlight against the deep-ice body-blue shards.

    **Snowflake ticks.** Four mid-edge **six-armed snowflake ticks** — three crossing spokes at 0°/60°/120° with a small forked barb at each of the six tips plus a filled blue hub diamond — reinforce the architectural symmetry without crowding the quote.

    **Debug band.** The TR cluster overlaps the default debug-banner band, so `glacier` carries an entry of 34 in `_DEBUG_LABEL_RIGHT_INSET`, mirroring `blueprint`'s rationale.

    **Tried and rejected.**
    - **Solid Spectra-6 green** for the phrase: read as a muddy mid-tone. The 3/8 blue stipple keeps the recipe out of that failure mode.
    - **50/50 G+B cyan:** against the solid-blue body it averaged too close to blue at panel viewing distance and read as a near-sibling tone, so the recipe was biased toward green to widen the hue stride.

## Font notes (from `docs/themes.md`)

  - `glacier` uses **Iceland** (Cyreal, OFL) — geometric techno / retro-futurism display face, same single-weight discipline as Righteous / Bangers / Atomic Age.

## Registration

- `THEME_ORDER`: sat after `deco`.
- `display_inky.THEME_SATURATION`: `"glacier": 0.5,`
- Had _BOLD_STROKE_BY_THEME["glacier"] = 1 (Iceland ships Regular only; the phrase took a faux-bold stroke).

### `THEMES` entry (`render_quote/theme_tables.py`)

```python
    # Icy / aurora: white ground, blue Iceland body, green accent.
    # ``draw_glacier_border`` adds frost-crystal shards in the corners and
    # star ticks at the mid-edges. ``_draw_text_body`` reroutes the green
    # accent to a 5/8:3/8 G+B teal (Bayer threshold 6/16); a 50/50 cyan reads
    # too close to the blue body.
    "glacier": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["blue"],
        "subtle": SPECTRA6["blue"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["green"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["blue"],
    },
```

### `THEME_FONTS` entry (`render_quote/theme_tables.py`)

```python
    "glacier": {
        # Iceland (OFL) — single-weight techno display face. The matched
        # phrase reuses Regular, and ``_draw_text_body`` adds a
        # ``stroke_width=1`` faux bold over the teal G+B stipple: the teal
        # alone sits too close in hue to the blue body. Heavy-sans fallbacks.
        "quote_regular": [
            ICELAND_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            ICELAND_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            ICELAND_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
```

### `_draw_text_body` branch (`render_quote/text.py`)

The colour reroute this theme had in `_draw_text_body`; a branch shared with another retired theme is shown whole.

```python
    elif theme in ("blueprint", "scholar") and fill == SPECTRA6["red"]:
        # Maroon (R+K 1:1): blueprint's red pencil pressed hard, scholar's
        # aged red-lead annotation. Border marks stay solid red.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["black"])
    elif theme == "illuminated" and fill == SPECTRA6["blue"]:
        # Violet (R+B 1:1) — Tyrian purple, in the same register as the
        # border's R+B+K plum cabochons. The red body never hits this branch.
        draw_text_dithered(image, xy, text, font, dark=SPECTRA6["red"], light=SPECTRA6["blue"])
    elif theme == "glacier" and fill == SPECTRA6["green"]:
        # Teal (G+B 5/8:3/8, Bayer threshold 6/16). 50/50 cyan read too close
        # to the blue body and solid green read muddy; the green bias pulls
        # the phrase off the body while staying cool. Plus a
        # ``stroke_width=1`` faux bold, since Iceland ships only Regular and
        # hue alone doesn't carry the differentiation.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["blue"], light_density=0.375, stroke_width=_bold_stroke_for_theme(theme))
    elif theme == "risograph" and fill == SPECTRA6["blue"]:
        # Violet (R+B 1:1) — the riso red-over-blue overprint. Keeps the
        # theme's no-black invariant by construction.
        draw_text_dithered(image, xy, text, font, dark=SPECTRA6["red"], light=fill)
```
