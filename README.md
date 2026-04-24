# LitClock

LitClock is a literary clock built from public-domain text. It picks a quote that matches the current fuzzy time bucket, renders it into an 800×480 image, and can push that image to an eInk display such as the Pimoroni Inky Impression 7.3.

![LitClock render preview](assets/preview.png)

## What this repo is

This repo contains both:

- the **runtime clock** that picks and renders quotes for the current time
- the **corpus/build tooling** used to mine, clean, enrich, and improve the quote dataset

If you are deploying or operating the clock, you mostly care about the runtime and the prebuilt assets in `assets/`.

## How LitClock was built

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

- `run_clock.py` - long-running clock loop, bucket-change refresh logic, optional display handoff
- `render_quote.py` - quote renderer, typography, highlighting, theme handling, Spectra 6 palette snapping
- `pick_quote.py` - runtime quote selection from the attributed dataset
- `display_inky.py` - thin bridge that sends a rendered image to the Inky display
- `inky_buttons.py` - listener for the four Inky Impression capacitive buttons (A/B/C/D), short + long press, liveness check
- `probe_buttons.py` - standalone GPIO press probe for verifying which pin each physical button fires
- `litclock_health.py` - summarises the telemetry sidecar (render count, p50/p95 latency, last error); supports `--json`, reads date-rotated files
- `buckets.py` - fuzzy time bucket mapping
- `web_server.py` + `web/` - optional local curator UI (off by default; enable with `--web-bind`)

### Runtime assets

- `assets/quote_database.jsonl` - **baked, display-ready runtime DB** (what the clock reads by default; produced by `bake_quote_database.py`)
- `assets/candidates-attributed.jsonl` - raw attributed corpus (baker input; curator-UI bucket inspector; defensive fallback if the baked DB is missing)
- `assets/selection_overrides.json` - selection tweaks/overrides used at runtime (bans, boosts, preferred buckets; editable via the curator UI)
- `assets/goodnight.png` - pre-rendered dark-theme "good night" frame shown during quiet hours
- `assets/preview.png` - README preview image

### Build and corpus tools

- `gutenberg_time_miner.py`
- `clean_display_quotes.py`
- `quality_filter.py`
- `enrich_metadata.py`
- `merge_candidates.py`
- `bucket_coverage.py`
- `fix_substring_time_matches.py`
- `target_sparse_buckets.py`
- `import_targeted_hits.py`

### Other important paths

- `tests/` - automated tests
- `output/` - generated output and analysis artifacts, not canonical runtime source
- `fonts/` - bundled Playfair Display fonts used by the renderer
- `litclock.service.example` - example systemd service for Pi deployment
- `pi_setup_inky_impression.md` - Pi setup notes
- `bootstrap_pi_inky.sh` - helper bootstrap script for Pi setup

## Runtime data contract

For normal runtime use, the clock expects prebuilt assets and does **not** need raw Gutenberg texts to render quotes. The canonical runtime input is `assets/quote_database.jsonl` — the display-ready DB baked from the raw corpus with scoring pre-computed. Everything else in `assets/` is either the raw corpus the baker reads, a hand-edited sidecar, or a build-time artifact.

| Path | Role | Committed | Ships to Pi | Produced by |
|---|---|---|---|---|
| `assets/quote_database.jsonl` | **baked display-ready DB — the runtime picker reads this** | yes | yes | `bake_quote_database.py` |
| `assets/candidates-attributed.jsonl` | raw attributed corpus | yes | yes (baker input + curator UI + fallback) | `enrich_metadata.py` → `apply_content_overrides.py` |
| `assets/content_overrides.json` | per-row hand fixes (source-of-truth) | yes | no (build-time only) | hand-edited |
| `assets/selection_overrides.json` | bans / boosts / preferred buckets (runtime-editable) | yes | yes | hand-edited or web UI |
| `assets/bucket-coverage.{json,md}` | coverage snapshot | yes | optional | `bucket_coverage.py` |
| `~/.litclock/state.json` | manual theme / quiet override | — | runtime, per-appliance | `run_clock.py` |
| `~/.litclock/history.jsonl` | anti-repeat ledger | — | runtime, per-appliance | `run_clock.py` |
| `~/.litclock/telemetry-YYYYMMDD.jsonl` | render / error telemetry | — | runtime, per-appliance | `run_clock.py` |

Read it as: `candidates-attributed.jsonl` + `content_overrides.json` are the **source of truth**; `quote_database.jsonl` is **derived** (regenerated by the baker) and is what the clock actually reads; the `~/.litclock/*` files are **per-appliance runtime state**. Treat `data/` and the mining/enrichment scripts as build-time tooling, not service startup dependencies.

If you are only updating the clock on a Pi, you should not need to rebuild the corpus on-device — the baked DB already ships in the repo.

## Quick start

### Local setup

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

### Render once locally

```bash
python3 run_clock.py --once
```

### Config file (recommended for appliance installs)

For a long-running appliance you almost never want the slew of CLI flags
below on the command line — move them into a TOML config and point
`run_clock.py` at it once:

```bash
# Copy the annotated example and edit in place
cp assets/config.toml.example ~/.litclock/config.toml
$EDITOR ~/.litclock/config.toml

# Run the loop using that config
python3 run_clock.py --config ~/.litclock/config.toml
```

Every key maps 1:1 to an argparse `dest` (snake_case — `display_script`,
`quiet_start`, `web_bind`, etc.), so anything you'd pass on the CLI can
live in the file. Precedence is **CLI flag > config value > argparse
default**, so ad-hoc one-offs like `--once`, `--mode debug`, or a
temporary `--quiet-off` still work on top of a shipped config. Three
transient flags are deliberately refused in the file (`--once`,
`--skip-preflight`, and `--config` itself) — listing them warns and
drops.

Fail-open on malformed / unreadable / schema-mismatched content (warns
to stderr, keeps running with argparse defaults); the one hard error is
pointing `--config` at a non-existent path, so a typoed unit-file path
fails fast in the journal instead of silently booting with defaults.

The shipped `litclock.service.example` passes `--config %S/litclock/config.toml`
exclusively — so tuning the appliance is a file edit plus `systemctl
restart`, no `daemon-reload` needed.

### Render once and push to the Inky display

```bash
python3 run_clock.py --once --display-script display_inky.py --mode production
```

### Run the full clock loop locally

```bash
python3 run_clock.py --display-script display_inky.py --mode production
```

### Themes

Five themes ship built-in, all constrained to the Spectra 6 panel palette (white / black / red / yellow / blue / green). Previews all show the same quote so the palette differences are the only variable — the real renders adapt layout to the picked line's length.

| `--theme`     | Preview | Page bg | Body text | Accent  | Feel                                   |
|---------------|---------|---------|-----------|---------|----------------------------------------|
| `default`     | <img src="assets/previews/default.png" width="240" alt="default theme preview">     | white   | black     | red     | Classic broadsheet                     |
| `dark`        | <img src="assets/previews/dark.png" width="240" alt="dark theme preview">        | black   | white     | yellow  | Night mode                             |
| `scholar`     | <img src="assets/previews/scholar.png" width="240" alt="scholar theme preview">     | white   | blue      | red     | Scholarly journal                      |
| `newsprint`   | <img src="assets/previews/newsprint.png" width="240" alt="newsprint theme preview">   | white   | black     | (none)  | Pure typography — bold-weight accent   |
| `nightvision` | <img src="assets/previews/nightvision.png" width="240" alt="nightvision theme preview"> | black   | green     | yellow  | Retro terminal / Apollo-era monitor    |

Pass `--theme auto` to let the clock pick by wall-clock time — `dark` between 18:00 and 06:00, `default` otherwise. `auto` is deliberately binary; the three "operator-choice" themes are never auto-selected. A manual button-B press (or a web-UI dropdown jump) overrides `auto` until the next midnight rollover.

Button B cycles forward through the list and wraps; the curator web UI at `/api/themes` exposes the same cycle plus a dropdown that jumps directly to any named theme. Clicking Apply on an unchanged selection is a no-op — it won't burn a 10–20 s eInk refresh and won't silently disable `auto` mode.

> Regenerate previews: the images under `assets/previews/` can be rebuilt from the renderer with a one-liner that loops over `render_quote.THEME_ORDER` and calls `render_quote.render(...)` with a fixed quote row. They're checked in so the README renders on GitHub without a build step.

### Inky buttons (short and long press)

The four capacitive buttons on an Inky Impression 7.3 are active whenever `run_clock.py` runs on a Pi with the `gpiozero` package installed. Pass `--buttons-off` on dev hosts or for headless smoke tests.

| Button | Short press | Long press (2s) |
|---|---|---|
| **A** | Skip — bans the current quote in the history ledger and picks a new one. | Un-skip — removes the last-skipped ban from the ledger and re-renders. Reverses a fat-fingered tap. |
| **B** | Cycle theme — advances through `default → dark → scholar → newsprint → nightvision` (wraps), persists to `--state-path`. The curator web UI also exposes a dropdown that jumps straight to any named theme. | — |
| **C** | Source card — shows a 5-second overlay with the title / author / Gutenberg ID / matched phrase. | — |
| **D** | Quiet now / wake — toggles the manual quiet override, persists to `--state-path`. | Shutdown — shows the goodnight frame, then runs `--shutdown-command` (default `sudo -n shutdown -h now`; empty to disable). |

Short and long actions are mutually exclusive per press: a long press fires only the hold callback, a quick tap fires only the short one.

If a button press lands while a render is already in flight (a Spectra 6 refresh can take 10–20s), the press is logged and dropped rather than queued — the UX is "first press wins, subsequent taps during that refresh are no-ops." Each hardware press is also logged with its GPIO pin so you can confirm the physical button reached the expected handler; for deeper wiring diagnosis run `python3 probe_buttons.py` on the Pi. The main loop also watches for a dead button listener (pin claim lost, background thread crashed) and logs one loud warning plus a telemetry entry if it detects one — presses won't work again until the process restarts.

### Persisted runtime state and telemetry

The loop can persist the manual theme and quiet overrides so they survive a restart, and it can log one JSONL entry per render/error for after-the-fact "is the appliance OK?" checks.

```bash
# Default paths (pass an empty string to disable either)
python3 run_clock.py \
  --state-path ~/.litclock/state.json \
  --telemetry-path ~/.litclock/telemetry.jsonl

# Human-readable telemetry summary for the last 24h
python3 litclock_health.py --hours 24

# JSON summary for cron / systemd health checks (exits 2 when unhealthy)
python3 litclock_health.py --hours 1 --json --fail-if-no-renders
```

Every file the next tick or boot reads is written atomically (`tmp → fsync → rename → fsync dir`) via the shared `atomic_io` helpers — runtime state, the rendered `output/current.png`, the selection-overrides sidecar, the history-ledger rewrite path, and the `apply_content_overrides` corpus writeback. A power cut or `SIGKILL` mid-write leaves the previous-known-good file byte-identical; it never leaves a truncated PNG or an empty ledger.

`SIGTERM` and `SIGINT` are handled gracefully: `systemctl restart litclock.service` flips a shared event that the main loop observes between ticks, drains any in-flight render via `state.render_lock`, stops the curator web server, closes GPIO buttons, and persists runtime state one last time before the process exits. `--once` keeps strict-exit behaviour for cron callers.

Telemetry is rotated by date: the `--telemetry-path` argument is a base path, but `run_clock.py` actually writes to `<stem>-YYYYMMDD<suffix>` siblings (e.g. `~/.litclock/telemetry-20260420.jsonl`) so a multi-year-running appliance keeps file size bounded. `--telemetry-retain-days` (default 90; pass 0 to disable) unlinks siblings older than that once per local-date rollover. `litclock_health.py` globs the directory for those siblings plus any legacy unsuffixed file at the exact base path and stream-reads them in order.

`litclock_health.py` exit codes:

- `0` — healthy (renders happened in the window, or no errors with nothing scheduled)
- `1` — telemetry log missing
- `2` — unhealthy: errors but zero renders, or `--fail-if-no-renders` with a silent window

### Startup frame

```bash
# Optional: push a static frame to the panel before the first quote renders
# so a cold boot doesn't ghost yesterday's image.
python3 run_clock.py --startup-image assets/goodnight.png
```

The extra refresh costs a Spectra 6 cycle (~10–20s) so this is off by default; enable when you care more about clean boot visuals than time-to-first-quote.

### Curator web UI

Off by default. Pass `--web-bind` to expose a small local HTTP surface that mirrors the physical buttons and lets you browse the corpus:

```bash
# Loopback only: safe to run anywhere, no auth required.
python3 run_clock.py --web-bind 127.0.0.1:8080
# open http://127.0.0.1:8080 in a browser

# LAN exposure: every POST requires a token supplied via X-LitClock-Token.
# Prefer --web-token-file on production so the token doesn't show up in `ps`.
echo "s0me-l0ng-random-string" > ~/.litclock/web.token
chmod 640 ~/.litclock/web.token
python3 run_clock.py --web-bind 0.0.0.0:8080 --web-token-file ~/.litclock/web.token
```

#### Turning the web UI on for an existing install

There is nothing extra to install — `web_server.py` and `web/` already ship with the repo and the UI is just a CLI flag on `run_clock.py`. To enable it on a box that is already running, add `--web-bind` to however you launch `run_clock.py`:

**Dev machine (foreground run).** Stop the current process and relaunch with the flag:

```bash
python3 run_clock.py --web-bind 127.0.0.1:8080
# then open http://127.0.0.1:8080
```

**Pi running under systemd.** Edit the config file that `ExecStart=` points at — no `daemon-reload` needed when you stay inside the config:

```bash
sudoedit /var/lib/litclock/config.toml
# add: web_bind = "127.0.0.1:8080"
sudo systemctl restart litclock.service
systemctl status --no-pager litclock.service     # confirm it came back up
```

`assets/config.toml.example` already ships commented-out `web_bind` / `web_token_file` lines near the bottom — uncomment the pair you want and you're done. (If the unit still uses raw `--web-bind` CLI flags on `ExecStart=`, `sudoedit` the unit itself and `daemon-reload` first, then `restart`.)

**Reaching a loopback-bound UI from another machine.** Keep the `127.0.0.1:8080` bind (no token needed) and SSH-tunnel into the Pi from your laptop:

```bash
ssh -L 8080:127.0.0.1:8080 pi@raspberrypi.local
# leave that session open, then open http://127.0.0.1:8080 on your laptop
```

**Reaching it directly over the LAN.** Switch to `0.0.0.0:8080` *and* supply a token file — `start_web_server` refuses to bind a non-loopback address without one, so you cannot accidentally expose a tokenless POST surface:

```bash
sudo install -m 640 -o pi -g pi /dev/null /var/lib/litclock/web.token
python3 -c "import secrets; print(secrets.token_urlsafe(32))" | sudo tee /var/lib/litclock/web.token > /dev/null
# edit /var/lib/litclock/config.toml to set:
#   web_bind       = "0.0.0.0:8080"
#   web_token_file = "/var/lib/litclock/web.token"
sudo systemctl restart litclock.service
```

Browsers can still `GET` the UI without credentials (telemetry, coverage, `current.png` are not sensitive), but every mutating `POST` must send `X-LitClock-Token: <the token>`. **Caveat:** the bundled `web/` UI does not currently attach that header — it was built for the loopback-no-auth path — so on a LAN+token bind the page loads and reads cleanly but the action buttons and overrides-save will come back as `401 missing or invalid token`. Until the UI grows a token field, the working options for a LAN+token deployment are:

- Drive mutating endpoints from `curl` (or any other client), e.g. `curl -X POST -H "X-LitClock-Token: $(cat ~/.litclock/web.token)" http://<pi>:8080/api/action/rerender`.
- Or just use the SSH-tunnel flow above — loopback bind needs no token and the bundled UI works end-to-end.

**How to tell it's working.** `journalctl -u litclock.service -n 20` should show a line like `web UI listening on 127.0.0.1:8080 (no token)` (or `(token required)` on a LAN bind). If the bind fails (port busy, missing token on a non-loopback bind) the main render loop keeps running and logs `web UI failed to start on …` — the panel won't go dark just because the web UI couldn't start.

The UI is vanilla HTML/JS/CSS served directly from `web/` — no build step, no framework, no extra runtime deps beyond what the clock already needs. When you open it you get:

- **Now showing** — live preview of `output/current.png`, the picked quote text, its attribution (`source_id` + `line_number`), and the matched time phrase the renderer bolded.
- **Controls** — five buttons that mirror the physical Inky panel (`A · Skip`, `A-hold · Un-skip`, `B · Cycle theme`, `C · Re-render`, `D · Quiet / wake`) plus a **theme dropdown** that jumps directly to any registered theme without stepping through the cycle. Each press returns `{ok: true}` or `{ok: false, error: "busy"}` and is appended to a small in-browser action log. A state pill next to the dropdown reports `manual: X` / `auto: X` / `fixed: X` so operators can see at a glance whether wall-clock switching is active.
- **Telemetry** — renders / errors / p50 / p95 latencies over the last 24h, reading the same date-rotated sidecar that `litclock_health.py` does.
- **Coverage grid** — 144 bucket cells coloured by corpus depth (from `assets/bucket-coverage.json`); click-through feeds the inspector.
- **Bucket inspector** — ranked candidate list for any bucket (or `HH:MM`), with every scorer component named so you can see *why* a different quote was not picked.
- **Overrides editor** — edits `assets/selection_overrides.json` inline; the server validates and atomically rewrites the file, rejecting bad bucket keys with 400.
- **History** — the anti-repeat ledger, newest first.

The UI shares the render lock with the button handlers, so every mutating action (skip, un-skip, theme, quiet, re-render, overrides save) respects "first press wins": a POST that lands during a 10–20s Spectra 6 refresh returns `409 busy` instead of queueing.

| Endpoint | Purpose |
|---|---|
| `GET /` | Curator HTML/JS/CSS |
| `GET /current.png` | Streams the current rendered frame |
| `GET /api/current` | `{time, bucket, theme, source_id, line_number, display_quote, matched_text, ...}` |
| `GET /api/telemetry?hours=24` | p50/p95 render/display latency + error counts (reuses `litclock_health`) |
| `GET /api/coverage` | The 144-bucket coverage snapshot from `assets/bucket-coverage.json` |
| `GET /api/themes` | `{themes, theme_arg, manual_theme, effective}` — feeds the dropdown |
| `GET /api/bucket/<bucket>?time=HH:MM&top=N` | Full ranked candidate list with per-component scores |
| `GET /api/overrides` | Current `assets/selection_overrides.json` |
| `GET /api/history?limit=N` | Recent anti-repeat ledger entries |
| `POST /api/overrides` | Validate + atomically rewrite overrides |
| `POST /api/action/{skip,unskip,theme,quiet,rerender}` | Mirrors buttons A/A-hold/B/D/C. `theme` accepts an optional `{"theme": "<name>"}` body to jump directly; empty body / missing field cycles. Malformed JSON returns 400 without mutating state. |

Security model: loopback binds (`127.0.0.1:*`, `localhost:*`, `::1:*`) skip auth entirely — the OS-level trust boundary is sufficient. Any other bind **requires** `--web-token` / `--web-token-file`; startup aborts rather than quietly expose a tokenless POST surface. Tokens are checked via the `X-LitClock-Token` header only; query-string tokens would leak into journald via HTTP request logging. GETs remain open on all binds — telemetry and `current.png` are not sensitive and the UI needs them without credentials.

### Quiet hours

The loop defaults to quiet hours **22:00–06:00** and pushes `assets/goodnight.png` to the display during that window instead of rendering corpus quotes.

```bash
# Shift or tighten the window
python3 run_clock.py --quiet-start 23:30 --quiet-end 07:00

# Swap the quiet image
python3 run_clock.py --quiet-image path/to/other.png

# Disable quiet hours entirely (24/7 rendering)
python3 run_clock.py --quiet-off
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
2. clone LitClock, render once, push once, then install the service

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
python stripes.py
```

#### Install LitClock on the Pi

```bash
source ~/.virtualenvs/pimoroni/bin/activate
git clone git@github.com:gkoch02/LitClock.git
cd ~/LitClock
python3 run_clock.py --once
python3 display_inky.py output/current.png
python3 run_clock.py --once --display-script display_inky.py --mode production
```

At that point, a fresh Pi should have everything needed to render locally and push to the display.

#### Optional bootstrap helper

There is also a helper script for first-time setup:

```bash
bash bootstrap_pi_inky.sh
```

That script installs base packages, launches the interactive Pimoroni installer, and then resumes LitClock setup after reboot.

### Existing Pi update flow

If the Pi is already provisioned and LitClock is installed, updating is simple:

```bash
git pull --ff-only origin main
sudo systemctl restart litclock.service
systemctl status --no-pager litclock.service
```

### Example service

See `litclock.service.example`.

Current service model:

- runs `run_clock.py`
- optionally calls `display_inky.py` after each render
- reads the prebuilt baked DB at `assets/quote_database.jsonl` (the canonical runtime input)
- does not rebuild corpus artifacts at startup

### Install the service

Once manual render and display tests work on the Pi:

```bash
cd ~/LitClock

# Stage the unit file and the config it references
sudo cp litclock.service.example /etc/systemd/system/litclock.service
sudoedit /etc/systemd/system/litclock.service    # fix User= / WorkingDirectory= / ExecStart= paths

# systemd creates /var/lib/litclock/ before ExecStart runs (StateDirectory=litclock),
# but the first boot still needs config.toml in place
sudo systemctl start litclock.service || true   # triggers StateDirectory creation
sudo cp assets/config.toml.example /var/lib/litclock/config.toml
sudo chown pi:pi /var/lib/litclock/config.toml
sudoedit /var/lib/litclock/config.toml          # tune keys for this appliance

sudo systemctl daemon-reload
sudo systemctl enable litclock.service
sudo systemctl restart litclock.service
sudo systemctl status litclock.service
```

Before enabling the service, update these fields to match the actual account and install path on the Pi:

- `User=`
- `WorkingDirectory=`
- `ExecStart=` (the path to `run_clock.py` and to the config file)

Day-to-day tuning after this — theme, quiet hours, web UI, startup
image, etc. — is a `sudoedit /var/lib/litclock/config.toml` +
`systemctl restart`. No `daemon-reload` because the unit file itself
doesn't change.

If another display service is already running, disable it first so LitClock owns the panel.

## Build pipeline notes

The build side of the repo exists to improve quote coverage and quality over time.

At a high level, the process is:

1. mine public-domain texts for time phrases
2. clean candidate quotes into displayable form
3. enrich and score them
4. merge and analyze coverage
5. apply per-row hand fixes from `assets/content_overrides.json`, producing the raw attributed corpus at `assets/candidates-attributed.jsonl`
6. bake that corpus into the display-ready `assets/quote_database.jsonl`, which is what the runtime clock actually reads

That work is intentionally separate from the steady-state render loop. Re-running step 6 (`bake_quote_database.py`) is what makes new corpus rows visible to a running appliance — committing raw-corpus changes without a matching bake ships no runtime effect.

## Operational notes

- The clock refreshes when the fuzzy time bucket changes, not every minute, and additionally skips a redraw when the picked quote is identical to the previous frame.
- If the exact bucket is weak or empty, the picker walks nearby buckets and records fallback metadata.
- `production` mode hides debug metadata for cleaner display output; `debug` mode draws a top-right `DEBUG MODE` banner and a centered bottom strip with bucket/layout/quality/id.
- Quiet hours are on by default (22:00–06:00) and show `assets/goodnight.png`; override with `--quiet-start` / `--quiet-end` / `--quiet-image`, or disable with `--quiet-off`. Button D toggles a manual quiet override at any time.
- Button B cycles through the full theme list and persists the choice to `--state-path`; the web UI dropdown jumps directly to any named theme. Button A's long press reverses the most recent skip.
- Five themes ship built-in: `default` (white/black/red), `dark` (black/white/yellow), `scholar` (white/blue/red), `newsprint` (white/black, no colour accent — bold-weight differentiation only), and `nightvision` (black/green/yellow retro-terminal). Every theme colour stays on the Spectra 6 palette.
- `--theme auto` switches dark/default by wall-clock time (dark 18:00–06:00); a manual button-B / web override wins until the next midnight rollover.
- Per-theme saturation: `display_inky.py` picks `0.5` for light-background themes and `0.7` for dark-background themes so accents don't go muddy.
- Telemetry at `--telemetry-path` (default `~/.litclock/telemetry.jsonl`) is rotated by date — `run_clock.py` writes to a `telemetry-YYYYMMDD.jsonl` sibling so long-running appliances don't accumulate one unbounded file. One line per render, one per loop-level error. `litclock_health.py --json` feeds systemd / cron health checks and auto-discovers the rotated siblings.
- The anti-repeat history ledger at `--history-path` (default `~/.litclock/history.jsonl`) is fsynced after each append so a power loss can't leave a buffered entry lost, and the reader logs a one-shot warning if it finds a malformed/torn line.
- If the Inky button listener dies mid-run (pin claim lost, background thread failed), the loop logs one loud warning plus a telemetry entry with `mode=buttons_dead` and stops retrying — restart the process to reclaim the pins.
- The optional curator web UI (`--web-bind`) runs in-process on a daemon thread and shares the render lock with the button handlers; it's the safe remote alternative to SSHing in to tap the panel or edit `selection_overrides.json` by hand. LAN binds require `--web-token` / `--web-token-file`.
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
- "which GPIO pin did that button actually fire?" -> `python3 probe_buttons.py` on the Pi
- "is the appliance alive?" -> `python3 litclock_health.py --hours 24` (use `--json` from cron)
- curator web UI / HTTP endpoints / overrides editor -> `web_server.py` + `web/` (enable with `--web-bind`)
- telemetry log (one JSONL entry per render/error) -> `~/.litclock/telemetry.jsonl`
- persisted manual theme / quiet override -> `~/.litclock/state.json`
- anti-repeat ledger of recently-shown quotes -> `~/.litclock/history.jsonl`
- runtime dataset questions -> `assets/quote_database.jsonl` (what the clock reads) + `assets/candidates-attributed.jsonl` (raw source)
