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

This works from the prebuilt runtime assets already committed in the repo:
- `assets/quote_database.jsonl` — the baked display-ready DB the clock reads by default
- `assets/candidates-attributed.jsonl` — the raw attributed corpus that feeds the baker (also consumed by the curator UI)

You do not need to rebuild corpus artifacts on the Pi just to run the clock.
Only rerun the corpus pipeline when you are intentionally changing source data or quote selection behavior — and remember to re-bake at the end so the new rows actually reach the runtime picker.

```bash
# optional maintenance-only rebuild path
python3 clean_display_quotes.py output/candidates-merged.jsonl --output output/candidates-cleaned.jsonl
python3 quality_filter.py output/candidates-cleaned.jsonl --output output/candidates-quality.jsonl
python3 fix_substring_time_matches.py output/candidates-quality.jsonl --output output/candidates-quality.jsonl
python3 enrich_metadata.py output/candidates-quality.jsonl --output assets/candidates-attributed.jsonl
python3 apply_content_overrides.py assets/candidates-attributed.jsonl
python3 bake_quote_database.py assets/candidates-attributed.jsonl --output assets/quote_database.jsonl
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
- the unit uses `Type=notify` + `WatchdogSec=180s` so systemd restarts a wedged-but-breathing loop, not just a fully-dead one. The `sd_notify` client in `sd_notify.py` is pure stdlib (no `systemd-python` dep); off systemd it is a no-op so `python3 run_clock.py` on a dev host behaves identically.
- the unit declares `StateDirectory=litclock`. systemd creates `/var/lib/litclock/` owned by `pi` before the service starts, and the sample's `--state-path` / `--history-path` / `--telemetry-path` / `--pidfile` / `--web-token-file` all point into that directory via `%S/litclock/...`.

After `sudo systemctl status litclock.service` reports `Active: active (running); notify`, confirm the supervisor is actually supervising:

```bash
# Should show a non-zero WatchdogTimestamp + pong within a few minutes
systemctl show litclock.service --property=WatchdogTimestamp,NotifyAccess
# Security posture — should score meaningfully better than the default unit
systemd-analyze security litclock.service
# Simulate a wedge (foreground console only):
sudo kill -STOP "$(systemctl show -p MainPID --value litclock.service)"
# After WatchdogSec expires, systemd kills + restarts the service.
```

### Migrating from `~/.litclock/` to `/var/lib/litclock`

Pre-phase-3 installs wrote state, history, telemetry, the pidfile, and the web token under `~/.litclock/`. The new unit uses `/var/lib/litclock/` so the sandbox can keep `$HOME` read-only. To preserve existing data across the switch:

```bash
# Stop the old service
sudo systemctl stop litclock.service

# Move or symlink the existing files. A move is simplest when there's no
# pre-phase-3 install to roll back to:
sudo mkdir -p /var/lib/litclock
sudo mv ~/.litclock/state.json       /var/lib/litclock/ 2>/dev/null || true
sudo mv ~/.litclock/history.jsonl    /var/lib/litclock/ 2>/dev/null || true
sudo mv ~/.litclock/telemetry-*.jsonl /var/lib/litclock/ 2>/dev/null || true
sudo mv ~/.litclock/web.token        /var/lib/litclock/ 2>/dev/null || true
sudo chown -R pi:pi /var/lib/litclock
sudo chmod 750 /var/lib/litclock

# Or: symlink ~/.litclock → /var/lib/litclock during a transition window so any
# stray tooling that still hardcodes the home path keeps working. Drop the
# symlink once all call sites have been audited.
# ln -s /var/lib/litclock ~/.litclock

sudo systemctl daemon-reload
sudo systemctl start litclock.service
```

`litclock_health.py` takes `--telemetry-path`, so ad-hoc health queries after the migration are just:

```bash
python3 litclock_health.py --telemetry-path /var/lib/litclock/telemetry.jsonl --hours 24
```

### Optional: allow button D long-press shutdown

The default `--shutdown-command` is `sudo -n shutdown -h now`, so a 2-second hold of button D can power the appliance down cleanly. That requires passwordless sudo for shutdown. A minimal sudoers drop-in:

```bash
sudo tee /etc/sudoers.d/litclock-shutdown <<'EOF'
pi ALL=(root) NOPASSWD: /sbin/shutdown
EOF
sudo chmod 440 /etc/sudoers.d/litclock-shutdown
```

**Sandbox interaction.** The sample unit sets `NoNewPrivileges=yes`, which blocks setuid binaries — meaning the `sudo -n shutdown` default will be denied once you enable that hardening. Two paths:

1. **Preferred:** change `--shutdown-command` to `systemctl poweroff`. polkit on Raspberry Pi OS already allows the active console user to poweroff without a password, and `systemctl` is not setuid so the sandbox leaves it alone. No sudoers drop-in required.
2. Drop `NoNewPrivileges=yes` from the unit to keep the sudo-based command working. The sandbox's other protections still apply.

If you prefer not to grant shutdown at all, set `--shutdown-command ""` in the service `ExecStart=` to turn hold-to-shutdown off entirely.

### Optional: health checks + telemetry

The loop writes a JSONL telemetry sidecar — one line per successful render, one per loop-level error — rotated by date. The `--telemetry-path` argument is a base path (default `~/.litclock/telemetry.jsonl`), and `run_clock.py` actually appends to a `telemetry-YYYYMMDD.jsonl` sibling so file size stays bounded on a long-running appliance. `litclock_health.py` summarises the last N hours and auto-discovers the rotated siblings.

```bash
# Human-readable summary
python3 litclock_health.py --hours 24

# Machine-readable; exit 2 when no renders landed in the window
python3 litclock_health.py --hours 1 --json --fail-if-no-renders
```

Wire the JSON form into a once-a-day cron / systemd timer if you want passive alerting without SSH journalctl spelunking.

### Optional: curator web UI

`run_clock.py` ships a small in-process HTTP surface for browsing telemetry / bucket coverage / the current frame and mirroring the four physical buttons from a phone or laptop. It is **off by default** and starts only when `--web-bind HOST:PORT` is passed.

```bash
# Loopback-only, no auth. Safe for SSH port-forward from your laptop.
python3 run_clock.py --display-script display_inky.py --web-bind 127.0.0.1:8080
# then on the laptop: ssh -L 8080:127.0.0.1:8080 pi@litclock
# and open http://127.0.0.1:8080

# LAN-exposed. POSTs (skip / theme / quiet / re-render / overrides save) require
# a token; put it in a file so it doesn't show up in `ps` / journald.
mkdir -p ~/.litclock
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > ~/.litclock/web.token
chmod 640 ~/.litclock/web.token
python3 run_clock.py \
  --display-script display_inky.py \
  --web-bind 0.0.0.0:8080 \
  --web-token-file ~/.litclock/web.token
```

To enable the UI under systemd, append the same flags to `ExecStart=` in `litclock.service` (commented examples are included in `litclock.service.example`). The UI shares `render_lock` with the button handlers, so a tap on the physical panel and a click in the browser will never render-race — the second one returns `409 busy` instead of queueing. GETs (the `current.png` preview, telemetry, coverage) stay open on all binds; only POSTs are token-gated.

See the "Curator web UI" section in `README.md` for the full endpoint list, UI panel descriptions, and security model.

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
