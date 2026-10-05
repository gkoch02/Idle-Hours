# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Idle Hours is an end-to-end literary-clock system: it harvests time-related quotes from Project Gutenberg, scores and cleans them, then picks and renders a quote for any clock time. The render is designed for a Pimoroni Inky Impression 7.3 Spectra 6 eInk panel (800×480, 6-color palette) but writes a plain PNG first, so it runs fine on any machine.

Every stage is a standalone Python 3 CLI script that reads/writes JSONL. The mining/selection pipeline is stdlib-only; `render_quote.py` pulls in Pillow, and `display_inky.py` additionally needs the Pimoroni `inky` package (Pi only).

## Common Commands

### Unified `idle-hours` CLI (v2)

```bash
# After `pip install -e .`, every script in the repo is reachable through
# one umbrella command:
idle-hours --help                          # list every subcommand
idle-hours run --display-script display_inky.py
idle-hours render --time 14:30
idle-hours pick --time 14:30
idle-hours health --hours 24 --json
idle-hours bake
idle-hours contact-sheet --output output/contact-sheet.png

# `idle-hours <sub> --help` forwards to the backing module's argparse so the
# per-subcommand flag list matches `python3 -m idle_hours.<sub> --help` exactly.
# After the v2.x package restructure, every backing module lives under the
# `idle_hours/` package; the `idle-hours` console script is the primary
# entry point and `python3 -m idle_hours.<module>` is the equivalent.
```

### Testing & linting

```bash
# Run the full test suite (CI runs it in parallel with -n auto; single-threaded takes a few minutes)
pytest

# Match CI: parallel + coverage on Python 3.12 (uses sys.monitoring tracer)
COVERAGE_CORE=sysmon pytest -n auto --dist loadscope --cov=idle_hours --cov-report=term-missing

# Run tests with coverage report
pytest --cov

# Run a specific test module
pytest tests/test_pick_quote.py

# Run ruff linter (checks E, W, F, I; line-length 130)
ruff check .

# Fix auto-fixable lint issues (mainly import ordering)
ruff check --fix .
```

### Runtime (render + optional display)

```bash
# Recommended: point run_clock at a TOML config file. Two ship in the repo:
#   assets/config.toml.example  — appliance preset (production, /var/lib paths)
#   assets/config.toml.defaults — every argparse default (copy-and-tweak ref)
# CLI flags below still work and override config values; absent keys fall
# back to argparse defaults. The systemd unit uses this form exclusively.
idle-hours run --config /var/lib/idle-hours/config.toml

# One-shot render of the current wall-clock time to output/current.png
idle-hours run --once

# Loop: re-renders whenever the fuzzy bucket changes (not every minute)
idle-hours run

# Loop + push each new render to a connected Inky Impression
idle-hours run --display-script display_inky.py

# Appliance / production mode (hides debug bucket/quality/time footer)
idle-hours run --display-script display_inky.py --mode production

# Dark theme (black background, white text, yellow accent) — both CLIs accept --theme
idle-hours run --display-script display_inky.py --theme dark

# Auto theme: dark between 18:00–06:00, default otherwise
# (button B toggles manually and overrides 'auto' until midnight)
idle-hours run --display-script display_inky.py --theme auto

# Broaden the auto rotation past the binary default/dark pair
# (e.g. scholar by day, nightvision by night — pick any registered theme)
idle-hours run --theme auto --auto-day-theme scholar --auto-night-theme nightvision

# Random theme: rerolls each time the displayed quote changes. Button B
# manual override still wins (until midnight), same as for 'auto'.
idle-hours run --display-script display_inky.py --theme random

# Optional curator web UI (off by default). 127.0.0.1 binds skip auth entirely;
# any other host requires --web-token (or --web-token-file for systemd).
# A configured token gates every POST and every JSON GET; cross-site POSTs and
# unrecognised Host headers are rejected on all binds (see docs/web_ui.md).
idle-hours run --web-bind 127.0.0.1:8080
idle-hours run --web-bind 0.0.0.0:8080 --web-token-file ~/.idle-hours/web.token
# Reaching the UI by an mDNS name or through a reverse proxy: name it, or the
# DNS-rebinding guard rejects the Host header.
idle-hours run --web-bind 127.0.0.1:8080 --web-allowed-host idle-hours.local
# Require the token on GET /metrics too (off by default for scrapers).
idle-hours run --web-bind 0.0.0.0:8080 --web-token-file ~/.idle-hours/web.token --web-metrics-token

# Webhook notifications (v2): POST every alert-worthy telemetry event to an
# operator-configured HTTP endpoint. Filter defaults to "errors / backoff /
# timeouts / button-died / state-validation / web-auth-fail / web-error";
# pass --webhook-all-events to widen to "everything except heartbeats and
# successful renders". Heartbeats are always filtered (alerting once a minute
# is spam). Best-effort: posts on a daemon thread with a 5s urllib timeout,
# failures log but never block the render path.
idle-hours run --webhook-url https://hooks.example.test/idle-hours
idle-hours run --webhook-url https://hooks.example.test/idle-hours --webhook-all-events

# Disable the Inky button listener (use on dev machines / headless smoke tests)
idle-hours run --buttons-off

# Relocate the curator-mutable corpus files onto a writable path. REQUIRED for
# the curator UI under the shipped systemd unit, whose ProtectSystem=strict
# mounts the installed package read-only (saves + "Bake now" 500 otherwise).
# Missing destinations are seeded from the bundled copies at startup, so the
# committed bans / content fixes migrate across on first boot.
idle-hours run --overrides         /var/lib/idle-hours/selection_overrides.json \
               --content-overrides /var/lib/idle-hours/content_overrides.json \
               --raw-corpus        /var/lib/idle-hours/candidates-attributed.jsonl \
               --baked-db          /var/lib/idle-hours/quote_database.jsonl

# Persisted runtime state (manual theme + manual quiet override) and telemetry sidecar
idle-hours run --state-path ~/.idle-hours/state.json --telemetry-path ~/.idle-hours/telemetry.jsonl
idle-hours run --telemetry-retain-days 30        # cap rotated telemetry siblings at 30 days (default 90; 0 disables)
idle-hours health --hours 24                  # human-readable summary
idle-hours health --hours 24 --json           # JSON for cron / systemd health checks
idle-hours health --hours 1 --fail-if-no-renders   # exit 2 if the window was silent
idle-hours health --hours 1 --max-heartbeat-age-minutes 5   # exit 2 if the main loop hasn't ticked in 5 min
idle-hours health --hours 1 --max-render-age-minutes 90     # exit 2 if the panel hasn't repainted in 90 min
                                                           # (stands down while quiet hours are open)
# Under the shipped systemd preset telemetry lives in /var/lib/idle-hours, not ~/.idle-hours.
# Point health at the same config file the unit uses rather than restating the path:
idle-hours health --config /var/lib/idle-hours/config.toml --hours 24

# Push a static "starting" frame at boot so the panel doesn't ghost yesterday's render
idle-hours run --startup-image assets/goodnight.png
# …or render the sleep quote on the fly in the active theme:
idle-hours run --theme scholar --startup-image auto

# Override the button-D long-press shutdown command (default: sudo -n shutdown -h now)
idle-hours run --shutdown-command ""             # disable shutdown-on-hold entirely

# Disable the default quiet-hours blackout (defaults 22:00–06:00)
idle-hours run --quiet-off
idle-hours run --quiet-start 23:30 --quiet-end 07:00

# The sleep frame ("To sleep, perchance to dream." — Hamlet) renders in the
# clock's own theme by default. --quiet-theme gives it one of its own:
idle-hours run --theme scholar --quiet-theme nightvision   # fixed dark sleep theme
idle-hours run --theme scholar --quiet-theme random        # rerolled once per night
idle-hours run --quiet-theme auto                          # wall-clock day/night picks

# Push a static PNG instead of rendering (ignores every theme setting)
idle-hours run --quiet-image assets/goodnight.png
# …or render the --quiet-start quote as the last frame of the night
idle-hours run --quiet-image ""

# Render a specific time directly (bypasses the loop)
idle-hours render --time 22:54

# Show the picker's JSON for a given time or explicit bucket
idle-hours pick --time 14:30
idle-hours pick --bucket h2_half_pastish

# Render a 12x12 contact sheet of every fuzzy bucket for visual QA
idle-hours contact-sheet --output output/contact-sheet.png
idle-hours contact-sheet --theme dark --mode debug   # theme/mode flags flow through

# Push a rendered PNG to the Inky panel (Pi only)
idle-hours display output/current.png
```

### Corpus / mining pipeline

```bash
# Mine a single Gutenberg ebook by ID
idle-hours mine --gutenberg-id 1342 --strict --output output/candidates.jsonl

# Mine multiple IDs
bash scripts/run_batch2.sh

# Mine local text files
idle-hours mine --input ~/books/ --output output/candidates.jsonl

# Merge multiple harvest runs (deduplicates)
idle-hours merge output/run1.jsonl output/run2.jsonl
# → candidates-merged.jsonl + candidates-merged-summary.json

# One-shot "mine + pipeline + merge into live corpus" driver for a curated list
# of clock-precise Gutenberg IDs (gutenberg_dawn_expansion_ids.txt).
# Safe to re-run — downloads cache in data/gutenberg/, merge_candidates dedupes.
bash scripts/run_dawn_expansion.sh

# Diagnose which GPIO pin each physical Inky button actually fires (Pi only).
# Prints timestamped PRESSED/released lines per pin. Use before blaming
# inky_buttons.BUTTON_GPIO or handler logic.
idle-hours probe-buttons
idle-hours probe-buttons --pins 5 6 16 24 17 13 26      # custom pin set
idle-hours probe-buttons --pull-down --bounce 0.02      # active-high + tight debounce

# Analyze which time buckets have few/no quotes. Counts DISPLAYABLE rows
# (quality ≥ 60, not banned — the baker's and picker's own gates); raw
# tallies ride alongside as raw_bucket_counts.
idle-hours coverage output/candidates-merged.jsonl
idle-hours coverage idle_hours/assets/candidates-attributed.jsonl --min-quality 60 \
    --overrides idle_hours/assets/selection_overrides.json \
    --output-json idle_hours/assets/bucket-coverage.json --output-md idle_hours/assets/bucket-coverage.md
# → bucket-coverage.json + bucket-coverage.md

# Search specifically for sparse/empty bucket phrases
idle-hours target-sparse output/bucket-coverage.json
# → targeted-candidates.jsonl

# Convert targeted hits for merging
idle-hours import-targeted output/targeted-candidates.jsonl
# → targeted-candidates-importable.jsonl

# Normalize excerpts into display-ready text
idle-hours clean output/candidates-merged.jsonl
# → candidates-cleaned.jsonl

# Add quality scores and flags
idle-hours quality output/candidates-cleaned.jsonl
# → candidates-quality.jsonl

# Repair rows whose matched_text is a substring of a longer time phrase
# (e.g. "five minutes past two" mis-captured inside "thirty-five minutes past two")
idle-hours fix-substring-times output/candidates-quality.jsonl

# Repair rows left tagged with legacy 8-state bucket names ("just_after",
# "half_pastish", etc.) from the pre-buckets.py drift era; also normalises
# embedded-newline matched_text back to a single clean phrase.
idle-hours fix-legacy-buckets output/candidates-quality.jsonl

# Attach title/author from Gutenberg headers
idle-hours enrich output/candidates-quality.jsonl
# → idle_hours/assets/candidates-attributed.jsonl

# Layer durable hand-curated fixes from the sidecar on top.
# No-op when the sidecar is empty; otherwise patches matching rows in place,
# stamps override_applied=true, and re-derives fuzzy_bucket from any
# time-affecting overrides. Warns on stderr for dangling keys.
idle-hours apply-overrides idle_hours/assets/candidates-attributed.jsonl
# → idle_hours/assets/candidates-attributed.jsonl (raw attributed corpus)

# Final stage: bake the display-ready runtime quote database.
# Drops daypart-only rows and rows below --min-quality, pre-computes the
# nine row-intrinsic score components + source rarity (against the full raw
# corpus so picks stay equivalent) into baked_score, caches
# inferred_quote_minute, and assigns a per-bucket baked_rank. The runtime
# picker reads this file by default and only recomputes the two request-time
# components (minute_penalty, override_bonus) per pick.
idle-hours bake idle_hours/assets/candidates-attributed.jsonl
# → idle_hours/assets/quote_database.jsonl (pick_quote.py default --database)
```

## Default paths

After the v2.x package restructure, three resolution rules apply:

- **Bundled package assets** (`idle_hours/assets/`, `idle_hours/fonts/`,
  `idle_hours/web/`) and the per-stage default JSONL paths anchor on
  `BASE_DIR = Path(__file__).resolve().parent` — which now points *inside*
  the installed package. The wheel ships these as `package-data`, so a
  bare `pip install idle-hours` resolves them correctly.
- **Runtime artefacts** (`output/current.png`, the Gutenberg download cache
  under `data/gutenberg/`, history / state / telemetry sidecars) anchor
  on **CWD**, not `BASE_DIR`. A `BASE_DIR`-relative output would write
  inside the installed package directory, which is not what an operator
  wants. The shipped appliance preset (`config.toml.example`) therefore
  sets `output` to an absolute path under `/var/lib/idle-hours/`; the
  systemd unit's `WorkingDirectory=` is the same directory, but it is
  there for `lgpio` (see "Appliance / Pi Setup"), not to anchor outputs.
- **Operator-supplied input paths** (`--render-script`, `--display-script`,
  `--quiet-image`, `--startup-image`) go through `path_resolution.resolve_input_path`,
  which tries CWD-relative first and falls back to `BASE_DIR`-relative when
  the CWD candidate doesn't exist. This lets `config.toml.defaults` keep
  relative strings like `render_script = "render_quote.py"` (resolves to
  the bundled script regardless of CWD), while an operator who drops
  `./my_renderer.py` in their working tree and points the config at it
  still gets *their* file. Absolute paths pass through unchanged. The
  asymmetry vs. outputs is deliberate — outputs MUST go to CWD (writing
  into site-packages is never what an operator wants), inputs prefer CWD
  but accept the bundled fallback for portability.

`scripts/run_batch2.sh` reads its Gutenberg IDs from
`scripts/gutenberg_batch_ids.txt`; the script resolves to the repo root and writes to `output/` regardless of the
caller's CWD.

## Pipeline Flow

```
Gutenberg texts / local .txt files
  ↓ gutenberg_time_miner.py
candidates-*.jsonl  (multiple runs possible)
  ↓ merge_candidates.py
candidates-merged.jsonl
  ↓ bucket_coverage.py
bucket-coverage.json  ← identifies gaps
  ↓ target_sparse_buckets.py
targeted-candidates.jsonl
  ↓ import_targeted_hits.py + merge_candidates.py
candidates-merged-plus-targeted.jsonl
  ↓ clean_display_quotes.py
candidates-cleaned.jsonl
  ↓ quality_filter.py
candidates-quality.jsonl
  ↓ fix_substring_time_matches.py (legacy; no-op on fresh harvests)
  ↓ fix_legacy_buckets.py           (legacy; no-op on fresh harvests)
  ↓ enrich_metadata.py
candidates-attributed.jsonl
  ↓ apply_content_overrides.py (layer assets/content_overrides.json on top)
assets/candidates-attributed.jsonl    ← raw attributed corpus (curator UI --input)
  ↓ bake_quote_database.py (drop daypart/low-quality, pre-score, per-bucket sort)
assets/quote_database.jsonl           ← pick_quote.py default --database
  ↓ pick_quote.py
JSON quote for requested time
  ↓ render_quote.py (imports pick_quote in-process)
output/current.png  (overwritten per render — stable filename)
  ↓ display_inky.py (optional, Pi-only)
Inky Impression eInk panel
  ↑ run_clock.py orchestrates the render→display loop
```

## Architecture

### Data model at a glance

The canonical runtime input is **`idle_hours/assets/quote_database.jsonl`** — the baked, display-ready DB produced by `bake_quote_database.py`. Everything else in `idle_hours/assets/` is either the raw corpus that feeds the baker, a hand-edited sidecar, or a build-time artifact. Use this table to answer "what's source-of-truth vs derived vs per-appliance state?":

| Path | Role | Committed | Ships to Pi | Produced by |
|---|---|---|---|---|
| `idle_hours/assets/quote_database.jsonl` | **baked display-ready DB — the runtime picker reads this** | yes | yes | `bake_quote_database.py` |
| `idle_hours/assets/candidates-attributed.jsonl` | raw attributed corpus | yes | yes (baker input + curator UI + fallback) | `enrich_metadata.py` → `apply_content_overrides.py` |
| `idle_hours/assets/content_overrides.json` | per-row hand fixes (source-of-truth) | yes | no (build-time only) | hand-edited or web UI `POST /api/content-overrides` (followed by `POST /api/bake`) |
| `idle_hours/assets/selection_overrides.json` | bans / boosts / preferred buckets / per-row bans (runtime-editable) | yes | yes | hand-edited or web UI `POST /api/overrides` |
| `idle_hours/assets/bucket-coverage.{json,md}` | coverage snapshot | yes | optional | `bucket_coverage.py` |
| `~/.idle-hours/state.json` | manual theme / quiet override | — | runtime, per-appliance | `run_clock.py` |
| `~/.idle-hours/history.jsonl` | anti-repeat ledger | — | runtime, per-appliance | `run_clock.py` |
| `~/.idle-hours/telemetry-YYYYMMDD.jsonl` | render / error / heartbeat / backoff / timeout telemetry | — | runtime, per-appliance | `run_clock.py` |

**These four paths are relocatable (v2.0.x).** `run_clock` exposes `--overrides` / `--content-overrides` / `--raw-corpus` / `--baked-db` (config keys `overrides` / `content_overrides` / `raw_corpus` / `baked_db`), defaulting to the bundled package copies. The appliance preset relocates all four into `/var/lib/idle-hours/`, because the shipped systemd unit's `ProtectSystem=strict` mounts the installed package read-only — with the defaults, `POST /api/overrides`, `POST /api/content-overrides`, and `POST /api/bake` all fail with a read-only-filesystem error (issue #179). `_seed_writable_corpus_paths` copies the bundled file to any relocated path that doesn't exist yet at startup (never overwriting), so the migration is automatic and lossless. Whatever these are set to is threaded to *both* the runtime picker (`_corpus_kwargs` → `peek_quote_id` + the `render_quote.py` subprocess argv) and the curator UI (`web_server.WebContext` reads the same four Namespace attributes) — splitting them would let the UI write a file the panel never reads.

Four invariants to keep in mind when touching this layer:

1. **Source-of-truth is the raw corpus + `content_overrides.json`.** If you want a row to change, change those. The baked DB is re-derivable from them; changes made directly to `quote_database.jsonl` will be clobbered the next time someone runs the pipeline.
2. **Runtime reads the baked DB.** `run_clock`, `render_quote`, and the `pick_quote` CLI all pass `database_path=DEFAULT_DATABASE_PATH` explicitly. A raw-corpus commit with no matching bake means the new rows are invisible to the appliance — the expand-corpus drivers (`run_dawn_expansion.sh`) include `bake_quote_database.py` as the last step for exactly this reason.
3. **Curator UI reads the raw corpus deliberately.** `/api/bucket` calls `pick_quote.select_candidates` (raw path) so an operator can see rows the baker dropped (daypart-only, quality below floor) and understand *why* a quote never appeared. Switching the curator to the baked DB would regress that visibility — don't.
4. **Every picker default must be an absolute, existing path.** `select_quote` / `select_candidates` previously defaulted `overrides_path` to the bare relative string `"assets/selection_overrides.json"`, which stopped existing when v2.x moved the tree under `idle_hours/`. `load_overrides` fail-opens on a missing file, so every caller relying on the default — including `render_quote.pick_quote`, i.e. the actual runtime render path — silently applied **no** bans, boosts, or preferred buckets: the curator's "Ban this quote" button wrote a ban the panel ignored forever. Both defaults are now `DEFAULT_OVERRIDES_PATH`, and `tests/test_pick_quote.py::TestOverridesPathDefaults` fails any picker default that is relative or non-existent. A CWD-relative default in this layer is always a bug — it resolves differently depending on where the process was started.

### Fuzzy Bucket System

The core abstraction. Each of 12 hours is divided into 12 minute-state buckets (144 total), named `h{HOUR}_{STATE}`. Plus `daypart` buckets (midnight, small_hours, dawn, morning, noon, afternoon, dusk, evening, night) for time references that don't specify an hour.

`buckets.py` is the single source of truth (`BUCKET_ORDER`, `DEFAULT_BUCKET_MINUTES`, `minute_bucket`, `bucket_for_time`, `neighbor_buckets`); `gutenberg_time_miner.py`, `run_clock.py`, `pick_quote.py`, `bucket_coverage.py`, and `fix_substring_time_matches.py` all import from it, so the rounding rule `rounded = ((minute + 2) // 5) * 5` only lives in one place.

| Rounded minute | State |
|---|---|
| 0 | `exact` |
| 5 | `five_past` |
| 10 | `ten_past` |
| 15 | `quarter_past` |
| 20 | `twenty_past` |
| 25 | `twenty_five_past` |
| 30 | `half_past` |
| 35 | `twenty_five_to` |
| 40 | `twenty_to` |
| 45 | `quarter_to` |
| 50 | `ten_to` |
| 55 | `five_to` |

**History:** An earlier revision of `fix_substring_time_matches.py` kept a private copy of the state names in the legacy 8-state form (`just_after`, `early_past`, etc.), which silently produced invalid `fuzzy_bucket` values no downstream consumer could match. The shared `buckets.py` module was extracted specifically to kill that class of drift — avoid reintroducing a second state table.

### Match Types

`gutenberg_time_miner.py` detects time phrases using named-group regexes:
- `digital` — `14:30` format
- `oclock_word` — "three o'clock"
- `quarter_half` — "quarter past six", "half past two", and (issue #301) the hyphenated "half-past ten" and the "quarter after seven" / "half after four" forms, which used to yield no row. `minutes_past_to` also takes the archaic reversed compound "five-and-twenty minutes past seven" (= 07:25, previously mined as 07:20). A minutes-less "ten past two" pattern is deliberately *not* added: "ten to one" is betting odds as often as a time.
- `quarter_to` — "quarter to eight"
- `minutes_past_to` — "ten minutes past five"
- `just_after_before` — "shortly after noon", "almost three"
- `clock_struck` — "the clock struck midnight". A bare `struck N` is accepted only with a striker (clock / watch / bell / chime / chronometer / church / tower / steeple / hour …) within 60 characters on either side, when N is `midnight` / `noon`, or when `o'clock` follows it directly (`struck one o'clock`); otherwise it is the verb ("she struck one of the fish", "struck one as an uncommonly strong dose" — five such rows sat at 01:00 in the baked DB, issue #298). An `o'clock` elsewhere nearby is *not* a striker: `\b` sits between the apostrophe and `clock`, so without an explicit lookbehind every nearby "o'clock" counted as one.
- `daypart` — bare "morning", "dusk" etc. (excluded by `--strict`)

**Overlapping spans are resolved, longest first (issue #298).** The patterns used to run independently over the text, so `oclock_word` also fired *inside* a `just_after_before` or `minutes_past_to` span and the same sentence was filed at two times: "just after nine o'clock" gave 09:03 *and* a wrong 09:00, "nearly one o'clock" 12:57 *and* 01:00 — 111 such pairs in the shipped corpus, which `merge_candidates` cannot collapse because `normalized_time` is in its key, and the wrong-time twin rendered with "one o'clock" bolded while the text said "nearly". `_non_overlapping_matches` collects every pattern's matches, sorts by `(start, -length, pattern order)` and drops any match whose span overlaps an accepted one, so the longer, more specific phrase wins. Candidates are therefore yielded in *text* order rather than pattern order, which is also what `--max-per-file` should count. Both fixes only affect future mines; the committed corpus had the affected rows purged and was re-baked.

Use `--strict` for production runs to reduce false positives (excludes `daypart` and `digital` matches). `--skip-fetch-errors` keeps batch runs alive when a Gutenberg download 404s.

**Known limitation — `digital` matcher drops in-prose times (issue #159, closed won't-fix).** The `digital` pattern's trailing lookahead `(?!\s+[A-Z][a-z])` runs under `re.IGNORECASE`, where `[A-Z]` / `[a-z]` both match any letter — so the lookahead rejects essentially every digital time followed by a word (`"14:30 in the afternoon"` → dropped; only punctuation-trailed times like `"9:15."` survive). **No production impact:** `--strict` excludes the `digital` match type entirely, so the committed corpus / baked DB were never built from digital matches. Left unfixed deliberately — the defect lives in a code path nobody exercises in production, and a fix would require a non-strict re-mine. If the matcher is ever revived for non-strict use, the fix is: (1) scope the trailing-capital lookahead case-sensitively, `(?!\s+(?-i:[A-Z][a-z]))` (valid under `requires-python >= 3.11`), so it only guards Title-Case headings; (2) extend the existing post-match reference guard at `gutenberg_time_miner.py` (`context_probe` → `\b(?:chapter|psalm|verse|book|epistle)\b`) with `section|canto|hymn` plus a leading-only, period-anchored guard for `No.`/`p.`/`pp.` — but **not** bare `no` (it would reject the common word). Note the `context_probe` guard already rejects chapter/psalm/verse independently of the lookahead, so the scoped-flag fix alone does not break the scripture-rejection tests in `tests/test_miner_match_types.py`.

### JSONL Record Schema

Fields accumulate as rows flow through the pipeline:

```
# From gutenberg_time_miner.py
source_path, source_id, match_type, matched_text, quote_text, context_text,
hour, minute, normalized_time, fuzzy_bucket, daypart_bucket, line_number, match_start, match_end

# Added by merge_candidates.py
canonical_quote, canonical_context

# Added by clean_display_quotes.py
display_quote, display_fragment (bool), cleanup_status ("complete_sentence" | "expanded_with_context" | "fragment_fallback" | "empty")

# Added by quality_filter.py
quality_score (0–100), quality_flags (list of penalty reasons)

# Added by enrich_metadata.py
author, title  # parsed from the cached Gutenberg header when available
```

### Deduplication Key

`merge_candidates.dedupe_key` identifies a hit by *where and what it matched*: `(source_id, line_number, matched_text.lower(), normalized_time)`. The same phrase at the same place in the same book is one hit however wide the sentence window around it was cut, and a different phrase or time on the same line is a different hit. On collision, keeps the entry with longer `context_text`. Rows with no `source_id` (local text files) fall back to `(normalized_time, daypart_bucket, canonical_quote)`, where `canonical_quote` is the lowercased, smart-quote-normalised `quote_text`. The earlier key was `(normalized_time, fuzzy_bucket, daypart_bucket, canonical_quote)` — both buckets are *derived* from the time, so a harvest-to-harvest change in the derivation let byte-identical hits through, and `canonical_quote` is the pre-clean window, so two fragments the cleaner later expands to the same sentence were distinct (issue #294). Merge cannot see display text at all (it runs before `clean`), which is why the picker also collapses textual twins at pick time — see "Quote Selection".

### Quality Scoring

`quality_filter.py` starts each row at 100 and applies penalties (see `BAD_PATTERNS` and `score_quote`). Heavy hitters:
- `contains_time_range` (`3:00–5:00`) and `contains_metadata` (copyright/project gutenberg/ebook): −55
- `contains_work_schedule` (schedule text: "working hours", "work shift", "nine to five") and `contains_modern_am_pm` (`am`/`pm` only as a clock suffix after a number; dotted `a.m.`/`p.m.` alone): −45. Both were far looser until issue #296 — `\bwork\b` hit the verb in ordinary prose and a bare `am` hit "I am", which was every one of the 56 am/pm flags in the shipped corpus; between them they kept ~80 good quotes under the bake floor.
- `contains_structural_label` (a *heading* — "Chapter IV", "BOOK 2", all-caps `ACT`/`SCENE` — never the words in prose, and a lone roman "I" only before punctuation so "the book I read" is the pronoun): −35
- `leading_heading` (issue #308): the excerpt still *opens* with a heading the cleaner strips — a bare Roman numeral of two or more letters ("XXXIV. Next morning…", or with no period when a capitalised sentence follows: "XI Emil came home…") or a run of three or more all-caps words before a sentence ("—CONTINUATION OF THE ENIGMA The night wind…"): −35. Defence in depth; `clean_edges` / `strip_heading_prefix` remove both, plus a leading ellipsis, orphan `_` markers, and PRIME / DOUBLE PRIME (tofu in forty bundled faces). `uppercase_heavy` (−15) stays mild on purpose: what it flags after the cleaner is mostly play speaker labels.
- `fragment`: −30, `too_short` (<50 chars) / `too_long` (>260 chars): −20
- Cleanup status other than `complete_sentence` or `expanded_with_context`: −20
- `digit_heavy` (≥6 digits): −25, `uppercase_heavy` (>18% uppercase): −15
- `weak_ending` (no terminal punct/quote): −10
- `unbalanced_quotes` (an odd count of `"`, or `“`/`”` that do not match one for one; single quotes are not checked because `’` is also the apostrophe): −15. Defence in depth behind the cleaner (issue #297): `clean_edges` keeps an edge quotation mark whose partner is inside the text and strips only an unpaired one (a closing mark at the start is always junk), `best_display_quote` prefers a run whose marks pair up over one that starts with the tail of a speech, and the winner has an unpaired edge mark dropped. What survives is a quotation that genuinely runs past the miner's window, which this penalty ranks below a clean alternative. `tests/test_corpus_invariants.py::TestQuotationBalance` caps the count in the baked DB.

Penalty reasons are appended to `quality_flags`. The score is floored at 0.

### Substring-Collision Fix

`fix_substring_time_matches.py` scans `display_quote` for the full pattern `<minute-word> minutes (past|to) <hour-word>`; if the row's stored `matched_text` is a strict substring of that longer phrase, the row's `matched_text`, `hour`, `minute`, `normalized_time`, and `fuzzy_bucket` are rewritten. Writes in-place by default (pass `--output` to redirect).

It also repairs the **quarter/half swallow**: a legacy `oclock_word` row whose quote reads "half-past ten o'clock", "half after eleven o'clock" or "a quarter before ten" but was filed at :00 with only "ten o'clock" bolded. `repair_row` rewrites it to the bare phrase the miner itself would capture (`half-past ten`, 10:30, `quarter_half`; `quarter to/before X` → `quarter_to` with the 12→1 wrap), so its dedupe key collides with a correctly mined twin, and `main()` then drops the repaired row in favour of that twin. It skips a row whose bare phrase also stands alone elsewhere in the quote, and any row whose time fields or display text carry a content override. Run over the committed corpus it repaired 66 rows and dropped 12 as twins; `TestQuarterHalfSwallowedPhrases` in `tests/test_corpus_invariants.py` fences the baked DB against a recurrence.

### Legacy-Bucket Repair

`fix_legacy_buckets.py` is the companion cleanup for rows tagged with the obsolete 8-state names (`just_after`, `early_past`, `quarter_pastish`, `half_pastish`, `late_past`, `just_before`, `quarter_toish`) harvested before `buckets.py` was extracted. For each such row with a valid `hour`/`minute`, it recomputes the canonical `h{hour}_{state}` bucket using the shared `minute_bucket` primitive (handling the top-of-hour rollover when `minute ≥ 58`). It also collapses runs of whitespace in `matched_text` back to a single space so phrases captured across a source line break (`"towards\ndusk"`) stay stored as a single clean phrase. `pick_quote.load_rows` already re-derives `fuzzy_bucket` from `normalized_time` so the stale values were not visibly broken at runtime, but storage should match the canonical schema so any future consumer reading `fuzzy_bucket` directly sees correct values and `merge_candidates` dedup keys stay stable. Writes in-place by default.

### Metadata Enrichment

`enrich_metadata.py` walks each row's `source_id`, opens the cached `data/gutenberg/pg<id>.txt`, and scans the first 120 lines for `Title: ` and `Author: ` headers. Results are cached per `source_id` so each file is parsed once. Fills `title`/`author` only when missing — existing values on a row are preserved. Output: `idle_hours/assets/candidates-attributed.jsonl`, consumed by `apply_content_overrides.py` (the next stage) and then by `pick_quote.py`.

### Content Overrides (`idle_hours/assets/content_overrides.json`)

Per-row sidecar for durable hand-curated fixes, applied by `apply_content_overrides.py` as the final pipeline stage on top of `idle_hours/assets/candidates-attributed.jsonl`. Exists because earlier revisions accumulated growing repair scripts (`fix_substring_time_matches.py`, `fix_legacy_buckets.py`) that patched *derivable* artifacts in place — any subsequent miner re-run would silently clobber the patch, so the same display bug could resurrect later. The sidecar decouples hand curation from pipeline regeneration: the fix lives here, and every re-run of the pipeline ends by re-applying it.

Keyed by `"<source_id>:<line_number>"` → partial row dict:

```json
{
  "141:482":  {"display_quote": "…"},
  "1342:99":  {"matched_text": "half past two", "normalized_time": "02:30"}
}
```

Allowed override fields: `display_quote`, `matched_text`, `author`, `title`, `quality_score`, `hour`, `minute`, `normalized_time`. Unknown fields are ignored with a stderr warning. After patching, `fuzzy_bucket` is re-derived from the post-override `normalized_time` (and `normalized_time` itself is re-derived from `hour`/`minute` when those are overridden without an explicit `normalized_time`; conversely an overridden `normalized_time` re-derives whichever of `hour`/`minute` the entry leaves out — issue #305), so time-affecting overrides stay internally consistent. Ill-typed values — a non-int or out-of-range `hour` / `minute` / `quality_score`, a `normalized_time` that is not zero-padded `HH:MM` — are skipped per field with a stderr warning rather than written. A replaced `display_quote` also re-runs the classification the old text went through: `display_fragment` (via the cleaner's `looks_fragment`), `cleanup_status`, `quality_flags` and — unless the entry sets it explicitly, or sets it to a malformed value — `quality_score` (via `quality_filter.score_quote`) are re-derived from the new text and recorded in `override_originals` like any other derived field, so removing the entry restores the fragment-era values. Before this a curator-trimmed sentence kept the score and fragment flag of the text it replaced: four clean quotes sat under the bake floor, and even once lifted they ranked with a fragment penalty. Patched rows are stamped `override_applied: true` for downstream debugging.

**Overrides are reversible (`override_originals`).** The stage writes its output back over its input, and so does the curator's "Bake now", so an override ends up baked into the raw corpus. Without a record of what it replaced, deleting a sidecar entry and re-running changed nothing — the edit was permanent, and unrecoverable on an appliance whose relocated corpus has no git history. The first time the sidecar writes a field, the row's previous value goes into `override_originals` (a derived `normalized_time` is recorded too); a field the sidecar no longer writes is restored from it, and a row left with no originals loses both `override_originals` and `override_applied`. Rows patched before the ledger existed record their already-patched value as the original, because the true one is gone. A sidecar entry that is present but not an object leaves its row untouched: treating a typo like a deletion would silently revert the override. The baker strips `override_originals` from the baked DB (`_RAW_ONLY_FIELDS`); the runtime never reads it.

`apply_content_overrides.apply_overrides` warns on stderr for **dangling keys** — sidecar entries that don't match any row in the input, typically caused by a typo or a row that later got dedup-dropped or filtered out. That's the intended replacement for *silent no-op* editing of `candidates-attributed.jsonl` by hand: fixes either apply (and are stamped) or loudly don't (and are logged).

**Fail-open loading, atomic writeback.** `load_overrides` catches `OSError` / `ValueError` / `JSONDecodeError` and a non-object root, emits one stderr warning, and returns `{}` so an editor-crash-truncated `content_overrides.json` doesn't abort the entire bake — worst case the picker runs with no sidecar patches applied. When `--output` is omitted (the default), output equals input, so `main` writes through `atomic_io.atomic_write_lines` (sibling-tmp → fsync → `os.replace` → dir-fsync). A crash mid-writeback leaves the existing `idle_hours/assets/candidates-attributed.jsonl` byte-identical instead of truncating the picker's runtime corpus.

**Soft discipline:** if you find yourself overriding more than a handful of rows for the same reason, that's a signal the upstream stage has a bug — push the fix into the miner / cleaner / quality filter rather than accumulating per-row patches.

**Curator UI editing.** As of v2 the sidecar is editable from the web UI via `GET /api/content-overrides` (returns the raw dict) and `POST /api/content-overrides` (validated atomic rewrite). The UI's "Bake now" button (`POST /api/bake`) runs `bake_quote_database.bake_rows` in-process so a save-then-bake round-trip drops the new excerpts onto the panel within seconds without an SSH session. Validation rejects unknown fields and bad key shapes with a 400; the same `apply_content_overrides.ALLOWED_FIELDS` set is the single source of truth.

**Legacy fix scripts.** `fix_substring_time_matches.py` and `fix_legacy_buckets.py` are retained as one-shot migration tools for corpus rows harvested by earlier miner revisions (the miner now collapses `matched_text` whitespace and the shared `buckets.py` prevents legacy 8-state names). Fresh mines should make them no-ops; see each script's docstring.

### Baked Quote Database (`idle_hours/assets/quote_database.jsonl`)

Final pipeline stage output, produced by `bake_quote_database.py` from the raw attributed corpus. This is the *display-ready database* the runtime picker consults by default; `candidates-attributed.jsonl` stays on disk as the raw corpus and is used by the curator UI's bucket inspector (`/api/bucket`).

**Why it exists.** Of the twelve score components in `pick_quote.score_row`, nine are row-intrinsic (`fragment`, `cleanup`, `metadata`, `dialogue`, `opening`, `source_bonus`, `quality`, `length_exactness`, `length_tiebreak`) and one more — `source_rarity_penalty` — depends only on the corpus as a whole; only `minute_penalty` and `override_bonus` actually change per request. Computing those ten components once at bake time, shipping them inline on each row, and dropping rows the picker would have filtered anyway (daypart-only rows with no `fuzzy_bucket`, rows below `--min-quality`) makes the runtime pick deterministic, smaller, and git-diffable: a regression in the scorer shows up as a diff to the committed database, not a silent drift in what the clock displays.

**Row schema additions.** Every baked row keeps its original fields plus:

- `baked_score` — list of ten ints in `BAKED_SCORE_COMPONENTS` order (see `bake_quote_database.py` and `pick_quote.py`). Drift between the two constant lists is how pick-equivalence silently breaks, so they're cross-checked in tests.
- `inferred_quote_minute` — what minute this row claims, cached once so `minute_penalty` doesn't re-run the regex sweep per tick.
- `baked_rank` — 0-based ordinal within the row's bucket after sorting ascending by `baked_score`. Purely for curator readability (the file is `(bucket, rank)`-ordered on disk); the runtime picker still sorts again once it has the two request-time components.
- `schema_version` — integer marker matching `BAKED_SCORE_SCHEMA_VERSION` in `bake_quote_database.py` / `pick_quote.py`. Bump whenever `BAKED_SCORE_COMPONENTS` changes (order, length, or semantics). `pick_quote._resolve_corpus` reads this field on the first baked row it encounters; a mismatch (stale `quote_database.jsonl` paired with a freshly `git pull`-ed `pick_quote.py`, or vice versa) triggers a fallback to the raw corpus with a stderr warning instead of silently scoring against a mis-aligned tuple. A baked DB pre-dating the field is treated as version 0 so upgrades surface loudly on first boot.

**Rarity is baked against the raw corpus**, not the baked subset — otherwise a source whose low-quality rows get dropped at bake time would count lower in the baked rarity than in the live one, and pick-equivalence between the two paths would break for that source's surviving rows. `tests/test_bake_quote_database.TestBakeRows::test_rarity_uses_full_input_corpus` pins this.

**Runtime lookup.** `pick_quote.select_quote` reads `idle_hours/assets/quote_database.jsonl` by default. If the file is missing, empty or schema-mismatched it falls back to the raw corpus with a stderr warning, so a bad bake degrades instead of crashing the loop. The warning fires once per version of the file, not once per pick (issue #234): the schema verdict is cached in `_SCHEMA_VERDICT_CACHE` on the same `(st_mtime_ns, st_size)` stamp the row cache uses, and the missing/empty cases latch on the path in `_DEGRADED_WARNED`. Two rules keep that correct:

- **Cache the verdict under the stamp the rows were loaded with.** `_load_rows_with_stamp` returns `(rows, stamp)` together and `_schema_mismatch_cached` takes that stamp. Re-statting would let a "Bake now" landing between load and stat cache an old verdict under the new file's stamp, and the latch would then hide it until the file changed again.
- **Any branch where the file exists clears the missing/empty latch.** That includes the schema-mismatch branch, so missing, then a bad bake, then missing again still warns each time.

`clear_corpus_cache()` resets both caches and the latch for tests. A process-local latch cannot cover the render subprocess, which starts with empty globals, so `run_clock` sets `pick_quote.SUPPRESS_WARNINGS_ENV` (`IDLE_HOURS_SUPPRESS_CORPUS_WARNINGS=1`) in its environment; the parent has already warned during its own peek. Only the exact string `"1"` suppresses, and a standalone `idle-hours render` still warns. It is an environment variable rather than a flag because an operator's own `--render-script` would reject an unknown flag and send the appliance into render backoff.

`score_row` detects `baked_score in row` and short-circuits into `compose_baked_score_key`, which interleaves the two request-time components back into the pre-baked tuple at the correct positions to reproduce `score_row`'s original 12-tuple layout exactly. `tests/test_bake_equivalence.py` sweeps all 144 canonical buckets and asserts baked and raw picks return the same `(source_id, line_number)`.

**What's still live, not baked.** `selection_overrides.json` (bans / boosts / preferred buckets) stays runtime, because the web UI rewrites it via `POST /api/overrides` — re-baking on every edit would block the UI on a CLI run. Bans are a cheap post-filter; boost/preferred bonuses fold into the `override_bonus` position of the sort key. The anti-repeat history ledger is also runtime (it mutates on every render).

**When to re-bake.** Any time `idle_hours/assets/candidates-attributed.jsonl` changes — expand-corpus drivers like `run_dawn_expansion.sh` already run `bake_quote_database.py` as the last pipeline step, and the git commit it suggests includes `idle_hours/assets/quote_database.jsonl` alongside the raw corpus and coverage snapshot. A raw-corpus commit without a matching baked-DB commit means the picker will happily ignore the newly added quotes until the next bake.

### Quote Selection (`pick_quote.py`)

Default database: `idle_hours/assets/quote_database.jsonl` (the baked DB — see "Baked Quote Database" above); raw-corpus fallback `idle_hours/assets/candidates-attributed.jsonl` via `--input`. Rows below `--min-quality` (default 60) are filtered out before scoring (a no-op on baked rows since the baker already enforces the floor); banned `source_id`s (from `selection_overrides.json`) are dropped entirely.

Candidates in a bucket are ranked by a long lexicographic tuple (lower is better at every position):

```
(fragment_penalty,           # 0 if display_fragment is False, else 1
 cleanup_penalty,             # 0 if cleanup_status in {"complete_sentence", "expanded_with_context"}, else 1
 minute_penalty,              # abs(requested_minute - inferred_quote_minute); 99 if either is None
 metadata_bonus,              # -3 both author+title, -1 one, +2 neither
 dialogue_penalty,            # +2 if text contains "he said" / "she said" / etc.
 opening_penalty,             # +2 weak opener (and/but/so/…), +1 pronoun opener
 source_bonus,                # +1 if no source_id
 override_bonus,              # -5 preferred_buckets[bucket] hit, -3 boost_source_ids hit
 -quality_score,              # higher quality wins
 length_penalty + exactness_bonus,
                              # |len(display_quote) - 140|, +80 cliff when len < 60
                              # (defence-in-depth so stubbornly short quotes lose to
                              # any reasonable-length alternative in-bucket), plus:
                              #   -2 for "five/ten minutes to" or "fifty-five minutes past"
                              #   -1 for "quarter"/"half" matches
 source_rarity_penalty,       # count of this row's source_id in the full corpus;
                              # ties between top-scored candidates go to rarer sources
 len(display_quote))          # final tiebreak
```

If no candidate in the target bucket qualifies, it walks outward through sibling minute-states of the same hour in alternating ±distance order (see `neighbor_buckets`); the chosen bucket is returned as `resolved_bucket` with `used_fallback: true`.

Among equally top-scoring rows, a seeded `random.Random(seed)` picks one so results are stable for a given `--seed`.

### Selection Overrides (`idle_hours/assets/selection_overrides.json`)

A small editable JSON doc consulted by `pick_quote.py` (its default `--overrides` path):

```json
{
  "ban_source_ids": [],        // source_ids excluded entirely
  "boost_source_ids": [],      // −3 in the ranking tuple
  "preferred_buckets": {},     // { "h3_late_past": 12345 } → that source_id wins in that bucket (−5)
  "ban_quote_keys": []         // ["141:482", ...] — per-row permanent bans (v2)
}
```

IDs are compared as strings. Edit this file rather than editing the scorer when you want to manually curate a specific bucket. `pick_quote.load_overrides` warns on stderr if any `preferred_buckets` key is not a valid `h{1..12}_{state}` bucket, so typos surface loudly instead of silently never firing. The loader fails open (issue #186): a truncated save or a non-object root degrades to empty overrides with a warning, and `sanitize_overrides` checks each field on its own, dropping a wrong-typed field or entry with a warning while the rest still applies. That is the only validator for this file: the curator UI's save runs the same function with `strict=True`, which raises on the first problem instead, and `TestSanitizeOverridesModes` holds the two modes together. Raising would freeze the panel in render backoff. The parsed result is cached on the file's stat stamp, so warnings fire once per version of the file, and the render subprocess stays quiet under `SUPPRESS_WARNINGS_ENV` like the corpus warnings.

**Per-row bans (`ban_quote_keys`, v2).** `ban_source_ids` blacklists every row from a Gutenberg ID — coarse but useful for "this whole book is unsuitable." `ban_quote_keys` is the fine-grained companion: a list of `"<source_id>:<line_number>"` strings, each dropping one row from the candidate pool **and every row that displays the same text** (issue #294): the committed corpus carries one passage under several keys — the miner fires on adjacent lines and the cleaner expands each to the same sentence run (`98:3534` … `98:3541`), and two Gutenberg editions of one book (`43` / `42`, `15` / `2701`) match identically — so a ban that matched only its own key was defeated by the twin. `pick_quote._twin_texts` resolves the banned keys to their `normalize_display_text` forms in one pass over the corpus, only when the list is non-empty. The anti-repeat ledger gets the same treatment, and `pick_best` collapses same-text candidates to their best-scored copy after scoring so a duplicated passage does not get two entries in the tie-break or two rows in the curator's inspector. The collapse runs identically on the baked and raw paths, which is what keeps `tests/test_bake_equivalence.py` green. Powers the curator UI's "Ban this quote" buttons (Now tab, bucket inspector, search results) so an operator can blacklist a single bad quote without nuking the rest of its source. `pick_quote.is_banned` checks both lists; the per-row check requires both `source_id` and `line_number` to be set on the row, so a malformed row can't be accidentally banned by a list entry. `load_overrides` defaults the field on legacy v1 sidecars so the rest of the picker doesn't have to special-case its absence. Every key check, in the loader and in the web UI, goes through `pick_quote.is_quote_key`, which uses `fullmatch` with ASCII digits so a key with a trailing newline or non-ASCII digits, which could never match a row, is rejected. The wholesale save layers the validated, normalised keys over the submitted document, so an operator's own extra top-level keys (a `_comment`, a field from a newer schema) survive the editor round-trip, as they do through the ban endpoint; the loader ignores them.

### Anti-Repeat History Ledger

A display-history ledger filters recently-shown quotes out of the candidate pool so the clock doesn't replay the same line twice in the same week. Default path is `~/.idle-hours/history.jsonl`; default window is 7 days. One entry per successful render:

```json
{"ts": "2026-04-19T14:30:00+00:00", "source_id": "141", "line_number": 482}
```

`pick_quote.load_recent_history` reads the ledger, drops entries older than `--history-days`, and returns a set of `(source_id, line_number)` tuples. `pick_best` applies a strict fresh-first filter: rows whose key is in that set are excluded before scoring, and if the filter empties the candidate pool the full list is used so sparse buckets still render something. `pick_quote.append_history` writes one line per successful render and then `fsync`s the handle so a power loss immediately after the call can't leave the entry buffered in the kernel — the worst failure case is one lost entry, never ledger-wide corruption. `pick_quote.remove_history_entries` (called by the button-A long-press "un-skip" action; removes *every* entry for the key, since a skip leaves both the render append and the ban append — issue #183) is the only code path that can rewrite the ledger from scratch; it goes through `atomic_io.atomic_write_text` so a `SIGKILL` between the read and the rewrite leaves either the pre-delete content (acceptable) or the post-delete content (acceptable) but never an empty or truncated ledger. If `load_recent_history` encounters a malformed line (partial write or external corruption), it logs a one-shot warning to stderr (`"history ledger {path}: malformed line skipped (corrupt or partial write); subsequent bad lines in this read will be suppressed"`) and continues; further bad lines in the same read are suppressed so a torn file doesn't spam the log.

Disable the filter by passing `--history-path ""` or `--history-days 0`. `select_quote` (the library entry point) defaults to **disabled** so unit tests and one-off callers are not affected; `run_clock.py` and `pick_quote.py`'s CLI default to **enabled**. `run_clock.py`:
- Calls `peek_quote_id` before `render_now` and forwards the peeked identity to the render subprocess as `--pin-quote SOURCE_ID:LINE --pin-matched-text TEXT`, so the subprocess renders *that exact row* instead of re-picking. The peek is authoritative; the old "peek and subprocess independently reach the same answer because they share a ledger snapshot" contract was only ever an implicit guarantee, and it broke outright on theme-only repaints, where the anti-repeat filter excluded the currently-displayed quote and silently swapped it (issue #190). run_clock still appends to the ledger only after the subprocess returns 0.

  **The pin key must carry `matched_text`.** `(source_id, line_number)` does **not** identify a corpus row — a single source line can carry several time phrases, so the committed `quote_database.jsonl` holds 128 duplicate `(source_id, line_number)` keys, many spanning different buckets (`"ten o'clock"` in `h10_exact` alongside `"close on ten o'clock"` in `h9_five_to`). A bare-key pin resolved to whichever copy came first on disk, which made ~8% of clock times render a phrase the picker never chose and report a bogus `resolved_bucket` / `used_fallback` in the debug footer. `run_clock._pin_key_for` therefore appends the peeked `matched_text` — the same discriminator `peek_quote_id` already tracks for dedup, for exactly this reason. Rows that still tie on `(key, matched_text)` but disagree on `fuzzy_bucket` (the same phrase mis-bucketed twice in the corpus) are broken by `neighbor_buckets(target_bucket)` order, so the pinned result reproduces the natural pick's bucket too. `tests/test_pick_quote.py::TestPinFidelityAgainstShippedCorpus` sweeps every canonical time against the real database and fails on any divergence — the synthetic-corpus pin tests all used unique keys, so they could not see this.

  **The pin respects bans but not the quality floor.** `pick_quote.is_banned` is re-checked on the pinned row, so a curator's "Ban this quote" click isn't undone by the next theme repaint; a banned, missing, or matched-text-mismatched pin falls through to a normal pick with a stderr warning. `--min-quality` is deliberately *not* re-applied — the row was already on the panel, and re-filtering it would swap the quote on a repaint, which is the bug the pin exists to prevent.
- Appends only after a successful render — never during quiet hours, never on failure, never when the dedup "quote unchanged" branch skips the redraw.
- Forwards `--history-path` / `--history-days` to `render_quote.py` via subprocess args so both processes agree on which ledger to consult.

**Ledger compaction.** `pick_quote.compact_history` drops entries older than `2 × --history-days` so a multi-year-running appliance doesn't linearly grow the file that every pick must stream through. The main loop calls `_maybe_compact_history` once per local-date rollover (gated by `state.last_compacted_date`) so we don't re-parse the ledger on every tick; `last_compacted_date` is set *before* the rewrite so a mid-compact crash doesn't re-trigger a retry storm the next tick. Rewrite routes through `atomic_io.atomic_write_text`, so a crash mid-compact leaves the original ledger intact. The `2×` slack means a short clock drift or an operator bumping `--history-days` up a day or two doesn't immediately evict rows that are about to be re-consulted. Malformed lines are preserved as-is (the compact pass is about bounded growth, not corruption repair — that's `load_recent_history`'s job).

### Rendering (`render_quote.py`)

Imports `pick_quote` in-process and lays out an 800×480 RGB PNG snapped to the six Spectra 6 inks (`snap_image_to_palette`). **Full reference — every theme's design notes, the font chains, and the colour-recipe table — lives in [`docs/themes.md`](docs/themes.md).** Read the relevant theme's entry there before touching its painter; most entries record approaches that were tried and rejected, and why.

**Core layout path (literary themes).** Three layouts in `LAYOUTS` (`hero` ≤90 chars, `standard` ≤170, `dense` otherwise). `fit_quote` shrinks the font in 2 pt steps until the wrapped lines fit; `fit_quote_balanced` wraps it and re-wraps on a narrower measure (then at up to 20% smaller sizes) when the last line would be a widow — one word, or under 30% of the measure — without adding a line or opening a half-empty middle line. Justification is decided per block by `justify_flags`: non-last lines ≥75% full are justified only if every one of them has ≥3 gaps and stretches each gap ≤0.45 em, otherwise the whole block is ragged; `_THEMES_RAGGED_RIGHT` (monospace, typewriter and handwriting faces) is always ragged. The hanging opening mark sits at a fixed x and may run under the first word on the standard and dense measures: a deliberate style choice, not a bug (a gutter-fitting mark was tried and reverted). The byline floors are 18 / 16 px. `resolve_display_match` + `tokenize_quote` + `wrap_styled_text` render the matched time phrase in bold + accent; wrapping breaks **only at whitespace** (no dangling `)` / `seven` split). `apply_theme_glyph_fallbacks` swaps characters a theme's face lacks for ASCII stand-ins. `--mode debug` (default) draws the `DEBUG MODE` banner + footer strip; `production` hides them. Output is written atomically to `output/current.png`. `_FONT_CACHE` memoises fonts (the bitmap fallback is deliberately not cached).

**Theme architecture.** `THEMES` (colours), `THEME_ORDER` (cycle order), `THEME_FONTS` (per-role candidate chains; variable fonts use `(path, "Instance")` tuples and **must** pin an instance — several defaults are Thin or Black). A theme is exactly one of: border-painted (`_BORDER_PAINTERS`; the `_CLEAR_RECT_PADS` themes are dispatched by name from `render` so the body knockout rect can be threaded through), a custom-render frame (`render_<theme>_frame`, registered in `_FRAME_RENDERERS` and listed in `CUSTOM_FRAME_THEMES` in `tests/test_theme_decoration.py`), or deliberately plain (`default`, `dark`). `diags` is a swatch panel, excluded from `--theme random`; `vinyl` is excluded from the button-B cycle.

**Adding a theme — checklist.**
1. `THEMES`, `THEME_ORDER`, `THEME_FONTS`, `display_inky.THEME_SATURATION` (`0.5` light ground, `0.7` dark / coloured / bloom-heavy), and `run_clock`'s `--theme` choices (a test pins the sync).
2. A border painter, or a `render_<theme>_frame` registered in `_FRAME_RENDERERS` plus a `CUSTOM_FRAME_THEMES` entry. Frame helpers are named `_<theme>_paint_*` (the decoration fence neuters them by name). Anything painted in the y=14-29 top-right band needs a `_DEBUG_LABEL_RIGHT_INSET` entry.
3. Golden fixture: `UPDATE_RENDER_GOLDEN=1 pytest tests/test_render_golden.py`. If the theme reads the wall clock, read it through `_now()` and add the theme to `CLOCK_DEPENDENT_THEMES`.
4. README row + preview (`python scripts/generate_theme_previews.py --theme NAME`), the README contact-sheet loop, and the spelled-out theme counts / rosters fenced by `tests/test_docs_theme_counts.py` and `tests/test_docs_theme_registry.py` (in README, `docs/CONTRIBUTING.md`, `docs/themes.md`, `docs/runtime.md`, `docs/web_ui.md`, `docs/testing.md`, `config.toml.defaults`).
5. A paragraph in `docs/themes.md` (theme + font), and a row in its colour table for any recipe you use.

**Conventions every theme follows** (each learned the hard way — details in `docs/themes.md`):
- **On-palette only.** Colours the panel lacks are synthesised by stippling two or three inks (`draw_text_dithered`, `_fill_swatch_stipple[_3way]`, or paint-a-sentinel-then-bbox-post-pass). Catalogue: `docs/spectra6_color_recipes.md`. Bias a mix toward the *less* luminous ink (5/8 R + 3/8 Y reads tangerine; 50/50 reads washed-out amber).
- **Judge on panel inks, not an RGB screenshot.** Calibrated inks: red ≈ `#62201E`, yellow ≈ `#C1BB1E`, blue ≈ `#233F8E`, green ≈ `#35563A`, black ≈ `#1F2226`, white ≈ `#B9C7C9`. Box-average to simulate 1–3 m viewing.
- **Dither pitfalls.** Two reads of the same Bayer tile are perfectly correlated — split one rank read into bands instead (`pride`, `bakelite`). Use `BAYER_8x8` for gradients. Jitter an ordered field over large areas (`position_noise` / seeded `randbytes`) or it lattices. Two periodic patterns beat. Lattices sampling the same pixels must have coprime periods.
- **Glow / relief / shading primitives:** `paint_neon_mask` (falling-density bloom, always pass `ground=` so later halos can't eat earlier cores; `glow_minor` for two-ink glows), `paint_relief_mask`, `paint_hatched_tone`, `paint_flow_strokes`, `paint_craquelure`, `shade_height_field`, `wrap_quote_into_masks`, `paint_mount_card`.
- **Shared small helpers — reuse, don't re-type** (issue #336 folded about fifty theme-prefixed copies into these): `_clock_hour12` (hour-only time surfaces), `_clock_hh_mm` (hour and minute; falls back to midnight on a malformed time, never raises), `_row_digest` (quote seeds), `_white_noise` / `_smooth_noise`, `_bayer_threshold_field`, `_lerp_stops`, `_halo_paste`, `_soft_ellipse_mask`, `_PANEL_INKS` + `_dither_calibrated` (Floyd–Steinberg in the measured ink space), `_shade_silhouette` / `_catmull_rom`, `_place_quote` + `_paint_placed` (fit, position and draw a ragged-right quote), `_fit_dotted_byline` / `_fit_from_title` / `draw_truncated_centred_byline` (bylines). A new `_<theme>_hour` or `_<theme>_seed` is a smell.
- **Committed raster plates** go through `dither_image_to_palette` / `_load_dithered_plate`, restricted to the theme's sub-palette, with a synthesised fallback when the asset is missing. Generators live in `scripts/generate_*_plate.py`.
- **Determinism.** Frames must be byte-identical across processes: never `hash()`; seed from `_row_digest` or a fixed seed. Don't read the wall clock unless listed in `CLOCK_DEPENDENT_THEMES`, and then only through `_now()`, the renderer's single clock seam (a golden-suite AST fence rejects any other `now()` / `today()` call). For a pure code move, `scripts/render_fingerprint.py` hashes every theme's frames, so a run on `main` and a run on the branch must match exactly. That is stricter than the golden suite's 0.1% tolerance.
- **Time surfaces.** The matched phrase carries the time. Never print HH:MM digits unless the object genuinely is a clock (`vhs` OSD). Hour-only carriers (Roman numerals, camera number, due stamp…) are pinned byte-identical across the minutes of an hour; otherwise `del time_str` at frame entry.
- **Fixed-geometry frames** compose at the canonical 800×480 and NEAREST-downsample for other sizes (`metro` convention; `TestFixedGeometryFramesDownscale`). Per-pixel writes must be bounds-clipped for `/api/preview` thumbnails.
- **Small text** in hairline serifs or two-ink stipples shreds after palette snapping — use a sturdier face or a solid ink for bylines and chrome.

### Runtime Loop (`run_clock.py`)

**Full reference: [`docs/runtime.md`](docs/runtime.md)**: config precedence, quiet hours and the sleep frame, auto/random themes, buttons, persisted state, telemetry and health gates, backoff, the watchdog, shutdown, and the per-module ownership / lock / thread tables. Read it before changing any `runtime_*` module.

**Tick.** Every `--interval-seconds` (60) the loop computes the fuzzy bucket. On a bucket or theme change it calls `peek_quote_id` in-process, skips the redraw if the `(source_id, line_number, display_quote, matched_text)` identity is unchanged, and otherwise spawns `render_quote.py` pinned to that exact row (`--pin-quote … --pin-matched-text …`) plus the optional `--display-script`. It appends to the anti-repeat ledger only after a successful render. `--once` renders one frame strictly; the loop logs and survives failures.

**Config.** `--config PATH` loads TOML whose keys mirror the argparse `dest` names; precedence is **CLI > config > argparse default** via `parser.set_defaults`. Malformed content fails open with a warning. A missing `--config` file, or a missing input path at pre-flight, exits **42** (`EXIT_CONFIG_ERROR`, paired with `RestartPreventExitStatus=42`). A new flag must be wired into `CONFIG_SCHEMA` (or `TRANSIENT_KEYS`), `config.toml.defaults`, and `config.toml.example`; four sync tests enforce it.

**Invariants worth knowing before editing:**
- **Every repaint pins the displayed quote** (`displayed_quote(state)`) and never re-peeks. A peek is history-filtered and would return a *different* row.
- **Quiet hours:** `render_quiet_frame` is the single "put the panel to sleep" path (honours `--quiet-image auto|<path>|""`, `--quiet-theme`), and the caller holds `render_lock`. `claim_quiet_edge` is the single edge detector, and whoever paints the frame claims the edge. A failed entry is retried through the backoff.
- **Theme resolution:** manual override (button B / web) wins until midnight. `auto` uses the day/night picks. `random` draws from a shuffled bag with a recent-window guard, once per displayed quote. `resolve_quiet_theme` is the source of truth for what is shown while asleep.
- **Identity triple** `(last_bucket, last_quote_id, last_effective_theme)` is committed after a successful render through `commit_render_result` and persisted, so a restart doesn't redraw. Transient modes (`card`) never commit. A few paths write fields directly on purpose: quiet exit, a failed shutdown and a pushed `--startup-image` clear `last_bucket` / `last_quote_id` so the next tick repaints, the main loop advances `last_bucket` when a peek finds the quote unchanged, and it seeds `last_effective_theme` on the first tick.
- **Three locks:** `render_lock` (coarse; buttons/web take it non-blocking via `_button_render_gate` and drop on busy), `state.lock` (fields; may nest inside `render_lock`), `ledger_lock` (history file; never nested). Never hold `state.lock` or `ledger_lock` across a subprocess.
- **All actions converge:** GPIO buttons and web POSTs both call `runtime_actions.action_*` → `_button_render_gate` → `_render_unlocked` → `commit_render_result`. There is no separate web path.
- **Lazy `import run_clock`** inside function bodies in `runtime_actions` / `runtime_quiet` / `runtime_theme` / `web_server`. It keeps the import graph acyclic and lets tests patch `run_clock.X`. The re-export block in `run_clock.py` exists for this.
- **Durability:** state, overrides, corpus and PNG writes all go through `atomic_io`, which stages through a unique temp file and reaps stale ones. A single-instance `fcntl` pidfile guards the loop.
- **Supervision:** subprocesses run under timeouts (render 45 s, display 60 s). Failures back off exponentially. Heartbeats are telemetry entries stamped with quiet state, and systemd `WATCHDOG=1` is pinged at every subprocess boundary as well as from the heartbeat. SIGTERM drains the in-flight render.
- **Telemetry:** date-rotated JSONL sibling files, fsync'd except heartbeats, pruned after `--telemetry-retain-days`. `idle-hours health` summarises it, and its render-age gates stand down while quiet hours are active.

**Buttons** (A/B/C/D on GPIO 5/6/16/24; long press = 2 s): A skip / long-press un-skip · B cycle theme · C 5 s source card · D sleep-or-wake toggle / long-press shutdown. The full table, including the cycle chain, is in `docs/runtime.md`.

### Contact Sheet (`contact_sheet.py`)

Offline QA tool. For each of the 144 `h{1..12}_{state}` buckets, calls `pick_quote.select_quote` at the bucket's canonical `HH:MM` (e.g. `h3_twenty_past` → `03:20`; `h12_*` maps to `00:MM`), renders the full 800×480 frame via `render_quote.render`, and downscales it into a tile on a 12×12 grid. Each tile gets a small `HH:MM  h{hour}_{state}` caption below so you can locate specific buckets at a glance. Flags: `--tile-width`/`--tile-height` (defaults 200×120), `--caption-height` (18), `--margin` (6), `--theme`, `--overrides` (defaults to the bundled sidecar; point it at an appliance's relocated copy), and `--mode` — defaults to `production` so the debug footer doesn't dominate small tiles. History filtering is forced off (snapshot of the whole corpus, not anti-repeated picks). Use this to spot regressions after a corpus change: layout bugs, malformed `matched_text`, repeat authors in adjacent buckets, or fallback-bucket frames that look visually wrong.

### Inky Display Bridge (`display_inky.py`)

Minimal Pillow → Pimoroni `inky.auto` bridge. Loads the PNG, resizes to the panel's native size if needed, and calls `inky.set_image(..., saturation=...).show()`. Designed to be called once per render from `run_clock.py`. Only needed on the Pi. Up to `MAX_ATTEMPTS` (3) calls are retried with `RETRY_BACKOFF_SECONDS = (1, 4)` between attempts so a momentary I/O hiccup doesn't crash the caller; if all attempts fail the script raises `SystemExit` so the loop in `run_clock.py` logs and moves on.

**Per-theme saturation.** `THEME_SATURATION` gives every registered theme one of two values. A light page ground takes `0.5`, which keeps accents from blowing out on white. A dark or coloured ground, or one dominated by falling-density blooms, takes `0.7`, which stops accents going muddy against it. The four themes that break that rule carry a one-line reason in the table, and `test_tier_follows_page_ground_except_listed_themes` keeps the rule and the list honest. The values are starting points, not panel measurements. `test_every_render_theme_has_saturation` fails if a new `THEMES` entry has no row. `run_clock.render_now` forwards `--theme` to `display_inky.py`, which calls `resolve_saturation(theme, override)`; an explicit `--saturation` always wins.

### Curator Web UI (`web_server.py`, `idle_hours/web/`)

**Full reference: [`docs/web_ui.md`](docs/web_ui.md)**: every endpoint, the security model, the connection limits, bake/ban/overrides semantics, and the UI layout.

Off by default. `--web-bind HOST:PORT` starts a `ThreadingHTTPServer` on a daemon thread **inside `run_clock`**, sharing `RuntimeState` and its locks. In-process is non-negotiable, because mutating POSTs go through the same `_button_render_gate` as the buttons. A startup failure is logged, not fatal. Static UI is plain HTML/JS/CSS with no build step.

**Security model.** Loopback binds skip auth. Any other bind **requires** `--web-token` / `--web-token-file` (hot-reloaded on mtime). A configured token gates every POST, every JSON GET, `/current.png` and `/api/preview`, via the `X-Idle-Hours-Token` header only. Only the static shell (and `/metrics` unless `--web-metrics-token`) stays open. On every bind, independent of the token: POSTs require `Content-Type: application/json` (415), `Origin` must match `Host` (403), and `Host` must be allowed for the bind (403, the DNS-rebinding guard; extend with `--web-allowed-host`). Unknown routes 404 before the auth check.

**Curation.** `/api/bucket` and `/api/search` read the **raw** corpus on purpose, so an operator can see rows the baker dropped. `POST /api/overrides` honours `If-Match` ETags (412 on a stale save). `POST /api/overrides/ban` does the ban read-modify-write server-side. `POST /api/bake` re-applies content overrides, writes the patched raw corpus back, and bakes in-process (409 if a render is in flight). Coverage and gaps are computed live using the baker's displayability gates.

### Appliance / Pi Setup

- **Fresh Pi:** `scripts/bootstrap_pi_inky.sh` runs from a checkout. First pass: installs the apt runtime deps plus Raspberry Pi OS's `python3-lgpio` / `python3-rpi-lgpio` GPIO backend, enables I2C + SPI, and stages `dtoverlay=spi0-0cs` in the boot config, then stops for the reboot. The Spectra 6 (E673) driver opens `/dev/spidev0.0` for data but drives GPIO8 chip-select itself, and the ordinary SPI overlay claims GPIO8 in the kernel — `spi0-0cs` exposes the bus with no kernel-owned chip selects. Second pass (`CONTINUE_AFTER_REBOOT=1`): verifies `/dev/spidev0.0` exists and GPIO8 is unclaimed, creates `~/.virtualenvs/pimoroni` with `--system-site-packages` (so the venv sees the distro's `lgpio` / `RPi.GPIO` — `gpiozero` on its own ships no pin backend, and the PyPI `rpi-lgpio` needs native build tools on Trixie / Python 3.13), installs `.[pi]`, renders once and pushes once. `tests/test_pi_deployment_contract.py` pins those contracts as string fences on the script, the unit and the appliance config.
- **Manual Pi notes:** `docs/pi_setup_inky_impression.md` is the long-form guide (hardware list, OS baseline, SPI / GPIO backend configuration, troubleshooting, the `~/.idle-hours` → `/var/lib/idle-hours` migration).
- **Boot-time service:** `ops/idle-hours.service.example` runs `python -m idle_hours.run_clock --config %S/idle-hours/config.toml` as `pi` under the `~/.virtualenvs/pimoroni` Python. Both `WorkingDirectory=` and `Environment=LG_WD=` are `/var/lib/idle-hours` and must stay equal: `lgpio` creates its `.lgd-nfy*` button-notification FIFO in `LG_WD` while its Python wrapper opens that FIFO relative to CWD, and the state directory is the one path writable under the sandbox without a `ReadWritePaths` hole into `$HOME`. The appliance preset writes `output` there as well, which is what let the old `/home/pi/IdleHours/output` carve-out go. Only `User=` and the `ExecStart=` interpreter path are install-specific.
- **Container (v2):** `Dockerfile` is a multi-stage OCI build — stage 1 produces wheels, stage 2 installs them into a Python 3.12-slim runtime as a non-root `idlehours` user. ARM64-first for Pi appliance use, multi-arch via `docker buildx build --platform linux/arm64,linux/amd64 -t idle-hours:2.6 .`. The Pi-only `[pi]` extra (`gpiozero` / `inky`) is **not** installed by default — that's a Pi-runtime concern. The base image renders PNGs and serves the curator UI without GPIO bindings. Run with `docker run --rm -p 8080:8080 -v idle-hours-state:/state idle-hours:2.6 idle-hours run --buttons-off --skip-preflight --web-bind 0.0.0.0:8080 --state-path /state/state.json --history-path /state/history.jsonl --telemetry-path /state/telemetry.jsonl --pidfile /state/run_clock.pid` for a headless dev instance. `.dockerignore` keeps `data/` (cached Gutenberg downloads), `output/`, `.git/`, and `tests/golden/` out of the build context so `buildx` doesn't ship multi-GB caches.

### Release Tooling

`scripts/release.py` implements a two-phase, non-publishing release flow. From
a clean `main` exactly matching `origin/main`, `prepare X.Y.Z` validates a
strictly increasing canonical version, rejects an existing `vX.Y.Z` tag,
creates `release/vX.Y.Z`, promotes the bullet entries under
`CHANGELOG.md`'s Unreleased heading, updates `pyproject.toml`, runs the
non-golden suite, builds a wheel and verifies its embedded name/version, then
commits. `--push` pushes the branch; `--open-pr` also opens the PR with `gh`.
After merge, `finalize X.Y.Z` repeats the clean/current-main, changelog, tag,
build and wheel-metadata checks before creating an annotated `vX.Y.Z` tag.
It never publishes a package or creates a GitHub Release. It does not push the
tag unless `--push` is explicit, and interactive confirmation is required
unless automation also passes `--yes`. The tag CI job remains an independent
server-side check of the same tag/package invariant.

### Testing

**Full reference: [`docs/testing.md`](docs/testing.md)**: suite layout, golden fixtures, the decoration and docs fences, the JS suite, packaging tests, pyproject settings, and the CI job matrix.

- One `tests/test_<module>.py` per module, class-based. `tests/conftest.py` isolates `$HOME` per test and unsets `IDLE_HOURS_PHOTO_PATH`.
- **Golden renders:** `tests/golden/renderer/*.png`, one per theme plus layout/mode scenarios, compared at ≤0.1% differing pixels. Regenerate with `UPDATE_RENDER_GOLDEN=1 pytest tests/test_render_golden.py`. README previews must stay current: `scripts/generate_theme_previews.py --check` runs in CI.
- **Structural fences** fail on *absence*, not just on change: `test_theme_decoration.py` (each painter/frame must actually paint), `test_docs_theme_counts.py` / `test_docs_theme_registry.py` (doc counts and rosters vs. the registries; a regex that matches nothing fails loudly), `test_ci_required_checks.py` (every CI job is required or explicitly advisory), `test_packaging.py` (wheel contents, no hardware imports).
- **Pixel assertions** use `tests/pixel_helpers.py` (`distinct_inks`, `ink_counts`, `pixel_bytes`), never `Image.getdata()`. Pillow removal notices are errors via `filterwarnings`.
- **Curator JS:** `node --test tests/js/*.test.mjs` loads the real `web/main.js` in a `node:vm` sandbox. The pytest bridge skips without node, so CI runs it directly.
- **CI** (`.github/workflows/ci.yml`): `lint`, `test (3.11)`, `test (3.12)`, `golden-render`, `web-ui-js`, `package-build` are required (`.github/rulesets/main-branch.json`). `coverage` (95% branch floor) and the tag-only `release-version` are advisory.

### Repo Layout

All Python modules and bundled runtime assets live under a single
`idle_hours/` package. The wheel ships the package directly via
`[tool.setuptools.packages.find]` + `[tool.setuptools.package-data]`, so
`pip install idle-hours` produces a working appliance — no separate
asset bundle needed. Runtime artefacts (`output/`, `data/`) and the
auxiliary trees (`scripts/`, `docs/`, `ops/`, `tests/`) stay at the repo
root.

```
idle_hours/                             single-package home for every Python module + bundled runtime asset
├─ __init__.py                          empty package marker (no re-exports — keeps run_clock ↔ runtime_* lazy-import contract clean)
├─ idle_hours_cli.py                    v2 — unified `idle-hours <subcommand>` entry point; lazy-imports each backing module's main() and rewrites sys.argv so existing parse_args() calls still work. pyproject.toml [project.scripts] registers it as the `idle-hours` console script.
├─ buckets.py                           shared bucket primitives (BUCKET_ORDER, minute_bucket, bucket_for_time, neighbor_buckets)
├─ atomic_io.py                         shared atomic-write primitives (text/bytes/lines) — unique tmp-sibling → fsync → os.replace → dir-fsync; durability for every appliance file the next tick reads
├─ jsonl_io.py                          streaming JSONL reader that logs + skips malformed lines
├─ gutenberg_time_miner.py              harvest regex-matched time phrases from .txt
├─ merge_candidates.py                  dedupe harvested JSONL rows
├─ bucket_coverage.py                   coverage report per (hour, minute-state) bucket
├─ target_sparse_buckets.py             targeted regex sweep for empty buckets
├─ import_targeted_hits.py              reshape targeted hits for merge
├─ clean_display_quotes.py              pick a displayable excerpt from each row (expands bare single-sentence hits with up to 2 neighbouring sentences, rejects mid-text chapter headings, keeps paired edge quotation marks and prefers a run whose quotes balance — issue #297, splits on sentence boundaries with two abbreviation classes — TITLE_ABBREVIATIONS "Mr./Mrs./Dr./St./J." always merged, SENTENCE_OK_ABBREVIATIONS "etc./p.m./U.S.A." only merged when the next fragment starts lowercase)
├─ quality_filter.py                    score + flag rows
├─ fix_substring_time_matches.py        LEGACY migration tool — repair substring-collision time tags in pre-fix JSONL
├─ fix_legacy_buckets.py                LEGACY migration tool — repair pre-buckets.py legacy 8-state names + matched_text whitespace
├─ enrich_metadata.py                   attach author/title from Gutenberg headers
├─ apply_content_overrides.py           layer assets/content_overrides.json onto candidates-attributed.jsonl
├─ bake_quote_database.py               final pipeline stage — bake the display-ready runtime DB (pre-scored, per-bucket sorted; pick_quote reads by default)
├─ pick_quote.py                        rank candidates, honor overrides, fall back to neighbors (exposes select_quote(); baked DB by default with raw-corpus fallback)
├─ render_quote.py                      Pillow layout → 800×480 Spectra-6 PNG (imports pick_quote in-process; also hosts dither_image_to_palette — render-time Floyd–Steinberg / ordered / Atkinson dithering of committed raster art to the inks, used by the anna_atkins cyanotype, grimdark gunmetal, letter aged-paper, daguerreotype silver, autochrome colour and control concrete plates; biomech instead dithers two *render-time* paintings — a lit height field to K+W and a dusk to K/R/Y/W — through the same FS path, and hosts `shade_height_field`, the Blinn-Phong height-field renderer)
├─ contact_sheet.py                     12×12 grid of all 144 bucket frames, for offline QA
├─ run_clock.py                         runtime loop (bucket-change-triggered, error-tolerant, quiet-hours-aware, button + auto-theme + telemetry; atomic state writes, date-rotated telemetry with retention sweep, SIGTERM/SIGINT graceful shutdown, button liveness check). Thin orchestrator — delegates state/telemetry/theme/quiet/action helpers to the runtime_* siblings below and re-exports them so existing `run_clock.X` imports and test patches keep resolving.
├─ runtime_log.py                       shared timestamped stderr/stdout logger (_log)
├─ path_resolution.py                   resolve_input_path() — CWD-relative-then-bundled fallback for operator-supplied input paths (--render-script / --display-script / --quiet-image / --startup-image / --photo-path). Outputs stay CWD-only since BASE_DIR now points inside site-packages. Also owns PHOTO_PATH_ENV, the `photo` theme's source variable — named here rather than in render_quote so run_clock can export it without importing Pillow (the reason theme_names exists).
├─ runtime_config.py                    TOML config-file loader (--config PATH on run_clock and idle_hours_health); also owns validate_hhmm, the single HH:MM rule run_clock's argparse type= wraps. Fail-open on malformed content; fails fast only on a typoed --config path. Keys mirror argparse dest names 1:1.
├─ runtime_state.py                     RuntimeState class — locks, mutable shared state between the loop, button listener, and web server
├─ theme_names.py                       PIL-free shim exposing `known_theme_names()` + `theme_cycle()` — three runtime modules and web_server need theme-name lists for state validation, manual-override gating, and dropdown ordering, all without dragging Pillow into their import graph; centralised here to kill the prior near-duplicate lazy-import blocks (which had drifted between `frozenset` and `tuple` return types)
├─ runtime_store.py                     persisted runtime state JSON (manual_theme / manual_quiet + render-identity triple) loaded + validated at startup and saved atomically via atomic_io
├─ pidfile.py                           single-instance fcntl.flock pidfile for run_clock.main (stale-pid reclaim, --pidfile opt-out)
├─ sd_notify.py                         pure-stdlib systemd sd_notify client (READY=1 at startup, WATCHDOG=1 from heartbeat); no-op when $NOTIFY_SOCKET is unset
├─ runtime_telemetry.py                 date-rotated JSONL telemetry sidecar (append_telemetry, append_heartbeat, daily_telemetry_path, prune_telemetry; v2 fans out alert-worthy entries to runtime_webhook)
├─ runtime_webhook.py                   v2 — fire-and-forget HTTP webhook for alert-worthy telemetry (errors, backoff, timeouts, button-died). configure() at startup; daemon-thread POST per event; bounded urllib timeout; never raises
├─ runtime_theme.py                     theme resolution — auto-dark window, manual override, midnight reset, random-pick shuffle bag + recent-window
├─ runtime_quiet.py                     in_quiet_hours + _display_quiet_image + render_quiet_frame + compute_quiet/enter_quiet/exit_quiet state machine. render_quiet_frame is the one three-way --quiet-image dispatch, shared by the main loop's rising edge (via enter_quiet), runtime_actions.action_quiet's manual toggle, action_theme's asleep-repaint, and the button-D shutdown preamble; --startup-image still reuses _display_quiet_image directly for its static-path branch.
├─ runtime_actions.py                   action_skip/unskip/theme/quiet/rerender + _button_render_gate — shared by GPIO buttons and the web UI; each action does a lazy `import run_clock` internally so tests that patch `run_clock.X` affect the call path (same pattern web_server.py uses)
├─ display_inky.py                      Pi-only image → Inky Impression bridge (retry with backoff, per-theme saturation)
├─ inky_buttons.py                      Pi-only gpiozero button listener (A/B/C/D → run_clock handlers, press_logger + buttons_alive supervision)
├─ probe_buttons.py                     Pi-only GPIO press probe — confirms which pin each physical button actually fires
├─ idle_hours_health.py                 telemetry summariser (render count, p50/p95 latency, last error; reads date-rotated sidecar)
├─ web_server.py                        optional curator HTTP UI (off by default, --web-bind to enable; shares render_lock with button handlers; v2 adds /metrics + /api/setup + /api/preview + /api/search + /api/gaps + /api/bake + /api/content-overrides)
├─ web/                                 vanilla HTML/JS/CSS served by web_server (index.html, main.js, style.css — no build step; mobile-first, four-tab layout: Now / Curate / Coverage / Activity). Ships as package-data.
├─ fonts/                               bundled display faces (ship as package-data so the wheel renders without external font installs). Includes Playfair Display (default/dark), inter/ (swiss), bitter/ (scholar), im-fell-english/ (alchemy + grimoire body + herbarium + cartograph italic), old-standard-tt/ (newsprint + beksinski), space-mono/ (nightvision + vinyl catalog + circuit), archivo/ (blueprint), eb-garamond/ + unifraktur/ (illuminated/gothic + tarot/vitrail body; unifraktur also = grimdark gold quote-mark ornament), cormorant-garamond/ + berkshire-swash/ (mucha + astrarium + vinyl), jost/ (bauhaus), rubik/ (risograph), bangers/ (comic), special-elite/ (dispatch), atomic-age/ (atomic), permanent-marker/ (marker), rye/ (saloon), cinzel-decorative/ (roman + tarot chrome + grimdark body + the expedition wordmark), medieval-sharp/ (alchemy ornament) + eagle-lake/ (grimoire matched phrase), righteous/ (deco), iceland/ (glacier), playwrite-gb-j-guides/ (chalkboard), patrick-hand-sc/ (placard), shojumaru/ (chanbara), antonio/ (lcars + marquee/vinyl/outrun chrome), oxanium/ (outrun body), bungee-shade/ (fillmore + marquee feature-title), cardo/ (firmament + marquee body + vinyl catalog bar), yuji-boku/ (kanagawa), uncial-antiqua/ (vitrail rose-window numeral + attribution), press-start-2p/ (questline — chunky 8-bit fixed-grid pixel face), pixelify-sans/ (chrono — clean proportional multi-weight 16-bit pixel sans), silkscreen/ (sampler — crisp low-res fixed-grid pixel face, Regular + Bold, stitch-mapped into cross-stitch cells), dancing-script/ (letter + escritoire body + matched phrase — fluid pen-script, variable weight), pinyon-script/ (letter ornament + anna_atkins handwritten Latin labels / quote-mark ornament — formal copperplate), libre-caslon-text/ (anna_atkins body + matched phrase — Caslon revival, variable weight), alegreya/ (lieder — literary-text serif; Regular lyrics, Bold matched phrase, Italic editorial marks), noto-music/ (lieder — the Unicode Musical Symbols *symbol* face supplying the G clef, noteheads and the tempo mark's quarter note; not a text face), quicksand/ (izakaya — rounded monoline geometric sans, the nearest open type gets to a bent glass tube), jost/ is also shared by pride (Futura-adjacent geometric sans, the register of 1970s poster and protest printing) and by bakelite (its near-monoline strokes are what bloom evenly under `paint_neon_mask`; a high-contrast face haloes unevenly and stops reading as a lit tube), alfa-slab-one/ (pulp — heavy mid-century advertising slab; the misregistration effect needs a fat face or the off-register fringe eats the letterform), space-mono/ is also shared by synoptic (instrument-printout register for the weather chart), lato/ (abyssal — humanist sans, sturdy enough to hold as white text over a dark gradient), antonio/ is also shared by vhs (first outing as a body face — a condensed cell is what lets the chroma ghosts clear the stem), special-elite/ + space-mono/ are shared by cardcatalog (typed card body + metal-type-wheel call number and date stamps), old-standard-tt/ + cinzel-decorative/ + pinyon-script/ + space-mono/ are shared by intaglio (engraved-currency Didone legend + masthead/denomination capitals + script promise line + serial/microprint), cormorant-garamond/ is also shared by nocturne (Medium instance for the body — enough stem weight to survive its faint halo), cinzel-decorative/ is also shared by plaque (one weight up — Bold body / Black phrase — so the relief faces have stroke mass), libre-caslon-text/ is also shared by daguerreotype (the caption slip; the two photographic themes share the Caslon on purpose), almendra/ (carcosa — Regular + Bold body, Almendra Display quote marks), titillium-web/ (trisolaris — technical humanist sans; Regular body, SemiBold matched phrase, Italic attribution), oswald/ (control's fallback only, since Game Font Library and Fonts In Use put the game's title cards in ITC Avant Garde Gothic Bold and its UI in an Akzidenz-Grotesk cut — control now sets the body and phrase in jost/ pinned Bold and the sign chrome in archivo/), jura/ (culture + orbital — static Medium / SemiBold / Bold humanist technical sans), share-tech-mono/ (culture + orbital — signal header and caption mono), fondamento/ (codex — calligraphic chancery book hand; Regular body, Italic matched phrase and byline), spectral/ + grenze-gotisch/ (biomech plate label + the whole of bosch's banderole — thorned blackletter-hybrid, variable weight pinned by name), barlow-condensed/ (semiotic — DIN-descended condensed grotesque, static Medium / SemiBold / Bold; also witcher's entry title, body and matched phrase, the nearest open face to the game's PF DIN Text Condensed), archivo-narrow/ (witcher — the narrow cut of Archivo, variable on weight and pinned by instance, the nearest open face to Bell Gothic Bold; every label and the WILD HUNT mark), michroma/ (atropos — wide, squared Eurostile-descended display sans, the nearest open face to Returnal's Kellion; one static Regular for the HUD chrome), saira/ (atropos + saros — a squared technical grotesque, variable on weight and width with a Thin default so every candidate pins an instance; the nearest open face to the commercial body faces of both games, Returnal's Erbaum and Saros's Tamba Sans; Regular body, SemiBold phrase, Medium / Italic bylines), orbitron/ (saros — squared geometric display sans pinned Bold for the wordmark, the nearest open face to Arame), michroma/ is also shared by saros (status chrome, the Korataki stand-in), by hitchhiker (every register — the square-shouldered monoline of the 1981 Guide's hand-lettered screens), by hal (the Discovery monitors' mnemonics, nameplate and tile labels — the open Microgramma the film's screens set their capitals in) and by lumon (the Lumon wordmark, for Manifold Extended CF); jost/ is also shared by hal (the body and byline — the open Futura of the film's signage) and dsky (every legend on the unit — NASA's panels were silkscreened in Futura Demi); special-elite/ is also shared by dsky (the quote typed on the flight-plan card); exo-2/ is also shared by oblivion (Light body, Medium phrase, Regular chrome — the open face in the family of Blender, the film's UI face); eb-garamond/ is also shared by yorha (the closest open face to Automata's unidentified classical UI serif); inter/ is also shared by lumon (the file name, completion and byline, for the show's Forma DJR); montserrat/ (lumon — the open Gotham, for the MDR terminal's number grid and the body; one variable roman file, default instance Regular, every candidate pinned); ibm-plex-mono/ is shared by observation only, exo-2/ (saros — the earlier body face, now the fallback behind Saira; a variable techno-humanist sans whose default instance is Thin), ibm-plex-mono/ (observation — static Medium / SemiBold / Bold, S.A.M.'s terminal face), libre-franklin/ (furies — Franklin Gothic revival for the wall text; variable, plus a separate italic file), fraunces/ (betweenus + betweenus_dark — the Between Us web app's soft variable serif; its default axis instance is Black, so every candidate pins a named instance), inter/ is also shared by betweenus + betweenus_dark (pill + legend chrome, the app's UI sans), im-fell-double-pica/ (expedition — the Fell type Clair Obscur: Expedition 33 sets its UI text in; roman body, italic matched phrase, no bold exists), bebas-neue/ (expedition — the condensed caps the same game sets its UI numbers in; the painted hour, brushed rough, and every label). caesar-dressing/ (hades — Open Window's brushed Greek-inscription display face, the one *Hades II* sets its title cards and god names in; the author as the boon's name and the wordmark), spectral-sc/ (hades — the small-caps cut of Spectral, the game's codex serif, for the book's title at the foot; spectral/ itself sets the body and the matched phrase), hammersmith-one/ (hades — Sorkin Type's open Johnston, the nearest open face to the game's P22 Underground, for the chrome labels), lato/ is also shared by hades (the game's secondary face, for the rarity label), barlow/ (expanse — Jeremy Tribby's DIN-descended grotesque at text width, the nearest open face to the modified DIN Pro *The Expanse* sets the Rocinante's screens in; Regular body, SemiBold matched phrase, Bold sender; barlow-condensed/ takes the labels and share-tech-mono/ the readouts and command line), libre-baskerville/ (goya — Benton's ATF Baskerville redrawn for screen with less contrast, two variable files pinned by instance; the register of Madrid's Imprenta Real in the Black Paintings' decade, and sturdy enough to hold on a dithered ochre). Each subdir ships its own license file (OFL.txt for OFL-licensed faces, LICENSE.txt for the Apache-licensed Special Elite + Permanent Marker).
└─ assets/                              corpus + sidecars + bundled images (ship as package-data)
   ├─ quote_database.jsonl              baked display-ready database — canonical runtime input that pick_quote / run_clock / render_quote read by default; regenerate via bake_quote_database whenever the raw corpus changes
   ├─ candidates-attributed.jsonl       raw attributed corpus — source-of-truth input to bake_quote_database; also served as the curator UI's /api/bucket view and used as pick_quote's defensive fallback if the baked DB is missing
   ├─ bucket-coverage.md                committed snapshot of the current corpus's bucket coverage
   ├─ bucket-coverage.json              machine-readable companion to bucket-coverage.md
   ├─ contact-sheet.png                 12×12 visual snapshot of every bucket's current pick (regenerate via contact_sheet)
   ├─ selection_overrides.json          manual bans/boosts/per-bucket preferences (pick_quote default --overrides)
   ├─ content_overrides.json            per-row content fixes (apply_content_overrides default --overrides)
   ├─ goodnight.png                     static dark-theme sleep frame — pixel-for-pixel what render_sleep_frame produces for theme="dark". No longer the --quiet-image default (that is now "auto"), but still shipped and still selectable by path; kept as the escape hatch for a custom image.
   ├─ anna_atkins_cyanotype.png         committed continuous-tone cyanotype photogram for the anna_atkins theme; Floyd–Steinberg-dithered to the inks at render time by render_quote.dither_image_to_palette (regenerate via scripts/generate_anna_atkins_plate.py)
   ├─ grimdark_gunmetal.png             committed continuous-tone weathered-metal plate for the grimdark theme Layer 0; dithered to white+black at render time (regenerate via scripts/generate_grimdark_plate.py)
   ├─ letter_aged_paper.png             committed continuous-tone aged-paper plate for the letter theme Layer 0; dithered to white/yellow/red/green at render time (regenerate via scripts/generate_letter_plate.py)
   ├─ control_concrete.png              committed continuous-tone board-formed concrete plate for the control theme's plinth (800×88); dithered to white+black at render time (regenerate via scripts/generate_control_plate.py)
   ├─ autochrome_garden.png             committed continuous-tone colour photograph for the autochrome theme; the only plate dithered against the FULL six-ink palette (regenerate via scripts/generate_autochrome_plate.py)
   ├─ tarot_plates.png                  3x4 sprite sheet of separated Marseille trumps (220x290 per hour) — the tarot theme's illustration panel; NOT dithered at render time (regenerate via scripts/ingest_tarot_plates.py)
   ├─ semiotic_signs.png                6x6 sprite sheet of Ron Cobb's Semiotic Standard signs (250x262 each, legend order) from LouH's CC BY 4.0 vector set — the semiotic theme's signs, classified onto the inks at render time (regenerate via scripts/ingest_semiotic_signs.py)
   ├─ semiotic/README.md                CC BY 4.0 attribution + changes made for semiotic_signs.png (ships with the sheet)
   ├─ tarot/dodal/                      source scans for the above: Jean Dodal Tarot de Marseille trumps I-XII (Lyon, 1701-1715, public domain) + a README recording provenance. Build-time input only — the runtime reads tarot_plates.png.
   ├─ config.toml.example               annotated example config for `idle-hours run --config` — appliance-oriented preset (production mode, auto theme, /var/lib paths, systemctl-poweroff)
   ├─ config.toml.defaults              faithful dump of every argparse default. Copying verbatim is a no-op vs. no --config; diffable reference for deployments pinned to explicit values
   ├─ preview.png                       README hero image
   └─ previews/                         per-theme preview thumbnails surfaced in the README theme table
                                        (regenerate via scripts/generate_theme_previews.py; never by hand)

scripts/                                bash drivers + the curated ID lists they consume (not part of the wheel)
├─ bootstrap_pi_inky.sh                 first-time Pi setup helper
├─ release.py                           guarded prepare/finalize release helper (version + changelog + wheel metadata + annotated tag; never publishes)
├─ run_batch2.sh                        bulk harvest driver (now invokes `python3 -m idle_hours.gutenberg_time_miner`)
├─ run_dawn_expansion.sh                one-shot "mine curated IDs → pipeline → merge into live corpus" driver
├─ gutenberg_batch_ids.txt              batch list of Gutenberg IDs for run_batch2.sh
├─ gutenberg_dawn_expansion_ids.txt     curated clock-precise Gutenberg ID list for run_dawn_expansion.sh
├─ generate_anna_atkins_plate.py        one-time art generator for assets/anna_atkins_cyanotype.png (the continuous-tone plate the anna_atkins theme dithers at render time); deterministic (seeded)
├─ generate_grimdark_plate.py           one-time art generator for assets/grimdark_gunmetal.png (the continuous-tone weathered-metal plate the grimdark theme dithers at render time); deterministic (seeded)
├─ generate_letter_plate.py             one-time art generator for assets/letter_aged_paper.png (the continuous-tone aged-paper plate the letter theme dithers at render time); deterministic (seeded)
├─ generate_control_plate.py            one-time art generator for assets/control_concrete.png (the board-formed concrete plate the control theme's plinth dithers at render time); deterministic (seeded)
├─ generate_autochrome_plate.py         one-time art generator for assets/autochrome_garden.png (the continuous-tone colour photograph the autochrome theme dithers against all six inks); deterministic (seeded)
├─ render_fingerprint.py               sha256 of every theme's frames (3 quote lengths × 2 times × 2 modes + thumbnail + sleep frame) with the clock pinned. --output on main, --compare on a branch: a pure refactor must be byte-identical (issue #335)
├─ generate_theme_previews.py           regenerates idle_hours/assets/previews/*.png — the README theme table's
│                                      thumbnails. Every preview is one pinned passage at one pinned time
│                                      (H. G. Wells, The Time Machine, at 10:00), so the table compares palette
│                                      and typography and nothing else. --check reports drift without writing
│                                      (CI runs it in the golden-render job); --theme NAME regenerates one;
│                                      --all rewrites the set and is deliberately opt-in.
├─ ingest_semiotic_signs.py            builds assets/semiotic_signs.png from LouH's Semiotic Standard PNGs at a pinned commit (or --source DIR); downscale + pack only, the colour mapping happens at render time
└─ ingest_tarot_plates.py               separates the Dodal card scans in assets/tarot/dodal/ into assets/tarot_plates.png (crop numeral/title bands + frame, local-threshold line detection, 3-ink separation). Prints a per-card ink histogram and can write a --contact sheet for eyeballing the crops.

docs/                                   long-form documentation
├─ pi_setup_inky_impression.md          long-form Pi setup doc
├─ spectra6_color_recipes.md            full Spectra 6 colour-synthesis recipe catalogue (referenced from CLAUDE.md's themes section)
├─ CODE_OF_CONDUCT.md                   Contributor Covenant v2.1
├─ CONTRIBUTING.md                      dev environment, pipeline overview, test conventions
├─ SECURITY.md                          vulnerability reporting policy
└─ UPGRADE.md                           one-time LitClock → Idle Hours migration steps

ops/idle-hours.service.example          sample systemd unit (Type=notify + WatchdogSec + StateDirectory + sandbox; copy into /etc/systemd/system/)

tests/                                  pytest suite — one module per backing module + conftest.py; pixel_helpers.py holds the Pillow-version-agnostic image assertions (distinct_inks / ink_counts / pixel_bytes); tests/golden/renderer/*.png are committed PNG fixtures for the golden-image suite (regenerate with UPDATE_RENDER_GOLDEN=1)
└─ js/                                  curator-UI JavaScript suite (node --test); harness.mjs loads the real web/main.js into a node:vm sandbox with a DOM stub. Bridged into pytest by tests/test_web_ui_js.py and run directly by the web-ui-js CI job.
output/                                 runtime render target (output/current.png); gitignored except .gitkeep. Resolved against CWD, not BASE_DIR — so renders land next to the working tree, not inside the installed package.
data/gutenberg/                         cached Gutenberg text downloads (gitignored)

CLAUDE.md                               this file
README.md                               user-facing overview + quick start
LICENSE                                 MIT
Dockerfile                              v2 multi-stage OCI image (Python 3.12-slim base, builder produces wheels, runtime installs them as a non-root user). ARM64-first for Pi appliance use; multi-arch via `docker buildx build --platform linux/arm64,linux/amd64`. The wheel ships fonts/assets/web as package-data, so no separate COPY of the static trees is needed in the runtime image.
.dockerignore                           excludes data/, output/, .git/, tests/golden/ and pycache from the build context so `docker buildx build` doesn't ship multi-GB caches
pyproject.toml                          project metadata + pytest / coverage / ruff configuration; `[tool.setuptools.packages.find]` + `[tool.setuptools.package-data]` are the source of truth for what the wheel carries
.github/workflows/ci.yml                GitHub Actions CI (lint + test, Python 3.11 & 3.12; golden-render and package-build jobs verify the wheel ships package-data correctly)
.github/rulesets/main-branch.json       source of truth for main's branch protection — the required-status-check list every CI job that runs on a PR must appear in (tests/test_ci_required_checks.py fences it). Not applied automatically; see .github/rulesets/README.md for the `gh api` sync command.
```
