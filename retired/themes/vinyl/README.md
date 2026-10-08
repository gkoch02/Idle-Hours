# `vinyl` (retired)

Retired from the rotation, the renderer and the live docs. Everything the theme was is kept in this folder so it can be restored as it was; see [`../../README.md`](../../README.md) for how.

## README row

| `vinyl`       | <img src="idle_hours/assets/previews/vinyl.png" width="240" alt="vinyl theme preview">             | cream/white | black | tangerine | Cormorant Garamond | Turntable and spoken-word LP |

## Design notes (from `docs/themes.md`)

  - `vinyl` (cream-washed sleeve / black Cormorant Garamond body / tangerine matched-phrase / red label + black tonearm) — a turntable + literary-audiobook LP back-cover. A custom-render frame that bypasses the literary layout entirely.

    **Register.** A 1950s/60s spoken-word LP in the **Caedmon Records / Spoken Arts / Listening Library register**. Those labels pressed Dylan Thomas, T. S. Eliot, Auden et al. reading their own work to vinyl; the discs looked mechanically identical to music LPs (33 RPM, grooved, jacketed, library-distributed), and they are the historical bridge between a vinyl visual and a literary corpus. The canvas divides down the middle: turntable left, liner notes right.

    **Disc.** A black vinyl LP (`_VINYL_DISK_R` = 168, centred at `(_VINYL_DISK_CX, _VINYL_DISK_CY) = (178, 246)`). The disc is sized so the tonearm geometry is solvable at all — see "Tried and rejected".

    **Sheen.** A **concentric sheen banding** across the programme band: `_VINYL_SHEEN_BANDS` cosine cycles of white density peaking at `_VINYL_SHEEN_PEAK`, read off `BAYER_8x8` with the rank jittered by `position_noise`. A *smooth* density ramp (the shape `chrono`'s sky and `abyssal`'s water use) gives the dither nothing periodic to alias against, and the eye still integrates it into the textured silvery band a pressed programme area has. A single heavier lead-in groove just inside the rim survives as an actual ellipse — an isolated ring has no pitch to beat with — over a smooth dead-wax ring between it and the label.

    **Tonearm.** `_vinyl_paint_tonearm` draws a pivoted arm. The pivot is *derived* from the disc rather than hardcoded (`_vinyl_tonearm_pivot`, at `_VINYL_PIVOT_DISTANCE_RATIO` = 1.46 disc radii and `_VINYL_PIVOT_ANGLE_DEG` = -40°), with a counterweight cylinder behind it (small black filled circle + red outline ring) and a black cartridge headshell at the front (a 4-point polygon rotated to follow the arm angle, since PIL has no rotate-rectangle primitive). The arm tube is **cased** — a 5-px black stroke under a 2-px white core — because a plain black tube was invisible for the entire stretch crossing the black record, which is the stretch that matters.

    **The minute drives the stylus radius, not a rim angle.** A record plays outside-in, so minute 0 puts the stylus at the outer edge of the programme band and minute 59 near the run-out (`_VINYL_RUNOUT_RATIO`), and the arm creeps inward across the hour exactly as a real one does while a side plays. The arm's *angle* falls out of geometry: with the pivot a fixed distance from the disc centre and a fixed `_VINYL_ARM_LENGTH_RATIO` (1.51, a 9-inch arm on a 12-inch record, the commonest consumer proportion), a stylus at radius r sits at a two-circle intersection. `tests/test_render_quote_themes.py::TestVinylFrame` pins the direction of travel (strictly decreasing radius — a rim-pinned stylus gives a *constant* one, which a non-increasing assertion accepts), that the tip stays on the programme band, and that its distance from the bearing is constant, which is the invariant separating a pivoted arm from a point placed at an angle.

    **Label.** The red `_VINYL_LABEL_R` = 76-px-radius label carries, all white-on-red: an outer 2-px black ring border (inset 4 px from the label edge), a `· SPOKEN WORD ·` format mark along the top arc in small Antonio Bold (the audiobook-LP equivalent of a music LP's STEREO format mark), the matched-phrase snippet truncated to 18 chars as the "passage title" in Cormorant Bold 11pt, a thin white hairline divider, an `IDLE HOURS` Cormorant Bold 14pt brand line, a `READ ALOUD` Cormorant Regular 11pt sub-title (the equivalent of a music LP's "VOLUME I"), a Space Mono Bold catalog number like `IH-H11-15` derived from the fuzzy bucket via `_vinyl_catalog_number`, and a `© YYYY` year stamp at the bottom arc.

    **Render order.** On the turntable side: **disk body (black + grooves only, no label / spindle) → tonearm (line may cross over the inner disk and label area) → label (red fill + outer ring + SPOKEN WORD mark + brand + spindle)**, so the label paints on top of the arm without the arm cutting through the brand-stack text.

    **Liner notes.** The right half is a cream-washed panel: a small red `— READING —` Antonio Bold heading at the top (the Caedmon-Records equivalent of a music LP's "TRACK ONE" sleeve heading), then a **spec strip** (`SIDE ONE · 33 RPM · MONO` left, `RUNNING TIME m:ss` right, in Space Mono Bold over a thin hairline rule — the technical line real spoken-word backs ran under each selection). The strip fills the dead cream between the heading and the vertically-centred quote and brackets the body symmetrically with the bottom catalog bar. The running time is a stable per-bucket digest, not `hash()`, so the frame stays byte-deterministic; the speed uses ASCII `33 RPM` since Space Mono has no `⅓` glyph. The literary quote follows in Cormorant Garamond with a tangerine R+Y 5/8:3/8 matched-phrase substitution (the documented `deco` / `astrarium` recipe), then the author · title attribution.

    **Catalog bar and badge.** A bottom bar reads `IDLE HOURS LITERARY RECORDINGS  ·  CAT NO. IH-H11-15  ·  © YYYY` in Cardo Italic 11pt with a thin black hairline rule above — the small-print band real LP back covers carry at the foot of the jacket. The two halves overran each other on a wide catalog number, so `_vinyl_paint_catalog_bar` degrades the imprint through `_VINYL_IMPRINTS` and *then* steps the point size down to `_VINYL_CATALOG_MIN_SIZE`, and both halves share one baseline via `anchor="ls"` / `"rs"`. A `33 RPM` badge sits in the top-right corner — ASCII is the canonical fallback every record-jacket designer reaches for when the fractional ⅓ isn't available.

    **Wear and saturation.** Daily-seeded wear marks on the sleeve (`_vinyl_paint_wear_speckle(seed=YYYYMMDD)`) — same-day re-renders produce the identical speckle pattern, day-to-day re-renders drift naturally. Saturation tier `0.5` (white-ground tier): the cream sleeve dominates visually and the black vinyl disk has no synthesised colour that needs a saturation boost; the matched-phrase tangerine R+Y uses the same recipe `astrarium` does and reads correctly at this saturation.

    **Tried and rejected.**
    - **A larger disc (r=200 at (200, 240)).** It ran flush to the left, top and bottom edges and left nowhere for the arm assembly to live — the pivot ended up only 1.27× the disc radius from the spindle, where no arm length puts the stylus in a sane place. Shrinking the disc is what makes the tonearm geometry solvable.
    - **Literal 1-px white groove hairlines every 3 px.** At that pitch the ring lattice beat against the dither into a blocky plaid — the "two periodic patterns beat" trap `bakelite` documents.
    - **A straight-line stylus,** then **a cartridge swept 360° around the *rim* at the minute's clock angle** (its own docstring conceded it was "allowed to be non-physical"). It looked like a stick on a ball crossing the record, reading as a scratch rather than as a tonearm.
    - **The unicode `⅓` glyph in the `33 RPM` badge:** Space Mono Bold doesn't carry that codepoint and the badge tofu'd.

## Font notes (from `docs/themes.md`)

  - `vinyl` uses **Cormorant Garamond** (Christian Thalmann, OFL — the same high-contrast humanist serif `mucha` and `astrarium` use) for the entire turntable-and-sleeve composition: Regular for the body, Bold for the matched-phrase tangerine, Bold for the label brand stack (IDLE HOURS), Regular for the READ ALOUD sub-title.

    **Chrome faces.** **Cardo Italic** fills the back-cover catalog bar at 11pt — the small-print typographic register real LP back covers use for the legal / catalog band. **Space Mono Bold** (Florian Karsten, OFL — same monospace face `nightvision` uses) carries the catalog number and the `33 RPM` badge, the canonical "engineered" register for record-jacket catalog numbers. **Antonio Bold** (variable Bold instance, same condensed sans `lcars` uses) fills the small chrome strips on the label (· SPOKEN WORD · format mark, © year stamp) and the liner-notes sleeve heading (— READING —) — small-chrome legibility same argument as marquee's.

## Registration

- `THEME_ORDER`: sat after `tarot`.
- `display_inky.THEME_SATURATION`: `"vinyl": 0.5,`
- Was the only member of CYCLE_EXCLUDED_THEMES: registered, reachable only by --theme vinyl.

### `THEMES` entry (`render_quote/theme_tables.py`)

```python
    # Spoken-word LP (Caedmon / Spoken Arts register). Custom frame
    # (``render_vinyl_frame``): turntable, grooves, tonearm, label and sleeve,
    # with the quote as the "reading passage" on the jacket back. The chrome
    # text (SPOKEN WORD, READING, READ ALOUD, the catalog bar) frames it as an
    # audiobook so it fits the literary corpus.
    "vinyl": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["black"],
    },
```

### `THEME_FONTS` entry (`render_quote/theme_tables.py`)

```python
    # Vinyl — Cormorant Garamond Regular / Bold: high-contrast forms that
    # read at both label scale (12 pt) and sleeve scale (~32 pt). The
    # ornament reuses Bold for the 33⅓ rpm badge.
    "vinyl": {
        "quote_regular": [
            (CORMORANT_VARIABLE, "Regular"),
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (CORMORANT_VARIABLE, "Bold"),
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (CORMORANT_VARIABLE, "Bold"),
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
```
