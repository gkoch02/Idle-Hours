# Upgrading from LitClock 2.x → Idle Hours

This release renames the product from **LitClock** to **Idle Hours**. The
rename is hard — every surface (package name, CLI command, filesystem paths,
HTTP token header, Prometheus metric names, systemd unit, brand strings)
moves at the same time, with no backward-compat aliases. Existing
appliances need a one-time manual migration.

If you've never installed LitClock, skip this document and read `README.md`
instead.

## What changed and why

`LitClock` was a developer-flavoured concatenation. `Idle Hours` names the
*use case* — a literary clock you glance at during contemplative reading —
rather than the implementation. The change pulls every surface to one
consistent name so a single string identifies the product everywhere it
appears: in CLI help, in `~/.idle-hours/state.json`, in Prometheus
dashboards, in the rendered astrarium brand banner, in the systemd journal.

A hard rename (no compatibility shims) is the cleanest endgame; the
trade-off is a one-time migration cost for each running appliance.

## Surfaces affected

| Surface | Before | After |
|---|---|---|
| PyPI distribution + CLI command | `litclock` | `idle-hours` |
| Python module names | `litclock_cli`, `litclock_health` | `idle_hours_cli`, `idle_hours_health` |
| Filesystem state dir (dev) | `~/.litclock/` | `~/.idle-hours/` |
| Filesystem state dir (appliance) | `/var/lib/litclock/` | `/var/lib/idle-hours/` |
| HTTP token header | `X-LitClock-Token` | `X-Idle-Hours-Token` |
| Prometheus metric prefix | `litclock_*` | `idle_hours_*` |
| systemd unit + `StateDirectory` | `litclock.service` / `StateDirectory=litclock` | `idle-hours.service` / `StateDirectory=idle-hours` |
| Linux user/group (Docker) | `litclock` | `idlehours` |
| Docker image tag | `litclock:2.0` | `idle-hours:2.0` |
| Docker volume name | `litclock-state` | `idle-hours-state` |
| Astrarium brand banner | `LITCLOCK // ASTRARIUM` | `IDLE HOURS // ASTRARIUM` |
| Diags overlay header | `LITCLOCK · DIAGS` | `IDLE HOURS · DIAGS` |
| Curator UI title | `LitClock Curator` | `Idle Hours Curator` |

## Migrating an appliance (systemd + bare-metal)

The steps below assume the legacy install ran from `~/LitClock` under the
`pi` user and used `~/.litclock/` for state (the documented dev path) or
`/var/lib/litclock/` (the sandboxed systemd path). Adjust paths for your
deployment.

```bash
# 1. Stop and disable the old service.
sudo systemctl stop litclock.service
sudo systemctl disable litclock.service

# 2. Pull the renamed code. Either rename the working tree or re-clone.
#    The CI badge and clone URLs in the docs now reference gkoch02/idle-hours;
#    GitHub redirects the old slug for ~12 months, so either form resolves.
cd ~
git -C LitClock pull
mv LitClock IdleHours        # cosmetic; BASE_DIR resolves relative to the file

# 3. Uninstall the old wheel (if installed globally) and re-install fresh.
#    pip will NOT replace `litclock` with `idle-hours` automatically — the
#    package name is different.
pip uninstall litclock
cd ~/IdleHours
pip install -e .

# 4a. Dev-style state under $HOME — move it once.
mv ~/.litclock ~/.idle-hours

# 4b. Sandboxed systemd state under /var/lib — same idea.
sudo mv /var/lib/litclock /var/lib/idle-hours
sudo chown -R pi:pi /var/lib/idle-hours

# 5. Install the new systemd unit. Edit paths inside it to match your
#    layout BEFORE enabling, then daemon-reload.
sudo cp idle-hours.service.example /etc/systemd/system/idle-hours.service
sudoedit /etc/systemd/system/idle-hours.service
sudo systemctl daemon-reload
sudo systemctl enable --now idle-hours.service

# 6. Confirm health.
idle-hours health --hours 1
systemctl status --no-pager idle-hours.service
# And in a browser:
#   http://<pi>:8080/                — title should read "Idle Hours Curator"
#   http://<pi>:8080/metrics         — series should be idle_hours_renders_total
```

## Migrating a Docker deployment

```bash
# 1. Stop the old container.
docker stop litclock
docker rm litclock

# 2. Build the renamed image. Multi-arch buildx is documented in README.md.
docker buildx build -t idle-hours:2.0 .

# 3. (Optional) rename the state volume. Docker doesn't care about volume
#    names, but the consistency is nicer for `docker volume ls`. Skip if you
#    don't mind keeping the old name.
docker volume create idle-hours-state
docker run --rm \
  -v litclock-state:/old \
  -v idle-hours-state:/new \
  alpine cp -a /old/. /new/
docker volume rm litclock-state

# 4. Bring up the renamed container.
docker run --rm -p 8080:8080 -v idle-hours-state:/state idle-hours:2.0 \
  idle-hours run --buttons-off --skip-preflight \
                 --web-bind 0.0.0.0:8080 \
                 --state-path /state/state.json \
                 --history-path /state/history.jsonl \
                 --telemetry-path /state/telemetry.jsonl \
                 --pidfile /state/run_clock.pid
```

## External integrations

- **Prometheus scrape rules / Grafana dashboards.** Every metric series
  renamed: `s/litclock_/idle_hours_/`. Notable: `litclock_renders_total` →
  `idle_hours_renders_total`, `litclock_last_heartbeat_age_seconds` →
  `idle_hours_last_heartbeat_age_seconds`. Alerting expressions and panel
  queries need the same find-and-replace. The metric *meaning* and labels
  are unchanged — values stay continuous through the cutover (modulo the
  brief gap while the appliance is down for migration).

- **Webhook receivers (`runtime_webhook.py`).** The JSON payload schema is
  unchanged. Only the `User-Agent` header (`LitClock/2.0` → `IdleHours/2.0`)
  and any source-name field in your receiver's own bookkeeping differ.

- **Private HTTP clients hitting the curator UI.** Anything that POSTs to
  `/api/action/*`, `/api/overrides`, `/api/content-overrides`, `/api/bake`,
  or `/api/setup` with a token must send the header
  `X-Idle-Hours-Token: <secret>` instead of `X-LitClock-Token: <secret>`.
  Update `curl` snippets accordingly:

  ```bash
  # Before:
  curl -X POST -H "X-LitClock-Token: $(cat ~/.litclock/web.token)" \
       http://<pi>:8080/api/action/rerender
  # After:
  curl -X POST -H "X-Idle-Hours-Token: $(cat ~/.idle-hours/web.token)" \
       http://<pi>:8080/api/action/rerender
  ```

## Rollback

The rename has no backward-compat shims, so rollback is "check out the
previous tag and reverse the state-dir move":

```bash
sudo systemctl stop idle-hours.service
sudo mv /var/lib/idle-hours /var/lib/litclock         # or ~/.idle-hours → ~/.litclock
cd ~/IdleHours && git checkout <pre-rename-commit>
mv ~/IdleHours ~/LitClock
sudo cp ~/LitClock/litclock.service.example /etc/systemd/system/litclock.service
sudo systemctl daemon-reload
sudo systemctl enable --now litclock.service
```

## Troubleshooting

- **"appliance starts but the panel never updates."** Most likely the state
  directory wasn't migrated, so the picker has no history and the dedup
  check in the main loop thinks the bucket hasn't changed. Confirm
  `~/.idle-hours/` (or `/var/lib/idle-hours/`) exists, is writable by the
  service user, and contains `state.json` / `history.jsonl` /
  `telemetry-YYYYMMDD.jsonl` after the first tick.

- **"Prometheus dashboard panels show 'No data'."** The metric names
  changed. Run a `s/litclock_/idle_hours_/` across your dashboard JSON
  and alerting rules. The shipped `/metrics` endpoint emits only the new
  names — there's no dual-emit.

- **"`pip install -e .` fails saying `litclock` is already installed."**
  The wheel changed name, so pip can't simply replace it. Uninstall first:

  ```bash
  pip uninstall litclock
  pip install -e .
  ```

- **"`idle-hours --help` says 'command not found'."** The new wheel
  registers `idle-hours`, not `litclock`. Confirm with `pip show
  idle-hours` and `which idle-hours`. If `which idle-hours` returns a path
  but invoking it errors, you probably have a venv mix-up — re-activate
  the env you ran `pip install -e .` in.

- **"my `curl` script gets 401 from the curator UI."** The token header
  renamed. Send `X-Idle-Hours-Token` instead of `X-LitClock-Token`.

- **"the systemd unit refuses to start with `Failed to set up unit
  invocation: No such file or directory`."** Likely `StateDirectory=` and
  the `ExecStart=` paths are still mismatched between old (`litclock`)
  and new (`idle-hours`) forms. Re-check the unit file against
  `idle-hours.service.example`.
