# Pi Setup Guide: Zero 2 W + Inky Impression 7.3 Spectra 6

This is the practical path for turning the literary clock prototype into a personal appliance.

## Choose your path

### Path A: Inky is already installed and working

If your Pi already has the Pimoroni Inky stack working in a virtualenv, this is the shortest path:

```bash
source ~/.virtualenvs/pimoroni/bin/activate
git clone git@github.com:gkoch02/idle-hours.git ~/IdleHours
cd ~/IdleHours
pip install -e '.[pi]'

# Smoke-test the render pipeline with argparse defaults — no config yet.
idle-hours run --once --buttons-off
idle-hours display output/current.png

# Stage a config (the appliance preset), then run the loop through it.
# This matches what the systemd unit will do later.
sudo install -d -o "$USER" -g "$USER" -m 0750 /var/lib/idle-hours
sudo install -o "$USER" -g "$USER" -m 0640 \
    idle_hours/assets/config.toml.example /var/lib/idle-hours/config.toml
idle-hours run --config /var/lib/idle-hours/config.toml
```

This works from the prebuilt runtime assets already committed in the repo:
- `idle_hours/assets/quote_database.jsonl` — the baked display-ready DB the clock reads by default
- `idle_hours/assets/candidates-attributed.jsonl` — the raw attributed corpus that feeds the baker (also consumed by the curator UI)

You do not need to rebuild corpus artifacts on the Pi just to run the clock.
Only rerun the corpus pipeline when you are intentionally changing source data or quote selection behavior — and remember to re-bake at the end so the new rows actually reach the runtime picker.

For an end-to-end "harvest a curated set of Gutenberg IDs and merge into the live corpus" flow, prefer the bundled driver script:

```bash
bash run_dawn_expansion.sh
```

It runs the full pipeline (mine → merge → clean → quality → fix-substring → enrich → bake) against `gutenberg_dawn_expansion_ids.txt`, regenerates the coverage snapshot, and re-bakes `idle_hours/assets/quote_database.jsonl`. Safe to re-run; downloads are cached and `merge_candidates` dedupes.

If you want to drive individual stages manually — e.g. iterating on a single transform — the order the driver script uses is:

```bash
# starting from a merged candidates file:
idle-hours clean output/candidates-merged.jsonl --output output/candidates-cleaned.jsonl
idle-hours quality output/candidates-cleaned.jsonl --output output/candidates-quality.jsonl
idle-hours fix-substring-times output/candidates-quality.jsonl   # in-place compatibility pass
idle-hours enrich output/candidates-quality.jsonl --output idle_hours/assets/candidates-attributed.jsonl
idle-hours apply-overrides idle_hours/assets/candidates-attributed.jsonl
idle-hours bake idle_hours/assets/candidates-attributed.jsonl --output idle_hours/assets/quote_database.jsonl
```

(Every subcommand is also reachable as `python3 -m idle_hours.<module>`;
there are no flat `*.py` scripts at the repo root.)

`fix_substring_time_matches.py` runs as a defensive compatibility pass: it's a no-op on fresh harvests (the current miner already collapses the substring-collision case) but rewrites time metadata in older JSONL rows that captured `"five minutes past two"` as a substring of `"thirty-five minutes past two"`. Keeping it in the manual flow above matches `run_dawn_expansion.sh` line-for-line, so a manually-driven rebuild produces the same corpus the driver script would. `fix_legacy_buckets.py` is the companion repair for pre-`buckets.py` 8-state bucket names; the dawn driver does not run it because that drift was eradicated before the dawn corpus existed, but include it after `quality_filter` if you're rebuilding from a JSONL old enough to contain those names.

If the one-shot render and one-shot display both work, you can move on to making it a boot-time service.

### Optional: Run Idle Hours as an appliance at boot

A sample systemd unit is included at:

- `ops/idle-hours.service.example`

Typical install on the Pi:

```bash
cd ~/IdleHours
sudo cp ops/idle-hours.service.example /etc/systemd/system/idle-hours.service

# The sample unit passes `--config %S/idle-hours/config.toml` exclusively
# and a missing --config path is a hard error by design — so stage the
# config before the first start. StateDirectory=idle-hours normally creates
# /var/lib/idle-hours on service start, but we need it sooner; `install -d`
# mirrors the ownership / mode systemd would've applied.
sudo install -d -o pi -g pi -m 0750 /var/lib/idle-hours
sudo install -o pi -g pi -m 0640 \
    idle_hours/assets/config.toml.example /var/lib/idle-hours/config.toml
sudoedit /var/lib/idle-hours/config.toml            # tune keys for this appliance

sudo systemctl daemon-reload
sudo systemctl enable --now idle-hours.service
sudo systemctl status idle-hours.service
```

Notes:
- the unit file itself only passes `--config %S/idle-hours/config.toml`. All tunable knobs — theme, mode, quiet hours, web UI, startup image, shutdown command, button opt-out — live in `/var/lib/idle-hours/config.toml`. Day-to-day changes are `sudoedit` + `systemctl restart`; `daemon-reload` is only needed when the unit file itself changes
- every key in the config maps 1:1 to an argparse `dest` on `run_clock.py` (snake_case — `display_script`, `quiet_start`, `web_bind`, etc.). `idle_hours/assets/config.toml.example` ships every supported key with inline documentation
- CLI flags still work and override config values — useful for ad-hoc troubleshooting (`systemctl stop` then `idle-hours run --once --mode debug ...`)
- edit `User=` and `ExecStart=` in the unit only if your Pi paths differ; keep
  `WorkingDirectory` and `LG_WD` on `/var/lib/idle-hours` so sandboxed `lgpio`
  can create and open its notification FIFO
- if `inky-photo-frame.service` is still enabled, stop/disable it first so Idle Hours can own the display
- for Inky button support, install Raspberry Pi OS's `python3-lgpio` and
  `python3-rpi-lgpio`, and create the virtualenv with `--system-site-packages`;
  `gpiozero` alone does not provide a pin backend
- the unit uses `Type=notify` + `WatchdogSec=180s` so systemd restarts a wedged-but-breathing loop, not just a fully-dead one. The `sd_notify` client in `sd_notify.py` is pure stdlib (no `systemd-python` dep); off systemd it is a no-op so `idle-hours run` on a dev host behaves identically.
- the unit declares `StateDirectory=idle-hours`. systemd creates `/var/lib/idle-hours/` owned by `pi` before the service starts, and the sample config's `state_path` / `history_path` / `telemetry_path` / `pidfile` / `web_token_file` all point into that directory.

After `sudo systemctl status idle-hours.service` reports `Active: active (running); notify`, confirm the supervisor is actually supervising:

```bash
# Should show a non-zero WatchdogTimestamp + pong within a few minutes
systemctl show idle-hours.service --property=WatchdogTimestamp,NotifyAccess
# Security posture — should score meaningfully better than the default unit
systemd-analyze security idle-hours.service
# Simulate a wedge (foreground console only):
sudo kill -STOP "$(systemctl show -p MainPID --value idle-hours.service)"
# After WatchdogSec expires, systemd kills + restarts the service.
```

### Migrating from `~/.idle-hours/` to `/var/lib/idle-hours`

Pre-phase-3 installs wrote state, history, telemetry, the pidfile, and the web token under `~/.idle-hours/`. The new unit uses `/var/lib/idle-hours/` so the sandbox can keep `$HOME` read-only. To preserve existing data across the switch:

```bash
# Stop the old service
sudo systemctl stop idle-hours.service

# Move or symlink the existing files. A move is simplest when there's no
# pre-phase-3 install to roll back to:
sudo mkdir -p /var/lib/idle-hours
sudo mv ~/.idle-hours/state.json       /var/lib/idle-hours/ 2>/dev/null || true
sudo mv ~/.idle-hours/history.jsonl    /var/lib/idle-hours/ 2>/dev/null || true
sudo mv ~/.idle-hours/telemetry-*.jsonl /var/lib/idle-hours/ 2>/dev/null || true
sudo mv ~/.idle-hours/web.token        /var/lib/idle-hours/ 2>/dev/null || true
sudo chown -R pi:pi /var/lib/idle-hours
sudo chmod 750 /var/lib/idle-hours

# Or: symlink ~/.idle-hours → /var/lib/idle-hours during a transition window so any
# stray tooling that still hardcodes the home path keeps working. Drop the
# symlink once all call sites have been audited.
# ln -s /var/lib/idle-hours ~/.idle-hours

sudo systemctl daemon-reload
sudo systemctl start idle-hours.service
```

`idle-hours health` takes `--telemetry-path` (or `--config`, which reads it from the same TOML the unit uses), so ad-hoc health queries after the migration are just:

```bash
idle-hours health --config /var/lib/idle-hours/config.toml --hours 24
# or, restating the path:
idle-hours health --telemetry-path /var/lib/idle-hours/telemetry.jsonl --hours 24
```

### Optional: allow button D long-press shutdown

A 2-second hold of button D runs `shutdown_command` and powers the appliance down cleanly. Pick one of:

1. **Recommended under the sandbox:** set `shutdown_command = "systemctl poweroff"` in `/var/lib/idle-hours/config.toml`. polkit on Raspberry Pi OS already allows the active console user to poweroff without a password, and `systemctl` is not setuid so the sample unit's `NoNewPrivileges=yes` leaves it alone. No sudoers drop-in required.
2. **Legacy / no sandbox:** keep the built-in default `sudo -n shutdown -h now`, which requires both a passwordless-sudo drop-in *and* removing `NoNewPrivileges=yes` from the unit (the sandbox blocks setuid binaries like `sudo`). The other sandbox protections still apply.

   ```bash
   sudo tee /etc/sudoers.d/idle-hours-shutdown <<'EOF'
   pi ALL=(root) NOPASSWD: /sbin/shutdown
   EOF
   sudo chmod 440 /etc/sudoers.d/idle-hours-shutdown
   ```

3. **Off entirely:** set `shutdown_command = ""` in the config to disable hold-to-shutdown.

### Optional: health checks + telemetry

The loop writes a JSONL telemetry sidecar — one line per successful render, one per loop-level error — rotated by date. The `--telemetry-path` argument is a base path (default `~/.idle-hours/telemetry.jsonl`), and `run_clock.py` actually appends to a `telemetry-YYYYMMDD.jsonl` sibling so file size stays bounded on a long-running appliance. `idle_hours_health.py` summarises the last N hours and auto-discovers the rotated siblings.

```bash
# Human-readable summary
idle-hours health --hours 24

# Machine-readable; exit 2 when no renders landed in the window
idle-hours health --hours 1 --json --fail-if-no-renders
```

Wire the JSON form into a once-a-day cron / systemd timer if you want passive alerting without SSH journalctl spelunking.

### Optional: curator web UI

`run_clock.py` ships a small in-process HTTP surface for browsing telemetry / bucket coverage / the current frame and mirroring the four physical buttons from a phone or laptop. It is **off by default** and starts only when `--web-bind HOST:PORT` is passed.

```bash
# Loopback-only, no auth. Safe for SSH port-forward from your laptop.
idle-hours run --display-script display_inky.py --web-bind 127.0.0.1:8080
# then on the laptop: ssh -L 8080:127.0.0.1:8080 pi@idle-hours
# and open http://127.0.0.1:8080

# LAN-exposed. POSTs (skip / theme / quiet / re-render / overrides save) require
# a token; put it in a file so it doesn't show up in `ps` / journald.
mkdir -p ~/.idle-hours
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > ~/.idle-hours/web.token
chmod 640 ~/.idle-hours/web.token
idle-hours run \
  --display-script display_inky.py \
  --web-bind 0.0.0.0:8080 \
  --web-token-file ~/.idle-hours/web.token
```

To enable the UI under systemd, uncomment `web_bind` / `web_token_file` in `/var/lib/idle-hours/config.toml` (the shipped `idle_hours/assets/config.toml.example` has commented-out lines for both the loopback and LAN-exposed shapes) and `sudo systemctl restart idle-hours.service`. The UI shares `render_lock` with the button handlers, so a tap on the physical panel and a click in the browser will never render-race — the second one returns `409 busy` instead of queueing. A configured token gates every POST **and** every JSON GET (`/api/history`, `/api/search`, `/api/bucket/*`, the override endpoints, ...). Only the static shell (`/`, `/main.js`, `/style.css`) stays open, because a browser loads it by tag and a tag cannot attach a request header — plus `/metrics`, which stays open for scrapers unless you set `web_metrics_token = true`. Note a *loopback* bind is strict about the `Host` header (the DNS-rebinding guard), so reaching the UI at an mDNS name or through a reverse proxy needs that name in `web_allowed_hosts`.

See the "Curator web UI" section in `README.md` for the full endpoint list, UI panel descriptions, and security model.

### Optional: verify which GPIO pin each button actually fires

If button handling seems wrong on a particular Inky variant, run the standalone probe to confirm the wiring before blaming handler code:

```bash
idle-hours probe-buttons
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

Idle Hours' bootstrap installs Pimoroni's `inky` package plus Raspberry Pi
OS's supported GPIO backend. The hardware configuration has one important
Spectra 6 wrinkle: the E673 driver opens `/dev/spidev0.0` for data but drives
GPIO8 chip-select itself. Ordinary SPI claims GPIO8 in the kernel. Configure
SPI with no kernel-managed chip selects:

```bash
sudo apt install -y gpiod python3-lgpio python3-rpi-lgpio
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0
grep -qx 'dtoverlay=spi0-0cs' /boot/firmware/config.txt || \
  echo 'dtoverlay=spi0-0cs' | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

After reboot, `/dev/spidev0.0` must exist and `gpioinfo` must not show GPIO8
claimed by `spi0 CS0`.

## Verify Inky works

Create a virtualenv that can see the OS GPIO bindings and verify the backend:

```bash
python3 -m venv --system-site-packages ~/.virtualenvs/pimoroni
source ~/.virtualenvs/pimoroni/bin/activate
python -c 'import lgpio, RPi.GPIO; print("GPIO backend: ok")'
```

If that fails:
- check board seating
- confirm `/dev/spidev0.0` exists
- confirm GPIO8 is not claimed by `spi0 CS0`
- confirm `dtparam=spi=on` and `dtoverlay=spi0-0cs` are in the boot config
- reboot and retry

If Idle Hours later errors on missing fonts, install these as a fallback:

```bash
sudo apt install -y fonts-noto-core fonts-dejavu-core
```

## Literary clock setup

Clone the project:

```bash
git clone git@github.com:gkoch02/idle-hours.git ~/IdleHours
cd ~/IdleHours
pip install -e '.[pi]'
```

Render once and push to the panel:

```bash
idle-hours run --once --buttons-off
idle-hours display output/current.png
```

Run full loop with hardware handoff:

```bash
idle-hours run --display-script display_inky.py
```

## Suggested service shape

The loop is good enough to run under `systemd` once the manual path works.

Recommended progression:
1. manual render test
2. manual Inky display test
3. manual combined loop
4. `systemd` service — see [Optional: Run Idle Hours as an appliance at boot](#optional-run-idle-hours-as-an-appliance-at-boot) above for the config-file + unit-file install steps

## Notes

- The renderer currently targets a generic canvas and resizes to panel dimensions in `display_inky.py`.
- That is fine for first bring-up.
- Once the panel is in hand, tune renderer dimensions to the panel's native resolution and visual character.
