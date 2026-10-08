# `risograph` (retired)

Retired from the rotation, the renderer and the live docs. Everything the theme was is kept in this folder so it can be restored as it was; see [`../../README.md`](../../README.md) for how.

## README row

| `risograph`   | <img src="idle_hours/assets/previews/risograph.png" width="240" alt="risograph theme preview">     | white       | red   | blue   | Rubik (rounded sans) | Two-colour riso zine          |

## Design notes (from `docs/themes.md`)

  - `risograph` (white/red/blue, Rubik rounded sans) — ZERO black ink, a two-colour riso print.

    **Accent.** The matched-phrase blue accent is rerouted in `_draw_text_body` to a 50/50 R+B violet stipple — the authentic riso double-pass overprint where the red and blue plates physically wash into purple; preserves the no-black-ink invariant by construction.

    **Knockout label.** The body rect is threaded through as `clear_rect` (pad 20/14/14) and knocked back to paper after the chunky bars and overprint circles paint, then framed with a 2 px red rule and a 2 px blue rule offset by the sheet's (5, 3) misregistration — a pasted-up label with the print-test shapes running behind it. Without the knockout the left bar and the circles sat under the first word and the attribution of most quotes.

    **Registration marks.** The `draw_risograph_border` shifted-accent registration crosses at the four corners paint in an off-palette sentinel and then bbox-post-pass through a 3-way 4×4 Bayer partition into LAVENDER (R+B+W ~1/3 each) — the paler "overprint" register-mark tone real risograph test sheets develop where two plates wash together. A **colour-registration bar** centred in the top margin carries five solid swatches (red / blue / lavender-overprint / red / blue) of the kind a print shop runs at the sheet edge to check ink density and plate alignment, the lavender swatch using the same R+B+W 3-way recipe; every swatch is red / blue / white only, preserving the no-black-ink invariant.

## Font notes (from `docs/themes.md`)

  - `risograph` uses **Rubik** (chunky rounded modern geometric sans — variable font whose axis default is Light (300) NOT Regular, so every THEME_FONTS candidate pins Regular / Bold explicitly; a missing `set_variation_by_name` call would render body text noticeably too thin).

## Registration

- `THEME_ORDER`: sat after `bauhaus`.
- `display_inky.THEME_SATURATION`: `"risograph": 0.7,  # two spot inks and no black to anchor them`

### `THEMES` entry (`render_quote/theme_tables.py`)

```python
    # Risograph / zine two-colour print. Red body, blue "overprint" on the
    # matched phrase, and no black ink anywhere — that constraint defines the
    # theme and is pinned as a test invariant. ornament_dark is blue so the
    # quote marks carry the second-colour texture. Rubik gives the zine
    # register.
    "risograph": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["red"],
        "subtle": SPECTRA6["red"],
        "faint": SPECTRA6["red"],
        "accent": SPECTRA6["blue"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["red"],
    },
```

### `THEME_FONTS` entry (`render_quote/theme_tables.py`)

```python
    "risograph": {
        # Rubik's default instance is Light (300), NOT Regular, so a missing
        # set_variation_by_name renders the body too thin. Pin Regular / Bold
        # on every candidate.
        "quote_regular": [
            (RUBIK_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (RUBIK_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (RUBIK_VARIABLE, "Bold"),
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
