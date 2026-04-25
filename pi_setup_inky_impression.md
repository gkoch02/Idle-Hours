# Pi Setup Guide: Zero 2 W + Inky Impression 7.3 Spectra 6

This is the practical path for turning the literary clock prototype into a personal appliance.

## Choose your path

### Path A: Inky is already installed and working

If your Pi already has the Pimoroni Inky stack working in a virtualenv, this is the shortest path:

```bash
source ~/.virtualenvs/pimoroni/bin/activate
git clone git@github.com:gkoch02/LitClock.git
cd LitClock

# Smoke-test the render pipeline with argparse defaults — no config yet.
python3 run_clock.py --once
python3 display_inky.py output/current.png

# Stage a config (the appliance preset), then run the loop through it.
# This matches what the systemd unit will do later.
sudo install -d -o "$USER" -g "$USER" -m 0750 /var/lib/litclock
sudo install -o "$USER" -g "$USER" -m 0640 \
    assets/config.toml.example /var/lib/litclock/config.toml
python3 run_clock.py --config /var/lib/litclock/config.toml
```

This works from the prebuilt runtime assets already committed in the repo:
- `assets/quote_database.jsonl` — the baked display-ready DB the clock reads by default
- `assets/candidates-attributed.jsonl` — the raw attributed corpus that feeds the baker (also consumed by the curator UI)

You do not need to rebuild corpus artifacts on the Pi just to run the clock.
Only rerun the corpus pipeline when you are intentionally changing source data or quote selection behavior — and remember to re-bake at the end so the new rows actually reach the runtime picker.

For an end-to-end "harvest a curated set of Gutenberg IDs and merge into the live corpus" flow, prefer the bundled driver script:

```bash
bash run_dawn_expansion.sh
```

It runs the full pipeline (mine → merge → clean → quality → fix-substring → enrich → bake) against `gutenberg_dawn_expansion_ids.txt`, regenerates the coverage snapshot, and re-bakes `assets/quote_database.jsonl`. Safe to re-run; downloads are cached and `merge_candidates` dedupes.

If you want to drive individual stages manually — e.g. iterating on a single transform — the order the driver script uses is:

```bash
# starting from a merged candidates file:
python3 clean_display_quotes.py output/candidates-merged.jsonl --output output/candidates-cleaned.jsonl
python3 quality_filter.py output/candidates-cleaned.jsonl --output output/candidates-quality.jsonl
python3 fix_substring_time_matches.py output/candidates-quality.jsonl   # in-place compatibility pass
python3 enrich_metadata.py output/candidates-quality.jsonl --output assets/candidates-attributed.jsonl
python3 apply_content_overrides.py assets/candidates-attributed.jsonl
python3 bake_quote_database.py assets/candidates-attributed.jsonl --output assets/quote_database.jsonl
```

`fix_substring_time_matches.py` runs as a defensive compatibility pass: it's a no-op on fresh harvests (the current miner already collapses the substring-collision case) but rewrites time metadata in older JSONL rows that captured `"five minutes past two"` as a substring of `"thirty-five minutes past two"`. Keeping it in the manual flow above matches `run_dawn_expansion.sh` line-for-line, so a manually-driven rebuild produces the same corpus the driver script would. `fix_legacy_buckets.py` is the companion repair for pre-`buckets.py` 8-state bucket names; the dawn driver does not run it because that drift was eradicated before the dawn corpus existed, but include it after `quality_filter` if you're rebuilding from a JSONL old enough to contain those names.

If the one-shot render and one-shot display both work, you can move on to making it a boot-time service.

### Optional: Run LitClock as an appliance at boot

A sample systemd unit is included at:

- `litclock.service.example`

Typical install on the Pi:

```bash
cd ~/LitClock
sudo cp litclock.service.example /etc/systemd/system/litclock.service

# The sample unit passes `--config %S/litclock/config.toml` exclusively
# and a missing --config path is a hard error by design — so stage the
# config before the first start. StateDirectory=litclock normally creates
# /var/lib/litclock on service start, but we need it sooner; `install -d`
# mirrors the ownership / mode systemd would've applied.
sudo install -d -o pi -g pi -m 0750 /var/lib/litclock
sudo install -o pi -g pi -m 0640 \
    assets/config.toml.example /var/lib/litclock/config.toml
sudoedit /var/lib/litclock/config.toml            # tune keys for this appliance

sudo systemctl daemon-reload
sudo systemctl enable --now litclock.service
sudo systemctl status litclock.service
```

Notes:
- the unit file itself only passes `--config %S/litclock/config.toml`. All tunable knobs — theme, mode, quiet hours, web UI, startup image, shutdown command, button opt-out — live in `/var/lib/litclock/config.toml`. Day-to-day changes are `sudoedit` + `systemctl restart`; `daemon-reload` is only needed when the unit file itself changes
- every key in the config maps 1:1 to an argparse `dest` on `run_clock.py` (snake_case — `display_script`, `quiet_start`, `web_bind`, etc.). `assets/config.toml.example` ships every supported key with inline documentation
- CLI flags still work and override config values — useful for ad-hoc troubleshooting (`systemctl stop` then `python3 run_clock.py --once --mode debug ...`)
- edit `User=`, `WorkingDirectory=`, and `ExecStart=` in the unit only if your Pi paths differ
- if `inky-photo-frame.service` is still enabled, stop/disable it first so LitClock can own the display
- install the `gpiozero` package into the same virtualenv if you want Inky button support (short press + 2s long press); otherwise set `buttons_off = true` in the config
- the unit uses `Type=notify` + `WatchdogSec=180s` so systemd restarts a wedged-but-breathing loop, not just a fully-dead one. The `sd_notify` client in `sd_notify.py` is pure stdlib (no `systemd-python` dep); off systemd it is a no-op so `python3 run_clock.py` on a dev host behaves identically.
- the unit declares `StateDirectory=litclock`. systemd creates `/var/lib/litclock/` owned by `pi` before the service starts, and the sample config's `state_path` / `history_path` / `telemetry_path` / `pidfile` / `web_token_file` all point into that directory.

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

A 2-second hold of button D runs `shutdown_command` and powers the appliance down cleanly. Pick one of:

1. **Recommended under the sandbox:** set `shutdown_command = "systemctl poweroff"` in `/var/lib/litclock/config.toml`. polkit on Raspberry Pi OS already allows the active console user to poweroff without a password, and `systemctl` is not setuid so the sample unit's `NoNewPrivileges=yes` leaves it alone. No sudoers drop-in required.
2. **Legacy / no sandbox:** keep the built-in default `sudo -n shutdown -h now`, which requires both a passwordless-sudo drop-in *and* removing `NoNewPrivileges=yes` from the unit (the sandbox blocks setuid binaries like `sudo`). The other sandbox protections still apply.

   ```bash
   sudo tee /etc/sudoers.d/litclock-shutdown <<'EOF'
   pi ALL=(root) NOPASSWD: /sbin/shutdown
   EOF
   sudo chmod 440 /etc/sudoers.d/litclock-shutdown
   ```

3. **Off entirely:** set `shutdown_command = ""` in the config to disable hold-to-shutdown.

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

To enable the UI under systemd, uncomment `web_bind` / `web_token_file` in `/var/lib/litclock/config.toml` (the shipped `assets/config.toml.example` has commented-out lines for both the loopback and LAN-exposed shapes) and `sudo systemctl restart litclock.service`. The UI shares `render_lock` with the button handlers, so a tap on the physical panel and a click in the browser will never render-race — the second one returns `409 busy` instead of queueing. GETs (the `current.png` preview, telemetry, coverage) stay open on all binds; only POSTs are token-gated.

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
4. `systemd` service — see [Optional: Run LitClock as an appliance at boot](#optional-run-litclock-as-an-appliance-at-boot) above for the config-file + unit-file install steps

## Notes

- The renderer currently targets a generic canvas and resizes to panel dimensions in `display_inky.py`.
- That is fine for first bring-up.
- Once the panel is in hand, tune renderer dimensions to the panel's native resolution and visual character.
