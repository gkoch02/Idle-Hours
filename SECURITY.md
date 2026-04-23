# Security Policy

LitClock is a small, single-operator home appliance. It is not a hosted
service, has no accounts or user data, and the canonical deployment is a
Raspberry Pi pushing an eInk frame once per fuzzy-minute bucket. The surface
area below is what exists; anything outside it is not in scope.

## Supported versions

Only the current `main` branch is supported. Security fixes land on `main`;
there are no long-lived release branches.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security reports.**

Use GitHub's private vulnerability reporting to file a report against
`gkoch02/litclock`:

- https://github.com/gkoch02/litclock/security/advisories/new

Include:

- a short description of the issue and its impact,
- the affected file / endpoint / flag,
- reproduction steps or a proof of concept,
- any suggested remediation.

You can expect an acknowledgement within **7 days** and a triage decision
within **30 days**. Because this is a volunteer-maintained hobby project,
fixes may take longer than that; the goal is to be honest about status, not
to commit to an SLA I can't meet.

Coordinated disclosure is appreciated — please give me a reasonable window to
ship a fix before publishing details.

## What's in scope

These are the surfaces where a security bug would matter:

- **Curator web UI (`web_server.py`, `web/`).** Off by default. Loopback binds
  (`127.0.0.1:*`, `localhost:*`, `::1:*`) run without authentication on the
  assumption that the OS-level trust boundary is sufficient; non-loopback
  binds **require** `--web-token` or `--web-token-file`, and `start_web_server`
  refuses to bind `0.0.0.0` without one. Token checks use
  `hmac.compare_digest` against the `X-LitClock-Token` header only. Report
  anything that lets an unauthenticated caller mutate state, read tokens from
  logs, or bypass the bind check.
- **Mutating endpoints (`POST /api/overrides`, `POST /api/action/*`).** These
  rewrite `assets/selection_overrides.json` and trigger renders / theme
  changes / shutdown. Report auth bypass, path traversal, injection, or
  writes outside the intended paths.
- **Button-D long-press shutdown.** Default command is
  `sudo -n shutdown -h now` and requires passwordless sudo. Report anything
  that lets a non-operator trigger shutdown, or any way the
  `--shutdown-command` override could be abused to run arbitrary commands
  from an untrusted input.
- **Runtime file writes** (`state.json`, `history.jsonl`, telemetry sidecar,
  rendered PNGs, ledger/corpus rewrites via `atomic_io`). Report path
  escape, TOCTOU, or corruption that survives the atomic-write primitive.
- **Corpus pipeline (`gutenberg_time_miner.py` → `bake_quote_database.py`).**
  Fetches from `www.gutenberg.org` and reads local text. Report anything
  that lets a malicious text file cause code execution, path traversal, or
  resource exhaustion in a pipeline operator's environment.

## What's out of scope

- Denial-of-service against the render loop by burning CPU on a developer
  machine. The appliance is single-user; there is no rate limit.
- Vulnerabilities in upstream dependencies (Pillow, Pimoroni `inky`,
  `gpiozero`). Please report those to their upstream projects. Mitigations
  we can apply (pinning, sandboxing, workarounds) are in scope.
- Vulnerabilities in Project Gutenberg itself or in cached texts under
  `data/gutenberg/`. Out of scope as a LitClock issue; in scope only if our
  handling of untrusted input is what creates the risk.
- Issues that require physical access to the Pi (GPIO, SD card, serial
  console) — if you can touch the device, you can already reboot it.
- Corpus-content complaints (a quote you dislike, a misattribution).
  Open a normal issue / PR with a `content_overrides.json` patch — see
  `CONTRIBUTING.md`.

## Hardening defaults worth knowing

- The example systemd unit (`litclock.service.example`) runs with
  `NoNewPrivileges=yes`, `ProtectSystem=strict`, `ProtectHome=read-only`,
  `PrivateTmp=yes`, and a scoped `StateDirectory=litclock`. The Button-D
  shutdown default (`sudo -n shutdown`) is **incompatible** with
  `NoNewPrivileges=yes`; swap it for `systemctl poweroff` under the sandbox.
- `--web-token-file` is preferred over `--web-token` in production so the
  secret isn't visible in `ps` output or journald. The file is hot-reloaded
  on `st_mtime` change, so rotating the token is a plain file replace.
- `atomic_io.atomic_write_*` is the single durability primitive for every
  file the next tick reads. If you're adding a new write path, route through
  it — don't reintroduce naive `open("w")`.
