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
- `buckets.py` - fuzzy time bucket mapping

### Runtime assets

- `assets/candidates-attributed.jsonl` - shipped runtime quote dataset
- `assets/selection_overrides.json` - selection tweaks/overrides used at runtime
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

For normal runtime use, the clock expects prebuilt assets and does **not** need raw Gutenberg texts to render quotes.

- Use `assets/candidates-attributed.jsonl` as the deployable runtime dataset.
- Use `assets/selection_overrides.json` for runtime selection overrides.
- Treat `data/` and the mining/enrichment scripts as build-time tooling, not service startup dependencies.

If you are only updating the clock on a Pi, you should not need to rebuild the corpus on-device.

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

### Render once and push to the Inky display

```bash
python3 run_clock.py --once --display-script display_inky.py --mode production
```

### Run the full clock loop locally

```bash
python3 run_clock.py --display-script display_inky.py --mode production
```

### Themes

Pass `--theme dark` to either `run_clock.py` or `render_quote.py` for a black-background / yellow-accent variant. `--theme default` is the white-background / red-accent original.

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
- uses the prebuilt dataset in `assets/candidates-attributed.jsonl`
- does not rebuild corpus artifacts at startup

### Install the service

Once manual render and display tests work on the Pi:

```bash
cd ~/LitClock
sudo cp litclock.service.example /etc/systemd/system/litclock.service
sudoedit /etc/systemd/system/litclock.service
sudo systemctl daemon-reload
sudo systemctl enable litclock.service
sudo systemctl start litclock.service
sudo systemctl status litclock.service
```

Before enabling the service, update these fields to match the actual account and install path on the Pi:

- `User=`
- `WorkingDirectory=`
- `ExecStart=`

If another display service is already running, disable it first so LitClock owns the panel.

## Build pipeline notes

The build side of the repo exists to improve quote coverage and quality over time.

At a high level, the process is:

1. mine public-domain texts for time phrases
2. clean candidate quotes into displayable form
3. enrich and score them
4. merge and analyze coverage
5. ship the resulting attributed dataset as a runtime asset

That work is intentionally separate from the steady-state render loop.

## Operational notes

- The clock refreshes when the fuzzy time bucket changes, not every minute, and additionally skips a redraw when the picked quote is identical to the previous frame.
- If the exact bucket is weak or empty, the picker walks nearby buckets and records fallback metadata.
- `production` mode hides debug metadata for cleaner display output; `debug` mode draws a top-right `DEBUG MODE` banner and a centered bottom strip with bucket/layout/quality/id.
- Quiet hours are on by default (22:00–06:00) and show `assets/goodnight.png`; override with `--quiet-start` / `--quiet-end` / `--quiet-image`, or disable with `--quiet-off`.
- The renderer is tuned for the Pimoroni Inky Impression 7.3 / Spectra 6 800×480 display.
- Final renders are snapped to the exact Spectra 6 palette for better hardware fidelity.
- Renderer changes can be surprisingly fragile around text normalization, wrapping, and emphasis/highlight matching, so keep render tests healthy.

## Useful files when something breaks

If the clock is behaving oddly, these are the first files to inspect:

- quote selection problems -> `pick_quote.py`
- highlight/layout/render issues -> `render_quote.py`
- loop/update/dedup/service behavior -> `run_clock.py`
- display handoff issues -> `display_inky.py`
- runtime dataset questions -> `assets/candidates-attributed.jsonl`
