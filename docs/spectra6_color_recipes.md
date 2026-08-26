# Spectra 6 Color Recipes

Reference catalogue for synthesising colours outside the native 6-ink Spectra 6 palette by interleaving two (or three) inks on a stipple pattern. Pulled together from the Pimoroni forum, [Frans-Willem/epd-dither](https://github.com/Frans-Willem/epd-dither), [Utzel-Butzel/epdoptimize](https://github.com/Utzel-Butzel/epdoptimize), [Toon-nooT/PhotoPainter-E-Ink-Spectra-6-image-converter](https://github.com/Toon-nooT/PhotoPainter-E-Ink-Spectra-6-image-converter), and the [myembeddedstuff "Beyond 6 Colors" article](https://myembeddedstuff.com/e-ink-spectra-6-color). Cross-referenced against the [Pimoroni Buccaneers thread on calibrated RGB values](https://forums.pimoroni.com/t/what-rgb-colors-are-you-using-for-the-colors-on-the-impression-spectra-6/27942) and the [einkframe.com Spectra 6 gamut deep-dive](https://www.einkframe.com/2025/11/26/spectra-6-color-gamut-part1/).

## What this document is

- **Audience.** Anyone adding a new theme to `render_quote.py` who needs a colour outside the 6-ink palette, or any operator curious about how the existing themes produce orange / mint / sky-blue.
- **Scope.** Recipes the codebase uses today, plus a vetted superset of recipes from upstream Spectra 6 dithering research that are reachable with the existing `draw_text_dithered` / `BAYER_4x4` primitives. Three-ink recipes are documented as forward references — they need a new primitive (`_three_way_bayer`) before a theme can pull from them.
- **Not in scope.** Photographic image dithering (Floyd–Steinberg, Atkinson, Stucki, error-diffusion kernels). Idle Hours paints glyphs and geometric ornaments, so we use ordered patterns. For photo work see [Frans-Willem/epd-dither](https://github.com/Frans-Willem/epd-dither) or [Toon-nooT's converter](https://github.com/Toon-nooT/PhotoPainter-E-Ink-Spectra-6-image-converter).

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

### Gradient density — the glow primitive

Every recipe above holds density **constant** across a region: two inks at a fixed ratio synthesise one flat colour. `paint_neon_mask(image, mask, core, glow, radius, gamma, cap, ground)` is the other axis — **one** ink at a *falling* density, so the eye integrates a gradient rather than a flat tone. Introduced for `izakaya`'s neon; reusable by anything that needs light to fall off (a lamp, a candle, a screen's spill, a halo).

It blurs an `"L"` glyph/shape mask (`ImageFilter.GaussianBlur`, the only use of `ImageFilter` in the renderer) and reads the blurred field back per pixel as the Bayer density. Four things about tuning it, all learned against the panel rather than derived:

| Knob | Rule | Failure mode if ignored |
|---|---|---|
| `radius` | Keep it comparable to the **stroke width**, never to the text block | A wide blur of a dense line of text *is* a solid rectangle, so the halo paints a uniform slab behind the whole line and reads as a coloured box |
| `gamma` | `> 1` (≈2.0–2.4) | The halo plateaus near the stroke and then cuts off at a visible edge instead of decaying over ~6–10 px |
| `cap` | Below solid (≈0.5–0.7) | The densest ring saturates and reads as a painted outline rather than as light |
| overall density | Tune against a **box-averaged** frame, not at 1:1 | Parameters that look correct pixel-for-pixel vanish once the eye averages them at 1–3 m; the near ring has to be denser than it looks right at pixel scale |

That last row is the one worth internalising for any recipe, not just this one: `img.resize((w//2, h//2), Image.BOX)` is a cheap stand-in for panel viewing distance, and it is the only honest way to judge a stipple. An image viewer's own resampling exaggerates a dither in the opposite direction — a 14%-blue wash can look like a solid blue slab on screen and correct on the panel.

Pass `core=None` to paint only the halo (for a shape drawn separately that just needs to glow), and `ground={...}` to restrict the halo to the ground inks so a later bloom cannot eat cores and decoration an earlier pass laid down.

### Tonal shading — lighting a colour field

A third axis, introduced for `pride`'s flag. Constant density synthesises a *colour*; falling density synthesises a *glow*; this synthesises **light falling on a surface** — a low-density overlay of the two achromatic inks (white on the faces turned toward the light, black on those turned away) laid over an arbitrary colour field, so a flat stripe reads as curved cloth. Peak densities stay well under 0.5: the overlay models light on a colour, and a face that reaches solid white reads as a blown highlight rather than a fold.

Two rules, both learned the hard way:

**Use one read of the tile, not two.** The obvious implementation picks the base ink by one Bayer read and then overwrites some of those pixels by a second read. It is wrong however the second read is phased, because a Bayer tile has a fixed cell count and *any* two reads of it are perfectly correlated — a shift merely selects a different fixed subset. Measured across all sixteen 4×4 shifts, the lit face of a 1:1 red+blue stripe came out at 0.27 or 0.73 red against a target of 0.50: the hue sliding toward blue on one face of every fold and toward red on the other, which is a colour shift wearing the costume of shading. Instead, resolve each pixel with a **single** read that partitions the tile three ways by rank — the lowest `round(density × cells)` cells take the lighting ink, and the remainder splits between the base inks in the base's own ratio. Worst-case drift falls to pure quantisation. A solid (single-ink) region is the degenerate case where the second base ink gets zero cells, so one branch covers both.

**Reach for `BAYER_8x8`, not `BAYER_4x4`.** A 4×4 tile offers 17 density levels, which is ample for a constant mix and far too coarse for a gradient: `pride`'s shading quantised to five steps across each fold and the step boundaries read as hard contour bands. The 8×8 tile (derived from the 4×4 by the standard recursive construction, so the two cannot drift apart) gives 65, and also lets a two-ink mix land on its exact ratio — 3/8 is 24/64 exactly, where 4×4 could only offer 6/16. **Any recipe dithering a smooth gradient rather than a constant mix should use the 8×8 tile.**

One more, shared with the glow primitive: if the shading rides a wave, the displacement and the lighting are **90° apart**. For a height field `h(x)`, the surface displaces by `h` but the light sees the *tilt* `dh/dx`, so the bright band belongs on the slope of a fold, not its crest. Put it on the crest and cloth reads as a corrugated roof.


### Chroma separation — synthesising a defect

A fourth axis, introduced for `vhs`. The three above all synthesise something the panel *should* be able to show and can't — a colour, a glow, a lit surface. `draw_text_chroma_shift(image, xy, text, font, core, left, right, offset, ground)` synthesises something a display should *not* show: the red and blue records of an analogue signal drifting out of registration. It is the only entry in this catalogue whose output is meant to look wrong.

Three passes, and **the order is load-bearing**:

```python
draw_text_chroma_shift(
    image, (x, y), chunk, font,
    core=SPECTRA6["white"], left=SPECTRA6["red"], right=SPECTRA6["blue"],
    offset=2, ground=frozenset({SPECTRA6["black"], SPECTRA6["blue"]}),
)
```

The two chroma ghosts go down first at opposite horizontal offsets, then the core covers the middle — so what survives is a red fringe on one edge, a blue fringe on the other, and clean text between. Paint the core first and the ghosts after and the colour lands *over* the letterform, which reads as a coloured outline rather than as a signal that has come apart. `ground` restricts the inks a ghost may overwrite, the same guard `paint_neon_mask` takes and for the same reason: without it a later line's fringe eats an earlier line's core.

Two things worth knowing before reaching for it:

**Offset must clear the stem, so the face has to be narrow.** At a 2 px offset on a wide face the separation is a fraction of the stem width and simply vanishes into it. `vhs` uses condensed Antonio for exactly this reason — the ghost has to emerge from the side of the stroke to be visible at all.

**Distinguish it from plate misregistration.** `pulp` paints its cover title's red plate at a *fixed offset in one direction* and drops black on top, which is a printing fault — a sheet slipping through a press. This is symmetric about the glyph because it models a *signal* splitting into its records, not a sheet moving. The two look different and mean different things; picking the wrong one gives a period-wrong result.

## Two-ink recipes

Single combined catalogue: recipes the codebase pulls today plus the unused-but-reachable recipes upstream literature consistently recommends. The **In use** column flags themes that currently invoke each recipe; rows marked "not in use" are forward references for future themes — they're listed because someone considering an ocean / winter / parchment / forest theme will want a starting point rather than re-deriving the recipe.

| Synthesised colour | Recipe | `draw_text_dithered` call | In use | Source |
|---|---|---|---|---|
| Tangerine / warm orange | red + yellow at 5/8 : 3/8 | `dark=red, light=yellow, light_density=0.375` | `deco` (matched phrase + border post-pass); `atomic` (mid-edge starburst rays — painted in red as a sentinel, then a per-starburst bbox post-pass Bayer-flips ~3/8 of the red pixels to yellow at threshold 6/16 so the rays read as the canonical mid-century atomic-spark warmth, while the atom-symbol orbits stay solid red for ray-vs-orbit contrast); `alchemy` (element triangle 🜂 Fire at the BL corner — same R+Y Bayer recipe for warm-orange flame); `grimoire` (☉ Sun mid-edge sigil — bbox-post-passed for the solar gold the alchemists called *aurum*); `lcars` (top + bottom elbow bars, quarter-circle elbows, and one of the six stacked rail blocks — the iconic Okudagram orange of every Star Trek: TNG / DS9 / Voyager console; same red-sentinel-then-bbox-Bayer-post-pass approach the `deco` border uses, so a future combined render would land both decorations on identical tangerine); `mucha` (corner-vine berry tips — each berry painted as a red sentinel and bbox-post-passed through `BAYER_4x4 < 6/16` to flip ~3/8 of the red pixels to yellow, reading as warm-spark tangerine at each vine's stem tip, the bright Belle-Époque counterpoint to the maroon stem and olive trefoil leaves); `vitrail` (amber / gold glass pane — one of the leaded "lights" in the stained-glass window's pane grid); `astrarium` (matched phrase + the oversized quote-mark ornaments via `_astrarium_paint_quote_panel`; separately the dial's ring quadrant and its small sun glyph, both in `_astrarium_paint_dial`); `vinyl` (sleeve matched-phrase substitution in `_vinyl_paint_quote_body`); `grimdark` (matched phrase — forge-amber, so the time phrase reads as molten metal against the black Imperial-Gothic bulkhead and ties to the gold trim); `pride` (the flag's **orange stripe** — the one place this recipe carries a whole band of the composition rather than an accent, and part of why the flag is renderable on Spectra 6 at all); `bakelite` (the **phosphor halo** around every lit character — the first use of this recipe at a *falling* density rather than a constant one, so the mix carries the hue while the density carries the glow. The ratio has to ride the density's own Bayer read as a split band, because a second read of the same tile is perfectly correlated with the first; see `_bakelite_paint_phosphor`) | Idle Hours / Beyond-6-Colors literature |
| Pure orange / amber | red + yellow at 1/2 : 1/2 | `dark=red, light=yellow` (default density) | — | Frans-Willem README. *Caveat:* reads as washed-out amber on the panel (yellow's higher luminance dominates). The deco theme historically used this recipe before being switched to the tangerine variant above; documented here so future authors don't repeat the same fix. |
| Gold / lit amber | yellow + red at 5/8 : 3/8 | `dark=yellow, light=red, light_density=0.375` | `bakelite` (the **stroke** of every lit character — the yellow-dominant counterpart to the tangerine halo that surrounds it, so a glowing glyph steps gold at the core, orange through the bloom and brown into the tube. Solid yellow was tried first and reads as pale citrus with an orange fringe pasted round it rather than as one hot amber, because the panel's yellow is a markedly green lemon; the 3/8 of red is what carries it onto amber) | Idle Hours. The mirror of the tangerine row above: same ink pair, opposite dominance. Reach for this one when the target is a *lit* amber (a phosphor stroke, a filament) and for tangerine when it is a pigment orange. |
| Pink / coral | red + white at 1/2 : 1/2 | `dark=red, light=white` | `placard` (thumbtack corner accents — weathered hand-painted red); `chalkboard` (eraser-smudge dots along the bottom inner edge — leftover pink eraser-stub residue); `pride` (the Progress chevron's **pink band** — white-dominant at 3/8 red for the pale rose rather than the 1:1 coral); `lcars` (the "advisory" pink rail block, painted as a half-rounded rectangle in red as a sentinel and then bbox-post-passed to flip half of those red pixels to white per `(x+y)&1` parity — the soft salmon button colour that distinguished "informational" rail panels from the "critical" red ones in the show's UI design); `vitrail` (rose / coral glass pane) | Idle Hours |
| Candlelit red | red + white at 3/4 : 1/4 | `dark=red, light=white, light_density=0.25` | `grimoire` (matched phrase); `gothic` (matched phrase — shares the candlelit-rubric signature with grimoire, the complementary-polarity blackletter sister) | Idle Hours |
| Mint | green + white at 1/2 : 1/2 | `dark=green, light=white` | `nightvision` (body / attribution / ornament); `marker` (left mid-edge dot — green sentinel post-passed to white at 50/50 `(x+y)&1` parity for a Stabilo-style highlighter wash sitting alongside the multi-colour marker palette); `vitrail` (mint glass pane) | Idle Hours / Beyond-6-Colors |
| Sage / muted green | green + white at 1/4 : 3/4 (inverted) | `dark=white, light=green, light_density=0.25` | `nightvision` (scanlines — bbox-post-pass on the scanline pixels flips ~25% of the painted green to white per `BAYER_4x4 < 4`, so the scanlines read as ambient ground glow rather than crisp bright-green CRT lines without crowding the body text) | Complement to mint; useful for a herbarium / botanical theme that wants a softer green. |
| Cyan | green + blue at 1/2 : 1/2 | `dark=green, light=blue` | `mucha` (matched phrase + outer rule decoration — matched-phrase green sentinel rerouted in `_draw_text_body` to a 50/50 G+B stipple for a cool cyan accent against the maroon body; the border's inset-18 rule is painted in green sentinel and perimeter-post-passed to flip half to blue per `(x+y)&1` parity so the rule and matched phrase share one cyan tone) | Beyond-6-Colors / Idle Hours. |
| Teal (green-biased cyan) | green + blue at 5/8 : 3/8 | `dark=green, light=blue, light_density=0.375` | `glacier` (matched phrase — body green sentinel rerouted in `_draw_text_body` to a green-biased Bayer 6/16 stipple. Earlier shipped at 50/50 cyan, but against the solid-blue body the cyan averaged too close to blue at panel viewing distance and read as a near-sibling tone rather than a highlight; biasing toward green pulls the matched phrase clearly off the body while keeping it in the cool-palette family, so the gradient reads as blue body → teal matched phrase → sky-blue ornament highlights); `vitrail` (teal glass pane) | Mirrors the tangerine / lime recipes: same ink pair as cyan but luminance-biased toward the less-blue ink for higher contrast against a same-axis body colour. |
| Sky blue | blue + white at 1/2 : 1/2 | `dark=blue, light=white` | `glacier` (frost-crystal diagonal-shard tip post-pass — sunlight catching the ice surface); `grimoire` (Moon ☽ mid-edge sigil — the helper now paints its outer disc in BLUE as a sentinel, and a bbox post-pass flips half of those blue pixels to white per `(x+y)&1` parity so the crescent reads as the cool argent / silver-blue of alchemical lunar work); `alchemy` (🜄 Water element triangle at the TR of the transmutation circle — the canonical cool-blue elemental pigment, paired against the 🜂 Fire triangle's R+Y tangerine on the opposite corner); `vitrail` (sky-blue glass pane); `pride` (the Progress chevron's **light blue band**) | Idle Hours / Beyond-6-Colors |
| Purple / violet | red + blue at 1/2 : 1/2 | `dark=red, light=blue` | `alchemy` (matched phrase + 🜁 Air element triangle); `grimoire` (♀ Venus mid-edge sigil); `illuminated` (matched phrase — Tyrian purple of the medieval scriptorium); `risograph` (matched phrase — authentic riso double-pass overprint where the red and blue plates physically wash into purple; preserves the theme's no-black-ink invariant by construction); `marker` (right mid-edge dot — "second marker dragged over the first"); `vitrail` (matched phrase — the violet-glass time-phrase accent via `draw_text_dithered` — plus a royal-purple glass pane); `tarot` (the card-name chrome — the matched phrase promoted to the trump's "true name" in Tyrian purple over the rubricated vellum card); `pride` (the flag's **violet stripe**, and the matched phrase drawn from it so the clock signal comes out of the subject rather than being imposed on it); `synoptic` (the **occluded front** — the one place in the rotation a synthesised colour is used for the same *reason* the source material uses it: an occluded front is a cold front that has overtaken a warm one, and real charts draw it purple precisely because it is the two fronts merged, which is exactly what the two inks are doing); `cardcatalog` (the **date-due stamps** and the matched phrase both — library date stamps really were purple, and painting the time phrase in the stamps' own ink makes the readable time and the stamped one visibly the same fact recorded twice) | Idle Hours / Beyond-6-Colors |
| Brown / sepia | red + green at 1/2 : 1/2 | `dark=red, light=green` | `saloon` (foxing speckles via `(px+py)&1` parity over `_SALOON_FOXING`; outer wanted-poster frame's 3 px rule painted in red, then the 4 edge strips are perimeter-post-passed to flip half of the painted pixels to green per `(x+y)&1` parity so the rule reads as rusted iron of a 19th-century wood-engraved cornerpiece frame); `placard` (outer sign-painter's frame — painted as a red 1 px rule, then a perimeter post-pass flips half of the pixels to green per `(x+y)&1` parity so the rule reads as weathered sandwich-board wood rather than fire-engine ink); `dispatch` (every other tractor-feed perforation pair flips from solid black to a red sentinel, then a per-perforation bbox post-pass flips half of those red pixels to green per parity — reads as "carbon-paper bleed", the rust-brown oxidation continuous-feed forms accumulate where the carbon backing meets the sprocket holes); `newsprint` (Layer 0 foxing speckles — 1 red + 1 green pixel per 4×4 Bayer tile at cell values 2 and 3, diagonally ~2.8 px apart, blends at panel distance into pale rust-brown lignin oxidation alongside the existing 12.5% black halftone); `pride` (the Progress chevron's **brown band** — deliberately *not* muted further with black, the option this row offers, because the band sits directly against the chevron's black band and a darker brown stops being distinguishable from it on six inks; note it looks olive in an RGB preview and reads as a true brown on the panel, whose calibrated red ~#62201E and green ~#35563A average to ~#4C3B2C against the flag's #613915 — do not "correct" it from a screenshot); `tarot` (Layer 0 foxing over cream via `_tarot_paint_vellum` — 1-in-32 R+G dots split by tile-coordinate parity so the scatter reads as random rather than grid-aligned, layered on a Y+W base so the card stock reads as older archival ritual document than fresh manuscript vellum); `cardcatalog` (the **manila card ground** — the same Y+W-cream-under-R+G-foxing pairing as tarot at roughly a fifth the foxing density, since a catalogue card is decades old and handled rather than centuries old and archival. **The foxing lattice must stay coprime with the cream wash's 4-pixel Bayer period**: the first implementation sampled `(7x + 13y) % 24 == 0` over even pixels, which forces `x % 4 == y % 4`, and both surviving diagonal cells of the tile sit below the cream threshold — so all 8000 candidates had already been claimed and the foxing pass painted nothing at all. Any two-layer ground recipe has this failure mode); `bakelite` (the **CRT's scanlines** — weighted 3:1 red:green rather than the even mix, because the panel's cool green measures grey at 1:1 and the tube has to read as warm brown; only every third row is painted, so the brown *is* the line structure rather than a wash over it) | Idle Hours / Beyond-6-Colors |
| Dark green / forest | green + black at 1/2 : 1/2 | `dark=green, light=black` | `herbarium` (matched phrase — body green sentinel rerouted in `_draw_text_body` to a 50/50 G+K stipple, reading as the dark-pressed plant material a real archival specimen develops over time; contrasts strongly with the cream Y+W Layer-0 wash and visually distinct from the Y+G olive used by the corner pressed-leaf border graphic) | Idle Hours — the first claim of this previously "not in use / forward reference" recipe; herbarium needed a green-family matched-phrase tone that wouldn't average into the yellow-tinted cream ground the way Y+G olive would have. `vitrail` also uses it as a "deep glass" forest pane in the leaded window. `circuit` uses it as a Layer-0 ground wash — flipping half of the flat-green `page_bg` to black on the `(x+y)&1` checkerboard so the PCB soldermask reads as deep bottle-green FR-4, distinct from `atomic`'s 1-in-4 white-on-green mint wash over the same starting ink. |
| Olive | yellow + green at 1/2 : 1/2 | `dark=yellow, light=green` | `roman` (laurel-sprig leaves on the bottom-centre corona triumphalis — each leaf is painted as a yellow ellipse then a per-leaf bbox post-pass flips half of the yellow pixels to green per `(x+y)&1` parity, reading as the canonical olive-green Mediterranean laurel a real Roman victory wreath was plaited from); `alchemy` (element triangle 🜃 Earth at the TL corner of the transmutation circle — painted in yellow and bbox-post-passed to flip half to green for the canonical alchemical "green earth" pigment); `herbarium` (corner pressed-leaf silhouette + stem + vein decorations — each leaf is painted as a yellow ellipse and bbox-post-passed to flip half the pixels to green per `(x+y)&1` parity, reading as the canonical dried-leaf olive a real pressed-and-aged specimen develops); `mucha` (trefoil leaf clusters on the corner vine ornaments — each leaf painted as a yellow ellipse then a per-vine bbox post-pass flips half to green per parity, reading as Art Nouveau leaf-green against the maroon stem); `vitrail` (olive glass pane) | Frans-Willem; Idle Hours. |
| Lime | yellow + green at 5/8 : 3/8 | `dark=yellow, light=green, light_density=0.375` | `nightvision` (matched phrase — yellow-biased green stipple via the same `light_density=0.375` Bayer threshold deco's tangerine uses, reads as the brighter neon "tactical readout" glow of a real HUD warning rather than the flat alert-flag yellow it was previously) | Mirrors the tangerine recipe (yellow-biased to keep the colour bright). |
| Cream / pale yellow | yellow + white at ~1/8 : ~7/8 (Layer-0 wash); yellow + white at 1/2 : 1/2 (full-density mix) | `dark=yellow, light=white` | `dispatch` (Layer 0 ground wash); `gothic` (mid-edge border diamonds — candle-flicker warmth); `illuminated` (Layer 0 ground wash — aged vellum); `deco` (rising-sun fan inner rays — a 2-tone post-pass on the rays' inner band flips remaining red pixels to white per parity after the tangerine pass, so the inner rays read as bright Y+W cream fading back into the R+Y tangerine at the tips, simulating a real sunburst's central glow); `herbarium` (Layer 0 ground wash — aged-paper specimen sheet tone); `mucha` (Layer 0 ground wash — Belle-Époque ivory poster ground); `fillmore` (Layer 0 ground wash — **same Y+W primitive at the same ~12.5% density, but applied to a *yellow* page_bg instead of a white one**, so the wash desaturates the saturated Spectra-6 yellow toward sun-faded poster stock rather than warming a white ground toward cream. The painted pixels' RGB values are identical to the other themes' cream washes; the perceived hue depends on which colour the eye averages from — starting from white reads as warmer-white / cream, starting from yellow reads as paler-yellow / sun-faded); `astrarium` (Layer 0 ground wash via `_astrarium_paint_cream_wash`, the helper `_tarot_paint_vellum` also builds on); `tarot` (the base layer under the R+G foxing, plus the `_tarot_paint_body_panel` interpretation-cartouche knockout); `vinyl` (Layer 0 sleeve wash on the liner-notes half); `lieder` (Layer 0 ground wash via the same `_astrarium_paint_cream_wash` helper — what makes the engraved page read as warm manuscript stock rather than the panel's flat white) | Warm off-white for parchment / vellum themes; the same primitive run on a yellow ground desaturates instead. |
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
| Lavender | red + blue + white @ 1/3 each | Octahedron interpolation between purple and sky-blue; in use by `risograph` (shifted-accent registration crosses at the four corners — each cross painted in an off-palette sentinel then bbox-post-passed through a 3-way 4×4 Bayer partition with cells 0-4 → red, 5-9 → blue, 10-15 → white (~1/3 each); reads as the paler "overprint" register-mark tone real risograph print test sheets develop where two plates wash together; preserves the theme's no-black-ink invariant by construction) AND `lcars` (the topmost and bottommost rail blocks on the LCARS sidebar — each block painted as a half-rounded rectangle in the same off-palette sentinel `(1, 1, 1)`, then a per-block 3-way Bayer post-pass partitions the painted pixels into ~1/3 red / 1/3 blue / 1/3 white. The lavender pastel reads as the signature non-Spectra-6 Okudagram accent — every Star Trek: TNG console panel had at least one lavender block in its sidebar palette) AND `vitrail` (a lavender glass pane in the leaded window, filled via `_fill_swatch_stipple_3way`) |
| Lilac / pale violet | red + blue + white @ 25 / 25 / 50 | Paler than lavender — heavier white lift |
| Seafoam / aqua | green + blue + white @ 40 / 30 / 30 | The cyan equivalent of sky-blue. **In use by `abyssal`** (the surface band of the deep-sea gradient, painted as a 3-way Bayer partition whose white and green weights fall linearly with depth — the mix is animated by depth rather than held at a fixed ratio, so the water reads turquoise at the surface and pure blue a hundred pixels down). Held open as a forward reference from the day this catalogue was written until `abyssal` claimed it. |
| Khaki / pale olive | yellow + green + white @ 40 / 30 / 30 | Softer green than mint. Future herbarium / botanical theme. |
| Beige / tan | red + yellow + white @ 25 / 25 / 50 | Lighter parchment than cream |

### Deep tones (3-ink with black) — rich nighttime palette

| Synthesised colour | Mix | Source |
|---|---|---|
| Plum | red + blue + black @ 1/3 each | `illuminated` (corner cabochon "jewels" — each filled circle painted in an off-palette sentinel then bbox-post-passed through a 3-way 4×4 Bayer partition with cells 0-4 → red, 5-9 → blue, 10-15 → black (~1/3 each), reading as the wine-dark lapis cabochons inset on the most precious medieval bindings). Deeper than the existing `alchemy` purple. Also in use by `vitrail` (the richest "deep glass" jewel pane in the stained-glass window, filled via `_fill_swatch_stipple_3way`). |
| Print sepia | red + yellow + black @ 40 / 40 / 20 | **More authentic than the existing red+green brown** the `saloon` foxing uses. Real archival sepia is yellow-brown, not red-green brown — worth flagging as a forward path if a future "old-photograph" theme wants to upgrade from the 2-ink approximation. |
| Maroon / burgundy | red + black @ 1/2 : 1/2 (2-ink) | 2-ink in practice; in use by `dispatch` (rubber-stamp imprint); `gothic` (corner quatrefoil lobes — iron-aged cathedral tracery); `chanbara` (rising-sun disc rim radial gradient + artist's-chop seal); `grimoire` (♂ Mars mid-edge sigil — oxblood iron); `blueprint` (matched phrase red fill rerouted in `_draw_text_body` to a 50/50 R+K stipple, reading as a darker red pencil pressed firmly into the drafting paper); `scholar` (matched phrase — same R+K path as blueprint, reading as aged red-lead of an academic-journal annotation against the Bitter slab serif body); `mucha` (body fill + corner-vine stems — the **first theme to use a synthesised colour as its primary body fill** rather than just an accent: the `text` THEMES slot holds the red sentinel that `_draw_text_body` routes through the same 50/50 R+K stipple as blueprint/scholar's matched phrase, reading as the deep wine / oxblood the period's poster lettering actually used; vine-stem ornaments on the corner decorations use the same recipe so body and ornament share one maroon); `fillmore` (body fill — same R+K stipple as mucha, subdues the otherwise-loud pure-red-on-saturated-yellow body without losing the psychedelic identity. Real Fillmore posters' red ink ended up darker once printed onto yellow stock anyway, so the perceived hue is period-authentic; the matched-phrase blue and corner-blob primaries stay solid so all six Spectra-6 natives are still visible) — listed here because it's the "with black" sibling of the pastel set above; useful for a leather-bound / oxblood theme |
| Navy | blue + black @ 1/2 : 1/2 (2-ink) | 2-ink in practice; in use by `bauhaus` (matched phrase blue fill rerouted in `_draw_text_body` to a 50/50 B+K stipple, reading as a tighter-contrast deeper-blue against the newly-yellow BL corner triangle in the border); `vitrail` (navy "deep glass" pane in the leaded window) — deeper than the panel's already-dim native blue, for a midnight theme |

(The maroon and navy rows are 2-ink and reachable via `draw_text_dithered` today; documented here so the K-darkened palette feels complete, not because they need a new primitive.)

### Chromatic mixes (3-ink, no white or black)

| Synthesised colour | Mix | Source |
|---|---|---|
| Burnt orange / terracotta | red + yellow + green @ 50 / 40 / 10 | The green dulls tangerine into terracotta. Future desert / canyon theme. |
| Forest-teal | green + blue + yellow @ 40 / 40 / 20 | Cyan dragged toward olive — denser than seafoam, for a deep-forest theme. |

`TestFillSwatchStipple3way::test_partition_ratios` (in `tests/test_render_quote.py`) sweeps the five density splits used by the diags swatch band and pins each region's pixel count within `±2%` tolerance on a fixed 32×32 sample tile — extend it when adding a new recipe whose density split isn't already covered.

## Four-ink recipes — narrower edge

**Also not yet supported.** A `_four_way_bayer` helper (4/4/4/4 cell partition) is the natural extension of the three-ink primitive, but at four inks per 16-cell tile the per-ink density is low enough that the eye starts reading the result as *texture* rather than as a uniform colour mix at close viewing distance (under ~1 m). At Idle Hours's intended viewing distance (1–3 m) the mix still reads cleanly. Use sparingly — the only recipes worth the implementation cost are the ones a 3-ink mix can't approximate:

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
- **Error diffusion (Floyd–Steinberg / Atkinson)** — out of scope for Idle Hours's ordered-pattern rendering; mentioned only in case a future theme wants to dither a photographic source asset. Atkinson is preferred for portraits (more localised, visually pleasing, less pattern repetition); Floyd–Steinberg for art (uniform noise, more colour-correct via global error diffusion).

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
- [Pimoroni Inky Impression 7.3" (2025 Edition) product page](https://shop.pimoroni.com/en-us/products/inky-impression) — the hardware Idle Hours targets.
- [Pimoroni: Getting Started with Inky Impression](https://learn.pimoroni.com/article/getting-started-with-inky-impression) — the manufacturer's quickstart, including the built-in dithering pass.
