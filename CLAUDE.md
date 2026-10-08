# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. It holds working notes and invariants; the references it links to are the one home for everything else, so follow the link rather than restating a fact here.

## What This Is

Idle Hours is an end-to-end literary-clock system: it harvests time-related quotes from Project Gutenberg, scores and cleans them, then picks and renders a quote for any clock time. The render is designed for a Pimoroni Inky Impression 7.3 Spectra 6 eInk panel (800×480, 6-color palette) but writes a plain PNG first, so it runs fine on any machine.

Every stage is a standalone Python 3 CLI script that reads/writes JSONL. The mining/selection pipeline is stdlib-only; `render_quote` pulls in Pillow, and `display_inky.py` additionally needs the Pimoroni `inky` package (Pi only).

## Where things are documented

| Topic | Home |
|---|---|
| Operator path: install, CLI, config file, quiet hours, buttons, curator UI, Pi deployment, the theme table | [`README.md`](README.md) |
| Corpus pipeline (mining → bake), every pipeline command, data model, quote selection, overrides, anti-repeat ledger, contact sheet | [`docs/pipeline.md`](docs/pipeline.md) |
| Runtime loop, default-path resolution, config precedence, quiet hours, themes at runtime, buttons, state, telemetry, supervision | [`docs/runtime.md`](docs/runtime.md) |
| Renderer, per-theme design notes, bundled-font table | [`docs/themes.md`](docs/themes.md) |
| Spectra 6 colour recipes | [`docs/spectra6_color_recipes.md`](docs/spectra6_color_recipes.md) |
| Curator web UI: endpoints, security model, curation semantics | [`docs/web_ui.md`](docs/web_ui.md) |
| Test suite, fences, CI jobs | [`docs/testing.md`](docs/testing.md) |
| Dev setup, contribution workflow, releases | [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) |
| Pi hardware and OS setup | [`docs/pi_setup_inky_impression.md`](docs/pi_setup_inky_impression.md) |

**Single-source, don't fence.** When two Python modules need the same list or constant, import it from one place (`theme_names.THEME_ORDER`, `pick_quote.BAKED_SCORE_COMPONENTS`). A sync test is for copies that *must* exist outside Python (README rosters, `config.toml.*`, docs tables); it is not a substitute for an import. If an import would drag in a heavy dependency, move the constant down to a lighter module rather than copying it (issue #394). A test's own hand-written expected values are not copies in this sense: they are the independent oracle (`CUSTOM_FRAME_THEMES`, the literals pinning `recent_window_size`), and reading the expectation back from the code under test makes the test unable to fail (issue #392).

**Don't write counts of registry members into prose** ("eighty-nine themes", "37 border painters"). Write "every theme in `THEME_ORDER`" or point at the registry. A count is a cache of `len()`; it drifts, and no test parses prose for a number (issue #352). Rosters a reader needs (the README theme table, the button-B chain) are fenced by `tests/test_docs_theme_registry.py`.

## Common Commands

```bash
pip install -e ".[dev]"     # dev install; registers the `idle-hours` console script

# Run the full test suite (CI runs it in parallel with -n auto; single-threaded takes a few minutes)
pytest

# Match CI: parallel + coverage on Python 3.12 (uses sys.monitoring tracer)
COVERAGE_CORE=sysmon pytest -n auto --dist loadscope --cov=idle_hours --cov-report=term-missing

# Run a specific test module
pytest tests/test_pick_quote.py

# Run ruff linter (checks E, W, F, I, B; line-length 130); --fix for import ordering
ruff check .

# Type-check the package (settings in pyproject.toml's [tool.mypy])
mypy

# Regenerate derived docs/assets after a change that affects them
UPDATE_RENDER_GOLDEN=1 pytest tests/test_render_golden.py     # golden renders
python3 scripts/generate_theme_previews.py --theme NAME          # README preview (--check in CI)
python3 scripts/generate_font_table.py                           # docs/themes.md font table
```

`idle-hours --help` lists every subcommand; `idle-hours <sub> --help` forwards to the backing module's argparse, and `python3 -m idle_hours.<module>` is the equivalent spelling. Everyday runtime invocations (`idle-hours run --once`, `idle-hours render --time 14:30`, `idle-hours pick --time 14:30`, `idle-hours health --hours 24`, `idle-hours contact-sheet`) are in the README; the full flag reference is in `docs/runtime.md`; the pipeline commands, in stage order, are in `docs/pipeline.md`.

## Default paths

Full rules in [`docs/runtime.md`](docs/runtime.md) ("Default paths"). The invariants:

- **Bundled package assets** (`idle_hours/assets/`, `fonts/`, `web/`) and per-stage default JSONL paths anchor on `BASE_DIR`, which is *inside* the installed package.
- **Runtime artefacts** (`output/current.png`, `data/gutenberg/`, history / state / telemetry) anchor on **CWD**, never `BASE_DIR`: writing into site-packages is never what an operator wants. The appliance preset uses absolute `/var/lib/idle-hours/` paths.
- **Operator-supplied inputs** (`--render-script`, `--display-script`, `--quiet-image`, `--startup-image`) go through `path_resolution.resolve_input_path`: CWD first, bundled fallback. Absolute paths pass through.
- **The bundled renderer is a module, not a path.** `--render-script "auto"` runs `python -m idle_hours.render_quote`; `runtime_render._render_command` is the one place that decides, including the legacy `"render_quote.py"` spellings (issues #335, #364).

## Corpus & selection

Full reference: [`docs/pipeline.md`](docs/pipeline.md). Pipeline order: miner → merge → (coverage → targeted sweep → import → merge) → clean → quality → (legacy fixers) → enrich → `apply_content_overrides` → `bake_quote_database` → picker.

- **Source of truth is the raw corpus (`idle_hours/assets/candidates-attributed.jsonl`) + `content_overrides.json`.** The baked `quote_database.jsonl` is derived; never edit it by hand.
- **Runtime reads the baked DB; a raw-corpus change without a re-bake is invisible to the panel.** Commit the bake with the corpus. Bump `BAKED_SCORE_SCHEMA_VERSION` whenever `BAKED_SCORE_COMPONENTS` changes; both are defined once in `pick_quote`, which the baker imports them from, and `tests/test_bake_equivalence.py` asserts baked and raw picks agree.
- **The curator UI reads the raw corpus on purpose** (`/api/bucket`, `/api/search`), so an operator can see rows the baker dropped. Don't switch it to the baked DB.
- **Every picker default path is absolute and exists.** A CWD-relative default once made the runtime silently ignore every ban (`TestOverridesPathDefaults`).
- **The four corpus paths are relocatable** (`--overrides` / `--content-overrides` / `--raw-corpus` / `--baked-db`) and must reach *both* the picker and the curator UI from the same Namespace; splitting them lets the UI write a file the panel never reads.
- **`buckets.py` is the single source of truth** for the bucket table and the rounding rule `((minute + 2) // 5) * 5`. Never add a second state table.
- **A `(source_id, line_number)` key does not identify a row**: one line can carry several time phrases. Pins carry `matched_text` too (`TestPinFidelityAgainstShippedCorpus`), and bans / the anti-repeat ledger reach a row's textual twins.
- **Sidecar loaders fail open** (a truncated `selection_overrides.json` / `content_overrides.json` warns and degrades, never crashes the loop); writers go through `atomic_io`. Content overrides are reversible via `override_originals`.
- **Push recurring fixes upstream.** If you are overriding more than a handful of rows for the same reason, fix the miner / cleaner / quality filter instead.

## Architecture


### Rendering (`render_quote.py`)

Imports `pick_quote` in-process and lays out an 800×480 RGB PNG snapped to the six Spectra 6 inks (`snap_image_to_palette`). **Full reference — every theme's design notes, the font chains, and the colour-recipe table — lives in [`docs/themes.md`](docs/themes.md).** Read the relevant theme's entry there before touching its painter; most entries record approaches that were tried and rejected, and why.

**Core layout path (literary themes).** Three layouts in `LAYOUTS` (`hero` ≤90 chars, `standard` ≤170, `dense` otherwise). `fit_quote` shrinks the font in 2 pt steps until the wrapped lines fit; `fit_quote_balanced` wraps it and re-wraps on a narrower measure (then at up to 20% smaller sizes) when the last line would be a widow — one word, or under 30% of the measure — without adding a line or opening a half-empty middle line. Justification is decided per block by `justify_flags`: non-last lines ≥75% full are justified only if every one of them has ≥3 gaps and stretches each gap ≤0.45 em, otherwise the whole block is ragged; `_THEMES_RAGGED_RIGHT` (monospace, typewriter and handwriting faces) is always ragged. The hanging opening mark sits at a fixed x and may run under the first word on the standard and dense measures: a deliberate style choice, not a bug (a gutter-fitting mark was tried and reverted). The byline floors are 18 / 16 px. `resolve_display_match` + `tokenize_quote` + `wrap_styled_text` render the matched time phrase in bold + accent; wrapping breaks **only at whitespace** (no dangling `)` / `seven` split). `apply_theme_glyph_fallbacks` swaps characters a theme's face lacks for ASCII stand-ins. `--mode debug` (default) draws the `DEBUG MODE` banner + footer strip; `production` hides them. Output is written atomically to `output/current.png`. `_FONT_CACHE` memoises fonts (the bitmap fallback is deliberately not cached).

**Theme architecture.** `THEMES` (colours), `THEME_ORDER` (cycle order), `THEME_FONTS` (per-role candidate chains; variable fonts use `(path, "Instance")` tuples and **must** pin an instance — several defaults are Thin or Black). A theme is exactly one of: border-painted (a `BorderSpec`: `render` lays the quote out, then paints the border once in a knockout pass that hands themes with a `clear_rect_pad` the body rect, and the time when `wants_time` is set; the specs with `paints_twice` also get a first paint on the bare page, because their look is the composite of two paints — issue #361, fenced by `TestPaintsTwice`), a custom-render frame (a `FrameSpec` naming `render_<theme>_frame`, also listed in `CUSTOM_FRAME_THEMES` in `tests/test_theme_decoration.py`), or deliberately plain (`default`, `dark`; `registry.PLAIN_THEMES`). `registry` builds the dispatch tables from every module's `SPEC` and fails at import if a theme is unclaimed, claimed twice or unknown; `_BORDER_PAINTERS`, `_FRAME_RENDERERS` and `_DEBUG_LABEL_RIGHT_INSET` are read-only views of it. `diags` is a swatch panel, excluded from `--theme random`. Either spec may also carry `sleep`, the theme's own quiet-hours frame, which `render_sleep_frame` draws in place of the bundled sleep quote (a theme that has one describes it in its `docs/themes.md` entry; the rest fall back to the quote).

**Adding a theme — checklist.**
1. `THEME_ORDER` (in the Pillow-free `theme_names.py`; `run_clock`'s `--theme` choices and `render_quote.THEME_ORDER` both read it), `THEMES` and `THEME_FONTS` (in `render_quote/theme_tables.py`), and `display_inky.THEME_SATURATION` (`0.5` light ground, `0.7` dark / coloured / bloom-heavy).
2. Its own `render_quote/themes/<theme>.py`, listed in `themes.THEME_MODULES` (a test fails if a theme module is missing from the facade), holding either a border painter or a `render_<theme>_frame`, and ending with its `SPEC` (`spec.BorderSpec` or `spec.FrameSpec`); a frame theme also needs a `CUSTOM_FRAME_THEMES` entry. A theme module never imports another theme module: code two themes use goes in `themes/_shared.py`. Frame helpers are named `_<theme>_paint_*` (the decoration fence neuters them by name). A border that paints in the y=14-29 top-right band sets `debug_label_inset` on its spec.
3. Golden fixture: `UPDATE_RENDER_GOLDEN=1 pytest tests/test_render_golden.py`. If the theme reads the wall clock, read it through `clock.now()` and add the theme to `CLOCK_DEPENDENT_THEMES`.
4. README row + preview (`python scripts/generate_theme_previews.py --theme NAME`), the README contact-sheet loop and the button-B chain in `docs/runtime.md` (rosters fenced by `tests/test_docs_theme_registry.py`), and `python3 scripts/generate_font_table.py` if the theme brings a new face (a new directory under `idle_hours/fonts/` with its licence file).
5. A paragraph in `docs/themes.md` (theme + font), and a row in its colour table for any recipe you use.
6. Optional: its own sleep frame, a `sleep=` renderer on its spec, with a `sleep` scenario in `tests/test_render_golden.py`.

**Conventions every theme follows** (each learned the hard way — details in `docs/themes.md`):
- **On-palette only.** Colours the panel lacks are synthesised by stippling two or three inks (`draw_text_dithered`, `_fill_swatch_stipple[_3way]`, or paint-a-sentinel-then-bbox-post-pass). Catalogue: `docs/spectra6_color_recipes.md`. Bias a mix toward the *less* luminous ink (5/8 R + 3/8 Y reads tangerine; 50/50 reads washed-out amber).
- **Judge on panel inks, not an RGB screenshot.** Calibrated inks: red ≈ `#62201E`, yellow ≈ `#C1BB1E`, blue ≈ `#233F8E`, green ≈ `#35563A`, black ≈ `#1F2226`, white ≈ `#B9C7C9`. Box-average to simulate 1–3 m viewing.
- **Dither pitfalls.** Two reads of the same Bayer tile are perfectly correlated — split one rank read into bands instead (`pride`, `bakelite`). Use `BAYER_8x8` for gradients. Jitter an ordered field over large areas (`position_noise` / seeded `randbytes`) or it lattices. Two periodic patterns beat. Lattices sampling the same pixels must have coprime periods.
- **Glow / relief / shading primitives:** `paint_neon_mask` (falling-density bloom, always pass `ground=` so later halos can't eat earlier cores; `glow_minor` for two-ink glows), `paint_relief_mask`, `paint_hatched_tone`, `paint_flow_strokes`, `paint_craquelure`, `shade_height_field`, `wrap_quote_into_masks`, `paint_mount_card`.
- **Shared small helpers — reuse, don't re-type** (issue #336 folded about fifty theme-prefixed copies into these): `_clock_hour12` (hour-only time surfaces), `_clock_hh_mm` (hour and minute; falls back to midnight on a malformed time, never raises), `_row_digest` (quote seeds), `_white_noise` / `_smooth_noise`, `_bayer_threshold_field`, `_lerp_stops`, `_halo_paste`, `_soft_ellipse_mask`, `_PANEL_INKS` + `_dither_calibrated` (Floyd–Steinberg in the measured ink space), `_shade_silhouette` / `_catmull_rom`, `_place_quote` + `_paint_placed` (fit, position and draw a ragged-right quote; both in `furniture`, not `themes/_shared`), `_place_lines` (position already-fitted lines centred or flush left by ink width, for `_paint_placed`, whose `accent_light=` stipples the matched phrase), `layout._trim_line` (drop a wrapped line's edge spaces; never re-type the loop), `_fit_dotted_byline` / `_fit_from_title` / `draw_truncated_centred_byline` (bylines). A new `_<theme>_hour` or `_<theme>_seed` is a smell.
- **Committed raster plates** go through `dither_image_to_palette` / `_load_dithered_plate`, restricted to the theme's sub-palette, with a synthesised fallback when the asset is missing. Generators live in `scripts/generate_*_plate.py`.
- **Determinism.** Frames must be byte-identical across processes: never `hash()`; seed from `_row_digest` or a fixed seed. Don't read the wall clock unless listed in `CLOCK_DEPENDENT_THEMES`, and then only through `clock.now()` (`render_quote/clock.py`), the renderer's single clock seam. Reach it through its module, never `from .clock import now`: a name import is a second binding that a patch on the seam cannot reach. A golden-suite AST fence rejects both a direct clock read (`now()`, `today()`, `time.time()`, `fromtimestamp()` …) and a name import of the seam. For a pure code move, `scripts/render_fingerprint.py` hashes every theme's frames, so a run on `main` and a run on the branch must match exactly. That is stricter than the golden suite's 0.1% tolerance.
- **Time surfaces.** The matched phrase carries the time. Never print HH:MM digits unless the object genuinely is a clock (`vhs` OSD). Hour-only carriers (Roman numerals, camera number, due stamp…) are pinned byte-identical across the minutes of an hour; otherwise `del time_str` at frame entry.
- **Fixed-geometry frames** compose at the canonical 800×480 and NEAREST-downsample for other sizes (`metro` convention; `TestFixedGeometryFramesDownscale`). Per-pixel writes must be bounds-clipped for `/api/preview` thumbnails.
- **Small text** in hairline serifs or two-ink stipples shreds after palette snapping — use a sturdier face or a solid ink for bylines and chrome.

### Runtime Loop (`run_clock.py`)

**Full reference: [`docs/runtime.md`](docs/runtime.md)**: config precedence, quiet hours and the sleep frame, auto/random themes, buttons, persisted state, telemetry and health gates, backoff, the watchdog, shutdown, and the per-module ownership / lock / thread tables. Read it before changing any `runtime_*` module.

**Tick.** Every `--interval-seconds` (60) the loop computes the fuzzy bucket. On a bucket or theme change it calls `peek_quote_id` in-process, skips the redraw if the `(source_id, line_number, display_quote, matched_text)` identity is unchanged, and otherwise spawns the renderer (`python -m idle_hours.render_quote`, or a custom `--render-script`) pinned to that exact row (`--pin-quote … --pin-matched-text …`) plus the optional `--display-script`. It appends to the anti-repeat ledger only after a successful render. `--once` renders one frame strictly; the loop logs and survives failures.

**Config.** `--config PATH` loads TOML whose keys mirror the argparse `dest` names; precedence is **CLI > config > argparse default** via `parser.set_defaults`. Malformed content fails open with a warning. A missing `--config` file, or a missing input path at pre-flight, exits **42** (`EXIT_CONFIG_ERROR`, paired with `RestartPreventExitStatus=42`). A new flag must be wired into `CONFIG_SCHEMA` (or `TRANSIENT_KEYS`), `config.toml.defaults`, and `config.toml.example`; tests enforce each. The two `config.toml.*` files are operator-facing copies, so their fences stay. `CONFIG_SCHEMA` is a Python copy of the argparse dests that should be derived from the parser; until it is, don't model new code on it.

**Invariants worth knowing before editing:**
- **Every repaint pins the displayed quote** (`displayed_quote(state)`) and never re-peeks. A peek is history-filtered and would return a *different* row.
- **Quiet hours:** `render_quiet_frame` is the single "put the panel to sleep" path (honours `--quiet-image auto|<path>|""`, `--quiet-theme`), and the caller holds `render_lock`. `claim_quiet_edge` is the single edge detector, and whoever paints the frame claims the edge. A failed entry is retried through the backoff.
- **Theme resolution:** manual override (button B / web) wins until midnight. `auto` uses the day/night picks. `random` draws from a shuffled bag with a recent-window guard, once per displayed quote. `resolve_quiet_theme` is the source of truth for what is shown while asleep.
- **Identity triple** `(last_bucket, last_quote_id, last_effective_theme)` is committed after a successful render through `commit_render_result` and persisted, so a restart doesn't redraw. Transient modes (`card`) never commit. A few paths write fields directly on purpose: quiet exit, a failed shutdown and a pushed `--startup-image` clear `last_bucket` / `last_quote_id` so the next tick repaints, the main loop advances `last_bucket` when a peek finds the quote unchanged, and it seeds `last_effective_theme` on the first tick.
- **Three locks:** `render_lock` (coarse; buttons/web take it non-blocking via `_button_render_gate` and drop on busy), `state.lock` (fields; may nest inside `render_lock`), `ledger_lock` (history file; never nested). Never hold `state.lock` or `ledger_lock` across a subprocess.
- **All actions converge:** GPIO buttons and web POSTs both call `runtime_actions.action_*` → `_button_render_gate` → `_render_unlocked` → `commit_render_result`. There is no separate web path.
- **Read helpers through their module, patch them where defined** (issue #353). Callers write `runtime_render.render_now(...)`, never `from runtime_render import render_now`, so a test patches `runtime_render.render_now` once and every caller sees it. No module under `idle_hours/` except `idle_hours_cli` imports `run_clock`, and `run_clock` re-exports nothing; `tests/test_runtime_layering.py` fences both.
- **Durability:** state, overrides, corpus and PNG writes all go through `atomic_io`, which stages through a unique temp file and reaps stale ones. A single-instance `fcntl` pidfile guards the loop.
- **Supervision:** subprocesses run under timeouts (render 45 s, display 60 s). Failures back off exponentially. Heartbeats are telemetry entries stamped with quiet state, and systemd `WATCHDOG=1` is pinged at every subprocess boundary as well as from the heartbeat. SIGTERM drains the in-flight render.
- **Telemetry:** date-rotated JSONL sibling files, fsync'd except heartbeats, pruned after `--telemetry-retain-days`. `idle-hours health` summarises it, and its render-age gates stand down while quiet hours are active.

**Buttons** (A/B/C/D on GPIO 5/6/16/24; long press = 2 s): A skip / long-press un-skip · B cycle theme · C 5 s source card · D sleep-or-wake toggle / long-press shutdown. The full table, including the cycle chain, is in `docs/runtime.md`.


### Inky Display Bridge (`display_inky.py`)

Minimal Pillow → Pimoroni `inky.auto` bridge. Loads the PNG, resizes to the panel's native size if needed, and calls `inky.set_image(..., saturation=...).show()`. Designed to be called once per render from `run_clock.py`. Only needed on the Pi. Up to `MAX_ATTEMPTS` (3) calls are retried with `RETRY_BACKOFF_SECONDS = (1, 4)` between attempts so a momentary I/O hiccup doesn't crash the caller; if all attempts fail the script raises `SystemExit` so the loop in `run_clock.py` logs and moves on.

**Per-theme saturation.** `THEME_SATURATION` gives every registered theme one of two values. A light page ground takes `0.5`, which keeps accents from blowing out on white. A dark or coloured ground, or one dominated by falling-density blooms, takes `0.7`, which stops accents going muddy against it. The themes that break that rule carry a one-line reason in the table, and `test_tier_follows_page_ground_except_listed_themes` keeps the rule and the list honest. The values are starting points, not panel measurements. `test_every_render_theme_has_saturation` fails if a new `THEMES` entry has no row. `runtime_render.render_now` forwards `--theme` to `display_inky.py`, which calls `resolve_saturation(theme, override)`; an explicit `--saturation` always wins.

### Curator Web UI (`web_server.py`, `idle_hours/web/`)

**Full reference: [`docs/web_ui.md`](docs/web_ui.md)**: every endpoint, the security model, the connection limits, bake/ban/overrides semantics, and the UI layout.

Off by default. `--web-bind HOST:PORT` starts a `ThreadingHTTPServer` on a daemon thread **inside `run_clock`**, sharing `RuntimeState` and its locks. In-process is non-negotiable, because mutating POSTs go through the same `_button_render_gate` as the buttons. A startup failure is logged, not fatal. Static UI is plain HTML/JS/CSS with no build step.

**Security model.** Loopback binds skip auth. Any other bind **requires** `--web-token` / `--web-token-file` (hot-reloaded on mtime). A configured token gates every POST, every JSON GET, `/current.png` and `/api/preview`, via the `X-Idle-Hours-Token` header only. Only the static shell (and `/metrics` unless `--web-metrics-token`) stays open. On every bind, independent of the token: POSTs require `Content-Type: application/json` (415), `Origin` must match `Host` (403), and `Host` must be allowed for the bind (403, the DNS-rebinding guard; extend with `--web-allowed-host`). Unknown routes 404 before the auth check.

**Curation.** `/api/bucket` and `/api/search` read the **raw** corpus on purpose, so an operator can see rows the baker dropped. `POST /api/overrides` honours `If-Match` ETags (412 on a stale save). `POST /api/overrides/ban` does the ban read-modify-write server-side. `POST /api/bake` re-applies content overrides, writes the patched raw corpus back, and bakes in-process (409 if a render is in flight). Coverage and gaps are computed live using the baker's displayability gates.

### Appliance / Pi Setup

- **Fresh Pi:** `scripts/bootstrap_pi_inky.sh` runs from a checkout. First pass: installs the apt runtime deps plus Raspberry Pi OS's `python3-lgpio` / `python3-rpi-lgpio` GPIO backend, enables I2C + SPI, and stages `dtoverlay=spi0-0cs` in the boot config, then stops for the reboot. The Spectra 6 (E673) driver opens `/dev/spidev0.0` for data but drives GPIO8 chip-select itself, and the ordinary SPI overlay claims GPIO8 in the kernel — `spi0-0cs` exposes the bus with no kernel-owned chip selects. Second pass (`CONTINUE_AFTER_REBOOT=1`): verifies `/dev/spidev0.0` exists and GPIO8 is unclaimed, creates `~/.virtualenvs/pimoroni` with `--system-site-packages` (so the venv sees the distro's `lgpio` / `RPi.GPIO` — `gpiozero` on its own ships no pin backend, and the PyPI `rpi-lgpio` needs native build tools on Trixie / Python 3.13), installs `.[pi]`, renders once and pushes once. `tests/test_pi_deployment_contract.py` pins those contracts as string fences on the script, the unit and the appliance config.
- **Manual Pi notes:** `docs/pi_setup_inky_impression.md` is the long-form guide (hardware list, OS baseline, SPI / GPIO backend configuration, troubleshooting, the `~/.idle-hours` → `/var/lib/idle-hours` migration).
- **Boot-time service:** `ops/idle-hours.service.example` runs `python -m idle_hours.run_clock --config %S/idle-hours/config.toml` as `pi` under the `~/.virtualenvs/pimoroni` Python. Both `WorkingDirectory=` and `Environment=LG_WD=` are `/var/lib/idle-hours` and must stay equal: `lgpio` creates its `.lgd-nfy*` button-notification FIFO in `LG_WD` while its Python wrapper opens that FIFO relative to CWD, and the state directory is the one path writable under the sandbox without a `ReadWritePaths` hole into `$HOME`. The appliance preset writes `output` there as well, which is what let the old `/home/pi/IdleHours/output` carve-out go. Only `User=` and the `ExecStart=` interpreter path are install-specific.
- **Container (v2):** `Dockerfile` is a multi-stage OCI build — stage 1 produces wheels, stage 2 installs them into a Python 3.12-slim runtime as a non-root `idlehours` user. ARM64-first for Pi appliance use, multi-arch via `docker buildx build --platform linux/arm64,linux/amd64 -t idle-hours:3.0 .`. The Pi-only `[pi]` extra (`gpiozero` / `inky`) is **not** installed by default — that's a Pi-runtime concern. The base image renders PNGs and serves the curator UI without GPIO bindings. Run with `docker run --rm -p 8080:8080 -v idle-hours-state:/state idle-hours:3.0 idle-hours run --buttons-off --skip-preflight --web-bind 0.0.0.0:8080 --state-path /state/state.json --history-path /state/history.jsonl --telemetry-path /state/telemetry.jsonl --pidfile /state/run_clock.pid` for a headless dev instance. `.dockerignore` keeps `data/` (cached Gutenberg downloads), `output/`, `.git/`, and `tests/golden/` out of the build context so `buildx` doesn't ship multi-GB caches.

### Release Tooling

`scripts/release.py prepare X.Y.Z` (from a clean `main` matching `origin/main`) promotes the changelog, bumps `pyproject.toml`, runs the non-golden suite, verifies the built wheel's metadata and commits on `release/vX.Y.Z`; `finalize X.Y.Z` re-checks after merge and creates the annotated tag. It never publishes, and never pushes without `--push`. Details in `docs/CONTRIBUTING.md` ("Releases").

### Testing

**Full reference: [`docs/testing.md`](docs/testing.md)**: suite layout, golden fixtures, the decoration and docs fences, the JS suite, packaging tests, pyproject settings, and the CI job matrix.

- One `tests/test_<module>.py` per module, class-based. `tests/conftest.py` isolates `$HOME` per test and unsets `IDLE_HOURS_PHOTO_PATH`.
- **Build a `run_clock` Namespace with `make_args(tmp_path, **overrides)`** from `tests/conftest.py`, never `argparse.Namespace(...)` by hand. It starts from the real parser, so runtime code reads `args.x` with no `getattr` fallback (issue #396).
- **Golden renders:** `tests/golden/renderer/*.png`, one per theme plus layout/mode scenarios, compared at ≤0.1% differing pixels. Regenerate with `UPDATE_RENDER_GOLDEN=1 pytest tests/test_render_golden.py`. README previews must stay current: `scripts/generate_theme_previews.py --check` runs in CI.
- **Structural fences** fail on *absence*, not just on change: `test_theme_decoration.py` (each painter/frame must actually paint), `test_docs_theme_registry.py` (doc rosters vs. the registries; a regex that matches nothing fails loudly), `test_font_table.py` (the generated font table is current and every bundled font is used), `test_ci_required_checks.py` (every CI job is required or explicitly advisory), `test_packaging.py` (wheel contents, no hardware imports).
- **Patch where a name is read.** `render_quote` is a package (issue #335). Reads through it (`rq.X`) resolve live in the submodule that binds `X`, but every write through it raises (`monkeypatch.setattr(rq, X, …)`, `patch("idle_hours.render_quote.X")`, `rq.X = …`), and `tests/test_render_quote_facade.py` fences the source for any such write. Patch the submodule whose code reads the name, e.g. `themes.<name>` for a theme's call site (`paint_neon_mask` as the `culture` frame reads it is `themes.culture.paint_neon_mask`), `text` for `_draw_text_body`'s (`tests/test_render_quote_facade.py`). To stub a whole border painter, replace its spec in `BORDER_SPECS`, which covers both of `render`'s passes.
- **Pixel assertions** use `tests/pixel_helpers.py` (`distinct_inks`, `ink_counts`, `pixel_bytes`), never `Image.getdata()`. Pillow removal notices are errors via `filterwarnings`.
- **Curator JS:** `node --test tests/js/*.test.mjs` loads the real `web/main.js` in a `node:vm` sandbox. The pytest bridge skips without node, so CI runs it directly.
- **Type checking:** `mypy` (no arguments) checks the whole `idle_hours` package, `render_quote` included. Pillow types a pixel as `float | tuple[int, ...]` because it cannot know the image mode, so per-pixel access goes through `palette.pixel_access` (an RGB frame), `gray_pixel_access` (a `1` / `L` mask, typed `int`) or `rgb_pixel_access` (typed `tuple[int, ...]`), never a bare `image.load()`. The typed two check the mode at runtime, which is what makes the narrower type true. `textbbox` is typed `float`; where a width must be an `int` (a `range`, an `Image.new` size), take `int()` of a box measured at `(0, 0)`, which is whole pixels already.
- **CI** (`.github/workflows/ci.yml`): `lint`, `typecheck`, `test (3.11)`, `test (3.12)`, `golden-render`, `web-ui-js`, `package-build` are required (`.github/rulesets/main-branch.json`). `coverage` (95% branch floor) and the tag-only `release-version` are advisory.

### Repo Layout

Every Python module and bundled runtime asset lives under the single `idle_hours/` package, which the wheel ships directly (`[tool.setuptools.packages.find]` + `[tool.setuptools.package-data]` in `pyproject.toml` are the source of truth for its contents). `output/` and `data/` are runtime artefacts; `scripts/`, `docs/`, `ops/` and `tests/` stay at the repo root and are not in the wheel. The README's "Repo map" describes each module from an operator's side; what follows is what you need when editing.

```
idle_hours/
├─ __init__.py              empty package marker (no re-exports)
├─ idle_hours_cli.py        `idle-hours <subcommand>`: lazy-imports each module's main() and rewrites sys.argv
├─ buckets.py               the bucket table and rounding rule (single source of truth)
├─ atomic_io.py             tmp-sibling → fsync → os.replace → dir-fsync; every file the next tick reads is written through it
├─ jsonl_io.py              streaming JSONL reader that logs and skips malformed lines
├─ gutenberg_time_miner.py, merge_candidates.py, bucket_coverage.py, target_sparse_buckets.py,
│  import_targeted_hits.py, clean_display_quotes.py, quality_filter.py, enrich_metadata.py,
│  apply_content_overrides.py, bake_quote_database.py
│                           the pipeline stages, in docs/pipeline.md order
├─ fix_substring_time_matches.py, fix_legacy_buckets.py
│                           legacy one-shot migration tools; no-ops on fresh harvests
├─ pick_quote.py            ranking, overrides, neighbour fallback, anti-repeat ledger (select_quote)
├─ render_quote/            the renderer package (issue #335; layering in docs/render_quote_split.md, fenced by
│                           tests/test_render_quote_layering.py). Shared layers, lowest first, each importing only
│                           from those before it: _paths → clock → palette → theme_tables → fonts → layout → text →
│                           primitives → furniture → themes/_shared, themes/_culture_common → themes/<name>.py (one
│                           module per theme, ending with its SPEC) → registry. spec sits just below themes/. core
│                           holds render(), the source card, the sleep frame and the CLI; _facade.py makes
│                           render_quote.X read live and refuses writes; __main__.py is what run_clock runs.
├─ contact_sheet.py         12×12 grid of every bucket's pick, for offline QA
├─ run_clock.py             thin orchestrator for the loop; reads runtime_* helpers through their modules, re-exports
│                           nothing, and nothing imports it back (issue #353)
├─ runtime_config.py        TOML config loader + validate_hhmm
├─ runtime_state.py         RuntimeState: locks and the shared mutable state
├─ runtime_store.py         persisted state.json (manual overrides + render-identity triple)
├─ runtime_telemetry.py     date-rotated telemetry + retention; fans alert-worthy entries out to runtime_webhook.py
├─ runtime_theme.py         auto / manual / random theme resolution
├─ runtime_quiet.py         quiet-hours state machine and render_quiet_frame (the one sleep-frame path)
├─ runtime_render.py        the render path: render_now (renderer + display subprocesses, timeouts), peek_quote_id,
│                           displayed_quote, _pin_key_for, ledger append, render backoff, renderer selection
├─ runtime_actions.py       action_* shared by GPIO buttons and the web UI, plus _button_render_gate
├─ runtime_log.py           timestamped logger
├─ path_resolution.py       resolve_input_path (CWD, then bundled) and PHOTO_PATH_ENV
├─ theme_names.py           the theme roster: THEME_ORDER, CYCLE_EXCLUDED_THEMES, known_theme_names, theme_cycle (Pillow-free)
├─ pidfile.py, sd_notify.py single-instance lock; stdlib systemd READY / WATCHDOG client
├─ idle_hours_health.py     telemetry summariser and health gates
├─ display_inky.py, inky_buttons.py, probe_buttons.py
│                           Pi-only: panel bridge (retry, per-theme saturation), button listener, GPIO probe
├─ web_server.py + web/     optional curator UI (vanilla HTML/JS/CSS, no build step)
├─ fonts/                   one directory per bundled family, each with its licence; which theme loads which
│                           face is the generated table in docs/themes.md ("Bundled fonts")
└─ assets/                  quote_database.jsonl (baked, what the runtime reads), candidates-attributed.jsonl (raw
                            corpus), selection_overrides.json, content_overrides.json, bucket-coverage.{json,md},
                            contact-sheet.png, goodnight.png, config.toml.example (appliance preset),
                            config.toml.defaults (every argparse default), committed raster plates (regenerate
                            with scripts/generate_*_plate.py or scripts/ingest_*.py, never by hand), previews/
                            (scripts/generate_theme_previews.py), tarot/ and semiotic/ source + attribution

scripts/   bash drivers (run_batch2.sh, run_dawn_expansion.sh) and their Gutenberg ID lists; bootstrap_pi_inky.sh;
           release.py; render_fingerprint.py (byte-identity check for pure render refactors);
           generate_theme_previews.py; generate_font_table.py; generate_*_plate.py / ingest_*.py (raster art)
docs/      the references in the table at the top of this file, plus UPGRADE.md, SECURITY.md, CODE_OF_CONDUCT.md
ops/       idle-hours.service.example (Type=notify, WatchdogSec, StateDirectory, sandbox)
tests/     one module per backing module; pixel_helpers.py; golden/renderer/*.png; js/ (node --test suite)
.github/   workflows/ci.yml; rulesets/main-branch.json (the required-check list, fenced by test_ci_required_checks.py)
Dockerfile, .dockerignore   multi-stage OCI build, ARM64-first, no [pi] extra
```
