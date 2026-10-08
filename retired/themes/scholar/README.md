# `scholar` (retired)

Retired from the rotation, the renderer and the live docs. Everything the theme was is kept in this folder so it can be restored as it was; see [`../../README.md`](../../README.md) for how.

## README row

| `scholar`     | <img src="idle_hours/assets/previews/scholar.png" width="240" alt="scholar theme preview">         | white       | blue  | red    | Bitter (slab)        | Academic textbook             |

## Design notes (from `docs/themes.md`)

  - `scholar` (white/blue/red, Bitter slab serif) — a hand-set academic-journal offprint.

    **Accent.** The matched-phrase red accent is rerouted in `_draw_text_body` to a 50/50 R+K maroon stipple, reading as the aged red-lead of an academic-journal annotation.

    **Border.** `draw_scholar_border` is a critical-edition treatment: a doubled blue frame (outer + inner rule), printer's L-shaped corner brackets tucked just inside the inner frame's four corners (the registration marks of a well-composed type area), a head asterism — three small red lozenges in the canonical `⁂` section-break triangle centred above the type area — and a matching foot folio ornament (a short centred blue rule pierced by a small red lozenge).

    **Marginalia.** Thin blue margin ruling lines run down both sides at x=40 / width-40 (clear of the widest dense-layout text column at x≥60), turning the three red footnote reference numbers from floating marks into proper hanging marginalia, each tagged with a small red tick on its outer side. Restrained by design — blue + red only, the vocabulary of a hand-set journal offprint rather than a marked-up term paper.

## Font notes (from `docs/themes.md`)

  - `scholar` uses **Bitter** — a slab serif; even-contrast blocky terminals read as "academic textbook" and sit visually far from Playfair's display-serif silhouette, Regular body + Bold accent.

## Registration

- `THEME_ORDER`: sat after `swiss`.
- `display_inky.THEME_SATURATION`: `"scholar": 0.5,`

### `THEMES` entry (`render_quote/theme_tables.py`)

```python
    # Scholarly journal: blue body on cream-white, red accent for the matched
    # phrase. Readable at a distance thanks to the strong blue/white contrast.
    "scholar": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["blue"],
        "subtle": SPECTRA6["blue"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["blue"],
    },
```

### `THEME_FONTS` entry (`render_quote/theme_tables.py`)

```python
    "scholar": {
        # Bitter slab serif. The variable font defaults to Thin (axis
        # minimum 100), so every candidate pins an instance — without it the
        # panel shows near-invisible ghost strokes.
        "quote_regular": [
            (BITTER_VARIABLE, "Regular"),
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (BITTER_VARIABLE, "Bold"),
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (BITTER_VARIABLE, "Bold"),
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
