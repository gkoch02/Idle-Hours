# Changelog

Notable user-facing changes to Idle Hours are recorded here. Releases use
canonical `vMAJOR.MINOR.PATCH` Git tags; the package version omits the leading
`v`.

## [Unreleased]

Add release notes here as changes merge. The release preparation tool moves
these entries under the new dated version heading.

- The baker and picker now skip a quote whose time phrase sits inside a
  hyphenated compound ("struck three-quarters", "twenty-three o'clock"),
  which the panel showed with no highlighted phrase. Two such quotes left
  the rotation.
- New `splitflap` theme: a split-flap message board on a wall, in the manner
  of a Vestaboard. The quote is set in capitals on a fixed grid of flap
  tiles, each split by its hinge, with the matched phrase on yellow colour
  tiles, the byline behind a run of colour tiles, and two tiles caught
  mid-flip. Its sleep frame lays a crescent moon and stars out in colour
  tiles over GOOD NIGHT.
- New `platform` theme: a railway departure board after dark, in the Lumen
  face's Round Medium and Round Bold. The book is the 1st train's
  destination, "via" its author; the quote runs as the calling points with
  the matched phrase in heavier dots; the station clock sits underneath. Its
  sleep frame reads "No further departures". Every dot is placed from the
  face's grid at the size each weight draws it.
- New `gantry` theme: an overhead motorway message sign at night. The quote
  runs in amber LEDs on a full-matrix sign hung from a steel truss, the
  matched phrase lit white and bold, with tail-light streaks running off
  under it and the source posted on a green guide sign whose exit number is
  the hour. The dot pitch is chosen per quote, so short quotes get big round
  LEDs and the longest still fit whole. Its sleep frame empties the road and
  sets the sign to TIRED? / REST AREA / NEXT EXIT →. Bundles the Lumen LED
  dot-matrix font (Font Studio, OFL).

- `vhs` draws its own sleep frame: the tape has run on into the station
  sign-off, colour bars over "THIS CONCLUDES OUR BROADCAST DAY" / GOOD NIGHT,
  under the quote frame's tape wear, with the deck's PLAY in place of the
  camcorder's REC and no clock burnt in. Its quote frame is unchanged.
- `dsky` draws its own sleep frame: the Apollo computer put into standby for
  the crew's rest period, with the STBY lamp lit, P06's VERB 50 NOUN 25
  "please perform" on the display, and the presleep checklist typed on the
  flight plan. Its quote frame is unchanged.
- Four more themes draw their own sleep frame: `lieder` (the opening phrase of
  Brahms's *Wiegenlied*, "Guten Abend, gut' Nacht", engraved), `sampler`
  ("Now I lay me down to sleep, / I pray the Lord my soul to keep." in
  cross-stitch), `semiotic` (HYPERSLEEP: the Nostromo's crew of seven in
  stasis, ship at rest) and `trisolaris` (a chaotic era: dehydrate, and rest
  until the stable era returns). Their quote frames are unchanged.
- `tarot` draws its own sleep frame: XVIII, La Lune, dealt in place of the
  hour's trump, with "To sleep, perchance to dream." as its reading. The
  plate is a new Dodal scan, separated by `ingest_tarot_plates.py`, which
  gains a `--single` mode for one card.
- `chrono` draws its own sleep frame: the End of Time, a lamppost burning
  on a platform in the void, the portrait hourglass run out, and the
  narrator's promise that the gates open again at dawn.
- Five more themes draw their own sleep frame: `marquee` (the letter board
  reads CLOSED / SEE YOU TOMORROW, every bulb still lit), `witcher` (the
  meditation screen, resting until dawn), `questline` (an inn after dark:
  "You rest at the inn. HP and MP are fully restored."), `yorha` (the archive
  asks "Enter sleep mode?" with Yes chosen) and `metro` (night service: day
  lines hollow, a dotted night line still running). Their quote frames are
  unchanged.
- Themes can now draw their own sleep frame. A theme without one still
  sleeps under "To sleep, perchance to dream." in its own layout, unchanged.
  The first to have one is `redacted`: a SUSPENDED Standby Order with every
  word blacked out but "lights", early in the first line, and "out", partway
  along the last.
- New `redacted` theme: a declassified Federal Bureau of Control document
  from *Control*. The quote is typed under the Bureau's letterhead with a red
  DECLASSIFIED stamp, the matched phrase in red, and black marker bars over
  words the censor took. Which words go is seeded from the quote, and the
  censor never touches the time phrase or any word that reads as a time.

## [3.0.0] - 2026-10-06

- **3.0 is a major release for code that imports Idle Hours, not for the
  appliance.** A config, a panel and a curator UI that ran 2.6 run 3.0
  unchanged. What moved is the Python surface: `idle_hours.render_quote` is
  now a package (#335) whose top-level names read live but refuse writes
  (patch the submodule that reads a name instead), the per-theme helpers were
  folded into shared ones (#336), and `idle_hours.run_clock` re-exports
  nothing from the `runtime_*` modules (#353), so `from idle_hours.run_clock
  import render_now` and the like must import from the defining module. A
  custom `--render-script` pointing at the old bundled `render_quote.py` file
  keeps working (see below).
- New `bladerunner` theme: *Blade Runner 2049*'s systems — an LAPD records
  terminal on black glass. The quote is a record in white Barlow Condensed
  with the matched phrase in yellow, beside a dithered X-ray of the box's
  pelvis with the serial boxed in red and magnified, and the twins' DNA, born
  06.10.21, identical base for base. Along the foot the baseline test's
  twelve prompts; the hour's is lit and the trace spikes above it.
- New `lasvegas` theme: *Blade Runner 2049*, K in the dead Las Vegas. The
  orange haze, dithered from red, yellow, black and white, swallows a skyline
  of broken casino towers; K stands among the beehives under the spinner's
  scanner tags. The quote sits in a black LAPD archive pane, white Barlow
  with the matched phrase in yellow, over a DNA strip seeded from the quote
  and twelve archive drawers whose lit cell is the hour.
- New `traumateam` theme: a *Cyberpunk* Trauma Team dispatch screen. A drawn
  white wordmark and six-armed mark over a red dispatch band that names the
  hour's responding unit (`AV-01` to `AV-12`), the quote in white Oxanium
  with the matched phrase on a red block, and a heart trace along the foot.
- The `photo` theme no longer washes out dark photographs. A dark picture was
  brightened by adding a flat amount to every pixel, which turned its blacks to
  mid-grey and the whole frame to fog on the panel. It is now lifted with a
  gamma curve that keeps the blacks, and only part way (to a mean of 0.50
  rather than the bright autochrome reference), so a moody scene stays moody.
  A photograph between the two keeps its own exposure.
- `render` paints a border theme's border once instead of twice for the 27
  border themes whose painters reproduce their own output, with byte-identical
  frames. Up to ~1.2 s saved per render on a Pi (`alchemy`). The ten that do
  not are marked `paints_twice` on their spec and keep both paints (#361).
- `run_clock` now launches the bundled renderer as `python -m idle_hours.render_quote`
  instead of by file path, ahead of `render_quote.py` becoming a package (#335).
  `--render-script` / `render_script` defaults to `"auto"`. A config that still says
  `render_script = "render_quote.py"`, as every appliance built from
  `config.toml.example` does, keeps working and logs a one-line note at startup
  asking for `"auto"`. A custom renderer path is unaffected.
- A hand-written `render_script` naming the old bundled file by absolute path
  (`/home/pi/IdleHours/idle_hours/render_quote.py`) also keeps meaning the bundled
  renderer after the package split, with the same startup note (#364). Only the
  file at this install's own location counts; any other `render_quote.py` is still
  a custom renderer.
- `idle-hours render --time` now rejects a malformed or out-of-range time
  (`25:99`, `garbage`) with a usage error, as `idle-hours pick` already did,
  instead of a `KeyError` traceback. A render with a malformed or missing time
  no longer crashes the `codex`, `vinyl`, `metro` or `diags` frames or the
  debug footer; they fall back to midnight, the 12 o'clock other themes
  already used.
- Curator web UI audit (#338): a request the appliance never answers now
  shows up as an error on every button and form, instead of leaving
  "Baking…" or "Loading…" on screen. The search form's "Enter at least one
  filter" hint shows again, and the setup wizard names why a theme could not
  be applied. 11 new JS tests.
- New `escritoire` theme: a handwritten letter on a mahogany writing desk,
  seen at an angle. The quote is laid out flat in Dancing Script, warped
  into perspective and thresholded back to solid ink, with the matched
  phrase in blue fountain-pen ink. Faint asemic lines fill the
  foreshortened far band, a fountain pen lies across them, a second page
  lies underneath, and an inkwell, a pen cup and a sander stand out of
  focus on the mahogany beyond.
- A hand-edited `selection_overrides.json` with a field of the wrong type no
  longer breaks the clock or bans the wrong book. A `null` list used to raise
  on every pick and freeze the panel in render backoff, and a ban written as
  the string `"141"` banned sources 1 and 4 instead of 141. Each field is now
  checked on its own: a bad field or entry is dropped with a warning and the
  rest of the file still applies.
- The wheel no longer ships four unused Spectral SC font weights (about 1 MiB).
- The wheel no longer ships three more unused font files (about 1 MiB): IBM
  Plex Mono Regular, Jura Regular and the Montserrat italic.
- `idle-hours contact-sheet` applies your bans and boosts again. It was
  loading overrides from a path that stopped existing in the package move, so
  the QA sheet could show quotes the panel never would. A new `--overrides`
  flag points it at an appliance's relocated copy.
- A problem in `selection_overrides.json` is reported once per edit of the
  file rather than on every pick, and the render subprocess no longer repeats
  it.
- A banned-quote key with a trailing newline or non-ASCII digits is now
  rejected instead of being saved as a ban that could never match.
- Literary-layout themes (the thirty-eight that share `render`'s text path)
  set type better: justification is decided per block and never opens
  rivers (no line with under three gaps or more than 0.45 em per gap is
  stretched; one such line sets the whole block ragged), monospace,
  typewriter and handwriting themes (`nightvision`, `circuit`, `dispatch`,
  `marker`, `chalkboard`, `placard`, `kanagawa`) are always ragged-right,
  a one-word last line is re-wrapped away (narrower measure first, then up
  to 20% smaller type), and the byline floors at 18 / 16 px so it reads
  from across the room. `assets/goodnight.png` is regenerated to match.
- `risograph` knocks the body text out to a misregistered red-over-blue
  label so the print-test bars and circles no longer run under the first
  word and the attribution.
- `alchemy` paints its transmutation circle as a faint blue stipple behind
  the text instead of solid hairlines through every line, and sets the
  matched phrase as a solid red rubric instead of a purple stipple that
  shredded MedievalSharp at body size.
- New `witcher` theme: *The Witcher 3: Wild Hunt* — a bestiary page on
  deckled parchment in a dark binding, the meditation dial with the title's
  three claw slashes at its hub and a sun or moon on the hour's radius, the
  entry in Barlow Condensed with the matched phrase in the interface's
  tangerine, and the signs the entry is susceptible to at the foot. Archivo
  Narrow is a new bundled face (OFL, from Google Fonts).
- New `hades` theme: *Hades II* — a boon at the Crossroads under the
  moon: a dithered night with the moon's phase as the hour, Hecate's green
  witchfire braziers on a ridge of cypresses and broken columns, and the
  quote on a black-and-gold boon card in a Greek-key frieze with Chronos's
  hourglass in the portrait medallion — the author as the god's name in
  Caesar Dressing, white Spectral text with the matched phrase in gold, the
  boon's rarity rolled from the quote. Caesar Dressing, Spectral SC and
  Hammersmith One are new bundled faces (OFL, from Google Fonts).
- New `expanse` theme: *The Expanse* — the Rocinante's console in the
  show's screen-graphics grammar: an orbital strip across the top with the
  stations as column heads and two trajectories curving through, black
  glass panels with their corners cut, a tactical plot whose tracked
  contact sits at the hour's bearing with its track and intercept and a
  row of arc gauges beneath, the quote as an incoming tightbeam in a
  bracketed feed frame — white Barlow with the matched phrase and the
  sender in the MCRN's orange — over a command line with the transmission
  ID, a boxed contacts list with silhouettes, and a foot of status pills,
  a waveform chart and `//` system text, all dealt from the quote. Barlow
  is a new bundled face (OFL, from Google Fonts).
- New `beksinski` theme: Zdzisław Beksiński's fantastic period — a
  procession across a dead plain toward a cathedral of bone, under a
  dust-coloured haze with a dim sun behind the spires. The haze and the
  plain are dithered to umber, ochre and bone with no green or blue in
  them, the cathedral is a bone silhouette with a rust rim light and the
  haze showing through its windows, and the hour is the number of hooded
  figures on the road. The quote is set in black Old Standard TT in the
  haze with the matched phrase in red; no new fonts.
- New `goya` theme: Francisco de Goya's *Pinturas negras* — *El Perro*: the
  ochre void painted in continuous tone and dithered to black, yellow, red
  and white over a crazed plaster, the dark slope at the foot with the dog's
  head turned up toward the matched phrase, the quote in black Libre
  Baskerville with the phrase in red, and the author and title on a Prado
  gallery label with an inventory number from the Gutenberg id. Libre
  Baskerville is a new bundled face (OFL, from Google Fonts).
- New `hal` theme: *2001: A Space Odyssey* — the Discovery One's main
  monitor as a solid blue flat with the hour's subsystem mnemonic on its
  header, the quote in white Jost with the matched phrase Bold in yellow,
  the twelve mnemonic tiles along the foot in the film's flat colours with
  the hour's tile white, and HAL's red lens in its white bezel blooming
  into the black beside the Discovery in wireframe and the hibernation
  traces. The screens are tubes, not blocks: a one-in-four raster over the
  ground under the type, a hairlined housing the phosphor leaks onto, and
  a title box round the mnemonic. No new fonts (Jost and Michroma).
- New `lumon` theme: *Severance* — the Macrodata Refinement terminal: a
  vignetted blue CRT dithered to blue and black in a black bezel, the
  file's town and its completion (the hour over twelve) in the header, a
  grid of white digits with the hour's scary cluster boxed, the quote in
  white Montserrat with the matched phrase Bold in yellow inside the
  refiner's hover box, and the five bins along the foot, all in a beige
  housing with the same raster and a blue leak onto the recessed glass
  edge. Montserrat is a new bundled face (OFL, from Google Fonts) — the
  open Gotham, for the number grid the show sets in a Gotham-like sans;
  the header and byline are Inter, for the show's Forma DJR.
- New `dsky` theme: the Apollo Guidance Computer's display and keyboard
  as a modelled unit on a dithered grey console — a shaded rim, dark-glass
  windows with a reflection, domed keycaps on a recessed tray, screws, a
  shadow — with the hour in its PROG register and telemetry seeded from
  the quote in true seven-segment strokes, white in a green bloom; the
  quote typed in Special Elite on a cream flight-plan card clipped beside
  it, the matched phrase in red ink. Real hardware; no new fonts.
- New `oblivion` theme: *Oblivion* — the Sky Tower's light table: grey
  glass dithered in continuous tone with a white pool under the quote and
  frosted panes, a contour map of the sector with the twelve hydro rigs
  on the terrain and a dial over it, a drone shaded Blinn-Phong with a
  red lens blooming into the glass, the quote in Exo 2 Light (the open
  face in the family of Blender, the film's UI typeface) with the matched
  phrase in red; the hour's rig is red on the map, its bearing on the
  dial, its cell filled in the status row. No new fonts.
- New `yorha` theme: *NieR: Automata* — the YoRHa archives: a cream
  sheet dithered in continuous tone with a vignette, the blurred ruined
  city along the foot and the diagonal hatch, crisp panels with soft
  shadows and corner ticks, the tab bar open at INTEL under the crest,
  Pod 042 modelled below the menu, twelve archive rows with the hour's
  inverted, the book's title over the entry, the quote in EB Garamond —
  the closest open face to the game's unidentified classical UI serif —
  with the matched phrase knocked out white of a black box as the
  selected item. No new fonts.
- New `hitchhiker` theme: the 1981 BBC *Hitchhiker's Guide to the
  Galaxy* — a Guide entry on the quoted author, hand-animated glyph by
  glyph in white Michroma with coloured line markers under the yellow
  masthead and the DON'T PANIC badge, the matched phrase in yellow,
  Figure 1 the Babel fish in cross-section under a CRT raster with its
  organs in the inks and numbered callouts, and Figure 2 the galaxy as a
  seeded spiral in a sector chart where the hour's sector is outlined
  with the Earth ringed inside it and YOU ARE HERE on a leader. No new
  fonts.
- Three game themes move to the faces the games actually use, or the
  nearest open ones (per Game Font Library): `control` sets its title card
  in Jost Bold and its sign in Archivo instead of Oswald; `atropos` sets the
  translation in Saira with Michroma kept for the HUD; `saros` sets the body
  in Saira and the wordmark in Orbitron with Michroma kept for the chrome.
  Saira and Orbitron are new bundled faces (OFL, from Google Fonts).
- New `expedition` theme: Sandfall's *Clair Obscur: Expedition 33* — the
  Monolith from the Lumière promenade at dusk, dithered against the panel's
  calibrated inks, with the Paintress painting the hour on the slab, a gust
  of Gommage petals, a gas lamp and balustrade, and the quote as a journal
  page in the game's own faces (IM Fell Double Pica, Bebas Neue, Cinzel
  Decorative).
- New `atropos` theme: night in the Overgrown Ruins of Housemarque's *Returnal*
  — a teal fog dithered to the cold inks, rain, Sentient statues, the Helios
  wreck, ember-lit tendrils and bullet-hell orbs, the quote as a translated
  xenoglyph cipher in Michroma and the hour as the cycle counter.
- New `saros` theme: Housemarque's *Saros* — a black sun in a dithered
  red-and-gold corona whose phase is the hour (the diamond-ring bead sits
  where the hour hand would point; totality at twelve), the colony
  silhouetted against the sunset band beneath it, the quote in Exo 2
  with the matched phrase as an ember. Bundles Exo 2 and Michroma (OFL).

## [2.6.0] - 2026-09-26

- `idle-hours run --once` now pins its render to the quote it picked, and so
  passes `--pin-quote` / `--pin-matched-text` to the render script as the
  main loop already did. A custom `--render-script` that does not accept
  those flags now fails under `--once` too.
- A pidfile that cannot be created because of the configuration (permission,
  a file where a directory should be, a read-only mount) exits 42 and halts
  the systemd unit;
  transient errors such as a full disk still exit 1 and are retried.
- Characters a theme's font cannot draw (the ellipsis in `glacier`, the
  prime marks in about forty faces) now render as ASCII stand-ins instead of
  a missing-glyph box.
- Replacing a quote's text through `content_overrides.json` now re-scores it
  from the new text, so a curator-trimmed sentence is no longer held under
  the display floor, or ranked as a fragment, by the text it replaced.
- Chapter numbers with no full stop ("XI Emil came home…") are stripped from
  quotes; nine shipped quotes carried one.
- Saving the whole overrides file from the curator UI keeps extra keys such
  as `_comment` instead of dropping them.
- Button D is now a real wake during quiet hours: the clock keeps ticking
  until the window ends, and skip, un-skip, re-render, the source card and
  theme changes no longer paint a clock quote onto a sleeping panel.
- A manual sleep or wake refreshes the panel once instead of twice, and a
  failed quiet-hours entry is retried rather than leaving the last quote up
  all night.
- `--startup-image` no longer leaves the startup frame on the panel until
  the next bucket change after a restart.
- The source card, its restore and re-render show the quote that is on the
  panel rather than the next-best pick.
- Content overrides can be undone: deleting an entry and pressing "Bake now"
  restores the row. "Bake now" also updates the raw corpus, so the inspector
  and search show the patched text.
- Banning a quote now also bans its textual twins, and the anti-repeat
  history treats twins as the same quote.
- The curator UI sends anti-framing and content-security headers, gates the
  image routes behind the token, bounds connection count and lifetime, and
  reports an asleep refusal as such instead of "busy".
- Coverage (grid, gap finder, snapshot) counts only quotes the panel can
  display, with raw counts alongside.
- Corpus quality: quotation marks stay paired, "am" and "work" are no longer
  penalised as modern schedule text, overlapping time phrases no longer file
  one sentence at two times, "struck one of the fish" is no longer a clock,
  and betting odds no longer fill the ten-to and twenty-to-one buckets.
- `idle-hours bake`, `apply-overrides` and `target-sparse` resolve relative
  paths against the current directory.
## [2.5.0] - 2026-09-24

- Aligned package metadata with the 2.5.0 release line and added CI validation
  that release tags match the version built into the Python package.
