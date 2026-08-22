<p align="center">
  <img src="idle_hours/assets/logo.svg" alt="Idle Hours" width="800">
</p>

# Idle Hours

[![CI](https://github.com/gkoch02/Idle-Hours/actions/workflows/ci.yml/badge.svg)](https://github.com/gkoch02/Idle-Hours/actions/workflows/ci.yml)

Idle Hours is a literary clock built from public-domain text. It picks a quote that matches the current fuzzy time bucket, renders it into an 800×480 image, and can push that image to an eInk display such as the Pimoroni Inky Impression 7.3.

![Idle Hours rendered in saloon, gothic, astrarium, and deco themes](idle_hours/assets/preview.png)

> **Upgrading from LitClock?** This project was previously named LitClock.
> The rename is hard (new package name, new CLI command, new filesystem
> paths, new HTTP token header, new Prometheus metric names, new systemd
> unit). See [`docs/UPGRADE.md`](docs/UPGRADE.md) for the one-time migration steps.

## Table of contents

- [What this repo is](#what-this-repo-is)
- [How Idle Hours was built](#how-idle-hours-was-built)
- [Repo map](#repo-map)
  - [Runtime](#runtime)
  - [Runtime assets](#runtime-assets)
  - [Build and corpus tools](#build-and-corpus-tools)
  - [Other important paths](#other-important-paths)
- [Runtime data contract](#runtime-data-contract)
- [Quick start](#quick-start)
  - [Local setup](#local-setup)
  - [Render once locally (smoke test)](#render-once-locally-smoke-test)
  - [Set up the config file](#set-up-the-config-file)
  - [Run the clock loop](#run-the-clock-loop)
  - [Render once and push to the Inky display](#render-once-and-push-to-the-inky-display)
  - [Themes](#themes)
  - [Inky buttons (short and long press)](#inky-buttons-short-and-long-press)
  - [Persisted runtime state and telemetry](#persisted-runtime-state-and-telemetry)
  - [Startup frame](#startup-frame)
  - [Curator web UI](#curator-web-ui)
  - [Quiet hours](#quiet-hours)
- [Testing](#testing)
- [Raspberry Pi deployment](#raspberry-pi-deployment)
  - [Fresh Pi setup](#fresh-pi-setup)
  - [Existing Pi update flow](#existing-pi-update-flow)
  - [Example service](#example-service)
  - [Install the service](#install-the-service)
- [Build pipeline notes](#build-pipeline-notes)
- [Operational notes](#operational-notes)
- [Useful files when something breaks](#useful-files-when-something-breaks)
- [Contributing and security](#contributing-and-security)

## What this repo is

This repo contains both:

- the **runtime clock** that picks and renders quotes for the current time
- the **corpus/build tooling** used to mine, clean, enrich, and improve the quote dataset

If you are deploying or operating the clock, you mostly care about the runtime and the prebuilt assets in `idle_hours/assets/`.

## How Idle Hours was built

At a high level, the project came together in stages:

1. mine public-domain books for phrases like "quarter past seven" or "ten minutes to midnight"
2. clean raw matches into displayable quotes
3. enrich, attribute, and score the candidates
4. organize them into fuzzy time buckets
5. pick the best quote for the current bucket at runtime, with nearby fallback when needed
6. render the result into an image tuned for the target eInk display

That build pipeline is how the runtime quote set came to exist. The clock itself then uses the prebuilt dataset and render loop to turn that corpus work into a live display.

## Repo map

### Runtime

- `idle_hours_cli.py` - **unified `idle-hours <subcommand>` entry point** (v2). Wraps every script below in one discoverable command; `pip install -e .` registers `idle-hours` as a console script. Backwards-compatible — `python3 <script>.py` still works for every subcommand.
- `run_clock.py` - long-running clock loop, bucket-change refresh logic, optional display handoff
- `runtime_*.py` - the seven siblings `run_clock.py` delegates to: `runtime_state` / `runtime_store` / `runtime_telemetry` / `runtime_quiet` / `runtime_theme` / `runtime_actions` / `runtime_log` (architecture in [`CLAUDE.md`](CLAUDE.md))
- `runtime_webhook.py` - v2 alert-firehose: posts alert-worthy telemetry events to an operator-configured HTTP endpoint on a daemon thread (errors, backoff, timeouts, button-died); never blocks the render path
- `render_quote.py` - quote renderer, typography, highlighting, theme handling, Spectra 6 palette snapping
- `pick_quote.py` - runtime quote selection from the attributed dataset
- `display_inky.py` - thin bridge that sends a rendered image to the Inky display
- `inky_buttons.py` - listener for the four Inky Impression capacitive buttons (A/B/C/D), short + long press, liveness check
- `probe_buttons.py` - standalone GPIO press probe for verifying which pin each physical button fires
- `idle_hours_health.py` - summarises the telemetry sidecar (render count, p50/p95 latency, last error); supports `--json`, reads date-rotated files
- `buckets.py` - fuzzy time bucket mapping (single source of truth — every other script imports from it)
- `atomic_io.py` - shared atomic-write primitive (tmp → fsync → rename → fsync dir) used by every file the next tick reads
- `pidfile.py` - single-instance `fcntl.flock` pidfile so overlapping `systemctl restart` cycles can't race
- `sd_notify.py` - pure-stdlib systemd `READY=1` / `WATCHDOG=1` client; no-op when `$NOTIFY_SOCKET` is unset
- `web_server.py` + `idle_hours/web/` - optional local curator UI (off by default; enable with `--web-bind`). v2 adds full corpus search, per-row content overrides editor, in-UI re-bake, side-by-side theme preview, gap finder, first-run wizard, Prometheus `/metrics`, mobile-first four-tab layout

### Runtime assets

- `idle_hours/assets/quote_database.jsonl` - **baked, display-ready runtime DB** (what the clock reads by default; produced by `bake_quote_database.py`)
- `idle_hours/assets/candidates-attributed.jsonl` - raw attributed corpus (baker input; curator-UI bucket inspector + full-text search; defensive fallback if the baked DB is missing)
- `idle_hours/assets/selection_overrides.json` - selection tweaks/overrides used at runtime (bans, boosts, preferred buckets, **per-row bans via `ban_quote_keys` (v2)**; editable via the curator UI)
- `idle_hours/assets/content_overrides.json` - per-row hand fixes layered onto the corpus at bake time; editable from the curator UI (v2) followed by `POST /api/bake` to make the edits visible
- `idle_hours/assets/goodnight.png` - pre-rendered dark-theme "good night" frame shown during quiet hours
- `idle_hours/assets/preview.png` - README preview image

### Build and corpus tools

The full pipeline order is documented in [Build pipeline notes](#build-pipeline-notes); the scripts themselves are:

- `gutenberg_time_miner.py` - harvest time-phrase candidates from Project Gutenberg or local `.txt` files
- `merge_candidates.py` - dedupe and merge multiple harvest runs
- `clean_display_quotes.py` - normalise raw matches into a displayable excerpt
- `quality_filter.py` - score rows and append quality flags
- `enrich_metadata.py` - attach title / author from cached Gutenberg headers
- `apply_content_overrides.py` - layer per-row hand fixes from `idle_hours/assets/content_overrides.json`
- `bake_quote_database.py` - final stage; produces `idle_hours/assets/quote_database.jsonl`, the runtime DB
- `bucket_coverage.py` - report which fuzzy buckets are sparse or empty
- `target_sparse_buckets.py` - targeted sweep for the buckets `bucket_coverage.py` flagged
- `import_targeted_hits.py` - reshape targeted hits so `merge_candidates.py` can absorb them
- `fix_substring_time_matches.py`, `fix_legacy_buckets.py` - one-shot migration tools for corpus rows from earlier miner revisions; no-ops on fresh harvests

### Other important paths

- `tests/` - automated tests (one module per script, plus golden fixtures under `tests/golden/`)
- `output/` - generated output and analysis artifacts, not canonical runtime source
- `idle_hours/fonts/` - bundled OFL typefaces used by the renderer (Playfair Display, Bitter, Old Standard TT, Space Mono, Archivo, EB Garamond, UnifrakturMaguntia, Jost, Rubik, Bangers, Press Start 2P, Pixelify Sans, Oxanium, … — one per theme)
- `ops/idle-hours.service.example` - example systemd service for Pi deployment
- `docs/pi_setup_inky_impression.md` - Pi setup notes
- `scripts/bootstrap_pi_inky.sh` - helper bootstrap script for Pi setup
- `Dockerfile` + `.dockerignore` - v2 multi-stage OCI build (ARM64-first, Pi-runtime extra not bundled). `docker buildx build --platform linux/arm64,linux/amd64 -t idle-hours:2.5 .`
- `docs/CONTRIBUTING.md`, `docs/SECURITY.md`, `docs/CODE_OF_CONDUCT.md` - process and policy docs

## Runtime data contract

For normal runtime use, the clock expects prebuilt assets and does **not** need raw Gutenberg texts to render quotes. The canonical runtime input is `idle_hours/assets/quote_database.jsonl` — the display-ready DB baked from the raw corpus with scoring pre-computed. Everything else in `idle_hours/assets/` is either the raw corpus the baker reads, a hand-edited sidecar, or a build-time artifact.

| Path | Role | Committed | Ships to Pi | Produced by |
|---|---|---|---|---|
| `idle_hours/assets/quote_database.jsonl` | **baked display-ready DB — the runtime picker reads this** | yes | yes | `bake_quote_database.py` (CLI or web UI `POST /api/bake`) |
| `idle_hours/assets/candidates-attributed.jsonl` | raw attributed corpus | yes | yes (baker input + curator UI + fallback) | `enrich_metadata.py` → `apply_content_overrides.py` |
| `idle_hours/assets/content_overrides.json` | per-row hand fixes (source-of-truth) | yes | no (build-time only) | hand-edited or web UI `POST /api/content-overrides` |
| `idle_hours/assets/selection_overrides.json` | bans / boosts / preferred buckets / per-row bans (runtime-editable) | yes | yes | hand-edited or web UI `POST /api/overrides` |
| `idle_hours/assets/bucket-coverage.{json,md}` | coverage snapshot | yes | optional | `bucket_coverage.py` |
| `~/.idle-hours/state.json` | manual theme / quiet override | — | runtime, per-appliance | `run_clock.py` |
| `~/.idle-hours/history.jsonl` | anti-repeat ledger | — | runtime, per-appliance | `run_clock.py` |
| `~/.idle-hours/telemetry-YYYYMMDD.jsonl` | render / error telemetry | — | runtime, per-appliance | `run_clock.py` |

Read it as: `candidates-attributed.jsonl` + `content_overrides.json` are the **source of truth**; `quote_database.jsonl` is **derived** (regenerated by the baker) and is what the clock actually reads; the `~/.idle-hours/*` files are **per-appliance runtime state**. Treat `data/` and the mining/enrichment scripts as build-time tooling, not service startup dependencies.

If you are only updating the clock on a Pi, you should not need to rebuild the corpus on-device — the baked DB already ships in the repo.

## Quick start

### Local setup

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

### The `idle-hours` CLI (v2)

After `pip install -e .` the project ships a single `idle-hours` command
that dispatches to every script in the repo:

```bash
idle-hours --help                          # list every subcommand
idle-hours run --display-script display_inky.py
idle-hours render --time 14:30
idle-hours pick --bucket h3_half_past
idle-hours health --hours 24 --json
idle-hours bake
idle-hours contact-sheet --output output/contact-sheet.png
```

`idle-hours <sub> --help` forwards to the backing script's argparse so the
flag list is identical to `python3 <sub>.py --help`. The umbrella CLI is
purely additive — every `python3 <script>.py` invocation in the rest of
this doc continues to work unchanged.

### Render once locally (smoke test)

Zero-setup sanity check — renders one frame using argparse defaults and
writes it to `output/current.png`:

```bash
idle-hours run --once
# or, with the unified CLI (v2):
idle-hours run --once
```

### Set up the config file

Anything beyond that smoke test should use a TOML config file. The
repo ships two of them:

- **`idle_hours/assets/config.toml.example`** — opinionated appliance preset
  (production mode, `auto` theme, `/var/lib/idle-hours/` paths,
  `systemctl poweroff` shutdown). This is what `ops/idle-hours.service.example`
  expects; copy it verbatim for Pi deployments and tweak from there.
- **`idle_hours/assets/config.toml.defaults`** — every key set to the value
  `run_clock.py` would use with no `--config` at all. Copying this
  verbatim is behaviourally a no-op; use it when you want an explicit,
  reviewable reference you can check into your deployment repo and
  diff against future upstream bumps.

```bash
# Dev machine: start from the defaults and tweak
mkdir -p ~/.idle-hours
cp idle_hours/assets/config.toml.defaults ~/.idle-hours/config.toml
$EDITOR ~/.idle-hours/config.toml
```

Every key maps 1:1 to an argparse `dest` (snake_case — `display_script`,
`quiet_start`, `web_bind`, etc.), so anything you'd pass on the CLI can
live in the file. Precedence is **CLI flag > config value > argparse
default**, so ad-hoc one-offs like `--once` or `--mode debug` still
work on top of a shipped config. Three transient flags are deliberately
refused in the file (`--once`, `--skip-preflight`, and `--config`
itself) — listing them warns and drops.

**One asymmetry to know about.** `store_true` flags — `buttons_off`,
`quiet_off` — can only be *enabled* from the CLI; there is no paired
`--buttons-on`. So a config with `buttons_off = true` cannot be
overridden from the command line for a one-off run. Leave boolean
toggles out of the config unless you want them permanent, or comment
them back out when you need CLI flexibility.

Fail-open on malformed / unreadable / schema-mismatched content (warns
to stderr, keeps running with argparse defaults); the one hard error is
pointing `--config` at a non-existent path, so a typoed unit-file path
fails fast in the journal instead of silently booting with defaults.

The shipped `ops/idle-hours.service.example` passes `--config %S/idle-hours/config.toml`
exclusively — so tuning the appliance is a file edit plus `systemctl
restart`, no `daemon-reload` needed.

### Run the clock loop

Once your config is staged, this is the canonical command. It reads
every runtime knob (render script, display push, theme, quiet hours,
etc.) from the file:

```bash
idle-hours run --config ~/.idle-hours/config.toml
```

### Render once and push to the Inky display

Same config, `--once` on top for a one-shot render-and-push (useful for
cron / bring-up):

```bash
idle-hours run --config ~/.idle-hours/config.toml --once
```

If you haven't staged a config yet, the equivalent ad-hoc CLI form is:

```bash
idle-hours run --once --display-script display_inky.py --mode production
```

### Themes

Forty-five themes ship built-in, all constrained to the Spectra 6 panel palette (white / black / red / yellow / blue / green). Each theme pairs its palette with a dedicated typeface. The previews below were rendered as each theme landed rather than in one batch, so they show several different passages — compare palette and typography, not line breaks; production renders adapt layout to the picked line.

| `--theme`     | Preview | Page bg | Body  | Accent | Typeface             | Feel                          |
|---------------|---------|---------|-------|--------|----------------------|-------------------------------|
| `default`     | <img src="idle_hours/assets/previews/default.png" width="240" alt="default theme preview">         | white       | black | red    | Playfair Display     | Classic broadsheet            |
| `dark`        | <img src="idle_hours/assets/previews/dark.png" width="240" alt="dark theme preview">               | black       | white | yellow | Playfair Display     | Night mode                    |
| `swiss`       | <img src="idle_hours/assets/previews/swiss.png" width="240" alt="swiss theme preview">             | white       | black | red    | Inter (grotesque sans) | Swiss International modernist (austere grid) |
| `scholar`     | <img src="idle_hours/assets/previews/scholar.png" width="240" alt="scholar theme preview">         | white       | blue  | red    | Bitter (slab)        | Academic textbook             |
| `herbarium`   | <img src="idle_hours/assets/previews/herbarium.png" width="240" alt="herbarium theme preview">     | cream/white | black | green  | IM Fell English (italic) | Pressed-plant specimen sheet |
| `newsprint`   | <img src="idle_hours/assets/previews/newsprint.png" width="240" alt="newsprint theme preview">     | white/black | black | (none) | Old Standard TT      | Bold-weight, no chroma        |
| `nightvision` | <img src="idle_hours/assets/previews/nightvision.png" width="240" alt="nightvision theme preview"> | black       | green | yellow | Space Mono           | Retro terminal                |
| `blueprint`   | <img src="idle_hours/assets/previews/blueprint.png" width="240" alt="blueprint theme preview">     | blue/white  | white | red    | Archivo (sans)       | Cyanotype drafting sheet      |
| `illuminated` | <img src="idle_hours/assets/previews/illuminated.png" width="240" alt="illuminated theme preview"> | white       | red   | blue   | EB Garamond + UnifrakturMaguntia | Rubricated manuscript |
| `gothic`      | <img src="idle_hours/assets/previews/gothic.png" width="240" alt="gothic theme preview">           | black       | white | red    | EB Garamond + UnifrakturMaguntia | Cathedral chronicle   |
| `bauhaus`     | <img src="idle_hours/assets/previews/bauhaus.png" width="240" alt="bauhaus theme preview">         | white       | black | blue   | Jost (geometric sans) | Bauhaus poster               |
| `risograph`   | <img src="idle_hours/assets/previews/risograph.png" width="240" alt="risograph theme preview">     | white       | red   | blue   | Rubik (rounded sans) | Two-colour riso zine          |
| `comic`       | <img src="idle_hours/assets/previews/comic.png" width="240" alt="comic theme preview">             | yellow      | black | red    | Bangers (comic)      | Golden-age comic panel        |
| `dispatch`    | <img src="idle_hours/assets/previews/dispatch.png" width="240" alt="dispatch theme preview">       | white       | black | red    | Special Elite (typewriter) | Vintage field dispatch  |
| `atomic`      | <img src="idle_hours/assets/previews/atomic.png" width="240" alt="atomic theme preview">           | green/white | black | red    | Atomic Age           | Mid-century Sputnik age       |
| `marker`      | <img src="idle_hours/assets/previews/marker.png" width="240" alt="marker theme preview">           | white       | black | blue   | Permanent Marker     | Fridge-doodle Sharpie         |
| `saloon`      | <img src="idle_hours/assets/previews/saloon.png" width="240" alt="saloon theme preview">           | white       | black | red    | Rye (wood-engraved slab) | Wild West wanted-poster   |
| `roman`       | <img src="idle_hours/assets/previews/roman.png" width="240" alt="roman theme preview">             | white       | black | red    | Cinzel Decorative    | Roman lapidary inscription    |
| `alchemy`     | <img src="idle_hours/assets/previews/alchemy.png" width="240" alt="alchemy theme preview">         | yellow/white | black | red   | IM Fell English + MedievalSharp | Parchment grimoire     |
| `grimoire`    | <img src="idle_hours/assets/previews/grimoire.png" width="240" alt="grimoire theme preview">       | black       | white | red    | IM Fell English + TFoustScript | Faustian spellbook       |
| `deco`        | <img src="idle_hours/assets/previews/deco.png" width="240" alt="deco theme preview">               | white       | black | red    | Righteous (display sans) | 1930s art-deco poster     |
| `glacier`     | <img src="idle_hours/assets/previews/glacier.png" width="240" alt="glacier theme preview">         | white       | blue  | green  | Iceland (techno display) | Icy / aurora panel        |
| `mucha`       | <img src="idle_hours/assets/previews/mucha.png" width="240" alt="mucha theme preview">             | cream/white | maroon | teal  | Cormorant Garamond + Berkshire Swash | Art Nouveau (Mucha vines)  |
| `chalkboard`  | <img src="idle_hours/assets/previews/chalkboard.png" width="240" alt="chalkboard theme preview">   | black       | white | yellow | Playwrite GB J Guides | Primary-school cursive guides |
| `placard`     | <img src="idle_hours/assets/previews/placard.png" width="240" alt="placard theme preview">         | white       | black | red    | Patrick Hand SC      | Hand-lettered sandwich board  |
| `chanbara`    | <img src="idle_hours/assets/previews/chanbara.png" width="240" alt="chanbara theme preview">       | black       | white | red    | Shojumaru (brush)    | Samurai-cinema poster         |
| `lcars`       | <img src="idle_hours/assets/previews/lcars.png" width="240" alt="lcars theme preview">             | black       | white | yellow | Antonio (condensed sans) | LCARS console (Okudagram) |
| `fillmore`    | <img src="idle_hours/assets/previews/fillmore.png" width="240" alt="fillmore theme preview">       | yellow      | red   | blue   | Bungee Shade (3D display) | 1960s psychedelic concert poster |
| `firmament`   | <img src="idle_hours/assets/previews/firmament.png" width="240" alt="firmament theme preview">     | navy        | white | gold   | Cardo (humanist serif) | 17th-century celestial atlas (Bayer's *Uranometria*) |
| `astrarium`   | <img src="idle_hours/assets/previews/astrarium.png" width="240" alt="astrarium theme preview">     | cream/white | black | tangerine | EB Garamond          | Astronomical-clock dashboard (custom layout) |
| `kanagawa`    | <img src="idle_hours/assets/previews/kanagawa.png" width="240" alt="kanagawa theme preview">       | white       | black | red    | Yuji Boku (sumi-brush) | Hokusai-inspired seigaiha woodblock |
| `marquee`     | <img src="idle_hours/assets/previews/marquee.png" width="240" alt="marquee theme preview">         | black       | white | red    | Cardo Italic + Bungee Shade | 1930s movie-palace marquee (custom layout) |
| `tarot`       | <img src="idle_hours/assets/previews/tarot.png" width="240" alt="tarot theme preview">             | cream/white | black | Tyrian purple | EB Garamond + Cinzel Decorative | Major-arcana card (custom layout) |
| `vinyl`       | <img src="idle_hours/assets/previews/vinyl.png" width="240" alt="vinyl theme preview">             | cream/white | black | tangerine | Cormorant Garamond | Turntable + literary-audiobook LP (custom layout) |
| `vitrail`     | <img src="idle_hours/assets/previews/vitrail.png" width="240" alt="vitrail theme preview">         | jewel glass | black | violet | EB Garamond + Uncial Antiqua | Gothic stained-glass window (custom layout, full palette) |
| `cartograph`  | <img src="idle_hours/assets/previews/cartograph.png" width="240" alt="cartograph theme preview">   | cream/white | black | red    | IM Fell English Italic | Antique cartographer's chart |
| `questline`   | <img src="idle_hours/assets/previews/questline.png" width="240" alt="questline theme preview">     | black       | white | yellow | Press Start 2P (pixel) | 8-bit RPG dialogue box (custom layout) |
| `chrono`      | <img src="idle_hours/assets/previews/chrono.png" width="240" alt="chrono theme preview">           | twilight blue | white | yellow | Pixelify Sans (pixel sans) | 16-bit SNES JRPG cutscene (FF6 era, custom layout) |
| `outrun`      | <img src="idle_hours/assets/previews/outrun.png" width="240" alt="outrun theme preview">           | black       | white | magenta | Oxanium (techno sans) | 1980s synthwave sunset (neon grid, custom layout) |
| `circuit`     | <img src="idle_hours/assets/previews/circuit.png" width="240" alt="circuit theme preview">         | forest green | white | gold   | Space Mono (mono)    | Printed circuit board (PCB silkscreen) |
| `letter`      | <img src="idle_hours/assets/previews/letter.png" width="240" alt="letter theme preview">           | cream/white | black | red    | Dancing Script + Pinyon Script | Wax-sealed handwritten letter |
| `grimdark`    | <img src="idle_hours/assets/previews/grimdark.png" width="240" alt="grimdark theme preview">       | black       | white | forge-amber | Cinzel Decorative + UnifrakturMaguntia | Warhammer-40K Imperial Gothic (gunmetal bulkhead) |
| `sampler`     | <img src="idle_hours/assets/previews/sampler.png" width="240" alt="sampler theme preview">         | cream/white | black | red    | Silkscreen (pixel)   | Counted cross-stitch embroidery sampler (custom layout) |
| `anna_atkins` | <img src="idle_hours/assets/previews/anna_atkins.png" width="240" alt="anna_atkins theme preview"> | Prussian blue | white | sky-blue | Libre Caslon Text + Pinyon Script | Anna Atkins 1843 botanical cyanotype (dithered photogram) |
| `diags`       | <img src="idle_hours/assets/previews/diags.png" width="240" alt="diags theme preview">             | white       | black | red    | DejaVu Sans          | Calibration / status panel    |

`diags` replaces the literary frame with a status panel — big clock + picker metrics (bucket / layout / quality / source / matched phrase), a `HOST` / `IP` / `UPTIME` strip, the Spectra 6 native palette, and the synthesised 2-ink stipple recipes documented in [`CLAUDE.md`](CLAUDE.md). Useful for on-panel colour calibration ("does `mint` actually read as green at viewing distance?") and for confirming the picker chose what you'd expect. It is **excluded from `--theme random`** (a random pick replacing the literary frame with a swatch screen would be surprising); manual selection via button B / web dropdown still works.

`astrarium` is the second theme that bypasses the literary layout (the first being `diags`). Renders a two-column dashboard: an astronomical-clock dial on the left (outer minute-tick ring, four halftone quadrants painted via the documented two-ink stipples — tangerine R+Y, sepia R+G, teal G+B, black with a seeded constellation speckle — and a central HH:MM digital readout), the quote on the right with the matched phrase in R+Y tangerine, and a bottom datum strip with two instrument-style panels — solar elevation (derived from time of day) and lunar phase (derived from day of year). Body type is **EB Garamond** — a humanist Renaissance old-style serif chosen for its eInk legibility, the same body face `illuminated` / `gothic` / `tarot` use. The earlier revision used Cormorant Garamond, but Cormorant's hairline strokes drop below 1 px on the Spectra 6 pixel grid at the dashboard's 18-38 pt fit range and disappear into the cream-washed ground; EB Garamond's even, moderate-contrast strokes survive the panel intact while preserving the period editorial register the dashboard wants. Same dispatch pattern as `diags`: the custom render path replaces the standard layout, so the `--mode debug` overlay does not apply.

`cartograph` is a hand-drawn antique cartographer's chart — the terrestrial-map sibling of the navigation trio that already includes `firmament` (celestial atlas) and `astrarium` (instrument-panel dashboard). Eleven-layer composition on a cream Y+W Bayer-washed parchment ground: a sepia 9×5 latitude/longitude **graticule** with degree-tick stubs at the canvas edges (the single biggest "this is a chart" cue — parallels and meridians are what turn an illustrated page into a navigable map); eight **rhumb lines** radiating from the compass rose at every 45° to the canvas edges (the canonical portolan-chart marking that signals navigational use); a sepia **foxing scatter** for aged-paper texture; two diagonal-corner **coastline silhouettes** at TL and BR, filled in R+G sepia via the documented two-ink recipe; three small scattered **islands** in the open-sea margins; an R+Y tangerine **compass rose** at the bottom-left (8-point — four long cardinals + four shorter ordinals); a small black **sea-serpent doodle** in the bottom-mid sea ("here be dragons" margin convention); three Latin **place-name labels** in italic sepia (*Mare Incognitum* top centre, *Insula Aurea* top right, *Terra Nova* bottom centre); and a doubled red+black rubricated **cartouche knockout** around the body text with small registration-cross corner accents, echoing the doubled rule `illuminated` and `tarot` use, here scaled inward as a contained cartouche rather than a page frame. Body in **IM Fell English Italic** (the period-accurate cartographic register 17th-century mapmakers used for ocean and place labels — promoting the Oxford-press italic from the ornament-only role `herbarium` uses for its Latin specimen tag to a primary body face is a fresh silhouette in the rotation). The matched-phrase role picks IM Fell *Regular* (upright Roman) — the canonical "place name vs body prose" distinction every real cartographer made, so differentiation arrives via colour (red) + roman/italic split rather than weight alone. Unlike `astrarium` / `marquee` / `tarot` / `vinyl`, `cartograph` runs through the **standard render path**, so the `--mode debug` overlay applies — the DEBUG MODE banner clears the chart in the top-right corner by design.

`marquee`, `tarot`, and `vinyl` are three more custom-render themes that follow the `astrarium` pattern — each dispatches out of `render()` into its own frame function and owns its composition top to bottom. **`marquee`** is a 1930s movie-palace facade: a black ground framed by an alternating yellow + red bulb-light border around the entire perimeter (with small white highlight pixels on each bulb so they read as lit glass), big chunky Bungee Shade book title at the top as the "feature title" (uppercased, auto-shrunk through 72→32pt and wrapping to two lines for long titles), a NOW SHOWING tagline above and ONE NIGHT ONLY below, the literary quote rendered in white Cardo Italic with a red matched-phrase accent as the feature copy, and a WRITTEN BY [AUTHOR] credit chrome at the bottom (yellow Antonio Bold label + white Cardo Italic name). The digital HH:MM is deliberately never surfaced — the matched-phrase red highlight in the body carries the time signal, the way every other quote-based literary clock does. **`tarot`** is a single centred major-arcana card on a cream-and-sepia foxed vellum ground: doubled red+black rubricated border with playing-card-style Roman numerals in all four corners (bottom pair rotated 180°), Roman-numeral hour at top (Cinzel Decorative Black), matched-phrase card name in Tyrian purple (R+B 1:1 dither), an hour-mapped emblem at centre (all twelve trumps — Magician through World — ship as detailed line-work templates, ~140–200 px tall), EB Garamond body sitting in a clean cream cartouche knocked out of the surrounding foxing, centred attribution. **`vinyl`** is a turntable + LP back-cover, framed as a 1950s/60s **literary audiobook recording** — same chassis a music LP would have, but with the chrome text in the spoken-word register that real labels like Caedmon Records (Dylan Thomas, T. S. Eliot, Auden) and Spoken Arts pressed during the original audiobook-on-vinyl era. A black vinyl LP fills the left half (centre at (200, 240), radius 200, densely-packed concentric groove hairlines + smooth dead-wax ring + heavier lead-in groove at the rim); a pivoted black tonearm pivots from the upper-right of the turntable with a visible counterweight + cartridge headshell + red stylus pin contacting the disk at the current-minute rim position (sweeping clockwise from 12-o'-clock). The red 80-px-radius label at the spindle carries an outer black ring border, a `· SPOKEN WORD ·` format mark, the matched-phrase passage title, an `IDLE HOURS / READ ALOUD` brand stack, a Space Mono catalog number like `IH-H2-30`, and a `© YYYY` year stamp. The right half is a cream-washed liner-notes panel: a small red `— READING —` heading at the top, the literary quote in Cormorant Garamond with a tangerine R+Y matched-phrase substitution, author/title attribution, and a bottom catalog bar reading `IDLE HOURS LITERARY RECORDINGS  ·  CAT NO. …  ·  © YYYY`. A `33 RPM` badge sits in the top-right corner. As with the other custom-render themes, `--mode debug` does not apply.

**`vitrail`** is a Gothic stained-glass cathedral window, and the theme that leans hardest into the panel's full colour gamut. Black lead-came tracery divides the canvas into an irregular hand-leaded mosaic of jewel-toned glass shapes (a jittered lattice split into varied quadrilaterals and triangular shards, not a uniform grid) that deliberately surface the entire synthesized Spectra 6 palette — the four saturated native inks plus amber/gold, royal purple, teal, plum, lavender, rose, sky-blue, olive, mint, navy and forest, each built from the documented stipple recipes so the frame stays on-palette. The came is drawn as a beveled raised bar (a white specular highlight on the upper-left, a black drop shadow on the lower-right) so it reads as a physical 3D lead frame standing proud of recessed glass rather than flat lines, and diagonal specular sheen bands are swept across the panes so the glass reads as a glossy reflective surface catching light. A pointed lancet arch is carved into the top; a rose-window medallion divides a stone-ringed glass disc into twelve jewel-tone petals and carries the Roman-numeral hour (in Uncial Antiqua) at its hub. The literary quote glows in a clear white-glass central cartouche knocked out of the colored field so the EB Garamond body and the violet-glass matched phrase stay legible, with author/title at the cartouche foot. The digital HH:MM is never surfaced — the matched phrase and the rose-window numeral carry the time. Fully deterministic and, like the other custom-render frames, dispatched out of `render()` into its own frame function (so `--mode debug` does not apply).

**`outrun`** is a 1980s synthwave / Outrun sunset — the "neon poster" counterpart to the cool digital themes (`nightvision` terminal-green, `chrono` JRPG-blue). Composition: a two-zone Bayer density-ramp dusk sky (deep indigo-navy zenith → blue → magenta horizon, with all the warm colour reserved for the sun so the quote keeps high white-on-cool contrast), a deterministic starfield, a neon perspective grid (magenta verticals fanning from a central vanishing point + cyan horizontals with perspective spacing, plotted per-pixel via Bresenham so the two-tone neon stays on the Spectra 6 palette), a bright horizon line, and the iconic **sliced retrowave half-sun** rising from behind the grid (yellow→tangerine→magenta gradient cut by horizontal slits that widen toward the horizon). The literary quote floats in the dark upper sky in white Oxanium (a techno display sans) with the matched time-phrase in synthesised magenta (a red-biased red+blue stipple that ties to the magenta grid verticals), and an Antonio author/title credit line sits below. The digital HH:MM is never surfaced — the matched phrase carries the time. Fully deterministic and, like the other custom-render frames, dispatched out of `render()` into its own frame function (so `--mode debug` does not apply).

Pass `--theme auto` to let the clock pick by wall-clock time. The defaults are `default` during the day (06:00–18:00) and `dark` at night (18:00–06:00) — the legacy binary contract. Broaden the rotation by setting `--auto-day-theme` and/or `--auto-night-theme` to any other registered theme, e.g.

```bash
idle-hours run --theme auto --auto-day-theme scholar --auto-night-theme nightvision
```

`auto` itself is rejected for the day/night picks (would be a config typo, not a useful recursion). A manual button-B press (or a web-UI dropdown jump) overrides `auto` until the next midnight rollover, when the override clears and `auto` resumes.

Pass `--theme random` to pick a theme at random each time the displayed quote changes (so every new bucket gets a fresh look). Picks are drawn from a shuffled bag rather than uniformly, so you see every eligible theme once before any repeats — and the most recent half of the rotation is held back from the front of the next pass, so a theme shown at the end of one pass can't turn up again a pick or two later. The pick is held for the lifetime of the displayed quote and is **not persisted** — a restart picks a fresh theme on the first render. Button B / the web-UI dropdown still wins over the random pick until midnight, the same way it wins over `auto`.

Button B cycles forward through the list and wraps; the curator web UI at `/api/themes` exposes the same cycle plus a dropdown that jumps directly to any named theme. Clicking Apply on an unchanged selection is a no-op — it won't burn a 10–20 s eInk refresh and won't silently disable `auto` / `random` mode.

> Regenerate previews: the images under `idle_hours/assets/previews/` can be rebuilt by looping over `render_quote.THEME_ORDER` and calling the `render_quote.py` CLI for a fixed time, e.g.:
>
> ```bash
> for theme in default dark swiss scholar herbarium newsprint nightvision blueprint illuminated gothic bauhaus risograph comic dispatch atomic marker saloon roman alchemy grimoire deco glacier mucha chalkboard placard chanbara lcars fillmore firmament astrarium kanagawa marquee tarot vinyl cartograph questline chrono outrun circuit letter grimdark sampler anna_atkins diags; do
>   idle-hours render --time 14:15 --theme "$theme" --mode production \
>     --output "idle_hours/assets/previews/$theme.png"
> done
> ```
>
> The PNGs are checked in so the README renders on GitHub without a build step. Every bundled typeface ships under `idle_hours/fonts/` (Playfair Display, Bitter, Old Standard TT, Space Mono, Archivo, EB Garamond, UnifrakturMaguntia, Jost, Rubik, Bangers, Special Elite, Atomic Age, Permanent Marker, Rye, Cinzel Decorative, IM Fell English, MedievalSharp, TFoustScript, Righteous, Iceland, Playwrite GB J Guides, Patrick Hand SC, Shojumaru, Antonio, Inter, Cormorant Garamond, Berkshire Swash, Bungee Shade) so the previews are reproducible without any system-font install. All bundled faces are OFL-licensed except Special Elite and Permanent Marker, which ship under Apache 2.0 (see `idle_hours/fonts/special-elite/LICENSE.txt` and `idle_hours/fonts/permanent-marker/LICENSE.txt`), and `idle_hours/fonts/TFoust.ttf` (TFoustScript, used by `grimoire`) whose font-metadata records `© 2025 myfont All rights reserved` with no explicit OFL/Apache grant — check redistribution terms with the upstream font source before shipping.

### Inky buttons (short and long press)

The four capacitive buttons on an Inky Impression 7.3 are active whenever `run_clock.py` runs on a Pi with the `gpiozero` package installed. Pass `--buttons-off` on dev hosts or for headless smoke tests.

| Button | Short press | Long press (2s) |
|---|---|---|
| **A** | Skip — bans the current quote in the history ledger and picks a new one. | Un-skip — removes the last-skipped ban from the ledger and re-renders. Reverses a fat-fingered tap. |
| **B** | Cycle theme — advances through `default → dark → scholar → newsprint → nightvision → blueprint → illuminated → bauhaus → risograph → comic` (wraps), persists to `--state-path`. The curator web UI also exposes a dropdown that jumps straight to any named theme. | — |
| **C** | Source card — shows a 5-second overlay with the title / author / Gutenberg ID / matched phrase. | — |
| **D** | Quiet now / wake — toggles the manual quiet override, persists to `--state-path`. | Shutdown — shows the goodnight frame, then runs `--shutdown-command` (default `sudo -n shutdown -h now`; empty to disable). |

Short and long actions are mutually exclusive per press: a long press fires only the hold callback, a quick tap fires only the short one.

If a button press lands while a render is already in flight (a Spectra 6 refresh can take 10–20s), the press is logged and dropped rather than queued — the UX is "first press wins, subsequent taps during that refresh are no-ops." Each hardware press is also logged with its GPIO pin so you can confirm the physical button reached the expected handler; for deeper wiring diagnosis run `idle-hours probe-buttons` on the Pi. The main loop also watches for a dead button listener (pin claim lost, background thread crashed) and logs one loud warning plus a telemetry entry if it detects one — presses won't work again until the process restarts.

### Persisted runtime state and telemetry

The loop can persist the manual theme and quiet overrides so they survive a restart, and it can log one JSONL entry per render/error for after-the-fact "is the appliance OK?" checks.

```bash
# Default paths (pass an empty string to disable either)
idle-hours run \
  --state-path ~/.idle-hours/state.json \
  --telemetry-path ~/.idle-hours/telemetry.jsonl

# Human-readable telemetry summary for the last 24h
idle-hours health --hours 24

# JSON summary for cron / systemd health checks (exits 2 when unhealthy)
idle-hours health --hours 1 --json --fail-if-no-renders

# Exit 2 if the panel hasn't repainted recently (a loop can heartbeat while stuck in backoff).
idle-hours health --hours 24 --max-render-age-minutes 90

# systemd installs relocate telemetry under /var/lib/idle-hours; read the path from the same
# config file the unit uses instead of restating it. An explicit --telemetry-path still wins.
idle-hours health --config /var/lib/idle-hours/config.toml --hours 24
```

Every file the next tick or boot reads is written atomically (`tmp → fsync → rename → fsync dir`) via the shared `atomic_io` helpers — runtime state, the rendered `output/current.png`, the selection-overrides sidecar, the history-ledger rewrite path, and the `apply_content_overrides` corpus writeback. A power cut or `SIGKILL` mid-write leaves the previous-known-good file byte-identical; it never leaves a truncated PNG or an empty ledger.

`SIGTERM` and `SIGINT` are handled gracefully: `systemctl restart idle-hours.service` flips a shared event that the main loop observes between ticks, drains any in-flight render via `state.render_lock`, stops the curator web server, closes GPIO buttons, and persists runtime state one last time before the process exits. `--once` keeps strict-exit behaviour for cron callers.

Telemetry is rotated by date: the `--telemetry-path` argument is a base path, but `run_clock.py` actually writes to `<stem>-YYYYMMDD<suffix>` siblings (e.g. `~/.idle-hours/telemetry-20260420.jsonl`) so a multi-year-running appliance keeps file size bounded. `--telemetry-retain-days` (default 90; pass 0 to disable) unlinks siblings older than that once per local-date rollover. `idle_hours_health.py` globs the directory for those siblings plus any legacy unsuffixed file at the exact base path and stream-reads them in order.

`idle_hours_health.py` exit codes:

- `0` — healthy (renders happened in the window, or no errors with nothing scheduled)
- `1` — telemetry log missing
- `2` — unhealthy: errors but zero renders, or `--fail-if-no-renders` with a silent window

### Startup frame

```bash
# Optional: push a static frame to the panel before the first quote renders
# so a cold boot doesn't ghost yesterday's image.
idle-hours run --startup-image assets/goodnight.png
```

The extra refresh costs a Spectra 6 cycle (~10–20s) so this is off by default; enable when you care more about clean boot visuals than time-to-first-quote.

### Curator web UI

Off by default. Pass `--web-bind` to expose a small local HTTP surface that mirrors the physical buttons and lets you browse the corpus:

```bash
# Loopback only: safe to run anywhere, no auth required.
idle-hours run --web-bind 127.0.0.1:8080
# open http://127.0.0.1:8080 in a browser

# LAN exposure: every POST requires a token supplied via X-Idle-Hours-Token.
# Prefer --web-token-file on production so the token doesn't show up in `ps`.
echo "s0me-l0ng-random-string" > ~/.idle-hours/web.token
chmod 640 ~/.idle-hours/web.token
idle-hours run --web-bind 0.0.0.0:8080 --web-token-file ~/.idle-hours/web.token
```

#### Turning the web UI on for an existing install

There is nothing extra to install — `web_server.py` and `idle_hours/web/` already ship with the repo and the UI is just a CLI flag on `run_clock.py`. To enable it on a box that is already running, add `--web-bind` to however you launch `run_clock.py`:

**Dev machine (foreground run).** Stop the current process and relaunch with the flag:

```bash
idle-hours run --web-bind 127.0.0.1:8080
# then open http://127.0.0.1:8080
```

**Pi running under systemd.** Edit the config file that `ExecStart=` points at — no `daemon-reload` needed when you stay inside the config:

```bash
sudoedit /var/lib/idle-hours/config.toml
# add: web_bind = "127.0.0.1:8080"
sudo systemctl restart idle-hours.service
systemctl status --no-pager idle-hours.service     # confirm it came back up
```

`idle_hours/assets/config.toml.example` already ships commented-out `web_bind` / `web_token_file` lines near the bottom — uncomment the pair you want and you're done. (If the unit still uses raw `--web-bind` CLI flags on `ExecStart=`, `sudoedit` the unit itself and `daemon-reload` first, then `restart`.)

> **Required for saving under systemd.** The unit sets `ProtectSystem=strict`, which mounts the installed package read-only — and the selection-overrides sidecar, the content-overrides sidecar, and the baked DB all live *inside* that package by default. Leave them there and the UI browses fine but every save and every **Bake now** returns HTTP 500 with a read-only-filesystem error. Relocate the four files into the state dir (already writable via `ReadWritePaths=`) by setting these in `/var/lib/idle-hours/config.toml`:
>
> ```toml
> overrides         = "/var/lib/idle-hours/selection_overrides.json"
> content_overrides = "/var/lib/idle-hours/content_overrides.json"
> raw_corpus        = "/var/lib/idle-hours/candidates-attributed.jsonl"
> baked_db          = "/var/lib/idle-hours/quote_database.jsonl"
> ```
>
> `config.toml.example` ships these pre-filled. On the next start, `run_clock` copies each bundled file to any of those paths that doesn't exist yet — so the committed bans, boosts, and per-row content fixes migrate across with no manual step, and existing files are never overwritten. Both the runtime picker and the curator UI read these same paths, so a ban applied in the UI takes effect on the panel at the next bucket change. Don't add the package directory to `ReadWritePaths=` instead — writing into `site-packages` defeats the sandbox and is clobbered on the next upgrade.

**Reaching a loopback-bound UI from another machine.** Keep the `127.0.0.1:8080` bind (no token needed) and SSH-tunnel into the Pi from your laptop:

```bash
ssh -L 8080:127.0.0.1:8080 pi@raspberrypi.local
# leave that session open, then open http://127.0.0.1:8080 on your laptop
```

**Reaching it directly over the LAN.** Switch to `0.0.0.0:8080` *and* supply a token file — `start_web_server` refuses to bind a non-loopback address without one, so you cannot accidentally expose a tokenless POST surface:

```bash
sudo install -m 640 -o pi -g pi /dev/null /var/lib/idle-hours/web.token
python3 -c "import secrets; print(secrets.token_urlsafe(32))" | sudo tee /var/lib/idle-hours/web.token > /dev/null
# edit /var/lib/idle-hours/config.toml to set:
#   web_bind       = "0.0.0.0:8080"
#   web_token_file = "/var/lib/idle-hours/web.token"
sudo systemctl restart idle-hours.service
```

Browsers can still `GET` the UI without credentials (telemetry, coverage, `current.png` are not sensitive), but every mutating `POST` must send `X-Idle-Hours-Token: <the token>`. **Caveat:** the bundled `idle_hours/web/` UI does not currently attach that header — it was built for the loopback-no-auth path — so on a LAN+token bind the page loads and reads cleanly but the action buttons and overrides-save will come back as `401 missing or invalid token`. Until the UI grows a token field, the working options for a LAN+token deployment are:

- Drive mutating endpoints from `curl` (or any other client), e.g. `curl -X POST -H "X-Idle-Hours-Token: $(cat ~/.idle-hours/web.token)" http://<pi>:8080/api/action/rerender`.
- Or just use the SSH-tunnel flow above — loopback bind needs no token and the bundled UI works end-to-end.

**How to tell it's working.** `journalctl -u idle-hours.service -n 20` should show a line like `web UI listening on 127.0.0.1:8080 (no token)` (or `(token required)` on a LAN bind). If the bind fails (port busy, missing token on a non-loopback bind) the main render loop keeps running and logs `web UI failed to start on …` — the panel won't go dark just because the web UI couldn't start.

The UI is vanilla HTML/JS/CSS served directly from `idle_hours/web/` — no build step, no framework, no extra runtime deps beyond what the clock already needs. **v2 reorganises it into a mobile-first four-tab layout** (Now / Curate / Coverage / Activity) with 44px tap targets and breakpoints at 768px (tablet) and 1024px (desktop), so the same UI works equally well from a phone-on-the-counter and a laptop. Tab state is kept in `location.hash` so a bookmark like `idle-hours.local#curate` jumps straight to the editor.

#### First-run wizard (v2)

A modal overlay appears on the very first visit to a fresh appliance: pick a theme from a thumbnail grid (each tile is a live `/api/preview` PNG of the current quote in that theme), confirm the configured quiet hours, dismiss. Choices are persisted to `state.json` so the wizard never reappears. Nothing about the clock loop changes — it's the discovery surface for knobs that were already CLI-configurable.

#### Tab: Now

- Live preview of `output/current.png`, the picked quote text, attribution (`source_id` + `line_number`), and the matched time phrase the renderer bolded.
- Five buttons that mirror the physical Inky panel (`A · Skip`, `A-hold · Un-skip`, `B · Cycle theme`, `C · Re-render`, `D · Quiet / wake`) plus a theme dropdown that jumps directly to any registered theme.
- **Ban this quote** button (v2): adds the current `(source_id, line_number)` to `ban_quote_keys` in the selection overrides sidecar so the picker never returns this exact row again — the rest of the source still works normally.
- Theme thumbnail grid: side-by-side previews of all forty-five registered themes, rendered against the current quote so you can compare typography + palette before committing. Click a tile to apply it.

#### Tab: Curate

- **Corpus search** (v2): full-text + author + title + bucket filters. Linear stdlib scan over the raw attributed corpus (~3K rows, <50 ms). Reads the raw corpus, not the baked DB, so an operator looking for "where did this quote go?" can find rows the baker dropped (low quality / daypart-only) and see why they're not appearing.
- **Bucket inspector**: ranked candidate list for any bucket (or `HH:MM`), with every scorer component named so you can see *why* a different quote was not picked. Each candidate has its own "Ban this quote" button.
- **Selection-overrides editor**: edits `idle_hours/assets/selection_overrides.json` inline; server validates (rejects bad bucket keys, malformed `ban_quote_keys` entries) and atomically rewrites.
- **Content-overrides editor (v2)**: edits `idle_hours/assets/content_overrides.json` — the per-row content sidecar applied at bake time. Strict per-field validation; allowed fields match `apply_content_overrides.ALLOWED_FIELDS` exactly.
- **Bake now (v2)**: re-runs `bake_quote_database.bake_rows` in-process, re-applying the content-overrides sidecar first so a "edit row → save → bake" flow drops new excerpts onto the panel within seconds. Held under `render_lock`; returns 409 (busy) if a render is in flight.

#### Tab: Coverage

- 144-cell bucket grid coloured by corpus depth; click-through feeds the inspector.
- **Bucket gap finder (v2)**: empty/sparse buckets surfaced with phrase suggestions lifted from `target_sparse_buckets.STATE_TEMPLATES`, so the suggested phrases match what the targeted-mining CLI would actually look for. Adjustable threshold; sorted emptiest-first.

#### Tab: Activity

- Telemetry: renders / errors / p50 / p95 latencies over the last 24 h, reading the same date-rotated sidecar that `idle_hours_health.py` does.
- History: the anti-repeat ledger, newest first.

The UI shares the render lock with the button handlers, so every mutating action (skip, un-skip, theme, quiet, re-render, overrides save, bake) respects "first press wins": a POST that lands during a 10–20s Spectra 6 refresh returns `409 busy` instead of queueing.

| Endpoint | Purpose |
|---|---|
| `GET /` | Curator HTML/JS/CSS (mobile-first four-tab layout) |
| `GET /current.png` | Streams the current rendered frame |
| `GET /metrics` | **v2** — Prometheus text-exposition format over a 24 h window (renders / errors / heartbeats / actions / latency p50+p95 / `last_heartbeat_age_seconds`). Unauthed on every bind. |
| `GET /api/current` | `{time, bucket, theme, source_id, line_number, display_quote, matched_text, ...}` |
| `GET /api/telemetry?hours=24` | p50/p95 render/display latency + error counts (reuses `idle_hours_health`) |
| `GET /api/coverage` | The 144-bucket coverage, computed live from the running corpus (falls back to `idle_hours/assets/bucket-coverage.json`) |
| `GET /api/gaps?threshold=N` | **v2** — empty/sparse buckets with harvester phrase suggestions |
| `GET /api/themes` | `{themes, theme_arg, manual_theme, effective}` — feeds the dropdown |
| `GET /api/bucket/<bucket>?time=HH:MM&top=N` | Full ranked candidate list with per-component scores |
| `GET /api/search?q=&author=&title=&bucket=&limit=N` | **v2** — linear-scan full-text search over the raw corpus |
| `GET /api/preview?theme=&time=HH:MM&width=&height=` | **v2** — render the current quote as PNG bytes in any theme (history disabled for determinism); side-effect-free |
| `GET /api/overrides` | Current `idle_hours/assets/selection_overrides.json` (now includes `ban_quote_keys`) |
| `GET /api/content-overrides` | **v2** — current `idle_hours/assets/content_overrides.json` (fail-open on corrupt sidecar) |
| `GET /api/setup` | **v2** — first-run wizard status + the values it shows (themes, quiet hours) |
| `GET /api/history?limit=N` | Recent anti-repeat ledger entries, joined against the corpus so each carries its quote text and attribution |
| `POST /api/overrides` | Validate + atomically rewrite selection overrides (now accepts `ban_quote_keys`) |
| `POST /api/content-overrides` | **v2** — validate + atomically rewrite the per-row content sidecar; empty `{}` is a legitimate "wipe everything" |
| `POST /api/bake` | **v2** — re-run `bake_quote_database.bake_rows` in-process under `render_lock`; re-applies the content-overrides sidecar first so save → bake reflects on the next tick. 409 when busy. |
| `POST /api/setup` | **v2** — mark first-run wizard complete; optional `{"theme": "<name>"}` body applies a theme before dismissing |
| `POST /api/action/{skip,unskip,theme,quiet,rerender}` | Mirrors buttons A/A-hold/B/D/C. `theme` accepts an optional `{"theme": "<name>"}` body to jump directly; empty body / missing field cycles. Malformed JSON returns 400 without mutating state. |

Security model: loopback binds (`127.0.0.1:*`, `localhost:*`, `::1:*`) skip auth entirely — the OS-level trust boundary is sufficient. Any other bind **requires** `--web-token` / `--web-token-file`; startup aborts rather than quietly expose a tokenless POST surface. Tokens are checked via the `X-Idle-Hours-Token` header only; query-string tokens would leak into journald via HTTP request logging. GETs remain open on all binds — telemetry and `current.png` are not sensitive and the UI needs them without credentials.

### Quiet hours

The loop defaults to quiet hours **22:00–06:00** and pushes `idle_hours/assets/goodnight.png` to the display during that window instead of rendering corpus quotes.

```bash
# Shift or tighten the window
idle-hours run --quiet-start 23:30 --quiet-end 07:00

# Swap the quiet image
idle-hours run --quiet-image path/to/other.png

# Disable quiet hours entirely (24/7 rendering)
idle-hours run --quiet-off
```

## Testing

Run the full test suite:

```bash
pytest
```

Run a targeted subset:

```bash
pytest tests/test_render_quote.py tests/test_run_clock.py
```

## Raspberry Pi deployment

The Pi should track `main` and use the prebuilt runtime assets already committed to the repo.

### Fresh Pi setup

For a brand-new Raspberry Pi, the setup has two phases:

1. install the Pimoroni Inky stack and verify the panel works
2. clone Idle Hours, render once, push once, then install the service

#### OS baseline

- Raspberry Pi OS Bookworm or later
- SSH enabled
- Wi-Fi configured

Update the box first:

```bash
sudo apt update && sudo apt upgrade -y
sudo reboot
```

#### Install system dependencies

```bash
sudo apt install -y git python3 python3-pip python3-venv python3-dev fonts-noto-core fonts-dejavu-core
```

#### Install Pimoroni Inky software

Pimoroni's installer is the supported path:

```bash
git clone https://github.com/pimoroni/inky ~/inky
cd ~/inky
./install.sh
```

Suggested installer answers:

- yes to virtualenv setup
- yes to example dependencies
- yes to copying examples
- docs optional

If the display does not work afterward, check `SPI` and `I2C` in `sudo raspi-config`, then reboot.

#### Verify the Inky panel works

```bash
source ~/.virtualenvs/pimoroni/bin/activate
cd ~/Pimoroni/inky/examples/spectra6
python3 -m idle_hours.stripes
```

#### Install Idle Hours on the Pi

```bash
source ~/.virtualenvs/pimoroni/bin/activate
git clone git@github.com:gkoch02/idle-hours.git
cd ~/IdleHours
idle-hours run --once
idle-hours display output/current.png
idle-hours run --once --display-script display_inky.py --mode production
```

At that point, a fresh Pi should have everything needed to render locally and push to the display.

#### Optional bootstrap helper

There is also a helper script for first-time setup:

```bash
bash scripts/bootstrap_pi_inky.sh
```

That script installs base packages, launches the interactive Pimoroni installer, and then resumes Idle Hours setup after reboot.

### Existing Pi update flow

If the Pi is already provisioned and Idle Hours is installed, updating is simple:

```bash
git pull --ff-only origin main
sudo systemctl restart idle-hours.service
systemctl status --no-pager idle-hours.service
```

### Example service

See `ops/idle-hours.service.example`.

Current service model:

- runs `run_clock.py`
- optionally calls `display_inky.py` after each render
- reads the prebuilt baked DB at `idle_hours/assets/quote_database.jsonl` (the canonical runtime input)
- does not rebuild corpus artifacts at startup

### Install the service

Once manual render and display tests work on the Pi:

```bash
cd ~/IdleHours

# Stage the unit file and the config it references. The unit declares
# StateDirectory=idle-hours, which auto-creates /var/lib/idle-hours on service
# start — but we need the config file in place BEFORE the first start
# (the sample unit passes --config %S/idle-hours/config.toml exclusively,
# and a missing --config path is a hard error by design).
sudo cp ops/idle-hours.service.example /etc/systemd/system/idle-hours.service
sudoedit /etc/systemd/system/idle-hours.service    # fix User= / WorkingDirectory= / ExecStart= paths

sudo install -d -o pi -g pi -m 0750 /var/lib/idle-hours
sudo install -o pi -g pi -m 0640 \
    idle_hours/assets/config.toml.example /var/lib/idle-hours/config.toml
sudoedit /var/lib/idle-hours/config.toml           # tune keys for this appliance

sudo systemctl daemon-reload
sudo systemctl enable --now idle-hours.service
sudo systemctl status idle-hours.service
```

Before enabling the service, update these fields to match the actual account and install path on the Pi:

- `User=`
- `WorkingDirectory=`
- `ExecStart=` (the path to `run_clock.py` and to the config file)

Day-to-day tuning after this — theme, quiet hours, web UI, startup
image, etc. — is a `sudoedit /var/lib/idle-hours/config.toml` +
`systemctl restart`. No `daemon-reload` because the unit file itself
doesn't change.

If another display service is already running, disable it first so Idle Hours owns the panel.

## Build pipeline notes

The build side of the repo exists to improve quote coverage and quality over time.

At a high level, the process is:

1. mine public-domain texts for time phrases
2. clean candidate quotes into displayable form
3. enrich and score them
4. merge and analyze coverage
5. apply per-row hand fixes from `idle_hours/assets/content_overrides.json`, producing the raw attributed corpus at `idle_hours/assets/candidates-attributed.jsonl`
6. bake that corpus into the display-ready `idle_hours/assets/quote_database.jsonl`, which is what the runtime clock actually reads

That work is intentionally separate from the steady-state render loop. Re-running step 6 (`bake_quote_database.py`) is what makes new corpus rows visible to a running appliance — committing raw-corpus changes without a matching bake ships no runtime effect.

## Operational notes

- The clock refreshes when the fuzzy time bucket changes, not every minute, and additionally skips a redraw when the picked quote is identical to the previous frame.
- If the exact bucket is weak or empty, the picker walks nearby buckets and records fallback metadata.
- `production` mode hides debug metadata for cleaner display output; `debug` mode draws a top-right `DEBUG MODE` banner and a centered bottom strip with bucket/layout/quality/id.
- Quiet hours are on by default (22:00–06:00) and show `idle_hours/assets/goodnight.png`; override with `--quiet-start` / `--quiet-end` / `--quiet-image`, or disable with `--quiet-off`. Button D toggles a manual quiet override at any time.
- Button B cycles through the full theme list and persists the choice to `--state-path`; the web UI dropdown jumps directly to any named theme. Button A's long press reverses the most recent skip.
- Forty-five themes ship built-in (full table with previews in the [Themes](#themes) section above): `default`, `dark`, `swiss`, `scholar`, `herbarium`, `newsprint`, `nightvision`, `blueprint`, `illuminated`, `gothic`, `bauhaus`, `risograph`, `comic`, `dispatch`, `atomic`, `marker`, `saloon`, `roman`, `alchemy`, `grimoire`, `deco`, `glacier`, `mucha`, `chalkboard`, `placard`, `chanbara`, `lcars`, `fillmore`, `firmament` (17th-century celestial atlas — navy synthesised ground, white Cardo serif body, gold cream matched phrase, constellation polylines + corner astronomy ornaments), `astrarium` (astronomical-clock dashboard — custom dial-plus-quote layout), `kanagawa` (Hokusai-inspired seigaiha woodblock — Yuji Boku sumi-brush body, indigo fish-scale wave pattern, hanko seal), `marquee` (1930s movie-palace facade — custom layout, alternating yellow + red bulb-light border, big Bungee Shade book-title chrome, Cardo Italic body, WRITTEN BY credit chrome), `tarot` (major-arcana card — custom layout, Roman-numeral hour + Tyrian-purple card name + hour-mapped emblem), `vinyl` (turntable + literary-audiobook LP back-cover — custom layout, pivoted tonearm as the minute indicator, Caedmon-Records-style spoken-word chrome), `vitrail` (Gothic stained-glass window — custom layout, black lead-came tracery over jewel-toned glass panes spanning the full synthesized palette, rose-window Roman numeral, quote on a clear white-glass cartouche), `cartograph` (antique cartographer's chart — IM Fell English Italic body, sepia coastlines + compass rose + sea-serpent doodle), `questline` (8-bit RPG dialogue scene — custom layout, Press Start 2P pixel face, author as the speaking NPC), `chrono` (16-bit SNES JRPG cutscene — custom layout, gradient twilight sky, shaded hourglass portrait window, Pixelify Sans), `outrun` (1980s synthwave sunset — custom layout, neon perspective grid + sliced retrowave sun, Oxanium), `circuit` (printed circuit board — forest-green soldermask, gold copper traces + plated pads, Space Mono silkscreen designators), `letter` (wax-sealed handwritten letter — Dancing Script body, dithered aged-paper plate, oxblood wax seal with a carved hourglass), `grimdark` (Warhammer-40K Imperial Gothic — dithered gunmetal bulkhead plate, gold Aquila + Mechanicus cog-skull, forge-amber matched phrase), `sampler` (counted cross-stitch sampler — custom layout, every glyph stamped as stitched X marks on Aida cloth), `anna_atkins` (1843 botanical cyanotype — Floyd–Steinberg-dithered photogram plate, copperplate Latin species labels, Libre Caslon Text), `diags` (calibration / status panel — excluded from `--theme random`). Every theme colour stays on the Spectra 6 palette.
- `--theme auto` switches dark/default by wall-clock time (dark 18:00–06:00); broaden the rotation past the binary default with `--auto-day-theme` / `--auto-night-theme`. `--theme random` rerolls the theme each time the picked quote changes (not persisted across restarts). A manual button-B / web override wins over either mode until the next midnight rollover.
- Per-theme saturation: `display_inky.py` picks `0.5` for light-background themes and `0.7` for dark-background themes so accents don't go muddy.
- Telemetry at `--telemetry-path` (default `~/.idle-hours/telemetry.jsonl`) is rotated by date — `run_clock.py` writes to a `telemetry-YYYYMMDD.jsonl` sibling so long-running appliances don't accumulate one unbounded file. One line per render, one per loop-level error. `idle_hours_health.py --json` feeds systemd / cron health checks and auto-discovers the rotated siblings.
- The anti-repeat history ledger at `--history-path` (default `~/.idle-hours/history.jsonl`) is fsynced after each append so a power loss can't leave a buffered entry lost, and the reader logs a one-shot warning if it finds a malformed/torn line.
- If the Inky button listener dies mid-run (pin claim lost, background thread failed), the loop logs one loud warning plus a telemetry entry with `mode=buttons_dead` and stops retrying — restart the process to reclaim the pins.
- The optional curator web UI (`--web-bind`) runs in-process on a daemon thread and shares the render lock with the button handlers; it's the safe remote alternative to SSHing in to tap the panel or edit `selection_overrides.json` by hand. LAN binds require `--web-token` / `--web-token-file`.
- **Webhook notifications (v2):** `--webhook-url <url>` posts a JSON body for each alert-worthy telemetry event (errors, backoff, render/display/shutdown timeouts, button-died, state-validation issues, web-auth failures). Heartbeats and successful renders are always filtered (alerting once a minute is spam, not signal). Best-effort: dispatched on a daemon thread with a 5 s timeout, failures log but never block the render path. Pass `--webhook-all-events` to widen the filter.
- **Prometheus `/metrics` (v2):** the curator UI exposes a standard text-exposition endpoint over a fixed 24 h window. Reuses the same `idle_hours_health.summarise` aggregation as `idle-hours health --json`, so the values match exactly. Stays open without auth on every bind so a Prometheus scraper on the LAN can hit it without managing a token.
- **OCI container (v2):** `Dockerfile` provides a multi-stage build (ARM64-first) so the appliance can ship as a container instead of a git clone. Run with `docker run --rm -p 8080:8080 -v idle-hours-state:/state idle-hours:2.5 idle-hours run --buttons-off --skip-preflight --web-bind 0.0.0.0:8080 --state-path /state/state.json --history-path /state/history.jsonl --telemetry-path /state/telemetry.jsonl --pidfile /state/run_clock.pid` for a headless dev instance. The Pi-only `[pi]` extra (`gpiozero` / `inky`) is *not* installed by default — that's a Pi-runtime concern.
- The renderer is tuned for the Pimoroni Inky Impression 7.3 / Spectra 6 800×480 display.
- Final renders are snapped to the exact Spectra 6 palette for better hardware fidelity.
- Renderer changes can be surprisingly fragile around text normalization, wrapping, and emphasis/highlight matching, so keep render tests healthy.

## Useful files when something breaks

If the clock is behaving oddly, these are the first files to inspect:

- quote selection problems -> `pick_quote.py`
- highlight/layout/render issues -> `render_quote.py`
- loop/update/dedup/service behavior -> `run_clock.py`
- display handoff issues -> `display_inky.py`
- button/long-press wiring -> `inky_buttons.py`
- "which GPIO pin did that button actually fire?" -> `idle-hours probe-buttons` on the Pi
- "is the appliance alive?" -> `idle-hours health --hours 24` (use `--json` from cron)
- curator web UI / HTTP endpoints / overrides editor -> `web_server.py` + `idle_hours/web/` (enable with `--web-bind`)
- telemetry log (one JSONL entry per render/error) -> `~/.idle-hours/telemetry.jsonl`
- persisted manual theme / quiet override -> `~/.idle-hours/state.json`
- anti-repeat ledger of recently-shown quotes -> `~/.idle-hours/history.jsonl`
- runtime dataset questions -> `idle_hours/assets/quote_database.jsonl` (what the clock reads) + `idle_hours/assets/candidates-attributed.jsonl` (raw source)

## Contributing and security

- [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) — dev environment, pipeline overview, what to do for each kind of change (runtime / corpus / pipeline / rendering), test conventions.
- [`docs/SECURITY.md`](docs/SECURITY.md) — how to report a vulnerability, what's in and out of scope.
- [`docs/CODE_OF_CONDUCT.md`](docs/CODE_OF_CONDUCT.md) — Contributor Covenant v2.1.

Deeper architecture and design notes live in [`CLAUDE.md`](CLAUDE.md); skim that first when modifying the runtime or pipeline.

There's also a project landing page at [plumpbug.dev/idlehours](https://plumpbug.dev/idlehours/home.html)
(privacy/support pages too, though Idle Hours needs neither an App Store account nor
authentication to use), maintained in the separate
[`gkoch02/plumpbug-site`](https://github.com/gkoch02/plumpbug-site) repo alongside the
other Plumpbug-family projects. This repo stays the source of truth for the theme gallery
and preview PNGs that page embeds.
