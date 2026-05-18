# Spectra 6 Color Recipes

Reference catalogue for synthesising colours outside the native 6-ink Spectra 6 palette by interleaving two (or three) inks on a stipple pattern. Pulled together from the Pimoroni forum, [Frans-Willem/epd-dither](https://github.com/Frans-Willem/epd-dither), [Utzel-Butzel/epdoptimize](https://github.com/Utzel-Butzel/epdoptimize), [Toon-nooT/PhotoPainter-E-Ink-Spectra-6-image-converter](https://github.com/Toon-nooT/PhotoPainter-E-Ink-Spectra-6-image-converter), and the [myembeddedstuff "Beyond 6 Colors" article](https://myembeddedstuff.com/e-ink-spectra-6-color). Cross-referenced against the [Pimoroni Buccaneers thread on calibrated RGB values](https://forums.pimoroni.com/t/what-rgb-colors-are-you-using-for-the-colors-on-the-impression-spectra-6/27942) and the [einkframe.com Spectra 6 gamut deep-dive](https://www.einkframe.com/2025/11/26/spectra-6-color-gamut-part1/).

## What this document is

- **Audience.** Anyone adding a new theme to `render_quote.py` who needs a colour outside the 6-ink palette, or any operator curious about how the existing themes produce orange / mint / sky-blue.
- **Scope.** Recipes the codebase uses today, plus a vetted superset of recipes from upstream Spectra 6 dithering research that are reachable with the existing `draw_text_dithered` / `BAYER_4x4` primitives. Three-ink recipes are documented as forward references — they need a new primitive (`_three_way_bayer`) before a theme can pull from them.
- **Not in scope.** Photographic image dithering (Floyd–Steinberg, Atkinson, Stucki, error-diffusion kernels). LitClock paints glyphs and geometric ornaments, so we use ordered patterns. For photo work see [Frans-Willem/epd-dither](https://github.com/Frans-Willem/epd-dither) or [Toon-nooT's converter](https://github.com/Toon-nooT/PhotoPainter-E-Ink-Spectra-6-image-converter).

## The 6 native inks

Two sets of RGB values matter, and confusing them is the most common source of "the recipe reads wrong on the panel":

- The **saturated palette identifiers** in `render_quote.SPECTRA6` (`(255,0,0)`, `(0,0,255)`, …) are *labels*. `snap_image_to_palette` quantises every output pixel to one of these six triples before handing the PNG to the panel. They are not the colours the panel actually displays.
- The **calibrated panel display values** are the colour the inks actually reflect under ambient light. Two independent calibrations agree closely:

| Ink | `SPECTRA6` palette ID | epdoptimize calibration | Pimoroni forum / Toon-nooT calibration |
|---|---|---|---|
| White | (255, 255, 255) | `#B9C7C9` | — (off-white with slight cyan tint) |
| Black | (0, 0, 0) | `#1F2226` | — |
| Red | (255, 0, 0) | `#62201E` | `#A02020` |
| Yellow | (255, 255, 0) | `#C1BB1E` | `#F0E050` |
| Blue | (0, 0, 255) | `#233F8E` | `#5080B8` |
| Green | (0, 255, 0) | `#35563A` | `#608050` |

The two calibrations differ because they measured different panels (Spectra 6 panels drift unit-to-unit) and rendered them under different ambient light. Use them as a **guide**, not a spec.

Two practical takeaways from these values:

1. **Blue and green are much darker than the palette labels suggest.** A "50% blue + 50% white" recipe doesn't read as the sky-blue you'd predict from `#5080B8 + #FFFFFF` on a monitor — it reads as a *deeper* sky-blue because the panel's blue is already dim. Same for green-on-white → mint.
2. **Yellow is significantly brighter than red.** The classic textbook "50% red + 50% yellow = orange" 1×1 checkerboard *consistently* reads as washed-out amber, not orange, on a Spectra 6 panel. Bias toward red (the `deco` 5/8 : 3/8 recipe) to land on tangerine. This luminance asymmetry is the rule, not the exception — any time you mix an ink with white, or yellow with anything else, expect the brighter ink to dominate perceptually and bias the ratio toward the dimmer one.

## The octahedron color model

From [Frans-Willem/epd-dither](https://github.com/Frans-Willem/epd-dither):

- Treat RGB space as a regular octahedron with **white at the top vertex, black at the bottom**, and **red / yellow / green / blue** at the four equatorial vertices.
- Any colour inside the solid is a **barycentric mix of ≤4 vertices**.
- Examples from the upstream README:
  - **Gray** = 50% black + 50% white
  - **Orange** = 50% red + 50% yellow (but see the bias warning above)
  - **Light orange** = 40% red + 40% yellow + 20% white

For glyph and geometric work the pattern primitives below are the practical realisation of the model. For photographic decomposition use `epd-dither`'s `OctahedronDecomposer`, which picks ≤4 vertices per pixel and feeds the weighted result into Bayer / blue noise / Floyd–Steinberg.

## Pattern primitives in `render_quote.py`

`draw_text_dithered(image, xy, text, font, dark, light, light_density=0.5)` selects one of three patterns based on `light_density`. `BAYER_4x4` is the shared 4×4 ordered matrix (values 0..15) used by both `draw_text_dithered` and the border painters (`draw_deco_border`, `draw_glacier_border`, `draw_placard_border`).

| Pattern | "Light" density | Trigger | Visual signature |
|---|---|---|---|
| Sparse 1-in-4 (`x%2 == 0 and y%2 == 0`) | 25% | `light_density <= 0.25` | Subtle wash of "light" over dominant "dark" |
| 4×4 ordered Bayer (`BAYER_4x4[y%4][x%4] < round(d*16)`) | any `d ∈ (0.25, 0.5)` | `0.25 < light_density < 0.5` | Biased mix dispersed across a 4×4 tile |
| 1×1 checkerboard (`(x+y) & 1`) | 50% | `light_density >= 0.5` | Equal-weight midpoint of two inks |

For ratios above 50%, swap `dark`/`light` and pass the complementary density (e.g. "5/8 yellow + 3/8 red" = `dark=yellow, light=red, light_density=0.375`).

## Two-ink recipes

Single combined catalogue: recipes the codebase pulls today plus the unused-but-reachable recipes upstream literature consistently recommends. The **In use** column flags themes that currently invoke each recipe; rows marked "not in use" are forward references for future themes — they're listed because someone considering an ocean / winter / parchment / forest theme will want a starting point rather than re-deriving the recipe.

| Synthesised colour | Recipe | `draw_text_dithered` call | In use | Source |
|---|---|---|---|---|
| Tangerine / warm orange | red + yellow at 5/8 : 3/8 | `dark=red, light=yellow, light_density=0.375` | `deco` (matched phrase + border post-pass); `atomic` (mid-edge starburst rays — painted in red as a sentinel, then a per-starburst bbox post-pass Bayer-flips ~3/8 of the red pixels to yellow at threshold 6/16 so the rays read as the canonical mid-century atomic-spark warmth, while the atom-symbol orbits stay solid red for ray-vs-orbit contrast); `alchemy` (element triangle 🜂 Fire at the BL corner — same R+Y Bayer recipe for warm-orange flame); `grimoire` (☉ Sun mid-edge sigil — bbox-post-passed for the solar gold the alchemists called *aurum*); `lcars` (top + bottom elbow bars, quarter-circle elbows, and one of the six stacked rail blocks — the iconic Okudagram orange of every Star Trek: TNG / DS9 / Voyager console; same red-sentinel-then-bbox-Bayer-post-pass approach the `deco` border uses, so a future combined render would land both decorations on identical tangerine); `mucha` (corner-vine berry tips — each berry painted as a red sentinel and bbox-post-passed through `BAYER_4x4 < 6/16` to flip ~3/8 of the red pixels to yellow, reading as warm-spark tangerine at each vine's stem tip, the bright Belle-Époque counterpoint to the maroon stem and olive trefoil leaves) | LitClock / Beyond-6-Colors literature |
| Pure orange / amber | red + yellow at 1/2 : 1/2 | `dark=red, light=yellow` (default density) | — | Frans-Willem README. *Caveat:* reads as washed-out amber on the panel (yellow's higher luminance dominates). The deco theme historically used this recipe before being switched to the tangerine variant above; documented here so future authors don't repeat the same fix. |
| Pink / coral | red + white at 1/2 : 1/2 | `dark=red, light=white` | `placard` (thumbtack corner accents — weathered hand-painted red); `chalkboard` (eraser-smudge dots along the bottom inner edge — leftover pink eraser-stub residue); `lcars` (the "advisory" pink rail block, painted as a half-rounded rectangle in red as a sentinel and then bbox-post-passed to flip half of those red pixels to white per `(x+y)&1` parity — the soft salmon button colour that distinguished "informational" rail panels from the "critical" red ones in the show's UI design) | LitClock |
| Candlelit red | red + white at 3/4 : 1/4 | `dark=red, light=white, light_density=0.25` | `grimoire` (matched phrase); `gothic` (matched phrase — shares the candlelit-rubric signature with grimoire, the complementary-polarity blackletter sister) | LitClock |
| Mint | green + white at 1/2 : 1/2 | `dark=green, light=white` | `nightvision` (body / attribution / ornament); `marker` (left mid-edge dot — green sentinel post-passed to white at 50/50 `(x+y)&1` parity for a Stabilo-style highlighter wash sitting alongside the multi-colour marker palette) | LitClock / Beyond-6-Colors |
| Sage / muted green | green + white at 1/4 : 3/4 (inverted) | `dark=white, light=green, light_density=0.25` | `nightvision` (scanlines — bbox-post-pass on the scanline pixels flips ~25% of the painted green to white per `BAYER_4x4 < 4`, so the scanlines read as ambient ground glow rather than crisp bright-green CRT lines without crowding the body text) | Complement to mint; useful for a herbarium / botanical theme that wants a softer green. |
| Cyan | green + blue at 1/2 : 1/2 | `dark=green, light=blue` | `glacier` (matched phrase — body green fill rerouted in `_draw_text_body` to a 50/50 G+B stipple, reads as aurora teal that completes the cool palette gradient `body-blue → matched-cyan → ornament-sky`); `mucha` (matched phrase + outer rule decoration — matched-phrase green sentinel rerouted in `_draw_text_body` to the same 50/50 G+B stipple as glacier, giving the cool teal accent that contrasts with the maroon body; the border's inset-18 rule is painted in green sentinel and perimeter-post-passed to flip half to blue per `(x+y)&1` parity so the rule and matched phrase share one cyan tone) | Beyond-6-Colors / LitClock. |
| Sky blue | blue + white at 1/2 : 1/2 | `dark=blue, light=white` | `glacier` (frost-crystal diagonal-shard tip post-pass — sunlight catching the ice surface); `grimoire` (Moon ☽ mid-edge sigil — the helper now paints its outer disc in BLUE as a sentinel, and a bbox post-pass flips half of those blue pixels to white per `(x+y)&1` parity so the crescent reads as the cool argent / silver-blue of alchemical lunar work) | LitClock / Beyond-6-Colors |
| Purple / violet | red + blue at 1/2 : 1/2 | `dark=red, light=blue` | `alchemy` (matched phrase + 🜁 Air element triangle); `grimoire` (♀ Venus mid-edge sigil); `illuminated` (matched phrase — Tyrian purple of the medieval scriptorium); `risograph` (matched phrase — authentic riso double-pass overprint where the red and blue plates physically wash into purple; preserves the theme's no-black-ink invariant by construction); `marker` (right mid-edge dot — "second marker dragged over the first") | LitClock / Beyond-6-Colors |
| Brown / sepia | red + green at 1/2 : 1/2 | `dark=red, light=green` | `saloon` (foxing speckles via `(px+py)&1` parity over `_SALOON_FOXING`; outer wanted-poster frame's 3 px rule painted in red, then the 4 edge strips are perimeter-post-passed to flip half of the painted pixels to green per `(x+y)&1` parity so the rule reads as rusted iron of a 19th-century wood-engraved cornerpiece frame); `placard` (outer sign-painter's frame — painted as a red 1 px rule, then a perimeter post-pass flips half of the pixels to green per `(x+y)&1` parity so the rule reads as weathered sandwich-board wood rather than fire-engine ink); `dispatch` (every other tractor-feed perforation pair flips from solid black to a red sentinel, then a per-perforation bbox post-pass flips half of those red pixels to green per parity — reads as "carbon-paper bleed", the rust-brown oxidation continuous-feed forms accumulate where the carbon backing meets the sprocket holes); `newsprint` (Layer 0 foxing speckles — 1 red + 1 green pixel per 4×4 Bayer tile at cell values 2 and 3, diagonally ~2.8 px apart, blends at panel distance into pale rust-brown lignin oxidation alongside the existing 12.5% black halftone) | LitClock / Beyond-6-Colors |
| Dark green / forest | green + black at 1/2 : 1/2 | `dark=green, light=black` | `herbarium` (matched phrase — body green sentinel rerouted in `_draw_text_body` to a 50/50 G+K stipple, reading as the dark-pressed plant material a real archival specimen develops over time; contrasts strongly with the cream Y+W Layer-0 wash and visually distinct from the Y+G olive used by the corner pressed-leaf border graphic) | LitClock — the first claim of this previously "not in use / forward reference" recipe; herbarium needed a green-family matched-phrase tone that wouldn't average into the yellow-tinted cream ground the way Y+G olive would have. |
| Olive | yellow + green at 1/2 : 1/2 | `dark=yellow, light=green` | `roman` (laurel-sprig leaves on the bottom-centre corona triumphalis — each leaf is painted as a yellow ellipse then a per-leaf bbox post-pass flips half of the yellow pixels to green per `(x+y)&1` parity, reading as the canonical olive-green Mediterranean laurel a real Roman victory wreath was plaited from); `alchemy` (element triangle 🜃 Earth at the TL corner of the transmutation circle — painted in yellow and bbox-post-passed to flip half to green for the canonical alchemical "green earth" pigment); `herbarium` (corner pressed-leaf silhouette + stem + vein decorations — each leaf is painted as a yellow ellipse and bbox-post-passed to flip half the pixels to green per `(x+y)&1` parity, reading as the canonical dried-leaf olive a real pressed-and-aged specimen develops); `mucha` (trefoil leaf clusters on the corner vine ornaments — each leaf painted as a yellow ellipse then a per-vine bbox post-pass flips half to green per parity, reading as Art Nouveau leaf-green against the maroon stem) | Frans-Willem; LitClock. |
| Lime | yellow + green at 5/8 : 3/8 | `dark=yellow, light=green, light_density=0.375` | `nightvision` (matched phrase — yellow-biased green stipple via the same `light_density=0.375` Bayer threshold deco's tangerine uses, reads as the brighter neon "tactical readout" glow of a real HUD warning rather than the flat alert-flag yellow it was previously) | Mirrors the tangerine recipe (yellow-biased to keep the colour bright). |
| Cream | yellow + white at 1/2 : 1/2 | `dark=yellow, light=white` | `dispatch` (Layer 0 ground wash); `gothic` (mid-edge border diamonds — candle-flicker warmth); `illuminated` (Layer 0 ground wash — aged vellum); `deco` (rising-sun fan inner rays — a 2-tone post-pass on the rays' inner band flips remaining red pixels to white per parity after the tangerine pass, so the inner rays read as bright Y+W cream fading back into the R+Y tangerine at the tips, simulating a real sunburst's central glow); `herbarium` (Layer 0 ground wash — aged-paper specimen sheet tone); `mucha` (Layer 0 ground wash — Belle-Époque ivory poster ground) | Warm off-white for parchment / vellum themes. |
| Gray (50/50) | black + white at 1/2 : 1/2 | `dark=black, light=white` | — | Frans-Willem. The renderer typically uses solid black or solid white directly rather than gray stipple, but listed here for completeness — a forward reference for an "engineering monochrome" theme that wants a softer body fill. |

## Three-ink recipes

**`render_quote._fill_swatch_stipple_3way`** is the implemented primitive — partitions the 4×4 Bayer tile into three regions by threshold (cells `< round(density_a * 16)` → ink A, cells `< round((density_a + density_b) * 16)` → ink B, the remainder → ink C). The implicit third density is `1 − density_a − density_b`. It powers the diags theme's 3-ink swatch band (`_DIAGS_TRIPLE_SWATCHES`) so an operator can hold the panel and verify whether (e.g.) the 1/3-each lavender or the white-heavy lilac actually reads as the named pastel at panel distance.

`draw_text_dithered` itself (the glyph-mask painter) still operates on two inks only. A theme that wants to paint *text* in a three-ink recipe — rather than a swatch fill or decorative graphic — needs to extend `draw_text_dithered` with a similar 3-way Bayer branch, or composite via two `draw_text_dithered` passes onto a `_fill_swatch_stipple_3way`-painted background. For decorative graphics and swatch fills the primitive below is the entry point today.

Recipes are grouped by *which pole of the octahedron* the third ink contributes — pastels (white-lifted), deep tones (black-darkened), and chromatic mixes (no W/K, all three inks equatorial). The luminance-asymmetry rule from the two-ink section still applies: when one of the three inks is yellow or white, bias the cell-count partition away from it or the brighter ink will dominate.

### Pastels (3-ink with white) — soft daytime palette

| Synthesised colour | Mix | Source |
|---|---|---|
| Light orange | red + yellow + white @ 40 / 40 / 20 | [Frans-Willem README example](https://github.com/Frans-Willem/epd-dither) |
| Salmon | red + yellow + white @ 1/3 each | Octahedron interpolation between coral and tangerine |
| Peach / apricot | red + yellow + white @ 30 / 50 / 20 | Yellow-leaning sibling of salmon — warmer, less coral |
| Lavender | red + blue + white @ 1/3 each | Octahedron interpolation between purple and sky-blue; in use by `risograph` (shifted-accent registration crosses at the four corners — each cross painted in an off-palette sentinel then bbox-post-passed through a 3-way 4×4 Bayer partition with cells 0-4 → red, 5-9 → blue, 10-15 → white (~1/3 each); reads as the paler "overprint" register-mark tone real risograph print test sheets develop where two plates wash together; preserves the theme's no-black-ink invariant by construction) AND `lcars` (the topmost and bottommost rail blocks on the LCARS sidebar — each block painted as a half-rounded rectangle in the same off-palette sentinel `(1, 1, 1)`, then a per-block 3-way Bayer post-pass partitions the painted pixels into ~1/3 red / 1/3 blue / 1/3 white. The lavender pastel reads as the signature non-Spectra-6 Okudagram accent — every Star Trek: TNG console panel had at least one lavender block in its sidebar palette) |
| Lilac / pale violet | red + blue + white @ 25 / 25 / 50 | Paler than lavender — heavier white lift |
| Seafoam / aqua | green + blue + white @ 40 / 30 / 30 | The cyan equivalent of sky-blue. Future ocean / spa theme. |
| Khaki / pale olive | yellow + green + white @ 40 / 30 / 30 | Softer green than mint. Future herbarium / botanical theme. |
| Beige / tan | red + yellow + white @ 25 / 25 / 50 | Lighter parchment than cream |

### Deep tones (3-ink with black) — rich nighttime palette

| Synthesised colour | Mix | Source |
|---|---|---|
| Plum | red + blue + black @ 1/3 each | `illuminated` (corner cabochon "jewels" — each filled circle painted in an off-palette sentinel then bbox-post-passed through a 3-way 4×4 Bayer partition with cells 0-4 → red, 5-9 → blue, 10-15 → black (~1/3 each), reading as the wine-dark lapis cabochons inset on the most precious medieval bindings). Deeper than the existing `alchemy` purple. |
| Print sepia | red + yellow + black @ 40 / 40 / 20 | **More authentic than the existing red+green brown** the `saloon` foxing uses. Real archival sepia is yellow-brown, not red-green brown — worth flagging as a forward path if a future "old-photograph" theme wants to upgrade from the 2-ink approximation. |
| Maroon / burgundy | red + black @ 1/2 : 1/2 (2-ink) | 2-ink in practice; in use by `dispatch` (rubber-stamp imprint); `gothic` (corner quatrefoil lobes — iron-aged cathedral tracery); `chanbara` (rising-sun disc rim radial gradient + artist's-chop seal); `grimoire` (♂ Mars mid-edge sigil — oxblood iron); `blueprint` (matched phrase red fill rerouted in `_draw_text_body` to a 50/50 R+K stipple, reading as a darker red pencil pressed firmly into the drafting paper); `scholar` (matched phrase — same R+K path as blueprint, reading as aged red-lead of an academic-journal annotation against the Bitter slab serif body); `mucha` (body fill + corner-vine stems — the **first theme to use a synthesised colour as its primary body fill** rather than just an accent: the `text` THEMES slot holds the red sentinel that `_draw_text_body` routes through the same 50/50 R+K stipple as blueprint/scholar's matched phrase, reading as the deep wine / oxblood the period's poster lettering actually used; vine-stem ornaments on the corner decorations use the same recipe so body and ornament share one maroon); `fillmore` (body fill — same R+K stipple as mucha, subdues the otherwise-loud pure-red-on-saturated-yellow body without losing the psychedelic identity. Real Fillmore posters' red ink ended up darker once printed onto yellow stock anyway, so the perceived hue is period-authentic; the matched-phrase blue and corner-blob primaries stay solid so all six Spectra-6 natives are still visible) — listed here because it's the "with black" sibling of the pastel set above; useful for a leather-bound / oxblood theme |
| Navy | blue + black @ 1/2 : 1/2 (2-ink) | 2-ink in practice; in use by `bauhaus` (matched phrase blue fill rerouted in `_draw_text_body` to a 50/50 B+K stipple, reading as a tighter-contrast deeper-blue against the newly-yellow BL corner triangle in the border) — deeper than the panel's already-dim native blue, for a midnight theme |

(The maroon and navy rows are 2-ink and reachable via `draw_text_dithered` today; documented here so the K-darkened palette feels complete, not because they need a new primitive.)

### Chromatic mixes (3-ink, no white or black)

| Synthesised colour | Mix | Source |
|---|---|---|
| Burnt orange / terracotta | red + yellow + green @ 50 / 40 / 10 | The green dulls tangerine into terracotta. Future desert / canyon theme. |
| Forest-teal | green + blue + yellow @ 40 / 40 / 20 | Cyan dragged toward olive — denser than seafoam, for a deep-forest theme. |

`TestFillSwatchStipple3way::test_partition_ratios` (in `tests/test_render_quote.py`) sweeps the five density splits used by the diags swatch band and pins each region's pixel count within `±2%` tolerance on a fixed 32×32 sample tile — extend it when adding a new recipe whose density split isn't already covered.

## Four-ink recipes — narrower edge

**Also not yet supported.** A `_four_way_bayer` helper (4/4/4/4 cell partition) is the natural extension of the three-ink primitive, but at four inks per 16-cell tile the per-ink density is low enough that the eye starts reading the result as *texture* rather than as a uniform colour mix at close viewing distance (under ~1 m). At LitClock's intended viewing distance (1–3 m) the mix still reads cleanly. Use sparingly — the only recipes worth the implementation cost are the ones a 3-ink mix can't approximate:

| Synthesised colour | Mix | Source |
|---|---|---|
| Warm grey / taupe | red + yellow + white + black @ ~25 each | More interesting than pure black+white gray — picks up a subtle warm cast from the R+Y pair |
| Cool slate | blue + green + white + black @ ~25 each | Cool counterpart to taupe — picks up a subtle cyan cast |

**Don't go past 4 inks.** The octahedron literature treats 5- and 6-vertex barycentric mixes as edge cases — `OctahedronDecomposer` (in `epd-dither`) explicitly limits itself to ≤4 vertices per pixel, and `epdoptimize`'s palette-distance model picks similarly small support sets. Past 4, per-cell density drops below 4 / 16 and the mix degenerates into either visible texture or muddy mid-grey.

## Designing a new themed accent

1. **Pick the target.** Sketch it as a sum of ≤2 nearby Spectra 6 inks. Use the **calibrated** values when predicting perceived hue — predicting from saturated palette IDs (`(255,0,0)` etc.) is the most common mistake. If the target isn't in the catalogue above, pick the two natives that bracket it on the colour wheel and look at where it sits inside the octahedron.
2. **Estimate the dominance ratio.** If the two inks have asymmetric luminance (yellow >> red, white >> any chroma, black << any chroma), **bias toward the less luminous ink** so the perceived hue lands on the target rather than on the brighter ink. The deco fix is the canonical example: 50/50 red+yellow looked amber, 5/8 red + 3/8 yellow reads as tangerine.
3. **Choose the pattern** from the patterns table. Start at 50/50 if you don't have a strong prior. Move to a 4×4 biased Bayer if 50/50 reads washed-out at panel distance.
4. **Wire it in.**
   - *Body text accents:* extend `_draw_text_body`'s per-theme switch with another `elif theme == "<name>" and fill == SPECTRA6[<dominant>]: draw_text_dithered(...)`.
   - *Decorative graphics:* paint the shape in the dominant ink, then do a `BAYER_4x4[y%4][x%4] < threshold and pixels[x, y] == dominant` post-pass to flip the minority pixels to the lighter ink (`draw_deco_border`'s final pass is the reference).
5. **Saturation tier.** Bump `display_inky.THEME_SATURATION["<theme>"]` to `0.7` if the accent needs to stay punchy against a non-white ground; `0.5` is the gentler tier for solid red on white themes (the `deco` recipe deliberately stays at `0.5` because the red-biased Bayer already corrects the perceived hue without a saturation bump).
6. **Test.** Add a `TestDrawTextDithered`-style ratio assertion if the recipe is novel; add the theme to the renderer golden suite (`tests/test_render_golden.py`) if you want a visual regression fence.

## Pattern selection cheat sheet

Distilled from the [myembeddedstuff "Beyond 6 Colors" article](https://myembeddedstuff.com/e-ink-spectra-6-color) and [Toon-nooT's converter README](https://github.com/Toon-nooT/PhotoPainter-E-Ink-Spectra-6-image-converter):

- **1×1 checkerboard (50/50)** — the workhorse for glyph fills and geometric ornaments. Best balance of colour blending and edge clarity. Default unless you have a luminance-asymmetry reason to bias.
- **4×4 ordered Bayer** — for biased ratios (3/8, 5/8, etc.). Disperses the bias across a tile so the eye doesn't read the individual pixels at panel viewing distance.
- **Sparse 1-in-4** — for "subtle wash" effects: candlelit red, faint stippling on otherwise-solid blocks. The minority ink reads as texture, not as a colour mix.
- **Error diffusion (Floyd–Steinberg / Atkinson)** — out of scope for LitClock's ordered-pattern rendering; mentioned only in case a future theme wants to dither a photographic source asset. Atkinson is preferred for portraits (more localised, visually pleasing, less pattern repetition); Floyd–Steinberg for art (uniform noise, more colour-correct via global error diffusion).

## How this doc relates to CLAUDE.md

The "Synthesising colours outside the Spectra 6 palette" section in [CLAUDE.md](CLAUDE.md) keeps a focused table of the **in-use** recipes — the source-of-truth quick reference for someone reading `render_quote.py` who needs to know which themes pull which recipe.

This document is the **catalogue and playbook**: calibrated panel values, the octahedron model, unused-but-reachable recipes, three-ink forward references, and the step-by-step authoring guidance. The two are intentionally complementary; cross-link from either entry point.

## Sources

- [Pimoroni Buccaneers forum: "What rgb colors are you using for the colors on the Impression (Spectra 6)?"](https://forums.pimoroni.com/t/what-rgb-colors-are-you-using-for-the-colors-on-the-impression-spectra-6/27942) — community-calibrated palette (red `#a02020`, yellow `#f0e050`, green `#608050`, blue `#5080b8`).
- [Utzel-Butzel/epdoptimize](https://github.com/Utzel-Butzel/epdoptimize) — JavaScript library with the calibrated `aitjcizeSpectra6Palette` used in the panel-display column above; supports error diffusion (Floyd–Steinberg, Atkinson, Stucki), ordered (Bayer), and random dithering modes.
- [Frans-Willem/epd-dither](https://github.com/Frans-Willem/epd-dither) — Rust library defining the octahedron decomposition model; `docs/decomposition.md` covers the per-pixel barycentric weighting and the `OctahedronDecomposer` strategy selection (Closest / Furthest / Average / Axis).
- [Toon-nooT/PhotoPainter-E-Ink-Spectra-6-image-converter](https://github.com/Toon-nooT/PhotoPainter-E-Ink-Spectra-6-image-converter) — uses the same `#a02020` / `#5080b8` calibration; recommends Atkinson for portraits, Floyd–Steinberg for art.
- [myembeddedstuff "Beyond 6 Colors: Exploring Dithering on Spectra 6-color E-Ink Displays"](https://myembeddedstuff.com/e-ink-spectra-6-color) — 50% checkerboard is the most reliable choice for sharp multi-tone shapes; expands the palette to ~13 usable colours.
- [einkframe.com Spectra 6 deep-dive (Part 1)](https://www.einkframe.com/2025/11/26/spectra-6-color-gamut-part1/) — overview of the panel's gamut.
- [einkframe.com Spectra 6 limitations](https://www.einkframe.com/2025/11/13/spectra-6-color-limitations/) — summary of the Reddit discussion of common pitfalls.
- [Pimoroni Inky Impression 7.3" (2025 Edition) product page](https://shop.pimoroni.com/en-us/products/inky-impression) — the hardware LitClock targets.
- [Pimoroni: Getting Started with Inky Impression](https://learn.pimoroni.com/article/getting-started-with-inky-impression) — the manufacturer's quickstart, including the built-in dithering pass.
