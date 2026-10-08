# `illuminated` (retired)

Retired from the rotation, the renderer and the live docs. Everything the theme was is kept in this folder so it can be restored as it was; see [`../../README.md`](../../README.md) for how.

## README row

| `illuminated` | <img src="idle_hours/assets/previews/illuminated.png" width="240" alt="illuminated theme preview"> | white       | red   | blue   | EB Garamond + UnifrakturMaguntia | Rubricated manuscript |

## Design notes (from `docs/themes.md`)

  - `illuminated` (white/red-body/blue-accent, EB Garamond + UnifrakturMaguntia blackletter ornaments) — a rubricated manuscript.

    **Border.** `draw_illuminated_border` paints a Layer 0 sparse 1-in-8 yellow-on-white cream Bayer wash for aged-vellum tone, a doubled rubricated red rule, and a plum "cabochon" centred on each outer corner — a filled circle painted in a sentinel ink and then bbox-post-passed through a 3-way 4×4 Bayer partition (cells 0-4 → red, 5-9 → blue, 10-15 → black) — evoking the wine-dark lapis cabochons inset on the most precious medieval bindings.

    **Head and foot.** A rubricated **head asterism** (three red lozenges in the canonical `⁂` section-break triangle, each pierced by a small blue dot — rubric + lapis, centred in the top margin) and a **foot line-filler** (a centred red rule + central red lozenge flanked by two small blue lozenges — the decorative line-ender medieval scribes ran to the end of a short final line), both centred so they clear the bottom-left attribution.

    **Accent.** The matched-phrase blue is rerouted in `_draw_text_body` to a 50/50 R+B violet stipple — Tyrian purple, the rarest dye of the scriptorium.

## Font notes (from `docs/themes.md`)

  - `illuminated` pairs **EB Garamond** (humanist old-style serif — different family branch from Playfair's transitional / Bitter's slab / Old Standard's Didone) for the body with **UnifrakturMaguntia** (blackletter) confined to the ornament slot for the oversized curly quotation marks — a blackletter body would shred dense-layout legibility on a 4-bit eInk panel.

## Registration

- `THEME_ORDER`: sat after `blueprint`.
- `display_inky.THEME_SATURATION`: `"illuminated": 0.5,`

### `THEMES` entry (`render_quote/theme_tables.py`)

```python
    # Medieval illuminated manuscript. White vellum, red body text
    # (rubrication, the traditional mark of a liturgical or emphasised
    # passage) and lapis-blue for the matched time phrase. EB Garamond
    # handles the body at legible sizes; the blackletter
    # UnifrakturMaguntia sits in the ornament slot for the big curly
    # quotation marks, carrying the scriptorium texture without wrecking
    # body legibility.
    "illuminated": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["red"],
        "subtle": SPECTRA6["red"],
        "faint": SPECTRA6["red"],
        "accent": SPECTRA6["blue"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["red"],
    },
```

### `THEME_FONTS` entry (`render_quote/theme_tables.py`)

```python
    "illuminated": {
        # EB Garamond body with a UnifrakturMaguntia ornament (quote marks
        # only): a blackletter body would shred at dense-layout sizes on the
        # panel.
        "quote_regular": [
            EBGARAMOND_REGULAR,
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            EBGARAMOND_BOLD,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            UNIFRAKTUR_BOOK,
            EBGARAMOND_BOLD,
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
