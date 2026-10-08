# `intaglio` (retired)

Retired from the rotation, the renderer and the live docs. Everything the theme was is kept in this folder so it can be restored as it was; see [`../../README.md`](../../README.md) for how.

## README row

| `intaglio`    | <img src="idle_hours/assets/previews/intaglio.png" width="240" alt="intaglio theme preview">       | white       | black | green  | Old Standard TT + Cinzel Decorative | Banknote engraving |

## Design notes (from `docs/themes.md`)

  - `intaglio` (white paper / black intaglio plate / green tint plate / red numbering press, Old Standard TT + Cinzel Decorative) — **a banknote face, engraved**, and the theme that introduces the renderer's fourth tone mechanism.

    **Tone as line-work.** `paint_hatched_tone` renders continuous tone as parallel engraved lines whose *weight* carries the grey at constant pitch, where every other synthesised tone is a per-pixel stipple. A custom-render frame (`render_intaglio_frame`), fully procedural with no committed plate, deliberately: guilloché exists *because* it is parametric.

    **The three-plate structure of a real note.** A woven green cycloid lathework band between black rules; four corner hypotrochoid medallions (`_intaglio_roulette_points` computes true spirograph closure from `(R−r)/r` in lowest terms, with step counts scaled so no polyline segment exceeds ~1.5 px — coarse sampling leaves dotted gaps on shallow arcs); a large faint ground rosette peeking around a white superellipse quote cartouche. The cartouche rim is shaded by the hatching primitive: one family at 33° carries the full tone, a second at 123° is laid only into the deepest half — the engraver's own cross-hatch rule, encoded as a shadows-only tone function rather than a parameter.

    **Chrome.** A letterspaced Cinzel masthead over a Pinyon Script promise line, a repeated-microtext rule ("IDLEHOURS·" at 6 px — reads as a hairline at panel distance, resolves as text up close), and a red Space Mono serial printed twice.

    **The time carrier is the denomination**: the hour spelled as a face value (SEVEN, TWELVE) in the corner medallions — hour only, as a word, the bakelite/cardcatalog coarse-hour posture, pinned by a byte-identical-across-minutes test. The serial derives from `_row_digest`, never the clock — encoding the minute in it would put readable digits of the time on the panel.

    **The matched phrase** stays black bold with a green lathework ribbon beneath (green *glyphs* measured too pale: panel green is ~70 luminance against white's ~195).

    **Moiré management is the constants' job:** hatch spacing ≥ 4 at angles off 0/45/90, families 90° apart, pure-white cartouche interior. Claims no synthesised recipe — the banknote palette is the one register where the panel's saturated native inks are period-correct. Saturation tier `0.5` (white ground).

## Font notes (from `docs/themes.md`)

  - `intaglio` uses **Old Standard TT** for the legend — the 19th-century Didone nearest the engraved-currency register, shared with `newsprint` on the usual grounds (a broadsheet and a banknote won't be confused). **Cinzel Decorative** (shared with `roman` / `tarot` / `grimdark`) carries the masthead and the corner denominations in the ornament slot; the frame loads **Pinyon Script** (the promise line) and **Space Mono** (serial, microprint rule) directly, the bakelite pattern of chrome faces loaded inline.

## Registration

- `THEME_ORDER`: sat after `metro`.
- `display_inky.THEME_SATURATION`: `"intaglio": 0.5,`

### `THEMES` entry (`render_quote/theme_tables.py`)

```python
    # Banknote / security engraving. Custom frame (``render_intaglio_frame``);
    # palette serves the palette-only paths (see the note above ``THEMES``).
    # The face is a real note's three plates: black intaglio, green tint
    # lathework, red numbering press, on white paper.
    "intaglio": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["green"],
        "accent": SPECTRA6["green"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["green"],
        "source": SPECTRA6["black"],
    },
```

### `THEME_FONTS` entry (`render_quote/theme_tables.py`)

```python
    # Intaglio's legend is Old Standard TT, the Didone nearest engraved
    # currency. Cinzel Decorative (ornament slot) carries the masthead and
    # denominations; the frame loads Pinyon Script (promise line) and Space
    # Mono (serial, microprint) directly, the bakelite pattern.
    "intaglio": {
        "quote_regular": [
            OLDSTANDARD_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            OLDSTANDARD_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            CINZELDECORATIVE_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
```
