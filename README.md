<p align="center">
  <img src="idle_hours/assets/logo.svg" alt="Idle Hours" width="800">
</p>

# Idle Hours

[![CI](https://github.com/gkoch02/Idle-Hours/actions/workflows/ci.yml/badge.svg)](https://github.com/gkoch02/Idle-Hours/actions/workflows/ci.yml)

Idle Hours is a literary clock: every few minutes it shows a sentence from a public-domain novel that names the current time, with the time phrase picked out in bold. Behind it is a pipeline that mines Project Gutenberg for phrases like "a quarter past seven", cleans and scores them, and bakes over two thousand quotes into a database ranked for each five-minute slot of the twelve-hour clock. A Raspberry Pi renders the pick for a six-colour eInk panel and runs unattended as a systemd appliance, with a small web UI for curating the corpus.

<!-- TODO(#354): photo of the physical Inky Impression panel goes here. preview.png below is a render, not the device. -->

![Idle Hours rendered in saloon, gothic, astrarium, and deco themes](idle_hours/assets/preview.png)

The mining pipeline and the appliance runtime are the product. The themes ([full table](#themes), design notes in [`docs/themes.md`](docs/themes.md)) are a deliberately open-ended creative layer built on a shared, golden-tested rendering toolkit.

## How it works

```mermaid
flowchart LR
    A[Gutenberg texts] -->|mine| B[raw candidates]
    B -->|clean + score| C[attributed corpus]
    C -->|bake| D[quote database]
    D -->|pick| E[quote for HH:MM]
    E -->|render| F[800×480 PNG]
    F -->|display| G[eInk panel]
```

1. **Mine.** Regexes find time phrases ("ten minutes to midnight", "the clock struck three") in Gutenberg books; overlapping matches resolve longest-first so "nearly one o'clock" is not also filed at 01:00.
2. **Clean and score.** Each hit becomes a displayable excerpt, gets a 0–100 quality score with named penalty flags, and picks up title and author. Hand fixes live in a sidecar, [`content_overrides.json`](idle_hours/assets/content_overrides.json), applied on top.
3. **Bake.** Ten of the twelve score components do not depend on the requested time. The baker computes them once and stores them on each row, so the runtime only adds the other two.
4. **Pick.** The runtime maps the time to one of 144 fuzzy buckets, ranks candidates, skips anything shown in the last week, and falls back to the nearest neighbouring bucket when one is empty.
5. **Render and display.** Pillow lays out the quote, snaps it to the panel's six inks, and pushes it to the Inky Impression. The loop repaints only when the bucket changes.

## Engineering highlights

- **Bake/raw pick equivalence.** The baked database must pick the same row as scoring the raw corpus live, for every one of the 144 buckets ([`TestPickEquivalenceShippedCorpus`](tests/test_bake_equivalence.py)).
- **Pin fidelity against the shipped corpus.** The runtime peeks a quote, then tells the render subprocess to draw exactly that row. A sweep over every clock time against the real database ([`TestPinFidelityAgainstShippedCorpus`](tests/test_pick_quote.py)) found that `(source_id, line_number)` is not unique, which had put the wrong phrase on the panel for about 8% of times. Every synthetic test had passed.
- **Durability.** State, overrides, the corpus and the rendered PNG are replaced through [`atomic_io`](idle_hours/atomic_io.py) (temp file, fsync, rename, fsync the directory). The append-only history ledger takes a cheaper route: each line is fsynced, and the reader skips a torn last line, so a power cut costs at most one entry. A [`pidfile`](idle_hours/pidfile.py) keeps one instance running. Configuration errors exit 42, which the [systemd unit](ops/idle-hours.service.example) lists under `RestartPreventExitStatus` so it halts instead of flapping; a read-only mount (`EROFS`) counts as configuration, while `ENOSPC` or `EIO` exits 1 and is retried. A pure-stdlib [`sd_notify`](idle_hours/sd_notify.py) client feeds the systemd watchdog.
- **Curator UI security.** Off-loopback binds require a token, checked in constant time with `hmac.compare_digest`. On every bind, POSTs must be `application/json`, `Origin` must match `Host`, and `Host` must be one the bind expects, which blocks DNS rebinding ([`web_server.py`](idle_hours/web_server.py), [`docs/web_ui.md`](docs/web_ui.md)).
- **Tests that fail on absence.** Structural tests fail when something is missing, not only when it changes: a theme that stops painting ([`test_theme_decoration.py`](tests/test_theme_decoration.py)), a doc whose theme count or roster drifts from the registry, a CI job that is not a required check. Each theme also has a golden render compared at 0.1% pixel tolerance ([`test_render_golden.py`](tests/test_render_golden.py)).

## How it was built

<!-- TODO(#354): owner-written. Say plainly that most commits are authored by Claude Code, describe the human role (issue specs, review, hardware integration, release process), and link two or three issues where the spec or review changed the outcome. -->

What the project deliberately does not do, and why, is in [`docs/decisions.md`](docs/decisions.md).

## Table of contents

- [How it works](#how-it-works)
- [Engineering highlights](#engineering-highlights)
- [How it was built](#how-it-was-built)
- [What this repo is](#what-this-repo-is)
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

## Repo map

### Runtime

- `idle_hours_cli.py` - **unified `idle-hours <subcommand>` entry point** (v2). Wraps every script below in one discoverable command; `pip install -e .` registers `idle-hours` as a console script. Every subcommand is also reachable as `python3 -m idle_hours.<module>`.
- `run_clock.py` - long-running clock loop, bucket-change refresh logic, optional display handoff
- `runtime_*.py` - the siblings `run_clock.py` delegates to: `runtime_state` / `runtime_store` / `runtime_telemetry` / `runtime_render` / `runtime_quiet` / `runtime_theme` / `runtime_actions` / `runtime_log` / `runtime_config` / `runtime_webhook` (architecture in [`docs/runtime.md`](docs/runtime.md))
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
- `idle_hours/assets/goodnight.png` - pre-rendered dark-theme sleep frame; optional static alternative to the themed quiet-hours render
- `idle_hours/assets/preview.png` - README preview image

### Build and corpus tools

The full pipeline order is documented in [Build pipeline notes](#build-pipeline-notes) and, stage by stage, in [`docs/pipeline.md`](docs/pipeline.md); the scripts themselves are:

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
- `Dockerfile` + `.dockerignore` - v2 multi-stage OCI build (ARM64-first, Pi-runtime extra not bundled). `docker buildx build --platform linux/arm64,linux/amd64 -t idle-hours:3.0 .`
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

> **Upgrading from LitClock?** This project was previously named LitClock.
> The rename is hard (new package name, new CLI command, new filesystem
> paths, new HTTP token header, new Prometheus metric names, new systemd
> unit). See [`docs/UPGRADE.md`](docs/UPGRADE.md) for the one-time migration steps.

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

`idle-hours <sub> --help` forwards to the backing module's argparse so the
flag list is identical to `python3 -m idle_hours.<module> --help`. The
umbrella CLI is purely additive over that module form; there are no flat
`<script>.py` files at the repo root to run directly.

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

Every theme in `render_quote.THEME_ORDER` ships built-in, each constrained to the Spectra 6 panel palette (white / black / red / yellow / blue / green). Each theme pairs its palette with a dedicated typeface. Every preview below is the same passage at the same time — H. G. Wells, *The Time Machine*, at ten o'clock — so what differs between them is palette, typography and decoration, and nothing else. Regenerate them with `python3 scripts/generate_theme_previews.py --all` (or `--theme NAME` for one, `--check` to see what has gone stale); production renders adapt layout to whichever line the picker returns, so a real panel will not be this uniform.

| `--theme`     | Preview | Page bg | Body  | Accent | Typeface             | Feel                          |
|---------------|---------|---------|-------|--------|----------------------|-------------------------------|
| `default`     | <img src="idle_hours/assets/previews/default.png" width="240" alt="default theme preview">         | white       | black | red    | Playfair Display     | Classic broadsheet            |
| `dark`        | <img src="idle_hours/assets/previews/dark.png" width="240" alt="dark theme preview">               | black       | white | yellow | Playfair Display     | Night mode                    |
| `swiss`       | <img src="idle_hours/assets/previews/swiss.png" width="240" alt="swiss theme preview">             | white       | black | red    | Inter (grotesque sans) | Swiss International modernist |
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
| `alchemy`     | <img src="idle_hours/assets/previews/alchemy.png" width="240" alt="alchemy theme preview">         | yellow/white | black | red    | IM Fell English + MedievalSharp | Parchment grimoire     |
| `grimoire`    | <img src="idle_hours/assets/previews/grimoire.png" width="240" alt="grimoire theme preview">       | black       | white | sky-blue | IM Fell English + Eagle Lake   | Faustian spellbook       |
| `deco`        | <img src="idle_hours/assets/previews/deco.png" width="240" alt="deco theme preview">               | white       | black | red    | Righteous (display sans) | 1930s art-deco poster     |
| `glacier`     | <img src="idle_hours/assets/previews/glacier.png" width="240" alt="glacier theme preview">         | white       | blue  | green  | Iceland (techno display) | Icy / aurora panel        |
| `mucha`       | <img src="idle_hours/assets/previews/mucha.png" width="240" alt="mucha theme preview">             | cream/white | maroon | teal  | Cormorant Garamond + Berkshire Swash | Art Nouveau (Mucha vines)  |
| `chalkboard`  | <img src="idle_hours/assets/previews/chalkboard.png" width="240" alt="chalkboard theme preview">   | black       | white | yellow | Playwrite GB J Guides | Primary-school cursive guides |
| `placard`     | <img src="idle_hours/assets/previews/placard.png" width="240" alt="placard theme preview">         | white       | black | red    | Patrick Hand SC      | Hand-lettered sandwich board  |
| `chanbara`    | <img src="idle_hours/assets/previews/chanbara.png" width="240" alt="chanbara theme preview">       | black       | white | red    | Shojumaru (brush)    | Samurai-cinema poster         |
| `lcars`       | <img src="idle_hours/assets/previews/lcars.png" width="240" alt="lcars theme preview">             | black       | white | yellow | Antonio (condensed sans) | LCARS console (Okudagram) |
| `fillmore`    | <img src="idle_hours/assets/previews/fillmore.png" width="240" alt="fillmore theme preview">       | yellow      | red   | blue   | Bungee Shade (3D display) | 1960s psychedelic concert poster |
| `firmament`   | <img src="idle_hours/assets/previews/firmament.png" width="240" alt="firmament theme preview">     | navy        | white | gold   | Cardo (humanist serif) | 17th-century celestial atlas |
| `astrarium`   | <img src="idle_hours/assets/previews/astrarium.png" width="240" alt="astrarium theme preview">     | cream/white | black | tangerine | EB Garamond          | Astronomical-clock dashboard |
| `kanagawa`    | <img src="idle_hours/assets/previews/kanagawa.png" width="240" alt="kanagawa theme preview">       | white       | black | red    | Yuji Boku (sumi-brush) | Hokusai-inspired seigaiha woodblock |
| `marquee`     | <img src="idle_hours/assets/previews/marquee.png" width="240" alt="marquee theme preview">         | black       | white | red    | Cardo Italic + Bungee Shade | 1930s movie-palace marquee |
| `tarot`       | <img src="idle_hours/assets/previews/tarot.png" width="240" alt="tarot theme preview">             | cream/white | black | Tyrian purple | EB Garamond + Cinzel Decorative | Major-arcana card |
| `vinyl`       | <img src="idle_hours/assets/previews/vinyl.png" width="240" alt="vinyl theme preview">             | cream/white | black | tangerine | Cormorant Garamond | Turntable and spoken-word LP |
| `vitrail`     | <img src="idle_hours/assets/previews/vitrail.png" width="240" alt="vitrail theme preview">         | jewel glass | black | violet | Liberation Serif + Uncial Antiqua | Gothic stained-glass window |
| `cartograph`  | <img src="idle_hours/assets/previews/cartograph.png" width="240" alt="cartograph theme preview">   | cream/white | black | red    | IM Fell English Italic | Antique cartographer's chart |
| `questline`   | <img src="idle_hours/assets/previews/questline.png" width="240" alt="questline theme preview">     | black       | white | yellow | Press Start 2P (pixel) | 8-bit RPG dialogue box |
| `chrono`      | <img src="idle_hours/assets/previews/chrono.png" width="240" alt="chrono theme preview">           | twilight blue | white | yellow | Pixelify Sans (pixel sans) | 16-bit JRPG cutscene |
| `outrun`      | <img src="idle_hours/assets/previews/outrun.png" width="240" alt="outrun theme preview">           | black       | white | magenta | Oxanium (techno sans) | 1980s synthwave sunset |
| `circuit`     | <img src="idle_hours/assets/previews/circuit.png" width="240" alt="circuit theme preview">         | forest green | white | gold   | Space Mono (mono)    | Printed circuit board |
| `letter`      | <img src="idle_hours/assets/previews/letter.png" width="240" alt="letter theme preview">           | cream/white | black | red    | Dancing Script + Pinyon Script | Wax-sealed handwritten letter |
| `grimdark`    | <img src="idle_hours/assets/previews/grimdark.png" width="240" alt="grimdark theme preview">       | black       | white | forge-amber | Cinzel Decorative + UnifrakturMaguntia | Warhammer 40K Imperial Gothic |
| `sampler`     | <img src="idle_hours/assets/previews/sampler.png" width="240" alt="sampler theme preview">         | cream/white | black | red    | Silkscreen (pixel)   | Cross-stitch embroidery sampler |
| `anna_atkins` | <img src="idle_hours/assets/previews/anna_atkins.png" width="240" alt="anna_atkins theme preview"> | Prussian blue | white | sky-blue | Libre Caslon Text + Pinyon Script | Anna Atkins botanical cyanotype |
| `lieder`      | <img src="idle_hours/assets/previews/lieder.png" width="240" alt="lieder theme preview">           | cream/white | black | red    | Alegreya (literary serif) | Engraved art-song manuscript |
| `izakaya`     | <img src="idle_hours/assets/previews/izakaya.png" width="240" alt="izakaya theme preview">         | black       | white | yellow | Quicksand + Yuji Boku | Neon alley at night |
| `abyssal`     | <img src="idle_hours/assets/previews/abyssal.png" width="240" alt="abyssal theme preview">         | deep blue   | white | mint   | Lato (humanist sans) | Deep-sea sounding gauge |
| `pride`       | <img src="idle_hours/assets/previews/pride.png" width="240" alt="pride theme preview">             | rainbow cloth | black | violet | Jost (geometric sans) | Progress Pride flag, flying |
| `pulp`        | <img src="idle_hours/assets/previews/pulp.png" width="240" alt="pulp theme preview">               | yellow      | black | red    | Alfa Slab One (fat slab) | 1940s lurid paperback cover |
| `synoptic`    | <img src="idle_hours/assets/previews/synoptic.png" width="240" alt="synoptic theme preview">       | white       | black | red    | Space Mono (mono)    | Weather-chart isobars and fronts |
| `vhs`         | <img src="idle_hours/assets/previews/vhs.png" width="240" alt="vhs theme preview">                 | black       | white | red/blue | Antonio (condensed sans) | Worn VHS tape with camcorder OSD |
| `bakelite`    | <img src="idle_hours/assets/previews/bakelite.png" width="240" alt="bakelite theme preview">       | brown CRT   | amber | white  | Jost + Space Mono    | Amber-phosphor CRT in bakelite |
| `cardcatalog` | <img src="idle_hours/assets/previews/cardcatalog.png" width="240" alt="cardcatalog theme preview"> | manila      | black | violet | Special Elite (typewriter) | Library catalogue card |
| `metro`       | <img src="idle_hours/assets/previews/metro.png" width="240" alt="metro theme preview">             | white       | black | red    | Jost + Space Mono    | Transit-map diagram |
| `intaglio`    | <img src="idle_hours/assets/previews/intaglio.png" width="240" alt="intaglio theme preview">       | white       | black | green  | Old Standard TT + Cinzel Decorative | Banknote engraving |
| `nocturne`    | <img src="idle_hours/assets/previews/nocturne.png" width="240" alt="nocturne theme preview">       | black       | white | yellow | Cormorant Garamond   | Whistler night river |
| `plaque`      | <img src="idle_hours/assets/previews/plaque.png" width="240" alt="plaque theme preview">           | green       | yellow | white | Cinzel Decorative    | Patinated bronze plaque |
| `daguerreotype` | <img src="idle_hours/assets/previews/daguerreotype.png" width="240" alt="daguerreotype theme preview"> | white   | black | red    | Libre Caslon Text    | Cased 1850s photograph |
| `autochrome` | <img src="idle_hours/assets/previews/autochrome.png" width="240" alt="autochrome theme preview"> | white   | black | red    | Libre Caslon Text    | 1907 Lumière colour plate |
| `photo` | <img src="idle_hours/assets/previews/photo.png" width="240" alt="photo theme preview"> | white   | black | red    | Libre Caslon Text    | Your own picture via `--photo-path` |
| `betweenus`   | <img src="idle_hours/assets/previews/betweenus.png" width="240" alt="betweenus theme preview">     | white/cream | black | red    | Fraunces + Inter      | Between Us app card, light |
| `betweenus_dark` | <img src="idle_hours/assets/previews/betweenus_dark.png" width="240" alt="betweenus_dark theme preview"> | black       | white | amber  | Fraunces + Inter      | Between Us app card, dark |
| `carcosa`     | <img src="idle_hours/assets/previews/carcosa.png" width="240" alt="carcosa theme preview">         | black       | white | yellow | Almendra             | The King in Yellow |
| `control`     | <img src="idle_hours/assets/previews/control.png" width="240" alt="control theme preview">         | white       | black | red    | Jost + Archivo       | Remedy's *Control*: the Astral Plane |
| `observation` | <img src="idle_hours/assets/previews/observation.png" width="240" alt="observation theme preview"> | black       | white | yellow | IBM Plex Mono        | *Observation*: S.A.M.'s camera feed |
| `trisolaris`  | <img src="idle_hours/assets/previews/trisolaris.png" width="240" alt="trisolaris theme preview">   | black       | white | yellow | Titillium Web        | *The Three-Body Problem* |
| `biomech`     | <img src="idle_hours/assets/previews/biomech.png" width="240" alt="biomech theme preview">         | black       | white | yellow | Spectral             | Giger and Beksiński biomechanical dusk |
| `codex`       | <img src="idle_hours/assets/previews/codex.png" width="240" alt="codex theme preview">           | cream       | black | red    | Fondamento           | *Codex Seraphinianus* |
| `culture`     | <img src="idle_hours/assets/previews/culture.png" width="240" alt="culture theme preview">         | black       | white | yellow | Jura + Share Tech Mono | Iain M. Banks's Culture: a Mind's signal |
| `orbital`     | <img src="idle_hours/assets/previews/orbital.png" width="240" alt="orbital theme preview">         | sky / white | black | blue   | Jura                 | The Culture's Arch: Orbital 24-hour dial |
| `furies` | <img src="idle_hours/assets/previews/furies.png" width="240" alt="furies theme preview"> | black       | white | orange | Libre Franklin       | Bacon's *Three Studies* triptych |
| `bosch` | <img src="idle_hours/assets/previews/bosch.png" width="240" alt="bosch theme preview"> | white       | black | red    | Grenze Gotisch       | Bosch's *Garden of Earthly Delights* |
| `semiotic` | <img src="idle_hours/assets/previews/semiotic.png" width="240" alt="semiotic theme preview"> | black       | black | red    | Barlow Condensed     | Ron Cobb's *Alien* hazard signs (signs: [LouH](https://github.com/louh/semiotic-standard), CC BY 4.0) |
| `atropos` | <img src="idle_hours/assets/previews/atropos.png" width="240" alt="atropos theme preview"> | black       | white | yellow | Saira + Michroma     | *Returnal*: night on Atropos |
| `saros` | <img src="idle_hours/assets/previews/saros.png" width="240" alt="saros theme preview"> | black       | white | yellow | Saira + Orbitron     | *Saros*: eclipse over Carcosa |
| `expedition` | <img src="idle_hours/assets/previews/expedition.png" width="240" alt="expedition theme preview"> | black       | white | yellow | IM Fell Double Pica  | *Clair Obscur: Expedition 33* Monolith |
| `witcher` | <img src="idle_hours/assets/previews/witcher.png" width="240" alt="witcher theme preview"> | white       | black | red    | Barlow Condensed + Archivo Narrow | *The Witcher 3* bestiary page |
| `hades` | <img src="idle_hours/assets/previews/hades.png" width="240" alt="hades theme preview"> | black       | white | yellow | Spectral + Caesar Dressing | *Hades II* boon at the Crossroads |
| `expanse` | <img src="idle_hours/assets/previews/expanse.png" width="240" alt="expanse theme preview"> | black       | white | yellow | Barlow + Share Tech Mono | *The Expanse*: the Rocinante's console |
| `beksinski` | <img src="idle_hours/assets/previews/beksinski.png" width="240" alt="beksinski theme preview"> | white       | black | red    | Old Standard TT      | Beksiński: a procession to a cathedral of bone |
| `goya` | <img src="idle_hours/assets/previews/goya.png" width="240" alt="goya theme preview"> | yellow      | black | red | Libre Baskerville | Goya's *Black Paintings*: *El Perro* |
| `hal` | <img src="idle_hours/assets/previews/hal.png" width="240" alt="hal theme preview"> | black       | white | yellow | Jost + Michroma | *2001: A Space Odyssey*: the Discovery's monitors and HAL's eye |
| `lumon` | <img src="idle_hours/assets/previews/lumon.png" width="240" alt="lumon theme preview"> | blue        | white | yellow | Montserrat + Inter | *Severance*: the Macrodata Refinement terminal |
| `dsky` | <img src="idle_hours/assets/previews/dsky.png" width="240" alt="dsky theme preview"> | black       | black | red    | Special Elite + Jost | The Apollo Guidance Computer's DSKY, on its console |
| `oblivion` | <img src="idle_hours/assets/previews/oblivion.png" width="240" alt="oblivion theme preview"> | white       | black | red    | Exo 2 Light | *Oblivion*: the Sky Tower's light table |
| `yorha` | <img src="idle_hours/assets/previews/yorha.png" width="240" alt="yorha theme preview"> | white       | black | black  | EB Garamond | *NieR: Automata*: the YoRHa archives |
| `hitchhiker` | <img src="idle_hours/assets/previews/hitchhiker.png" width="240" alt="hitchhiker theme preview"> | black       | white | yellow | Michroma | The 1981 BBC *Hitchhiker's Guide* entry |
| `escritoire` | <img src="idle_hours/assets/previews/escritoire.png" width="240" alt="escritoire theme preview"> | white       | black | blue   | Dancing Script | A handwritten letter on a writing desk, seen at an angle |
| `lasvegas` | <img src="idle_hours/assets/previews/lasvegas.png" width="240" alt="lasvegas theme preview"> | black       | white | yellow | Barlow + Barlow Condensed | *Blade Runner 2049*: K in the dead Las Vegas |
| `bladerunner` | <img src="idle_hours/assets/previews/bladerunner.png" width="240" alt="bladerunner theme preview"> | black       | white | yellow | Barlow Condensed + Share Tech Mono | *Blade Runner 2049*: the LAPD's records terminal |
| `traumateam` | <img src="idle_hours/assets/previews/traumateam.png" width="240" alt="traumateam theme preview"> | black       | white | red    | Oxanium | *Cyberpunk*: a Trauma Team dispatch screen |
| `redacted` | <img src="idle_hours/assets/previews/redacted.png" width="240" alt="redacted theme preview"> | white       | black | red    | Special Elite + Archivo | *Control*: a declassified Bureau document, words blacked out |
| `diags`       | <img src="idle_hours/assets/previews/diags.png" width="240" alt="diags theme preview">             | white       | black | red    | DejaVu Sans          | Calibration / status panel    |

Most themes share the standard literary layout. A number of them are **custom-render frames** that own their whole composition (a dial, a card, a flag, a transit map…); for those the `--mode debug` overlay does not apply. Almost none print the time as digits (`vhs`, whose on-screen display is a real clock, is the exception): the matched phrase in the quote carries it, sometimes alongside a themed hour marker such as a Roman numeral, a time signature or a depth gauge.

`diags` is a status panel rather than a literary frame — big clock, picker metrics, host / IP / uptime, and the Spectra 6 palette with its stippled recipes. It is handy for on-panel colour calibration, and it is **excluded from `--theme random`**; manual selection via button B or the web dropdown still works.

Design notes for every theme — layout, typeface, how each colour is synthesised from the six inks, and what was tried and rejected — live in [`docs/themes.md`](docs/themes.md).

Pass `--theme auto` to let the clock pick by wall-clock time. The defaults are `default` during the day (06:00–18:00) and `dark` at night (18:00–06:00) — the legacy binary contract. Broaden the rotation by setting `--auto-day-theme` and/or `--auto-night-theme` to any other registered theme, e.g.

```bash
idle-hours run --theme auto --auto-day-theme scholar --auto-night-theme nightvision
```

`auto` itself is rejected for the day/night picks (would be a config typo, not a useful recursion). A manual button-B press (or a web-UI dropdown jump) overrides `auto` until the next midnight rollover, when the override clears and `auto` resumes.

Pass `--theme random` to pick a theme at random each time the displayed quote changes (so every new bucket gets a fresh look). Picks are drawn from a shuffled bag rather than uniformly, so you see every eligible theme once before any repeats — and the most recent half of the rotation is held back from the front of the next pass, so a theme shown at the end of one pass can't turn up again a pick or two later. The pick is held for the lifetime of the displayed quote and is **not persisted** — a restart picks a fresh theme on the first render. Button B / the web-UI dropdown still wins over the random pick until midnight, the same way it wins over `auto`.

Button B cycles forward through the list and wraps; the curator web UI at `/api/themes` exposes the same cycle plus a dropdown that jumps directly to any named theme. Clicking Apply on an unchanged selection is a no-op — it won't burn a 10–20 s eInk refresh and won't silently disable `auto` / `random` mode.

> Regenerate previews: the images under `idle_hours/assets/previews/` are built by looping over `render_quote.THEME_ORDER` and calling the `python -m idle_hours.render_quote` CLI. **Pin the quote** — the table reads as one passage shown eighty-nine ways, so a preview rendered from a fresh pick would show a different quote from its neighbours, and the picker's answer for a given time moves as the corpus grows:
>
> ```bash
> for theme in default dark swiss scholar herbarium newsprint nightvision blueprint illuminated gothic bauhaus risograph comic dispatch atomic marker saloon roman alchemy grimoire deco glacier mucha chalkboard placard chanbara lcars fillmore firmament astrarium kanagawa marquee tarot vinyl vitrail cartograph questline chrono outrun circuit letter grimdark sampler anna_atkins lieder izakaya abyssal pride pulp synoptic vhs bakelite cardcatalog metro intaglio nocturne plaque daguerreotype autochrome photo betweenus betweenus_dark carcosa control observation trisolaris biomech codex culture orbital furies bosch semiotic atropos saros expedition witcher hades expanse beksinski goya hal lumon dsky oblivion yorha hitchhiker escritoire lasvegas bladerunner traumateam redacted diags; do
>   idle-hours render --time 10:00 --theme "$theme" --mode production \
>     --pin-quote 35:646 --pin-matched-text "ten o’clock" \
>     --output "idle_hours/assets/previews/$theme.png"
> done
> ```
>
> That is H. G. Wells, *The Time Machine* — "It was at ten o’clock today that the first of all Time Machines began its career." — and the command above reproduces the checked-in image byte-for-byte for the themes whose frame carries no clock element. The set has been rebuilt per-theme as themes changed rather than all at once, so the themes that surface the hour or minute (`metro`, `astrarium`, `vinyl`, `cardcatalog`, `bakelite`, `intaglio`, `plaque`, `pulp`, `vhs`, `synoptic`, `tarot`, `vitrail`, `lieder`, `izakaya`, `abyssal` …) were rendered at other times and will shift if you re-run the whole loop. Regenerate the theme you changed, not the set.
>
> The PNGs are checked in so the README renders on GitHub without a build step. Every bundled typeface ships under `idle_hours/fonts/` (Playfair Display, Bitter, Old Standard TT, Space Mono, Archivo, EB Garamond, UnifrakturMaguntia, Jost, Rubik, Bangers, Special Elite, Atomic Age, Permanent Marker, Rye, Cinzel Decorative, IM Fell English, MedievalSharp, Eagle Lake, Righteous, Iceland, Playwrite GB J Guides, Patrick Hand SC, Shojumaru, Antonio, Inter, Cormorant Garamond, Berkshire Swash, Bungee Shade) so the previews are reproducible without any system-font install. All bundled faces are OFL-licensed except Special Elite and Permanent Marker, which ship under Apache 2.0 (see `idle_hours/fonts/special-elite/LICENSE.txt` and `idle_hours/fonts/permanent-marker/LICENSE.txt`). Every family ships its licence text beside it, which both licences require and `tests/test_font_licenses.py` enforces. A previous release bundled `idle_hours/fonts/TFoust.ttf` in the `grimoire` matched-phrase slot; its metadata recorded `© 2025 myfont All rights reserved` with no grant, so it was not ours to redistribute under the MIT licence and has been replaced by Eagle Lake (Astigmatic, OFL). See the **Third-party content** section of [LICENSE](LICENSE).

### Inky buttons (short and long press)

The four capacitive buttons on an Inky Impression 7.3 are active whenever `run_clock.py` runs on a Pi with the `gpiozero` package installed. Pass `--buttons-off` on dev hosts or for headless smoke tests.

| Button | Short press | Long press (2s) |
|---|---|---|
| **A** | Skip — bans the current quote in the history ledger and picks a new one. | Un-skip — removes the last-skipped ban from the ledger and re-renders. Reverses a fat-fingered tap. |
| **B** | Cycle theme — advances through `default → dark → scholar → newsprint → nightvision → blueprint → illuminated → bauhaus → risograph → comic` (wraps), persists to `--state-path`. The curator web UI also exposes a dropdown that jumps straight to any named theme. | — |
| **C** | Source card — shows a 5-second overlay with the title / author / Gutenberg ID / matched phrase. | — |
| **D** | Quiet now / wake — toggles the manual quiet override, persists to `--state-path`. | Shutdown — shows the sleep frame, then runs `--shutdown-command` (default `sudo -n shutdown -h now`; empty to disable). |

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
# Stands down while quiet hours are open — the loop is supposed to be silent then — and
# resumes measuring from the window's close, so a failure to wake up is still caught.
# Works for any window width: the loop stamps the quiet state onto every heartbeat,
# so a --hours 1 cron run at 03:00 sees it even though the 22:00 edge is long out of view.
idle-hours health --hours 24 --max-render-age-minutes 90

# systemd installs relocate telemetry under /var/lib/idle-hours; read the path from the same
# config file the unit uses instead of restating it. An explicit --telemetry-path still wins.
idle-hours health --config /var/lib/idle-hours/config.toml --hours 24
```

Every file the next tick or boot reads is written atomically (`unique tmp → fsync → rename → fsync dir`) via the shared `atomic_io` helpers — runtime state, the rendered `output/current.png`, the selection-overrides sidecar, the history-ledger rewrite path, and the `apply_content_overrides` corpus writeback. A power cut or `SIGKILL` mid-write leaves the previous-known-good file byte-identical; it never leaves a truncated PNG or an empty ledger. The staging file is uniquely named per write, so two writers of one target (an `idle-hours bake` racing the curator UI's "Bake now", say) each publish a whole payload rather than a blend of both — last writer wins, which is a lost edit, not a corrupt corpus. Staging files abandoned by a hard kill (power cut, or a render subprocess killed at its timeout) are swept on the next successful write to the same target, once they are an hour old.

`SIGTERM` and `SIGINT` are handled gracefully: `systemctl restart idle-hours.service` flips a shared event that the main loop observes between ticks, drains any in-flight render via `state.render_lock`, stops the curator web server, closes GPIO buttons, and persists runtime state one last time before the process exits. `--once` keeps strict-exit behaviour for cron callers.

Telemetry is rotated by date: the `--telemetry-path` argument is a base path, but `run_clock.py` actually writes to `<stem>-YYYYMMDD<suffix>` siblings (e.g. `~/.idle-hours/telemetry-20260420.jsonl`) so a multi-year-running appliance keeps file size bounded. `--telemetry-retain-days` (default 90; pass 0 to disable) unlinks siblings older than that once per local-date rollover. `idle_hours_health.py` globs the directory for those siblings plus any legacy unsuffixed file at the exact base path and stream-reads them in order.

`idle_hours_health.py` exit codes:

- `0` — healthy (renders happened in the window, or no errors with nothing scheduled)
- `1` — telemetry log missing
- `2` — unhealthy: errors but zero renders, or `--fail-if-no-renders` with a silent window

### Startup frame

```bash
# Optional: push a frame to the panel before the first quote renders
# so a cold boot doesn't ghost yesterday's image.
idle-hours run --startup-image auto                    # the sleep frame, in your theme
idle-hours run --startup-image assets/goodnight.png    # or any static PNG
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

Every API read and every mutating `POST` must send `X-Idle-Hours-Token: <the token>`; only the static shell (`/`, `/main.js`, `/style.css`) is served without it. The bundled `idle_hours/web/` UI attaches the header itself — it prompts for the token on first use and keeps it in `localStorage` — including for the `current.png` preview and the theme thumbnails, which it fetches with the header and shows as object URLs, so a LAN+token bind works end-to-end from the browser. Scripted access works the same way:

- `curl -H "X-Idle-Hours-Token: $(cat ~/.idle-hours/web.token)" http://<pi>:8080/api/current`
- `curl -X POST -H "Content-Type: application/json" -H "X-Idle-Hours-Token: $(cat ~/.idle-hours/web.token)" http://<pi>:8080/api/action/rerender`
- Or use the SSH-tunnel flow above — a loopback bind needs no token at all.

**How to tell it's working.** `journalctl -u idle-hours.service -n 20` should show a line like `web UI listening on 127.0.0.1:8080 (no token)` (or `(token required)` on a LAN bind). If the bind fails (port busy, missing token on a non-loopback bind) the main render loop keeps running and logs `web UI failed to start on …` — the panel won't go dark just because the web UI couldn't start.

The UI is vanilla HTML/JS/CSS served directly from `idle_hours/web/` — no build step, no framework, no extra runtime deps beyond what the clock already needs. **v2 reorganises it into a mobile-first four-tab layout** (Now / Curate / Coverage / Activity) with 44px tap targets and breakpoints at 768px (tablet) and 1024px (desktop), so the same UI works equally well from a phone-on-the-counter and a laptop. Tab state is kept in `location.hash` so a bookmark like `idle-hours.local#curate` jumps straight to the editor.

#### First-run wizard (v2)

A modal overlay appears on the very first visit to a fresh appliance: pick a theme from a thumbnail grid (each tile is a live `/api/preview` PNG of the current quote in that theme), confirm the configured quiet hours, dismiss. Choices are persisted to `state.json` so the wizard never reappears. Nothing about the clock loop changes — it's the discovery surface for knobs that were already CLI-configurable.

#### Tab: Now

- Live preview of `output/current.png`, the picked quote text, attribution (`source_id` + `line_number`), and the matched time phrase the renderer bolded.
- Five buttons that mirror the physical Inky panel (`A · Skip`, `A-hold · Un-skip`, `B · Cycle theme`, `C · Re-render`, `D · Quiet / wake`) plus a theme dropdown that jumps directly to any registered theme.
- **Ban this quote** button (v2): adds the current `(source_id, line_number)` to `ban_quote_keys` in the selection overrides sidecar so the picker never returns this exact row again — the rest of the source still works normally.
- Theme thumbnail grid: side-by-side previews of every registered theme, rendered against the current quote so you can compare typography + palette before committing. Click a tile to apply it.

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
| `GET /api/coverage` | The 144-bucket coverage, computed live from the running corpus and counting only rows the panel can display (quality floor + bans; raw tallies alongside as `raw_bucket_counts`); falls back to `idle_hours/assets/bucket-coverage.json` |
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

Security model: loopback binds (`127.0.0.1:*`, `localhost:*`, `::1:*`) skip auth entirely — the OS-level trust boundary is sufficient. Any other bind **requires** `--web-token` / `--web-token-file`; startup aborts rather than quietly expose a tokenless POST surface. Tokens are checked via the `X-Idle-Hours-Token` header only; query-string tokens would leak into journald via HTTP request logging.

A configured token gates every POST **and** every JSON GET (`/api/history`, `/api/search`, `/api/bucket/*`, both override endpoints, ...) — the UI already sends the header on all of them, so this costs it nothing. Only the static shell (`/`, `/main.js`, `/style.css`) stays open, because a browser loads it by tag and a tag cannot attach a request header; the UI fetches `/current.png` and `/api/preview` with the header and shows them as object URLs. `/metrics` stays open for scrapers unless you pass `--web-metrics-token`.

Independently of the token, the server rejects cross-site and rebound requests on **every** bind, including the tokenless loopback one the quick-start recommends:

- every POST must send `Content-Type: application/json` (415 otherwise), which forces a CORS preflight the server never answers — so a page the operator happens to have open can't POST here at all. **If you drive the API with curl, add `-H 'Content-Type: application/json'`** — a bare `curl -X POST .../api/bake` now returns 415;
- a POST whose `Origin` names a different host than its own `Host` header is rejected (403);
- a request whose `Host` isn't one we answer for is rejected (403) — this is the DNS-rebinding guard. Loopback binds accept `127.0.0.1` / `localhost` / `::1`; if you reach the UI by an mDNS name or through a reverse proxy, name it with `--web-allowed-host idle-hours.local` (repeatable; config key `web_allowed_hosts`). Only the hostname is compared, never the port, so a port-rewriting proxy still works. A non-loopback bind stays permissive here unless you configure an allowlist — those binds require a token anyway.

### Quiet hours

The loop defaults to quiet hours **22:00–06:00**. During that window it stops
picking corpus quotes and shows a **sleep frame** instead — "To sleep, perchance
to dream." (Hamlet), rendered through the normal literary layout so it picks up
your theme's borders, fonts, and accent colour like any other frame.

```bash
# Shift or tighten the window
idle-hours run --quiet-start 23:30 --quiet-end 07:00

# Disable quiet hours entirely (24/7 rendering)
idle-hours run --quiet-off
```

#### Giving sleep its own theme

`--quiet-theme` is independent of `--theme`, so the panel can read one way by
day and another overnight:

```bash
# Fixed: a dark theme for the small hours
idle-hours run --theme scholar --quiet-theme nightvision

# Random: rerolled once per night, on entering quiet hours — not per tick
idle-hours run --theme scholar --quiet-theme random

# Wall-clock day/night picks, same rule as --theme auto
idle-hours run --quiet-theme auto
```

The default is `inherit` — the sleep frame uses whatever theme the clock is
already showing. A manual theme override (button B, or the web dropdown) always
wins over `--quiet-theme`, and pressing button B while the panel is asleep
repaints the *sleep frame* in the new theme rather than waking it with a quote.

#### Showing a static image instead

```bash
# Any PNG. Ignores every theme setting — it's a fixed image.
idle-hours run --quiet-image path/to/other.png

# assets/goodnight.png still ships: it's a frozen dark-theme render of the
# same sleep frame, so it looks identical to --quiet-theme dark.
idle-hours run --quiet-image assets/goodnight.png

# Or render the --quiet-start quote as the last frame of the night
idle-hours run --quiet-image ""
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

1. configure the Spectra 6 SPI bus and Raspberry Pi OS GPIO backend
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
sudo apt install -y git gpiod python3 python3-pip python3-venv python3-dev \
  python3-lgpio python3-rpi-lgpio fonts-noto-core fonts-dejavu-core
```

#### Configure Spectra 6 SPI

The E673 driver opens `/dev/spidev0.0` for data but controls GPIO8 chip-select
itself. Standard SPI claims GPIO8 in the kernel, so use the no-CS overlay:

```bash
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0
grep -qx 'dtoverlay=spi0-0cs' /boot/firmware/config.txt || \
  echo 'dtoverlay=spi0-0cs' | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

After reboot, verify `/dev/spidev0.0` exists and `gpioinfo` does not show GPIO8
claimed by `spi0 CS0`.

#### Verify the Inky panel works

```bash
python3 -m venv --system-site-packages ~/.virtualenvs/pimoroni
source ~/.virtualenvs/pimoroni/bin/activate
python -c 'import lgpio, RPi.GPIO; print("GPIO backend: ok")'
```

#### Install Idle Hours on the Pi

```bash
source ~/.virtualenvs/pimoroni/bin/activate
git clone git@github.com:gkoch02/Idle-Hours.git ~/IdleHours
cd ~/IdleHours
pip install -e '.[pi]'
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

That script installs the OS GPIO backend, configures the no-CS SPI overlay,
pauses for the required reboot, creates the virtualenv, and verifies both the
GPIO imports and a real panel push.

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

- runs `python -m idle_hours.run_clock --config /var/lib/idle-hours/config.toml`
- optionally calls `display_inky.py` after each render (the appliance config enables it)
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
sudoedit /etc/systemd/system/idle-hours.service    # fix User= / ExecStart= paths if needed

sudo install -d -o pi -g pi -m 0750 /var/lib/idle-hours
sudo install -o pi -g pi -m 0640 \
    idle_hours/assets/config.toml.example /var/lib/idle-hours/config.toml
sudoedit /var/lib/idle-hours/config.toml           # tune keys for this appliance

sudo systemctl daemon-reload
sudo systemctl enable --now idle-hours.service
sudo systemctl status idle-hours.service
```

Before enabling the service, update these fields to match the actual account and virtualenv on the Pi:

- `User=`
- `ExecStart=` (the virtualenv's `python` and the config file path)

Leave `WorkingDirectory=` and `Environment=LG_WD=` on `/var/lib/idle-hours`.
They are not install-path settings: `lgpio` creates its button-notification
FIFO in `LG_WD` and its Python wrapper opens it relative to the working
directory, so the two must stay on the same sandbox-writable path or the
button listener fails to start. The render output goes there too (the
appliance config sets `output = "/var/lib/idle-hours/current.png"`), so the
unit needs no write hole into your home directory.

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
- Every registered theme ships built-in; the [Themes](#themes) table above is the roster, with a preview, palette and typeface per row, and [`docs/themes.md`](docs/themes.md) holds the design notes behind each one.
- `--theme auto` switches dark/default by wall-clock time (dark 18:00–06:00); broaden the rotation past the binary default with `--auto-day-theme` / `--auto-night-theme`. `--theme random` rerolls the theme each time the picked quote changes (not persisted across restarts). A manual button-B / web override wins over either mode until the next midnight rollover.
- Per-theme saturation: `display_inky.py` picks `0.5` for light-background themes and `0.7` for dark-background themes so accents don't go muddy.
- Telemetry at `--telemetry-path` (default `~/.idle-hours/telemetry.jsonl`) is rotated by date — `run_clock.py` writes to a `telemetry-YYYYMMDD.jsonl` sibling so long-running appliances don't accumulate one unbounded file. One line per render, one per loop-level error. `idle_hours_health.py --json` feeds systemd / cron health checks and auto-discovers the rotated siblings.
- The anti-repeat history ledger at `--history-path` (default `~/.idle-hours/history.jsonl`) is fsynced after each append so a power loss can't leave a buffered entry lost, and the reader logs a one-shot warning if it finds a malformed/torn line.
- If the Inky button listener dies mid-run (pin claim lost, background thread failed), the loop logs one loud warning plus a telemetry entry with `mode=buttons_dead` and stops retrying — restart the process to reclaim the pins.
- The optional curator web UI (`--web-bind`) runs in-process on a daemon thread and shares the render lock with the button handlers; it's the safe remote alternative to SSHing in to tap the panel or edit `selection_overrides.json` by hand. LAN binds require `--web-token` / `--web-token-file`.
- **Webhook notifications (v2):** `--webhook-url <url>` posts a JSON body for each alert-worthy telemetry event (errors, backoff, render/display/shutdown timeouts, button-died, state-validation issues, web-auth failures). Heartbeats and successful renders are always filtered (alerting once a minute is spam, not signal). Best-effort: dispatched on a daemon thread with a 5 s timeout, failures log but never block the render path. Pass `--webhook-all-events` to widen the filter.
- **Prometheus `/metrics` (v2):** the curator UI exposes a standard text-exposition endpoint over a fixed 24 h window. Reuses the same `idle_hours_health.summarise` aggregation as `idle-hours health --json`, so the values match exactly. Stays open without auth on every bind so a Prometheus scraper on the LAN can hit it without managing a token.
- **OCI container (v2):** `Dockerfile` provides a multi-stage build (ARM64-first) so the appliance can ship as a container instead of a git clone. Run with `docker run --rm -p 8080:8080 -v idle-hours-state:/state idle-hours:3.0 idle-hours run --buttons-off --skip-preflight --web-bind 0.0.0.0:8080 --state-path /state/state.json --history-path /state/history.jsonl --telemetry-path /state/telemetry.jsonl --pidfile /state/run_clock.pid` for a headless dev instance. The Pi-only `[pi]` extra (`gpiozero` / `inky`) is *not* installed by default — that's a Pi-runtime concern.
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

Deeper architecture and design notes live in `docs/`: [`pipeline.md`](docs/pipeline.md), [`runtime.md`](docs/runtime.md), [`themes.md`](docs/themes.md), [`web_ui.md`](docs/web_ui.md) and [`testing.md`](docs/testing.md). [`CLAUDE.md`](CLAUDE.md) lists the invariants to know before modifying the runtime or pipeline.

There's also a project landing page at [plumpbug.dev/idlehours](https://plumpbug.dev/idlehours/home.html)
(privacy/support pages too, though Idle Hours needs neither an App Store account nor
authentication to use), maintained in the separate
[`gkoch02/plumpbug-site`](https://github.com/gkoch02/plumpbug-site) repo alongside the
other Plumpbug-family projects. This repo stays the source of truth for the theme gallery
and preview PNGs that page embeds.
