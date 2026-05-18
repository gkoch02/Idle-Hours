# Theme Proposals — Filling Gaps in the Current Spread

## Context

LitClock's renderer ships **24 literary themes** (25 with the `diags` panel), each pairing a Spectra-6 palette with a distinct typographic register and a custom border painter. The set is already broad — transitional / slab / humanist / Didone serifs, grotesque / geometric / rounded sans, blackletter, monospace, handwritten, brush, wood-engraved, art-deco display — and covers historical aesthetics from Roman lapidary (`roman`) through medieval manuscript (`illuminated`, `gothic`, `alchemy`, `grimoire`), broadsheet (`newsprint`), wild-west (`saloon`), 1930s art-deco (`deco`, `bauhaus`), 1950s atomic-age (`atomic`), and 1980s sci-fi (`lcars`, `nightvision`).

A survey of the 24 themes against the bundled font directory and the in-use colour recipes (see `spectra6_color_recipes.md`) reveals several **conspicuous gaps** that, if filled, would noticeably broaden the rotation's visual silhouette:

- **No clean modernist register.** Every theme either decorates aggressively (deco / bauhaus / atomic / lcars borders) or carries strong historical character. Nothing is austere, grid-driven, mid-century-functional — the Swiss International / Massimo-Vignelli typographic tradition has no representative.
- **Sage / forest / khaki / terracotta colour territory is unclaimed.** Eight two-ink and three-ink recipes are documented in `spectra6_color_recipes.md` but flagged "not in use" — the green-side of the colour wheel is dramatically underrepresented (only `glacier`'s frost-shards and `roman`'s laurel sprigs use green-derived synthesised colours, and both treat it as accent rather than identity).
- **Art Nouveau / organic-curve register is absent.** Every existing border painter uses straight rules, geometric figures, or angular ornaments. Nothing leans into sinuous, organic, plant-form decoration.
- **1960s psychedelic register is absent.** No theme expresses the saturated, multi-colour, swirly poster art of Wes Wilson / Victor Moscoso — the visual mode that *demands* all six Spectra-6 inks simultaneously.

This document proposes **four new themes** chosen to fill those gaps with maximum distinctness from the existing 24. Each entry specifies the register, palette (native + two-/three-ink synthesised), font family with OFL/Apache sourcing, border-painter concept, saturation tier, and the `THEME_FONTS` fallback chain — enough to drop straight into `render_quote.py` without further design work.

The four picks (`swiss`, `herbarium`, `mucha`, `fillmore`) are deliberately complementary: they span austere → ornate, monochrome-restrained → polychrome-saturated, geometric → organic, and historical → counter-cultural. Together they widen each axis the current rotation underexplores.

---

## Proposal 1 — `swiss` (Swiss International / modernist functional)

### Register
The Swiss style of the 1950s–60s: Helvetica, asymmetric grid, ragged-right left-aligned body, single hairline rule, no ornament, no border. The rotation has *no* austere modernist theme — `bauhaus` is geometric-constructed and ornament-heavy, `blueprint` is engineering, `lcars` is sci-fi. This fills the most striking historical gap.

### Palette (all Spectra-6 natives — no two-ink synthesis needed)
- `page_bg`: white
- `text` / body: black
- `accent` / matched phrase: red (used sparingly — just the matched phrase and one horizontal rule)
- No third colour. **Defining feature: typography does all the work, palette is austere.**

### Font
**Inter** (Rasmus Andersson, OFL) — the modern open-source Helvetica replacement, variable font with Regular and Bold instances. Add `fonts/inter/Inter-Variable.ttf` (variable axis pinned via `set_variation_by_name("Regular")` / `"Bold"`, same pattern as `scholar` / `bauhaus` / `risograph`).
- Body: Inter Regular, slightly tighter tracking than default Playfair
- Matched phrase: Inter Bold (no colour shift would betray the modernist principle, so the **matched-phrase role uses Bold weight** alongside the red accent — type-weight does the heavy lifting, accent colour is a quiet highlight)
- Fallback chain: Inter → DejaVu Sans → Liberation Sans → Noto Sans → Playfair (so a missing-Inter install lands on grotesque-sans silhouette, never on a serif)

### Border / decoration
**`draw_swiss_border`** — deliberately minimal, the inverse of every other border painter:
- Single 1 px black hairline rule at `y = 60` (a horizontal rule positioned high on the page, dividing a small header zone from the body — the classic Swiss "Müller-Brockmann grid" gesture)
- A red 4-px filled square at `(width - 40, 28)` in the header zone (the only chromatic accent on the page besides the matched phrase — references Vignelli's NYC Subway signage, Müller-Brockmann's concert posters)
- No corner ornaments, no frame, no second rule. The composition's signature is *what's missing* — every other theme decorates, this one refuses to.

### Saturation
`THEME_SATURATION["swiss"] = 0.5` — white ground, restrained palette.

### Why it fills a gap
- **Only theme in the rotation with no decorative border at all**, by design — a deliberate counterpoint to the borderful majority.
- Introduces grotesque sans typography in a *pure* form (Archivo's already in `blueprint` but paired with engineering decoration; Inter would be the first time it stands alone).
- Reads instantly different from any other white-ground theme at panel distance — the sparseness *is* the visual identity.

### THEME_FONTS entry
```python
"swiss": {
    "quote_regular": [(str(BASE_DIR / "fonts/inter/Inter-Variable.ttf"), "Regular"),
                       "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", ...],
    "quote_bold":    [(str(BASE_DIR / "fonts/inter/Inter-Variable.ttf"), "Bold"), ...],
    "ornament":      [(str(BASE_DIR / "fonts/inter/Inter-Variable.ttf"), "Bold"), ...],
}
```

---

## Proposal 2 — `herbarium` (botanical specimen sheet)

### Register
A pressed-plant specimen sheet from a 19th-century natural-history herbarium: aged cream paper, dried-leaf olive accents, Latin binomial labels in a quiet serif. Pairs with `scholar` (academic journal) and `newsprint` (broadsheet) tonally but reads as **scientific natural-history rather than literary or journalistic**, and crucially *opens the green colour territory* that the current rotation barely touches.

### Palette
- `page_bg`: white, with Layer 0 sparse 1-in-8 yellow-on-white Bayer wash (the cream recipe `dispatch` / `illuminated` already use — aged-paper warmth)
- `text` / body: black
- `accent` / matched phrase: **olive** (yellow + green at 1/2:1/2 — the recipe `roman`'s laurel sprigs already use). The matched phrase rerouted in `_draw_text_body` to a 50/50 Y+G stipple — reads as dried-leaf olive, the perceived colour of a real pressed-and-aged herbarium specimen.
- Secondary decorative accent: **sage** (white + green inverted at 3/4:1/4, the `nightvision` scanline recipe) for the border's leaf veins

### Font
**IM Fell DW Pica** (Igino Marini, OFL) — already partially bundled in `fonts/im-fell-english/` for `alchemy`/`grimoire`. Either reuse the existing IM Fell English (close enough register) **or** add the DW Pica variant for visual differentiation. The 17th-century Oxford-press cut reads as scientific-historical without dragging the manuscript / occult register `alchemy` and `grimoire` already own.
- Body: IM Fell DW Pica Regular
- Matched phrase: IM Fell DW Pica Italic (italic + olive synthesised accent does the differentiation — italic is canonical for Latin scientific names, anchoring the register)
- Fallback: DejaVu Serif Italic → Liberation Serif Italic → Playfair Italic → Playfair Regular

### Border / decoration — `draw_herbarium_border`
The signature element: a **pressed-leaf specimen and its hand-lettered label** in the bottom-right corner.
1. Layer 0 ground wash (cream, as above)
2. Thin black hairline rule framing the page at inset 14 px — the engraver's-frame convention of a real herbarium mounting sheet
3. **Pressed-leaf silhouette** in the lower-right corner: a stylised oval leaf (~80×40 px) painted in olive (yellow sentinel ink, bbox-post-passed with green at 50/50 parity — same recipe as `roman`'s laurel leaves), with a darker olive midrib and three pairs of side veins post-passed in sage (the muted W+G variant) so the vein structure reads at panel distance but doesn't crowd the body. The leaf sits *under* the body text z-order — text is drawn on top.
4. **Specimen label**: a small rectangular cartouche bottom-left (the corner *opposite* the leaf, balancing the composition), drawn as a 1 px black rule outlining a ~120×30 px box with the Latin phrase **"Tempus fugit"** rendered in tiny IM Fell italic inside — a single Latin gesture that anchors the herbarium register without crowding the literary quote.
5. Four small black "pinhole" dots at the corners of the inner rule (where a real specimen would be physically pinned to the mounting sheet)

### Saturation
`THEME_SATURATION["herbarium"] = 0.5` — white-ground theme, gentle accent.

### Why it fills a gap
- **Opens the olive / sage / cream colour story for an entire theme** — no current theme uses green-derived colour as its defining accent (only as supporting decoration in `roman` / `glacier`).
- Adds the "scientific specimen" cultural register — distinct from `scholar` (academic) and `newsprint` (journalistic).
- Layered decoration concept (Layer 0 wash + frame + corner specimen + balanced label) is more elaborate than most existing themes, evoking the *physicality* of a real mounted specimen — but anchored to existing two-ink recipes so it stays palette-clean.
- Latin "Tempus fugit" connects subtly to the literary-clock concept without being heavy-handed.

### THEME_FONTS entry
Reuses the bundled IM Fell English chain that `alchemy` / `grimoire` already pull from, plus an italic candidate added for the matched phrase.

---

## Proposal 3 — `mucha` (Art Nouveau, organic curves)

### Register
The 1900s Belle Époque poster aesthetic of Alphonse Mucha and the Vienna Secession: sinuous serpentine ornament, organic plant-form motifs, ivory + maroon + teal palette, decorative-display lettering for headings paired with humanist body type. Fills the Art Nouveau historical gap **and** introduces organic / curvilinear border decoration — every current border painter is angular or geometric, this would be the first all-curve composition.

### Palette
- `page_bg`: white with Layer 0 cream wash (same Y+W 50/50 recipe `illuminated` uses)
- `text` / body: **maroon** (red + black at 1/2:1/2, the recipe `dispatch` / `gothic` / `chanbara` already use). Body text painted in red as sentinel, then bbox-post-passed to flip half to black per `(x+y)&1` parity — reads as a deep wine / oxblood, the canonical Mucha poster body colour.
- `accent` / matched phrase: **forest-teal** (green + blue + yellow at 40/40/20 — currently unused 3-ink chromatic mix from `spectra6_color_recipes.md`). The richest unused colour territory in the codebase. Implementing requires extending `draw_text_dithered` with a 3-way Bayer branch (or compositing two passes), but the same primitive would unlock future "deep forest" themes.
- Alternative if 3-ink text dithering is deferred: use **cyan** (green + blue 1/2:1/2, `glacier`'s recipe) for the matched phrase — still in the teal family, reachable with the existing 2-ink primitive.

### Font
**Cormorant Garamond** (Christian Thalmann, OFL) — a high-contrast humanist serif with the dramatic curves that fit Mucha-era display typography (more decorative than EB Garamond / IM Fell, sharing none of their austere register). Variable font with Regular / Bold instances.
- Body: Cormorant Garamond Regular
- Matched phrase: Cormorant Garamond Bold + teal accent
- Ornament slot: **Berkshire Swash** (Astigmatic, OFL) — a flourished art-nouveau-revival display face for the oversized quote marks. Same designer as Atomic Age and Righteous, so the bundled-fonts integration pattern is already established.
- Fallback chain: Cormorant → EB Garamond → DejaVu Serif → Playfair

### Border / decoration — `draw_mucha_border`
The signature element: **organic vine ornaments at two diagonal corners**, the first all-curve border in the rotation.
1. Layer 0 cream wash (as `illuminated`)
2. **Vine ornaments** at top-left and bottom-right (diagonal balance, asymmetric like a real Mucha poster):
   - Each ornament is a Bézier-curve-approximated S-shaped stem rendered as connected 4-point polylines (PIL doesn't ship curves, but `n-point polygon approximation` is a known LitClock pattern — `atomic`'s atom orbits use it). Stem painted in maroon (R+K stipple).
   - Three trefoil leaf clusters sprouting from each stem: each leaf a small filled ellipse painted in olive (Y+G, same as `herbarium` / `roman`)
   - One small filled circle "berry" at the stem tip, painted in red as sentinel and bbox-post-passed for **tangerine** (R+Y at 5/8:3/8, the established `deco` / `atomic` / `lcars` recipe) — the warm-spark accent
3. Thin teal hairline rule at inset 18, painted in the same forest-teal / cyan synthesis the matched phrase uses — ties border and body together
4. Top-right and bottom-left corners deliberately *unornamented* — the asymmetry is the signature of a Mucha composition (real Mucha posters compose around an off-centre figure, not a symmetric frame)

### Saturation
`THEME_SATURATION["mucha"] = 0.7` — multi-colour synthesised palette benefits from the higher saturation tier (same as `risograph` and `comic`).

### Why it fills a gap
- **First theme with an all-curve / organic border** — every current decoration is angular, geometric, or rule-based. Bézier-approximated vines complete a missing visual vocabulary.
- Fills Art Nouveau historical gap with a Mucha-specific anchor (rather than a generic "ornate" theme).
- Either unlocks 3-ink text dithering (forest-teal, opening forest / spa / deep-water territory for future themes) or commits to the cyan fallback recipe — both productive outcomes.
- Body text in maroon rather than black is a deliberate departure — no current theme uses a synthesised colour as its *primary* body fill. Demonstrates the recipe's range and produces a frame that's immediately distinguishable from any other white/cream-ground theme.

---

## Proposal 4 — `fillmore` (1960s psychedelic concert poster)

### Register
The Fillmore Auditorium concert posters of 1966–68 by Wes Wilson, Victor Moscoso, Stanley Mouse, and Rick Griffin: saturated multi-colour fields, swirly hand-drawn lettering that bends to the composition, organic blob-shaped panels, and *every available ink used simultaneously*. The only theme in the rotation that would deliberately deploy all six Spectra-6 natives — total visual contrast to `swiss`'s austerity.

### Palette
- `page_bg`: yellow (the canonical Fillmore poster ground — sun-faded "billiard-cloth yellow")
- `text` / body: **red** (the saturated single-colour body of countless 1967 Avalon Ballroom posters)
- `accent` / matched phrase: **blue** (deep psychedelic blue — pure Spectra-6 native, the Janis Joplin / Big Brother poster contrast)
- Secondary decorative accents from the border: green, black, white — used in panels and outlines so the whole frame ends up using all six Spectra-6 inks at once. **Defining feature: maximum chromatic saturation, in deliberate visual opposition to every other theme.**

### Font
**Bungee Shade** (David Jonathan Ross, OFL) — a 3D-blocked display face with strong outlines, evoking the chunky shaded lettering on 1960s rock posters without trying to faithfully reproduce Wes Wilson's actually-illegible hand. Bungee Shade lands "psychedelic-adjacent" with full readability preserved, which is the right trade-off for a literary clock — illegibility is non-negotiable in this rotation.
- Alternatively: **Rubik Mono One** (Hubert and Fischer, OFL) — chunkier and even bolder, single weight, paired with a contrasting italic body for the actual quote
- Body: Bungee Shade Regular (oversized, shaded — display-as-body, same approach as `comic` / `atomic`)
- Matched phrase: Bungee Shade Regular with the blue accent doing the differentiation work (Bungee ships only Regular, like Bangers / Atomic Age — the bichrome-on-single-weight trick is established)
- Fallback: Bungee → Bangers → Atomic Age → DejaVu Sans Bold → Playfair Bold

### Border / decoration — `draw_fillmore_border`
The signature element: **organic blob panels** in two corners, plus a third saturated-colour element.
1. **Blob panel** in the top-left corner: a free-form organic shape (~140×100 px) painted as a filled polygon approximating a melted-amoeba silhouette (Bézier approximation via the n-point polygon trick, same as Mucha's vines / atomic's orbits). Filled in **green** (Spectra-6 native — a pure-colour panel that *contrasts* with the yellow ground rather than synthesising a mixed colour). A small filled red star inside the green blob — single-glyph paint, no synthesis.
2. **Blob panel** in the bottom-right corner: a mirror-image free-form polygon filled in **blue** (Spectra-6 native), with a small filled yellow circle inside.
3. **Concentric ring decoration** in the upper-right, between the green blob and the body text: three concentric circle outlines painted in red, sized to suggest the "vibration" / "expansion" wavefronts that radiate from focal points in real Fillmore posters. Filled circles instead of ellipses, evenly spaced.
4. No outer frame — the composition is *grounded by the blobs* rather than by a containing rectangle, which is exactly how real Fillmore posters compose. Each blob is positioned to *not* overlap the y=14–29 debug-banner band (top-left blob occupies y=40–140, well below; bottom-right is by definition out of the way), so no entry in `_DEBUG_LABEL_RIGHT_INSET` is needed.

### Saturation
`THEME_SATURATION["fillmore"] = 0.7` — yellow-ground theme with multiple saturated accents, follows `comic` and `risograph` precedent.

### Why it fills a gap
- **First theme to use all six Spectra-6 inks at once**, deliberately. Every other theme picks a 3- or 4-ink subset; `fillmore` is the visual maximalist.
- Fills the 1960s psychedelic historical register, which currently has zero representation.
- Yellow ground + saturated red body + saturated blue accent is a palette combination *no* current theme uses — `comic` is the only yellow-ground theme but pairs it with black body and red accent.
- Organic blob shapes are a new decoration vocabulary distinct from `mucha`'s vines (which are linear / curvilinear): blobs are *filled organic shapes*, vines are *organic strokes*. The two together broaden organic decoration into two complementary sub-modes.
- Demonstrates that LitClock's renderer can express counter-cultural visual energy without compromising legibility — a useful proof point for future maximalist themes.

---

## Summary table

| Proposed theme | Register | Page bg | Body | Accent | Signature novelty |
|---|---|---|---|---|---|
| `swiss` | Swiss International, 1950s–60s modernist | white | black | red | First borderless theme — austerity by subtraction |
| `herbarium` | 19th-century pressed-plant specimen sheet | cream wash | black | olive (Y+G) | Opens olive/sage colour territory for an entire theme; layered Layer-0 + corner-leaf + balanced-label composition |
| `mucha` | 1900s Art Nouveau (Mucha, Vienna Secession) | cream wash | maroon (R+K) | forest-teal 3-ink or cyan 2-ink | First all-curve / organic border; first synthesised-colour body text |
| `fillmore` | 1966–68 psychedelic concert poster | yellow | red | blue | First theme to use all six Spectra-6 natives simultaneously; first blob-panel decoration |

Together these four widen the rotation along four distinct axes:
- **Austere ↔ saturated**: `swiss` and `fillmore` are visual opposites
- **Geometric ↔ organic**: `swiss` (rectilinear hairline) → `mucha` (curvilinear vines) → `fillmore` (organic blobs)
- **Historical ↔ contemporary feel**: `herbarium` and `mucha` are anchored to specific historical periods, `swiss` is mid-century with continuing relevance, `fillmore` is the most period-specific but also the most visually loud
- **Green colour territory ↔ everywhere else**: `herbarium`'s olive-body identity finally claims the green axis the existing 24 only borrow from

## Critical files (for follow-up implementation, if approved)

- `render_quote.py` — add `THEMES` entries, add to `THEME_ORDER` tuple (with explicit position decisions: probably insert `swiss` after `default`/`dark`, `herbarium` near `scholar`, `mucha` near `illuminated`, `fillmore` near `comic`), add `THEME_FONTS` entries, add four border-painter functions, wire into `_BORDER_PAINTERS` dict, extend `_draw_text_body` per-theme switch for the synthesised-colour matched phrases / body
- `display_inky.py` — add `THEME_SATURATION` entries (the `test_every_render_theme_has_saturation` test will fail until each is wired)
- `run_clock.py` — add `swiss` / `herbarium` / `mucha` / `fillmore` to the `--theme` argparse `choices=` list (the `TestActionThemeCycle::test_cli_theme_choices_match_theme_order` test pins this sync)
- `fonts/` — add `fonts/inter/` (swiss), optionally `fonts/cormorant-garamond/` + `fonts/berkshire-swash/` (mucha), `fonts/bungee/` (fillmore); each subdir ships its own OFL.txt / LICENSE.txt
- `spectra6_color_recipes.md` — add `herbarium` to the "olive" recipe row's *In use* column; add `mucha` to maroon body + (if 3-ink) forest-teal rows; cross-check `fillmore` uses no synthesised colour at all (deliberately)
- `tests/golden/renderer/` — regenerate goldens via `UPDATE_RENDER_GOLDEN=1 pytest tests/test_render_golden.py` after the renderer changes are in
- `CLAUDE.md` — extend the long `THEMES` paragraph with four-theme entries describing each border, palette, and font fallback chain (matches the established documentation style for `lcars`, `chanbara`, `placard`, etc.)

## Verification

A proposal-stage plan only needs to verify *that the proposal hangs together*, not that it renders correctly (no code is being written). To validate:

1. **Cross-check** each proposed palette against `spectra6_color_recipes.md` — every two-ink synthesis named here (olive, maroon, tangerine, cream, sage, cyan) already has an established recipe; only `mucha`'s forest-teal would be a genuinely new implementation, and the cyan fallback is offered as the safer alternative.
2. **Cross-check** font licensing — all four proposed font families ship under OFL or Apache 2 (Inter / Cormorant Garamond / Berkshire Swash / Bungee / Rubik Mono One are OFL; the bundled IM Fell English reused by `herbarium` is already OFL). No proprietary fonts are required.
3. **Cross-check** distinctness against existing themes — none of the four duplicate an existing theme's register, palette, or font family. `swiss` shares Inter's grotesque-sans territory with `blueprint`'s Archivo but is borderless; `herbarium` shares IM Fell with `alchemy` / `grimoire` but italic + olive accent + specimen-sheet decoration differs entirely; `mucha`'s Cormorant Garamond doesn't appear in any existing theme; `fillmore`'s Bungee Shade is new.
4. **Confirm with user**: if the proposals are accepted, the implementation-plan PR would then sequence the four themes (probably one per PR or one combined PR with separate commits), starting with `swiss` (simplest — palette and font reuse existing recipes, only a minimal border painter needed) and ending with `mucha` (most complex — likely 3-ink text dithering primitive extension).
