# Pi Setup Guide: Zero 2 W + Inky Impression 7.3 Spectra 6

This is the practical path for turning the literary clock prototype into a personal appliance.

## Choose your path

### Path A: Inky is already installed and working

If your Pi already has the Pimoroni Inky stack working in a virtualenv, this is the shortest path:

```bash
source ~/.virtualenvs/pimoroni/bin/activate
git clone git@github.com:gkoch02/LitClock.git
cd LitClock
python3 run_clock.py --once
python3 display_inky.py output/current.png
python3 run_clock.py --display-script display_inky.py
```

This works from the prebuilt runtime dataset already committed in the repo:
- `assets/candidates-attributed.jsonl`

You do not need to rebuild corpus artifacts on the Pi just to run the clock.
Only rerun the corpus pipeline when you are intentionally changing source data or quote selection behavior.

```bash
# optional maintenance-only rebuild path
python3 clean_display_quotes.py output/candidates-merged.jsonl --output output/candidates-cleaned.jsonl
python3 quality_filter.py output/candidates-cleaned.jsonl --output output/candidates-quality.jsonl
python3 fix_substring_time_matches.py output/candidates-quality.jsonl --output output/candidates-quality.jsonl
python3 enrich_metadata.py output/candidates-quality.jsonl --output assets/candidates-attributed.jsonl
```

If the one-shot render and one-shot display both work, you can move on to making it a boot-time service.

### Optional: Run LitClock as an appliance at boot

A sample systemd unit is included at:

- `litclock.service.example`

Typical install on the Pi:

```bash
cd ~/LitClock
sudo cp litclock.service.example /etc/systemd/system/litclock.service
sudo systemctl daemon-reload
sudo systemctl enable litclock.service
sudo systemctl start litclock.service
sudo systemctl status litclock.service
```

Notes:
- the sample runs `run_clock.py` in `--mode production`
- edit `User=`, `WorkingDirectory=`, and `ExecStart=` if your Pi paths differ
- if `inky-photo-frame.service` is still enabled, stop/disable it first so LitClock can own the display
- install the `gpiozero` package into the same virtualenv if you want Inky button support (short press + 2s long press); otherwise add `--buttons-off` to `ExecStart=`

### Optional: allow button D long-press shutdown

The default `--shutdown-command` is `sudo -n shutdown -h now`, so a 2-second hold of button D can power the appliance down cleanly. That requires passwordless sudo for shutdown. A minimal sudoers drop-in:

```bash
sudo tee /etc/sudoers.d/litclock-shutdown <<'EOF'
pi ALL=(root) NOPASSWD: /sbin/shutdown
EOF
sudo chmod 440 /etc/sudoers.d/litclock-shutdown
```

If you prefer not to grant that, set `--shutdown-command ""` in the service `ExecStart=` to turn the hold-to-shutdown off.

### Optional: health checks + telemetry

The loop writes a JSONL telemetry sidecar — one line per successful render, one per loop-level error — rotated by date. The `--telemetry-path` argument is a base path (default `~/.litclock/telemetry.jsonl`), and `run_clock.py` actually appends to a `telemetry-YYYYMMDD.jsonl` sibling so file size stays bounded on a long-running appliance. `litclock_health.py` summarises the last N hours and auto-discovers the rotated siblings.

```bash
# Human-readable summary
python3 litclock_health.py --hours 24

# Machine-readable; exit 2 when no renders landed in the window
python3 litclock_health.py --hours 1 --json --fail-if-no-renders
```

Wire the JSON form into a once-a-day cron / systemd timer if you want passive alerting without SSH journalctl spelunking.

### Optional: verify which GPIO pin each button actually fires

If button handling seems wrong on a particular Inky variant, run the standalone probe to confirm the wiring before blaming handler code:

```bash
python3 probe_buttons.py
# press each physical button on the panel;
# each press prints a timestamped line showing which GPIO pin fired
```

Defaults cover the standard Inky Impression pins (5/6/16/24) plus a few common alternates (13/17/26). Override with `--pins` to probe arbitrary GPIOs, and `--pull-down` / `--bounce` for non-standard wiring.

## Path B: Fresh Inky setup

Follow the rest of this document if you are starting from a fresh Pi or have not yet installed the Pimoroni Inky software.

## Hardware

- Raspberry Pi Zero 2 W (headered)
- Pimoroni Inky Impression 7.3 Spectra 6
- microSD card
- appropriate power supply
- Wi-Fi access

## OS baseline

- Raspberry Pi OS **Bookworm or later**
- SSH enabled
- Wi-Fi configured

## One-time Pi prep

Update the system first:

```bash
sudo apt update && sudo apt upgrade -y
sudo reboot
```

## Inky software install

Pimoroni recommends installing via their `inky` repo:

```bash
git clone https://github.com/pimoroni/inky
cd inky
./install.sh
```

Suggested answers during install:
- yes to virtualenv setup
- yes to copying examples
- yes to example dependencies
- docs optional

Then reboot:

```bash
sudo reboot
```

## Verify Inky works

Activate Pimoroni virtualenv:

```bash
source ~/.virtualenvs/pimoroni/bin/activate
```

Run a known-good Spectra example:

```bash
cd ~/Pimoroni/inky/examples/spectra6
python stripes.py
```

If that fails:
- check board seating
- enable `I2C` and `SPI` in `sudo raspi-config`
- reboot and retry

If LitClock later errors on missing fonts, install these as a fallback:

```bash
sudo apt install -y fonts-noto-core fonts-dejavu-core
```

## Literary clock setup

Clone the project:

```bash
git clone git@github.com:gkoch02/LitClock.git
cd LitClock
```

Render once to file:

```bash
python3 run_clock.py --once
```

Push the current render to Inky:

```bash
python3 display_inky.py output/current.png
```

Run full loop with hardware handoff:

```bash
python3 run_clock.py --display-script display_inky.py
```

## Suggested service shape

The loop is good enough to run under `systemd` once the manual path works.

Recommended progression:
1. manual render test
2. manual Inky display test
3. manual combined loop
4. `systemd` service

## Notes

- The renderer currently targets a generic canvas and resizes to panel dimensions in `display_inky.py`.
- That is fine for first bring-up.
- Once the panel is in hand, tune renderer dimensions to the panel's native resolution and visual character.
