# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

LitClock is an end-to-end literary-clock system: it harvests time-related quotes from Project Gutenberg, scores and cleans them, then picks and renders a quote for any clock time. The render is designed for a Pimoroni Inky Impression 7.3 Spectra 6 eInk panel (800×480, 6-color palette) but writes a plain PNG first, so it runs fine on any machine.

Every stage is a standalone Python 3 CLI script that reads/writes JSONL. The mining/selection pipeline is stdlib-only; `render_quote.py` pulls in Pillow, and `display_inky.py` additionally needs the Pimoroni `inky` package (Pi only).

## Common Commands

### Unified `litclock` CLI (v2)

```bash
# After `pip install -e .`, every script in the repo is reachable through
# one umbrella command:
litclock --help                          # list every subcommand
litclock run --display-script display_inky.py
litclock render --time 14:30
litclock pick --time 14:30
litclock health --hours 24 --json
litclock bake
litclock contact-sheet --output output/contact-sheet.png

# `litclock <sub> --help` forwards to the backing script's argparse so the
# per-subcommand flag list matches `python3 <sub>.py --help` exactly.
# Backwards-compat: every `python3 <script>.py …` invocation in the rest
# of this doc keeps working — the umbrella CLI is purely additive.
```

### Testing & linting

```bash
# Run the full test suite (~2525 tests; ~50s in CI with -n auto, single-threaded ~3m)
pytest

# Match CI: parallel + coverage on Python 3.12 (uses sys.monitoring tracer)
COVERAGE_CORE=sysmon pytest -n auto --dist loadscope --cov=. --cov-report=term-missing

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
python3 run_clock.py --config /var/lib/litclock/config.toml

# One-shot render of the current wall-clock time to output/current.png
python3 run_clock.py --once

# Loop: re-renders whenever the fuzzy bucket changes (not every minute)
python3 run_clock.py

# Loop + push each new render to a connected Inky Impression
python3 run_clock.py --display-script display_inky.py

# Appliance / production mode (hides debug bucket/quality/time footer)
python3 run_clock.py --display-script display_inky.py --mode production

# Dark theme (black background, white text, yellow accent) — both CLIs accept --theme
python3 run_clock.py --display-script display_inky.py --theme dark

# Auto theme: dark between 18:00–06:00, default otherwise
# (button B toggles manually and overrides 'auto' until midnight)
python3 run_clock.py --display-script display_inky.py --theme auto

# Broaden the auto rotation past the binary default/dark pair
# (e.g. scholar by day, nightvision by night — pick any registered theme)
python3 run_clock.py --theme auto --auto-day-theme scholar --auto-night-theme nightvision

# Random theme: rerolls each time the displayed quote changes. Button B
# manual override still wins (until midnight), same as for 'auto'.
python3 run_clock.py --display-script display_inky.py --theme random

# Optional curator web UI (off by default). 127.0.0.1 binds skip auth entirely;
# any other host requires --web-token (or --web-token-file for systemd).
python3 run_clock.py --web-bind 127.0.0.1:8080
python3 run_clock.py --web-bind 0.0.0.0:8080 --web-token-file ~/.litclock/web.token

# Webhook notifications (v2): POST every alert-worthy telemetry event to an
# operator-configured HTTP endpoint. Filter defaults to "errors / backoff /
# timeouts / button-died / state-validation / web-auth-fail / web-error";
# pass --webhook-all-events to widen to "everything except heartbeats and
# successful renders". Heartbeats are always filtered (alerting once a minute
# is spam). Best-effort: posts on a daemon thread with a 5s urllib timeout,
# failures log but never block the render path.
python3 run_clock.py --webhook-url https://hooks.example.test/litclock
python3 run_clock.py --webhook-url https://hooks.example.test/litclock --webhook-all-events

# Disable the Inky button listener (use on dev machines / headless smoke tests)
python3 run_clock.py --buttons-off

# Persisted runtime state (manual theme + manual quiet override) and telemetry sidecar
python3 run_clock.py --state-path ~/.litclock/state.json --telemetry-path ~/.litclock/telemetry.jsonl
python3 run_clock.py --telemetry-retain-days 30        # cap rotated telemetry siblings at 30 days (default 90; 0 disables)
python3 litclock_health.py --hours 24                  # human-readable summary
python3 litclock_health.py --hours 24 --json           # JSON for cron / systemd health checks
python3 litclock_health.py --hours 1 --fail-if-no-renders   # exit 2 if the window was silent
python3 litclock_health.py --hours 1 --max-heartbeat-age-minutes 5   # exit 2 if the main loop hasn't ticked in 5 min

# Push a static "starting" frame at boot so the panel doesn't ghost yesterday's render
python3 run_clock.py --startup-image assets/goodnight.png
# …or render an in-theme "Good night." frame on the fly (matches --theme):
python3 run_clock.py --theme scholar --startup-image auto

# Override the button-D long-press shutdown command (default: sudo -n shutdown -h now)
python3 run_clock.py --shutdown-command ""             # disable shutdown-on-hold entirely

# Disable the default quiet-hours blackout (defaults 22:00–06:00, shows assets/goodnight.png)
python3 run_clock.py --quiet-off
python3 run_clock.py --quiet-start 23:30 --quiet-end 07:00 --quiet-image assets/goodnight.png
# Render an in-theme "Good night." frame at the rising edge instead of a static PNG
python3 run_clock.py --theme auto --auto-night-theme nightvision --quiet-image auto

# Render a specific time directly (bypasses the loop)
python3 render_quote.py --time 22:54

# Show the picker's JSON for a given time or explicit bucket
python3 pick_quote.py --time 14:30
python3 pick_quote.py --bucket h2_half_pastish

# Render a 12x12 contact sheet of every fuzzy bucket for visual QA
python3 contact_sheet.py --output output/contact-sheet.png
python3 contact_sheet.py --theme dark --mode debug   # theme/mode flags flow through

# Push a rendered PNG to the Inky panel (Pi only)
python3 display_inky.py output/current.png
```

### Corpus / mining pipeline

```bash
# Mine a single Gutenberg ebook by ID
python3 gutenberg_time_miner.py --gutenberg-id 1342 --strict --output output/candidates.jsonl

# Mine multiple IDs
bash run_batch2.sh

# Mine local text files
python3 gutenberg_time_miner.py --input ~/books/ --output output/candidates.jsonl

# Merge multiple harvest runs (deduplicates)
python3 merge_candidates.py output/run1.jsonl output/run2.jsonl
# → candidates-merged.jsonl + candidates-merged-summary.json

# One-shot "mine + pipeline + merge into live corpus" driver for a curated list
# of clock-precise Gutenberg IDs (gutenberg_dawn_expansion_ids.txt).
# Safe to re-run — downloads cache in data/gutenberg/, merge_candidates dedupes.
bash run_dawn_expansion.sh

# Diagnose which GPIO pin each physical Inky button actually fires (Pi only).
# Prints timestamped PRESSED/released lines per pin. Use before blaming
# inky_buttons.BUTTON_GPIO or handler logic.
python3 probe_buttons.py
python3 probe_buttons.py --pins 5 6 16 24 17 13 26      # custom pin set
python3 probe_buttons.py --pull-down --bounce 0.02      # active-high + tight debounce

# Analyze which time buckets have few/no quotes
python3 bucket_coverage.py output/candidates-merged.jsonl
# → bucket-coverage.json + bucket-coverage.md

# Search specifically for sparse/empty bucket phrases
python3 target_sparse_buckets.py output/bucket-coverage.json
# → targeted-candidates.jsonl

# Convert targeted hits for merging
python3 import_targeted_hits.py output/targeted-candidates.jsonl
# → targeted-candidates-importable.jsonl

# Normalize excerpts into display-ready text
python3 clean_display_quotes.py output/candidates-merged.jsonl
# → candidates-cleaned.jsonl

# Add quality scores and flags
python3 quality_filter.py output/candidates-cleaned.jsonl
# → candidates-quality.jsonl

# Repair rows whose matched_text is a substring of a longer time phrase
# (e.g. "five minutes past two" mis-captured inside "thirty-five minutes past two")
python3 fix_substring_time_matches.py output/candidates-quality.jsonl

# Repair rows left tagged with legacy 8-state bucket names ("just_after",
# "half_pastish", etc.) from the pre-buckets.py drift era; also normalises
# embedded-newline matched_text back to a single clean phrase.
python3 fix_legacy_buckets.py output/candidates-quality.jsonl

# Attach title/author from Gutenberg headers
python3 enrich_metadata.py output/candidates-quality.jsonl
# → assets/candidates-attributed.jsonl

# Layer durable hand-curated fixes from the sidecar on top.
# No-op when the sidecar is empty; otherwise patches matching rows in place,
# stamps override_applied=true, and re-derives fuzzy_bucket from any
# time-affecting overrides. Warns on stderr for dangling keys.
python3 apply_content_overrides.py assets/candidates-attributed.jsonl
# → assets/candidates-attributed.jsonl (raw attributed corpus)

# Final stage: bake the display-ready runtime quote database.
# Drops daypart-only rows and rows below --min-quality, pre-computes the
# nine row-intrinsic score components + source rarity (against the full raw
# corpus so picks stay equivalent) into baked_score, caches
# inferred_quote_minute, and assigns a per-bucket baked_rank. The runtime
# picker reads this file by default and only recomputes the two request-time
# components (minute_penalty, override_bonus) per pick.
python3 bake_quote_database.py assets/candidates-attributed.jsonl
# → assets/quote_database.jsonl (pick_quote.py default --database)
```

## Default paths

Most pipeline scripts resolve relative `--input`/`--output` paths against the repo root (they anchor on `BASE_DIR = Path(__file__).resolve().parent`), so commands work from anywhere. Gutenberg downloads are cached in `data/gutenberg/` (relative to CWD); `enrich_metadata.py` reads from there by default.

Historical note: `run_batch2.sh` and some defaults still reference `projects/author-clock/...` paths from when this code lived inside a larger workspace. When running those, either symlink that path into place or pass explicit `--input`/`--output`. The batch list in `gutenberg_batch_ids.txt` mirrors the `--gutenberg-id` args baked into `run_batch2.sh`.

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

The canonical runtime input is **`assets/quote_database.jsonl`** — the baked, display-ready DB produced by `bake_quote_database.py`. Everything else in `assets/` is either the raw corpus that feeds the baker, a hand-edited sidecar, or a build-time artifact. Use this table to answer "what's source-of-truth vs derived vs per-appliance state?":

| Path | Role | Committed | Ships to Pi | Produced by |
|---|---|---|---|---|
| `assets/quote_database.jsonl` | **baked display-ready DB — the runtime picker reads this** | yes | yes | `bake_quote_database.py` |
| `assets/candidates-attributed.jsonl` | raw attributed corpus | yes | yes (baker input + curator UI + fallback) | `enrich_metadata.py` → `apply_content_overrides.py` |
| `assets/content_overrides.json` | per-row hand fixes (source-of-truth) | yes | no (build-time only) | hand-edited or web UI `POST /api/content-overrides` (followed by `POST /api/bake`) |
| `assets/selection_overrides.json` | bans / boosts / preferred buckets / per-row bans (runtime-editable) | yes | yes | hand-edited or web UI `POST /api/overrides` |
| `assets/bucket-coverage.{json,md}` | coverage snapshot | yes | optional | `bucket_coverage.py` |
| `~/.litclock/state.json` | manual theme / quiet override | — | runtime, per-appliance | `run_clock.py` |
| `~/.litclock/history.jsonl` | anti-repeat ledger | — | runtime, per-appliance | `run_clock.py` |
| `~/.litclock/telemetry-YYYYMMDD.jsonl` | render / error / heartbeat / backoff / timeout telemetry | — | runtime, per-appliance | `run_clock.py` |

Three invariants to keep in mind when touching this layer:

1. **Source-of-truth is the raw corpus + `content_overrides.json`.** If you want a row to change, change those. The baked DB is re-derivable from them; changes made directly to `quote_database.jsonl` will be clobbered the next time someone runs the pipeline.
2. **Runtime reads the baked DB.** `run_clock`, `render_quote`, and the `pick_quote` CLI all pass `database_path=DEFAULT_DATABASE_PATH` explicitly. A raw-corpus commit with no matching bake means the new rows are invisible to the appliance — the expand-corpus drivers (`run_dawn_expansion.sh`) include `bake_quote_database.py` as the last step for exactly this reason.
3. **Curator UI reads the raw corpus deliberately.** `/api/bucket` calls `pick_quote.select_candidates` (raw path) so an operator can see rows the baker dropped (daypart-only, quality below floor) and understand *why* a quote never appeared. Switching the curator to the baked DB would regress that visibility — don't.

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
- `quarter_half` — "quarter past six", "half past two"
- `quarter_to` — "quarter to eight"
- `minutes_past_to` — "ten minutes past five"
- `just_after_before` — "shortly after noon", "almost three"
- `clock_struck` — "the clock struck midnight"
- `daypart` — bare "morning", "dusk" etc. (excluded by `--strict`)

Use `--strict` for production runs to reduce false positives (excludes `daypart` and `digital` matches). `--skip-fetch-errors` keeps batch runs alive when a Gutenberg download 404s.

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

`merge_candidates.py` deduplicates on `(normalized_time, fuzzy_bucket, daypart_bucket, canonical_quote)` where `canonical_quote` is lowercased with smart quotes and excess whitespace normalized. On collision, keeps the entry with longer `context_text`.

### Quality Scoring

`quality_filter.py` starts each row at 100 and applies penalties (see `BAD_PATTERNS` and `score_quote`). Heavy hitters:
- `contains_time_range` (`3:00–5:00`) and `contains_metadata` (copyright/project gutenberg/ebook): −55
- `contains_work_schedule` (bare word "work") and `contains_modern_am_pm`: −45
- `contains_structural_label` (chapter/book/act/scene): −35
- `fragment`: −30, `too_short` (<50 chars) / `too_long` (>260 chars): −20
- Cleanup status other than `complete_sentence` or `expanded_with_context`: −20
- `digit_heavy` (≥6 digits): −25, `uppercase_heavy` (>18% uppercase): −15
- `weak_ending` (no terminal punct/quote): −10

Penalty reasons are appended to `quality_flags`. The score is floored at 0.

### Substring-Collision Fix

`fix_substring_time_matches.py` scans `display_quote` for the full pattern `<minute-word> minutes (past|to) <hour-word>`; if the row's stored `matched_text` is a strict substring of that longer phrase, the row's `matched_text`, `hour`, `minute`, `normalized_time`, and `fuzzy_bucket` are rewritten. Writes in-place by default (pass `--output` to redirect).

### Legacy-Bucket Repair

`fix_legacy_buckets.py` is the companion cleanup for rows tagged with the obsolete 8-state names (`just_after`, `early_past`, `quarter_pastish`, `half_pastish`, `late_past`, `just_before`, `quarter_toish`) harvested before `buckets.py` was extracted. For each such row with a valid `hour`/`minute`, it recomputes the canonical `h{hour}_{state}` bucket using the shared `minute_bucket` primitive (handling the top-of-hour rollover when `minute ≥ 58`). It also collapses runs of whitespace in `matched_text` back to a single space so phrases captured across a source line break (`"towards\ndusk"`) stay stored as a single clean phrase. `pick_quote.load_rows` already re-derives `fuzzy_bucket` from `normalized_time` so the stale values were not visibly broken at runtime, but storage should match the canonical schema so any future consumer reading `fuzzy_bucket` directly sees correct values and `merge_candidates` dedup keys stay stable. Writes in-place by default.

### Metadata Enrichment

`enrich_metadata.py` walks each row's `source_id`, opens the cached `data/gutenberg/pg<id>.txt`, and scans the first 120 lines for `Title: ` and `Author: ` headers. Results are cached per `source_id` so each file is parsed once. Fills `title`/`author` only when missing — existing values on a row are preserved. Output: `assets/candidates-attributed.jsonl`, consumed by `apply_content_overrides.py` (the next stage) and then by `pick_quote.py`.

### Content Overrides (`assets/content_overrides.json`)

Per-row sidecar for durable hand-curated fixes, applied by `apply_content_overrides.py` as the final pipeline stage on top of `assets/candidates-attributed.jsonl`. Exists because earlier revisions accumulated growing repair scripts (`fix_substring_time_matches.py`, `fix_legacy_buckets.py`) that patched *derivable* artifacts in place — any subsequent miner re-run would silently clobber the patch, so the same display bug could resurrect later. The sidecar decouples hand curation from pipeline regeneration: the fix lives here, and every re-run of the pipeline ends by re-applying it.

Keyed by `"<source_id>:<line_number>"` → partial row dict:

```json
{
  "141:482":  {"display_quote": "…"},
  "1342:99":  {"matched_text": "half past two", "normalized_time": "02:30"}
}
```

Allowed override fields: `display_quote`, `matched_text`, `author`, `title`, `quality_score`, `hour`, `minute`, `normalized_time`. Unknown fields are ignored with a stderr warning. After patching, `fuzzy_bucket` is re-derived from the post-override `normalized_time` (and `normalized_time` itself is re-derived from `hour`/`minute` when those are overridden without an explicit `normalized_time`), so time-affecting overrides stay internally consistent. Patched rows are stamped `override_applied: true` for downstream debugging.

`apply_content_overrides.apply_overrides` warns on stderr for **dangling keys** — sidecar entries that don't match any row in the input, typically caused by a typo or a row that later got dedup-dropped or filtered out. That's the intended replacement for *silent no-op* editing of `candidates-attributed.jsonl` by hand: fixes either apply (and are stamped) or loudly don't (and are logged).

**Fail-open loading, atomic writeback.** `load_overrides` catches `OSError` / `ValueError` / `JSONDecodeError` and a non-object root, emits one stderr warning, and returns `{}` so an editor-crash-truncated `content_overrides.json` doesn't abort the entire bake — worst case the picker runs with no sidecar patches applied. When `--output` is omitted (the default), output equals input, so `main` writes through `atomic_io.atomic_write_lines` (sibling-tmp → fsync → `os.replace` → dir-fsync). A crash mid-writeback leaves the existing `assets/candidates-attributed.jsonl` byte-identical instead of truncating the picker's runtime corpus.

**Soft discipline:** if you find yourself overriding more than a handful of rows for the same reason, that's a signal the upstream stage has a bug — push the fix into the miner / cleaner / quality filter rather than accumulating per-row patches.

**Curator UI editing.** As of v2 the sidecar is editable from the web UI via `GET /api/content-overrides` (returns the raw dict) and `POST /api/content-overrides` (validated atomic rewrite). The UI's "Bake now" button (`POST /api/bake`) runs `bake_quote_database.bake_rows` in-process so a save-then-bake round-trip drops the new excerpts onto the panel within seconds without an SSH session. Validation rejects unknown fields and bad key shapes with a 400; the same `apply_content_overrides.ALLOWED_FIELDS` set is the single source of truth.

**Legacy fix scripts.** `fix_substring_time_matches.py` and `fix_legacy_buckets.py` are retained as one-shot migration tools for corpus rows harvested by earlier miner revisions (the miner now collapses `matched_text` whitespace and the shared `buckets.py` prevents legacy 8-state names). Fresh mines should make them no-ops; see each script's docstring.

### Baked Quote Database (`assets/quote_database.jsonl`)

Final pipeline stage output, produced by `bake_quote_database.py` from the raw attributed corpus. This is the *display-ready database* the runtime picker consults by default; `candidates-attributed.jsonl` stays on disk as the raw corpus and is used by the curator UI's bucket inspector (`/api/bucket`).

**Why it exists.** Of the twelve score components in `pick_quote.score_row`, nine are row-intrinsic (`fragment`, `cleanup`, `metadata`, `dialogue`, `opening`, `source_bonus`, `quality`, `length_exactness`, `length_tiebreak`) and one more — `source_rarity_penalty` — depends only on the corpus as a whole; only `minute_penalty` and `override_bonus` actually change per request. Computing those ten components once at bake time, shipping them inline on each row, and dropping rows the picker would have filtered anyway (daypart-only rows with no `fuzzy_bucket`, rows below `--min-quality`) makes the runtime pick deterministic, smaller, and git-diffable: a regression in the scorer shows up as a diff to the committed database, not a silent drift in what the clock displays.

**Row schema additions.** Every baked row keeps its original fields plus:

- `baked_score` — list of ten ints in `BAKED_SCORE_COMPONENTS` order (see `bake_quote_database.py` and `pick_quote.py`). Drift between the two constant lists is how pick-equivalence silently breaks, so they're cross-checked in tests.
- `inferred_quote_minute` — what minute this row claims, cached once so `minute_penalty` doesn't re-run the regex sweep per tick.
- `baked_rank` — 0-based ordinal within the row's bucket after sorting ascending by `baked_score`. Purely for curator readability (the file is `(bucket, rank)`-ordered on disk); the runtime picker still sorts again once it has the two request-time components.
- `schema_version` — integer marker matching `BAKED_SCORE_SCHEMA_VERSION` in `bake_quote_database.py` / `pick_quote.py`. Bump whenever `BAKED_SCORE_COMPONENTS` changes (order, length, or semantics). `pick_quote._resolve_corpus` reads this field on the first baked row it encounters; a mismatch (stale `quote_database.jsonl` paired with a freshly `git pull`-ed `pick_quote.py`, or vice versa) triggers a fallback to the raw corpus with a stderr warning instead of silently scoring against a mis-aligned tuple. A baked DB pre-dating the field is treated as version 0 so upgrades surface loudly on first boot.

**Rarity is baked against the raw corpus**, not the baked subset — otherwise a source whose low-quality rows get dropped at bake time would count lower in the baked rarity than in the live one, and pick-equivalence between the two paths would break for that source's surviving rows. `tests/test_bake_quote_database.TestBakeRows::test_rarity_uses_full_input_corpus` pins this.

**Runtime lookup.** `pick_quote.select_quote` reads `assets/quote_database.jsonl` by default; if the file is missing or empty it falls back to the raw corpus with a stderr warning, so a stale/absent bake degrades gracefully instead of crashing the loop. `score_row` detects `baked_score in row` and short-circuits into `compose_baked_score_key`, which interleaves the two request-time components back into the pre-baked tuple at the correct positions to reproduce `score_row`'s original 12-tuple layout exactly. `tests/test_bake_equivalence.py` sweeps all 144 canonical buckets and asserts baked and raw picks return the same `(source_id, line_number)`.

**What's still live, not baked.** `selection_overrides.json` (bans / boosts / preferred buckets) stays runtime, because the web UI rewrites it via `POST /api/overrides` — re-baking on every edit would block the UI on a CLI run. Bans are a cheap post-filter; boost/preferred bonuses fold into the `override_bonus` position of the sort key. The anti-repeat history ledger is also runtime (it mutates on every render).

**When to re-bake.** Any time `assets/candidates-attributed.jsonl` changes — expand-corpus drivers like `run_dawn_expansion.sh` already run `bake_quote_database.py` as the last pipeline step, and the git commit it suggests includes `assets/quote_database.jsonl` alongside the raw corpus and coverage snapshot. A raw-corpus commit without a matching baked-DB commit means the picker will happily ignore the newly added quotes until the next bake.

### Quote Selection (`pick_quote.py`)

Default database: `assets/quote_database.jsonl` (the baked DB — see "Baked Quote Database" above); raw-corpus fallback `assets/candidates-attributed.jsonl` via `--input`. Rows below `--min-quality` (default 60) are filtered out before scoring (a no-op on baked rows since the baker already enforces the floor); banned `source_id`s (from `selection_overrides.json`) are dropped entirely.

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

### Selection Overrides (`assets/selection_overrides.json`)

A small editable JSON doc consulted by `pick_quote.py` (its default `--overrides` path):

```json
{
  "ban_source_ids": [],        // source_ids excluded entirely
  "boost_source_ids": [],      // −3 in the ranking tuple
  "preferred_buckets": {},     // { "h3_late_past": 12345 } → that source_id wins in that bucket (−5)
  "ban_quote_keys": []         // ["141:482", ...] — per-row permanent bans (v2)
}
```

IDs are compared as strings. Edit this file rather than editing the scorer when you want to manually curate a specific bucket. `pick_quote.load_overrides` warns on stderr if any `preferred_buckets` key is not a valid `h{1..12}_{state}` bucket, so typos surface loudly instead of silently never firing.

**Per-row bans (`ban_quote_keys`, v2).** `ban_source_ids` blacklists every row from a Gutenberg ID — coarse but useful for "this whole book is unsuitable." `ban_quote_keys` is the fine-grained companion: a list of `"<source_id>:<line_number>"` strings, each dropping exactly one row from the candidate pool. Powers the curator UI's "Ban this quote" buttons (Now tab, bucket inspector, search results) so an operator can blacklist a single bad quote without nuking the rest of its source. `pick_quote.is_banned` checks both lists; the per-row check requires both `source_id` and `line_number` to be set on the row, so a malformed row can't be accidentally banned by a list entry. `load_overrides` defaults the field on legacy v1 sidecars so the rest of the picker doesn't have to special-case its absence. `web_server.validate_overrides_payload` enforces the same `<source_id>:<line_number>` regex shape as the content-overrides keys (`CONTENT_OVERRIDE_KEY_RE`).

### Anti-Repeat History Ledger

A display-history ledger filters recently-shown quotes out of the candidate pool so the clock doesn't replay the same line twice in the same week. Default path is `~/.litclock/history.jsonl`; default window is 7 days. One entry per successful render:

```json
{"ts": "2026-04-19T14:30:00+00:00", "source_id": "141", "line_number": 482}
```

`pick_quote.load_recent_history` reads the ledger, drops entries older than `--history-days`, and returns a set of `(source_id, line_number)` tuples. `pick_best` applies a strict fresh-first filter: rows whose key is in that set are excluded before scoring, and if the filter empties the candidate pool the full list is used so sparse buckets still render something. `pick_quote.append_history` writes one line per successful render and then `fsync`s the handle so a power loss immediately after the call can't leave the entry buffered in the kernel — the worst failure case is one lost entry, never ledger-wide corruption. `pick_quote.remove_last_history_entry` (called by the button-A long-press "un-skip" action) is the only code path that can rewrite the ledger from scratch; it goes through `atomic_io.atomic_write_text` so a `SIGKILL` between the read and the rewrite leaves either the pre-delete content (acceptable) or the post-delete content (acceptable) but never an empty or truncated ledger. If `load_recent_history` encounters a malformed line (partial write or external corruption), it logs a one-shot warning to stderr (`"history ledger {path}: malformed line skipped (corrupt or partial write); subsequent bad lines in this read will be suppressed"`) and continues; further bad lines in the same read are suppressed so a torn file doesn't spam the log.

Disable the filter by passing `--history-path ""` or `--history-days 0`. `select_quote` (the library entry point) defaults to **disabled** so unit tests and one-off callers are not affected; `run_clock.py` and `pick_quote.py`'s CLI default to **enabled**. `run_clock.py`:
- Calls `peek_quote_id` before `render_now` so the ledger snapshot both the peek and the subprocess see is identical (run_clock appends only after the subprocess returns 0).
- Appends only after a successful render — never during quiet hours, never on failure, never when the dedup "quote unchanged" branch skips the redraw.
- Forwards `--history-path` / `--history-days` to `render_quote.py` via subprocess args so both processes agree on which ledger to consult.

**Ledger compaction.** `pick_quote.compact_history` drops entries older than `2 × --history-days` so a multi-year-running appliance doesn't linearly grow the file that every pick must stream through. The main loop calls `_maybe_compact_history` once per local-date rollover (gated by `state.last_compacted_date`) so we don't re-parse the ledger on every tick; `last_compacted_date` is set *before* the rewrite so a mid-compact crash doesn't re-trigger a retry storm the next tick. Rewrite routes through `atomic_io.atomic_write_text`, so a crash mid-compact leaves the original ledger intact. The `2×` slack means a short clock drift or an operator bumping `--history-days` up a day or two doesn't immediately evict rows that are about to be re-consulted. Malformed lines are preserved as-is (the compact pass is about bounded growth, not corruption repair — that's `load_recent_history`'s job).

### Rendering (`render_quote.py`)

Imports `pick_quote` in-process (`pick_quote_module.select_quote`) and lays out an 800×480 RGB PNG — no subprocess, no stdout-JSON contract. Key details:

- **Palette.** Colors are drawn from the 6-color Spectra 6 palette (white/black/red/yellow/blue/green) and the final image is re-snapped to that palette via `snap_image_to_palette` so the Inky dithering stays predictable.
- **Themes.** The `THEMES` dict defines twenty-eight color sets, cycle-ordered by the `THEME_ORDER` tuple: `default` (white/black/red, Playfair Display), `dark` (black/white/yellow, Playfair Display), `swiss` (white/black/red, Inter grotesque sans — Swiss International / mid-century modernist functional, the only theme in the rotation whose border decoration is deliberately *minimal*: a single 1 px black hairline rule across the page at y=60 plus a tiny 6×6 px filled red square at (width-40, y=42) anchoring the asymmetric Müller-Brockmann / Vignelli grid. No frame, no corner ornaments, no Layer-0 wash — austerity by subtraction is the visual identity, a counterpoint to every other border-rich theme. The square is positioned below the y=14-29 debug-banner band so swiss is intentionally absent from `_DEBUG_LABEL_RIGHT_INSET`.), `scholar` (white/blue/red, Bitter slab serif — the matched-phrase red accent is rerouted in `_draw_text_body` to a 50/50 R+K maroon stipple, reading as aged red-lead of an academic-journal annotation), `newsprint` (white/black/no-accent — bold-weight differentiation only, Old Standard TT, plus a `draw_newsprint_border` Scotch-rule frame: thick outer rule + hairline inner rule, no corner accents — broadsheet typography lives entirely in ink weight, not chromatic contrast. The Layer 0 ground pairs the original 12.5% black halftone with a faint 12.5% sepia-foxing layer — 1 red + 1 green pixel per 4×4 Bayer tile at cell values 2 and 3, diagonally ~2.8 px apart — blends at panel distance into the pale rust-brown tint real archival newspaper paper develops as the lignin oxidises under light. The matched-phrase / body / accent THEMES slots stay black-on-black so `test_newsprint_theme_has_no_colour_accent` still passes — the rust-brown lives entirely on the *paper*, not the typography), `nightvision` (black/green/yellow, Space Mono retro-terminal feel. The body / attribution / oversized-quote-mark glyphs are stippled with white in a 50/50 Bayer pattern via `_draw_text_body` + `draw_text_dithered` so Spectra-6 saturated green lifts to a perceived mint that reads at panel distance instead of the dimmer pure-green ink the panel produces solid. The matched-phrase yellow accent is rerouted in `_draw_text_body` to a 5/8:3/8 Y+G LIME stipple (yellow-biased green via the same Bayer threshold deco's tangerine uses) so the phrase reads as the brighter neon "tactical readout" glow of a real HUD warning rather than the flat alert-flag yellow it was previously. The HUD corner brackets in `draw_nightvision_border` stay solid green (decorative silhouettes would fragment under stippling), but the faint scanlines now get a sage post-pass — bbox-flipping ~25% of the painted green to white per Bayer threshold 4, so they read as ambient W+G 1:3 ground glow rather than crisp bright-green CRT lines. Plus a `draw_nightvision_border` HUD-style frame: four L-shaped green corner brackets with NO continuous outer frame between them — the bracket-only composition is the signature camera-viewfinder / weapons-HUD motif), `blueprint` (white/blue/red, Archivo geometric sans — drafting aesthetic. The matched-phrase red accent is rerouted in `_draw_text_body` to a 50/50 R+K maroon stipple (shared seam with `scholar`), reading as a darker red pencil pressed firmly into the cyanotype drafting paper. Plus a `draw_blueprint_border` decorative frame: thin blue outer rectangle with red crosshair "registration marks" centred on each corner, echoing the print-alignment ticks used on engineering drawings, and a thin blue graph-paper grid painted inside the frame at 20px spacing so the ground reads as engineering paper rather than an empty sheet — text is painted on top so the grid only shows through between glyphs), `illuminated` (white/red-body/blue-accent, EB Garamond + UnifrakturMaguntia blackletter ornaments — rubricated manuscript, plus a `draw_illuminated_border` decorative frame: Layer 0 sparse 1-in-8 yellow-on-white cream Bayer wash for aged-vellum tone, doubled rubricated red rule, and a plum "cabochon" — filled circle painted in a sentinel ink and then bbox-post-passed through a 3-way 4×4 Bayer partition (cells 0-4 → red, 5-9 → blue, 10-15 → black) — centred on each outer corner, evoking the wine-dark lapis cabochons inset on the most precious medieval bindings. The matched-phrase blue is also rerouted in `_draw_text_body` to a 50/50 R+B violet stipple — Tyrian purple, the rarest dye of the scriptorium), `gothic` (black-ground/white-body/red-accent, the same UnifrakturMaguntia blackletter promoted from ornament-only to *both* the matched-phrase bold and the oversized quote marks — short matched phrases like "half past two" render in dramatic red blackletter, sitting in the body like a chapter heading. The matched-phrase red is stippled with the same sparse 1-in-4 white-on-red dither (`light_density=0.25`) that `grimoire` uses on *its* blackletter matched phrase via `_draw_text_body`, so both sister blackletter themes share a candlelit-rubric signature against their respective grounds — the recipe is the documented "candlelit red" two-ink mix. Pairs with a `draw_gothic_border` decorative frame: double rule (red outer + white inner — distinct from `illuminated`'s single-ink doubled rule) with red-and-white quatrefoils — four small red lobes around a tiny white centre dot — at the four outer corners (the iconic four-lobed Gothic-tracery motif found in cathedral rose windows and printed-book ornaments), plus small red diamond ornaments centred on each mid-edge as chapter-divider accents. Visually the opposite polarity of `illuminated` so the two blackletter themes complement rather than duplicate), `bauhaus` (white/black/blue-accent + red-ornaments, Jost geometric sans — three primaries simultaneously, plus a `draw_bauhaus_border` decorative frame: thin black outer rectangle with red-circle (TL) / blue-square (TR) / yellow-triangle (BL) / red-circle (BR) corner accents — the BL triangle paints in yellow rather than the second blue it was pre-Stage-3 so all three Bauhaus primaries (red + blue + yellow) appear simultaneously on the page alongside the black outer frame. The matched-phrase blue accent is rerouted in `_draw_text_body` to a 50/50 B+K navy stipple, giving the matched phrase tighter contrast against the new yellow triangle than the body-vs-accent palette would otherwise produce. The themes with borders — atomic / bauhaus / blueprint / comic / dispatch / gothic / illuminated / newsprint / nightvision — are dispatched via `_paint_theme_border` / `_BORDER_PAINTERS` at the top of both `render` and `render_source_card`; four of them paint in the top-right corner (bauhaus / blueprint / gothic / illuminated), so the debug-mode "DEBUG MODE" banner shifts inward for those via the `_DEBUG_LABEL_RIGHT_INSET` dict — extend that dict when adding another theme-specific TR graphic. Dispatch's TR rubber-stamp graphic sits below the label band, and atomic's atom symbol is centred horizontally, so both deliberately stay absent from that dict), `risograph` (white/red/blue, Rubik rounded sans — ZERO black ink, two-colour riso print. The matched-phrase blue accent is rerouted in `_draw_text_body` to a 50/50 R+B violet stipple — the authentic riso double-pass overprint where the red and blue plates physically wash into purple; preserves the no-black-ink invariant by construction. The `draw_risograph_border` decoration's shifted-accent registration crosses at the four corners paint in an off-palette sentinel and then bbox-post-pass through a 3-way 4×4 Bayer partition into LAVENDER (R+B+W ~1/3 each) — the paler "overprint" register-mark tone real risograph print test sheets develop where two plates wash together), `comic` (yellow-ground/black-body/red-accent, Bangers comic-book display, plus a `draw_comic_corner_stripes` decoration: 45° racing stripes cycling through blue / green / red / black, masked to a right-triangle pinned to the bottom-right corner of the canvas — hypotenuse spans the lower-right quadrant from `(width/2, height)` up to `(width, height/2)`, so bands fan out from the corner without obscuring the quote body. The stripe palette is hardcoded at module scope (`_COMIC_STRIPE_PALETTE`) since the cool blue/green half of the chevron isn't reachable from the comic theme dict's two non-bg accents — an exception to the "borders pull from `colors`" pattern that would otherwise force a THEMES-schema extension and re-pin every cross-theme invariant test), and `dispatch` (white/black/red, Special Elite slab-mono typewriter face — vintage office / field-report / dossier register, plus a `draw_dispatch_border` decoration: a sparse 1-in-8 yellow-on-white Bayer cream wash painted as Layer 0 across the page ground (per `BAYER_4x4[y%4][x%4] < 2` — same Bayer threshold `newsprint`'s halftone uses but flipped for `page_bg→yellow` so the page reads as a faint cream/vellum tone, the documented Y+W cream recipe), thin black outer frame, two columns of small tractor-feed perforation circles down the side margins (echoing continuous-feed dot-matrix sprocket holes — every other pair flips from solid black to a sepia stipple via the documented R+G sentinel-paint-then-bbox-post-pass pattern, reading as the rust-brown "carbon-paper bleed" real continuous-feed forms accumulate where the carbon backing oxidises through the sprocket holes), and a maroon rubber-stamp imprint in the upper right inside the frame — two concentric ellipse outlines plus four short diagonal hatch lines, painted in red as a sentinel and then bbox-post-passed to flip half to black per `(x+y)&1` parity (the documented R+K maroon recipe), so the stamp reads as the aged-ink oxblood of a real archival stamp rather than fire-engine red. Same palette as `default` but the slab-mono typewriter face plus the dossier graphics give it a completely different silhouette. The stamp sits at y≈40–70, well below the `DEBUG MODE` banner band, so dispatch is intentionally absent from `_DEBUG_LABEL_RIGHT_INSET`), and `atomic` (green-ground/black-body/red-accent — the only theme to claim Spectra 6's flat green as a *page background* — paired with the chunky 1950s Atomic Age display face. Plus a `draw_atomic_border` decoration: a rounded-corner red outer frame (Googie streamlined-modern curves), a centred atom symbol at the top of the page (three rotated red ellipse "orbits" at 0° / 60° / 120° plus a small filled red nucleus — PIL's `ellipse` doesn't accept rotation, so each orbit is drawn as a 64-point polygon-line approximation rotated through the standard 2×2 cosine/sine matrix), and twin tangerine starbursts at the mid-edges (eight rays radiating from a small filled dot — the iconic atomic-energy spark of mid-century diner / motel signage. Each ray is painted in red as a sentinel ink, then a per-starburst bbox post-pass Bayer-flips ~3/8 of the red pixels to yellow at threshold 6/16 — the documented R+Y 5/8:3/8 tangerine recipe `deco` already uses for its matched phrase — so the rays read as the warm atomic-spark glow of period-correct mid-century advertising rather than the harsh fire-engine red the atom orbits use. The atom symbol itself stays solid red so rays-vs-orbits reads as a visual contrast — solid orbits, warm-stippled rays). Reads as a vintage atomic-age advertisement at a glance. The atom is centred horizontally so it doesn't conflict with the right-aligned `DEBUG MODE` banner; atomic is intentionally absent from `_DEBUG_LABEL_RIGHT_INSET`). Five additional display-face themes round out the rotation: `deco` (white/black/red-stippled-to-yellow → perceived orange, Righteous geometric art-deco display sans — Astigmatic, OFL, single-weight, matched phrase reuses Regular and earns differentiation from the synthesised-orange accent alone, a richer variant of the bichrome-ribbon trick comic / dispatch / atomic / marker / saloon use because Spectra 6 has no orange ink — both `_draw_text_body` (matched-phrase glyphs) and `draw_deco_border`'s final pass (stepped L-shapes + rising-sun fan) flip half of the painted red pixels to yellow on the same `(x+y) & 1` checkerboard so body text and decoration land on one shared tangerine tone at panel distance, the warm sunburst-and-chevron palette the period actually used rather than fire-engine red. Plus a `draw_deco_border` decorative frame: doubled hairline rule at insets 14 and 22 px, four concentric stepped-corner L-shapes per corner — the canonical 1930s skyscraper-steps motif found on every cinema marquee and travel poster — and a centred rising-sun fan at the top inner edge: a small filled accent dot with five short radial rays fanning upward through the band between the two rules. After the global tangerine pass converts the rays from red to R+Y tangerine, a second cream-gradient post-pass on just the inner ~5 px of the fan band flips remaining red pixels to white per `(x+y)&1` parity — so the inner rays read as bright Y+W cream fading back into the R+Y tangerine at the tips, simulating a true sunburst's central glow rather than a uniform tangerine fan. Centred horizontally and stepped corners reach x ≤ width-14, so `deco` is deliberately absent from `_DEBUG_LABEL_RIGHT_INSET` for the same reason as `atomic` / `dispatch`), and `glacier` (white/blue/green, Iceland geometric techno display face — Cyreal, OFL, the first theme to pair a blue body with a green accent. The matched-phrase green accent is rerouted in `_draw_text_body` to a 50/50 G+B cyan stipple — aurora teal completing the cool-palette gradient: blue body → cyan matched phrase → sky-blue ornament highlights on the frost-crystal border. Plus a `draw_glacier_border` decorative frame: thin blue outer rule at inset 14, four corner frost-crystal clusters of three angular shards each — two blue shards fanning along the adjacent edges plus one longer green-tipped diagonal shard for aurora light on ice — the diagonal shard's green pixels are post-pass-flipped to white on a 50/50 `(x+y)&1` checkerboard inside each cluster's bbox (the documented sky-blue two-ink recipe), so the eye averages green+white at panel distance into a sunlight-on-ice highlight reading against the deep-ice body-blue shards — and four mid-edge snowflake-tick stars (a filled diamond plus a thin orthogonal cross) reinforcing the architectural symmetry without crowding the quote. The TR cluster overlaps the default debug-banner band, so `glacier` carries an entry of 34 in `_DEBUG_LABEL_RIGHT_INSET` mirroring `blueprint`'s rationale). And `chalkboard` (black-ground/white-body/yellow-accent, Playwrite GB J Guides — TypeTogether, OFL — the UK primary-school joined cursive handwriting model *with* the dotted-outline guide letters schoolchildren trace over. Single-weight (Regular only); the dotted/hollow letterforms themselves are the point, so the matched-phrase role reuses Regular and gains differentiation from the yellow chalk-stick accent. Falls back through DejaVu Sans Italic / Liberation Sans Italic before degrading to the Playfair chain so a missing install lands on at least a slanted silhouette rather than dropping a cursive theme onto an upright serif. Plus a `draw_chalkboard_border` decoration: doubled white wooden frame (outer 3 px rule at inset 8 + inner 1 px rule at inset 18, with the ~7 px gap between them left unfilled so the black ground reads through as dark wood grain), a deterministic chalk-dust stipple of single-pixel white dots tucked into the bottom-left corner — pinned to the BL because that's where the chalk tray actually sits on a classroom board — a small green-chalk teacher's `✓` check-mark at the upper-right inner margin (drawn in solid Spectra 6 green at y≈50 as two short line segments forming the canonical "marked correct" annotation; sits below the y=14-29 `DEBUG MODE` banner band by construction), and five small coral eraser-smudge dots spaced along the bottom inner edge (each painted as a 3 px filled red circle then post-passed with white at 50/50 `(x+y)&1` parity inside its bbox so the eye averages red+white at panel distance into coral pink — the documented R+W 1:1 two-ink recipe — reading as the faint pink eraser-stub residue that builds up at the bottom of a real classroom chalkboard). The TR check-mark stays inside x ≤ width-22 and y ≥ 38, so `chalkboard` is intentionally absent from `_DEBUG_LABEL_RIGHT_INSET` — same exemption as `dispatch` / `atomic`). And `placard` (white/black/red, Patrick Hand SC — Patrick Wagesreiter, OFL — friendly hand-printed face whose small caps for lowercase do almost all the visual work, giving the text the silhouette of hand-lettered shop signage / sandwich-board menus. Single-weight (Regular only); the matched-phrase role reuses Regular and gains differentiation from the red accent alone, same trick comic / dispatch / atomic / marker / saloon / deco / glacier / chalkboard already use. Falls back through DejaVu / Liberation / Noto Sans Bold before degrading to the Playfair chain so a missing install lands on a chunky display silhouette. Plus a `draw_placard_border` decoration: doubled sign-painter's frame at insets 14 and 18 — the outer rule painted as a 1 px red stroke and then perimeter-post-passed to flip half of its pixels to green on the 50/50 `(x+y)&1` checkerboard so the eye averages red+green at panel distance into rust-brown sepia (the documented R+G 1:1 two-ink recipe, same recipe `saloon`'s foxing uses), reading as the weathered sandwich-board wood of a sun-faded A-frame menu rather than the harsh printer-ink black of a freshly typeset poster; the inner rule stays solid black so the colour shift between the two parallel rules reads as "core inked, weathered at edges." Four red filled "thumbtack" circles (radius 4) at the inner corners suggest pins holding the sign up — each tack's red pixels are post-pass-flipped to white on a 50/50 `(x+y)&1` checkerboard inside its own bbox (the documented coral-pink two-ink recipe), so the eye averages red+white at panel distance into weathered hand-painted sign-painter red rather than fire-engine vermilion (the exposed corners of a sandwich-board sign would be the first thing to fade in the rain). The four tacks sit at y ≈ 38 / y ≈ height-38, well below the default debug-banner band (y=14-29), so `placard` is intentionally absent from `_DEBUG_LABEL_RIGHT_INSET` — same exemption as `dispatch`). And `chanbara` (black-ground/white-body/red-accent, Shojumaru — Astigmatic / Brian J. Bonislawsky, OFL — a dramatic brush-painted display face by the same designer as Righteous and Atomic Age, evoking samurai cinema posters and Japanese woodblock prints. Single-weight (Regular only); the matched-phrase role reuses Regular and gains differentiation from the red sun-disc accent alone, same bichrome trick the other display-face themes use. Falls back through heavy DejaVu / Liberation / Noto Sans Bold before degrading to the Playfair chain so a missing install lands on a heavy display silhouette. Plus a `draw_chanbara_border` decoration: a large red filled "rising-sun" disc anchored off-canvas in the bottom-right corner (centre at width+30 / height+30, radius 220 — only the upper-left arc visible, sweeping dramatically through the lower-right quadrant of the page; the white quote text rendered on top reads cleanly thanks to the high white-on-red contrast and the palette-snap pass), balanced diagonally by a small red artist's-chop seal in the top-left corner (a 28×36 px filled red rectangle with one thin white horizontal "ichi" stroke through its centre, vaguely suggesting a Japanese hanko ink seal without committing to specific kanji). The dominant graphic sits in the BL/BR quadrants by design so the top-right stays clear of the debug banner — `chanbara` is intentionally absent from `_DEBUG_LABEL_RIGHT_INSET`, same exemption as `dispatch` / `atomic` / `placard` / `chalkboard`). Three further themes — `herbarium`, `mucha`, and `fillmore` — fill gaps in the rotation's visual spread: `herbarium` (white/cream/black/forest-green, IM Fell English italic — 19th-century pressed-plant specimen sheet; the matched-phrase green accent is rerouted in `_draw_text_body` to a 50/50 G+K stipple — forest green, the documented dark-green recipe from `spectra6_color_recipes.md`'s "not in use / forward reference" section that herbarium now claims, reading as the dark-pressed plant material a real archival specimen develops. The first theme whose defining colour story is the green axis — every other green-touching theme (`nightvision` / `glacier` / `roman`) uses green as a secondary accent against a different body colour. Plus a `draw_herbarium_border` decoration: cream Layer-0 wash (Y@12.5% Bayer, same recipe `illuminated` / `dispatch` use), thin black engraver's hairline rule at inset 14, four small "pinhole" dots at the inner corners (where the specimen would be pinned to the mounting sheet), a stylised pressed-leaf silhouette in the bottom-right corner — painted in yellow as a sentinel ink and bbox-post-passed to flip half to green per `(x+y)&1` parity → olive (Y+G 1:1, the documented recipe `roman`'s laurel sprigs already use) — with darker olive midrib and side veins, and a "Tempus fugit" specimen cartouche in the bottom-left diagonally counterweighting the leaf. The TR pinhole at (width-18, 17) sits inside the y=14-29 banner band horizontally adjacent to the default label edge, so `herbarium` carries an entry of 24 in `_DEBUG_LABEL_RIGHT_INSET` for a 4 px breathing gap), `mucha` (cream-washed white / maroon body / cyan matched phrase, Cormorant Garamond + Berkshire Swash ornament — Art Nouveau / Belle-Époque poster, the first theme to use a synthesised colour as its primary body fill rather than just an accent: the `text` THEMES slot holds the red sentinel ink that `_draw_text_body` routes through a 50/50 R+K stipple → maroon (R+K 1:1, the same documented recipe `dispatch` / `gothic` / `chanbara` / `grimoire` / `blueprint` / `scholar` use for their matched phrases, here promoted to the body), reading as the deep wine / oxblood the period's poster lettering actually used. The matched phrase shifts to cyan (G+B 1:1, the `glacier` recipe) for cool-vs-warm contrast against the maroon body. Plus a `draw_mucha_border` decoration — the rotation's first all-curve / organic border: cream Layer-0 wash (same Y+W recipe as `illuminated` / `dispatch` / `herbarium`), thin teal rule at inset 18 painted in green as a sentinel ink and perimeter-post-passed to flip half to blue per `(x+y)&1` parity → cyan (tying the rule to the matched-phrase colour story), and S-shaped organic vine ornaments at the top-left and bottom-right corners — each vine is a 7-point polyline-approximated Bézier S-curve (PIL doesn't ship curves; the same n-point polygon trick `atomic`'s atom orbits use) with three trefoil leaf clusters painted in yellow as an olive sentinel (Y+G, same as the `herbarium` leaf) and a small berry at each stem tip painted in red and bbox-post-passed through `BAYER_4x4 < 6/16` → tangerine (R+Y 5/8:3/8, the documented recipe `deco` and `atomic` use). The top-right and bottom-left corners are deliberately *unornamented* — Mucha posters compose asymmetrically around an off-centre figure, and reproducing that asymmetry is the visual signature; mucha is intentionally absent from `_DEBUG_LABEL_RIGHT_INSET` for the same reason), and `fillmore` (sun-faded-yellow ground / maroon-stippled body / blue matched phrase, Bungee Shade — 1960s Fillmore concert poster (Wes Wilson / Victor Moscoso / Stanley Mouse), the visual maximalist of the rotation: deliberately surfaces every Spectra-6 native ink simultaneously across the page (yellow + white in the Layer-0 wash, blue matched phrase, green / blue / red / yellow corner blob inks, black in the body's R+K stipple plus Bungee Shade's drop-shadow strokes). The body's `text` THEMES slot is the red sentinel that `_draw_text_body` routes through a 50/50 R+K stipple → maroon — the same recipe `mucha` uses for its body — to subdue the otherwise-loud pure-red-on-saturated-yellow combination without losing the psychedelic identity; real Fillmore posters' red ink ended up darker once printed onto yellow stock anyway, so the perceived hue is period-authentic. The `draw_fillmore_border` painter further softens the ground with a sparse 1-in-8 white-on-yellow Layer-0 Bayer wash (`BAYER_4x4[y%4][x%4] < 2`, ~12.5% of yellow pixels flipped to white) — same density as the cream washes `illuminated` / `dispatch` / `herbarium` / `mucha` use on their *white* grounds, here flipped so the wash desaturates a yellow ground rather than warming a white one. Reads as the partly-sun-faded yellow poster stock a real Fillmore audience would have seen on a venue door rather than the fire-bright Spectra-6 pure yellow. Plus a `draw_fillmore_border` decoration: two free-form 18-point polygon "blob" panels at diagonal corners — a green blob in the top-left at (38, 38) with scale 0.4 and a small red 5-point star inside, mirrored by a blue blob in the bottom-right with a yellow filled inner circle. Each blob is seeded deterministically so the silhouette is reproducible (the same seed always produces the same polygon). The blobs are sized to fit inside the ~72 px top / bottom margins that `render` leaves free of body text (`block_top = max(72, ...)`), so the corner panels never intrude into the quote block. No outer frame — the composition is grounded by the corner blobs rather than by a containing rectangle, exactly the way real Fillmore posters compose; fillmore is intentionally absent from `_DEBUG_LABEL_RIGHT_INSET` since the TR is empty by design). Every theme colour must stay on the Spectra 6 palette (enforced by a test). `--theme` selects one (plus `auto` which picks day/night by wall-clock hour, and `random` which rerolls the theme each time the displayed quote changes); `run_clock.py` forwards it via `--theme`. Button B advances through `THEME_ORDER` one step per press; the web UI dropdown jumps directly. Adding a new theme: extend `render_quote.THEMES`, add to `THEME_ORDER`, add a `render_quote.THEME_FONTS` entry (see "Fonts" below — missing themes silently fall back to the Playfair chain, defeating the point of per-theme typography), add a `display_inky.THEME_SATURATION` entry, and update `run_clock.py`'s `--theme` argparse choices (the `TestActionThemeCycle::test_cli_theme_choices_match_theme_order` test pins the sync).
- **Fonts.** Typography is per-theme, and each non-default theme deliberately picks a face from a different type *family* so the rendered frame's silhouette changes with the theme — not just its palette. `THEME_FONTS` maps each `THEMES` entry to a dict with `quote_regular` / `quote_bold` / `ornament` candidate chains, each a list of path strings OR `(path, variation_name)` tuples. The tuple form targets variable fonts — `load_font` calls `set_variation_by_name(name)` after the truetype load, so e.g. the scholar theme picks Regular/Bold instances from a single variable `Bitter-Variable.ttf` (whose default axis instance is Thin — a missing variation call would render near-invisible hairlines on the panel). `default` and `dark` share the Playfair Display chain (transitional / high-contrast serif; repo-local `fonts/`, then common Pi/Linux paths, with DejaVu Serif / Liberation Serif / Noto Serif as system fallbacks). `scholar` uses **Bitter** — a slab serif; even-contrast blocky terminals read as "academic textbook" and sit visually far from Playfair's display-serif silhouette, Regular body + Bold accent. `newsprint` uses **Old Standard TT** (vintage broadsheet / scientific-journal Didone revival — Regular body + Bold accent). `nightvision` uses **Space Mono** (retro-terminal monospace — Regular + Bold; DejaVu Sans Mono is the system-font fallback). `blueprint` uses **Archivo** (grotesque sans — the first pure-sans silhouette in the rotation; ships static Regular + Bold TTFs). `illuminated` pairs **EB Garamond** (humanist old-style serif — different family branch from Playfair's transitional / Bitter's slab / Old Standard's Didone) for the body with **UnifrakturMaguntia** (blackletter) confined to the ornament slot for the oversized curly quotation marks — a blackletter body would shred dense-layout legibility on a 4-bit eInk panel. `gothic` reuses the same EB Garamond body but promotes **UnifrakturMaguntia** into *both* the `quote_bold` and `ornament` slots, so the matched time phrase joins the oversized quote marks in dramatic red blackletter — the font defines the theme rather than appearing as a guest accessory, while the body stays in legible Renaissance serif so a 200-character dense layout still reads cleanly. `bauhaus` uses **Jost** (Futura-adjacent geometric-constructed sans — same sans family as blueprint but from the geometric branch rather than the grotesque, so the two sans themes remain distinguishable; variable font, Regular / Bold pinned via `set_variation_by_name`). `risograph` uses **Rubik** (chunky rounded modern geometric sans — variable font whose axis default is Light (300) NOT Regular, so every THEME_FONTS candidate pins Regular / Bold explicitly; a missing `set_variation_by_name` call would render body text noticeably too thin). `comic` uses **Bangers** (all-caps comic-book display hand — the only display / hand-lettered face in the rotation; only one weight ships so the matched-phrase role re-uses the same file and gains differentiation purely through the accent colour). `dispatch` uses **Special Elite** — a slab-mono typewriter face whose deliberately uneven inking is the whole point. Like Bangers it ships only Regular, so the matched-phrase role re-uses the same file and gains differentiation through the accent colour alone — period-authentic, since a real bichrome typewriter ribbon shifted between black and red without changing weight. The fallback chain falls through Space Mono (the closest in-rotation typewriter-adjacent face) and DejaVu Sans Mono before degrading to the Playfair serif chain, so a missing-Special-Elite install lands on a typewriter-flavoured mono rather than dropping a slab-typewriter theme onto a transitional serif silhouette. `atomic` uses **Atomic Age** — a chunky 1950s display face from Sorkin Type (OFL) with pointed angular terminals on slab bodies, very mid-century signage / Sputnik-poster register. Like Bangers / Special Elite / UnifrakturMaguntia it ships only Regular, so the matched-phrase role re-uses the same file and gains differentiation through the accent colour alone. Body text in a display face is loud by design — that's the point. Falls back through DejaVu Sans Bold (and other heavy sans) before degrading to the Playfair serif chain, so a missing-Atomic-Age install lands on a heavy display silhouette rather than an elegant serif. Every per-theme chain ends at the Playfair / DejaVu defaults so a missing-font install degrades to the default face instead of dropping to the PIL bitmap fallback. System metadata / debug strips always use DejaVu / Noto / Liberation Sans regardless of theme. Install `apt install fonts-noto-core fonts-dejavu-core` if the bundled fonts aren't found. When every TTF candidate is missing, `load_font` logs a one-shot warning to stderr before returning `ImageFont.load_default()` so a misconfigured install surfaces instead of silently producing an 8-pixel bitmap render.
- **Layouts.** Three named layouts (`hero` ≤90 chars, `standard` ≤170, `dense` otherwise) each define their own `max_width`, `quote_height`, font size range, line-height multiplier, and quote-mark sizing. See the `LAYOUTS` dict.
- **Bold time phrase.** `resolve_display_match` tries to grow a multi-word time phrase ("five minutes past", etc.) inside the display text, then `tokenize_quote`/`wrap_styled_text` render it in bold + accent color while keeping word wrap correct across the bold boundary.
- **Text cleanup.** `strip_underscore_emphasis` drops Gutenberg's `_emphasis_` markers and `normalize_dashes` converts bare `--` to em-dashes before layout.
- **Fit loop.** `fit_quote` shrinks the quote font in 2pt steps from the layout's `font_max` down to `font_min` until all lines fit within `quote_height`.
- **Justification.** Non-last lines are fully justified by distributing leftover slack across inter-word spaces — but only when slack is ≤25% of the layout's `max_width`. Loose lines fall back to ragged-right because wide forced gaps look worse than uneven right edges.
- **Modes.** `--mode debug` (default) draws a top-right `DEBUG MODE` banner (rendered in sans-bold to match the footer strip, in the theme's accent color) plus a centered bottom strip (`HH:MM · bucket[ → resolved] · layout X · quality N · id source:Lline`) separated from the quote block by a dotted horizontal rule. `--mode production` hides all of that for a clean appliance look.
- **Outputs.** `--output` defaults to `output/current.png` (the same stable filename `run_clock.py` passes explicitly), so repeated ad-hoc CLI invocations overwrite one file instead of leaking up to 1440 `render-HHMM.png` siblings across a day. Pass an explicit path when you want a persistent per-time artifact. The PNG is encoded to a `BytesIO` and written via `atomic_io.atomic_write_bytes` so a power cut mid-save can't leave a truncated frame for the next tick (and for `display_inky.py`) to read. The underlying PIL `Image` is explicitly `close()`d after encoding to release the file handle — important over months of continuous operation.
- **Hot-path caches.** `fit_quote` calls `load_font` up to 18 times per render with the same candidate chain at different sizes; without memoisation that's 36 path-existence scans + 36 `ImageFont.truetype` opens per render. `_FONT_CACHE` keys on `(normalised_candidates, size)` so repeats are O(1), and the variation tuple form `(path, "Bold")` keys distinctly from the plain string so a per-theme variable-font Bold/Regular split stays isolated. **The bitmap fallback is deliberately NOT cached** — a transient miss (NFS hiccup, brief filesystem unavailability) would otherwise pin the subprocess to degraded rendering for its lifetime, and `contact_sheet.py` renders 144 frames in one process. Time-phrase regex compilation moved to module load (`_TIME_PHRASE_PATTERNS`, sorted longest-first), and `_direct_match_pattern` shares one compiled pattern between `resolve_display_match` and `tokenize_quote` instead of recompiling per call. `wrap_styled_text` memoises space widths per font-id within a single call (a 140-char quote has ~25 spaces × 18 fit iterations × 2 fonts → ~450 redundant `textbbox` calls per render before the memo). The `_FONT_CACHE` lifetime is the renderer subprocess (single-threaded), so no FD-leak risk; `tests/test_render_quote.py` clears it autouse around every test so cache state from a prior test can't mask path-existence assertions in the current one.

### Synthesising colours outside the Spectra 6 palette

See [`spectra6_color_recipes.md`](spectra6_color_recipes.md) for the full recipe catalogue (in-use + reachable-but-unused), calibrated panel-ink values, the octahedron colour model, and the step-by-step authoring playbook. The table below is the short in-use-only reference for code readers; the linked doc is the forward-looking reference for theme authors.

Spectra 6 only has six inks (white / black / red / yellow / blue / green). Any other colour a theme wants — orange, mint, purple, sky blue, brown — must be **synthesised in software** by interleaving two natives on a stipple pattern. The PNG stays fully on-palette so `snap_image_to_palette` and the panel's own internal dithering pass don't re-quantise it into something else, and the eye averages adjacent pixels into the perceived mixed colour at panel-viewing distance (1–3 m for the LitClock appliance).

**Principle.** Decompose the target colour into a weighted mix of the nearest base inks, then paint each pixel as exactly one base ink chosen so the local density matches the weights. Reference framework: [Frans-Willem/epd-dither](https://github.com/Frans-Willem/epd-dither) treats RGB as an octahedron with the six inks at the vertices and any interior point as a barycentric mix. Confirmation in the Spectra 6 community ("Beyond 6 Colors" / `epdoptimize` / Pimoroni forum): the same approach extends the visible palette to ~12–13 usable colours total. **Caveat:** the panel's measured-ink RGB drifts per unit (calibrated values from `Utzel-Butzel/epdoptimize`: panel red ≈ `#62201E`, yellow ≈ `#C1BB1E`, blue ≈ `#233F8E`, green ≈ `#35563A`, black ≈ `#1F2226`, white ≈ `#B9C7C9`), so the recipes below are **textbook starting points**, not pixel-perfect specs — bias toward the more-saturated ink if a result reads washed-out at panel distance.

**Patterns.** `draw_text_dithered` already supports all three branches and `BAYER_4x4` is the shared 4×4 ordered matrix for the third. For ratios above 50%, swap `dark`/`light` and pass the complementary density (e.g. "5/8 yellow + 3/8 red" = `dark=yellow, light=red, light_density=0.375`).

| Pattern | "Light" density | Trigger | Visual signature |
|---|---|---|---|
| Sparse 1-in-4 (`x%2 == 0 and y%2 == 0`) | 25% | `light_density <= 0.25` | Subtle wash of "light" over dominant "dark" |
| 4×4 ordered Bayer (`BAYER_4x4[y%4][x%4] < round(d*16)`) | any `d ∈ (0.25, 0.5)` | `0.25 < light_density < 0.5` | Biased mix dispersed across a 4×4 tile |
| 1×1 checkerboard (`(x+y) & 1`) | 50% | `light_density >= 0.5` | Equal-weight midpoint of two inks |

**Two-ink recipes** (named tones the literature consistently cites; **In use** column flags which themes already pull each recipe today).

| Synthesised colour | Recipe | Pattern call | In use |
|---|---|---|---|
| Tangerine / warm orange | red + yellow at 5/8 : 3/8 | `dark=red, light=yellow, light_density=0.375` | `deco` (body matched phrase + border post-pass); `atomic` (mid-edge starburst rays — bbox-scoped post-pass flips ~3/8 of the painted red to yellow per Bayer threshold 6/16; atom-symbol orbits stay solid red for ray-vs-orbit contrast); `alchemy` (🜂 Fire element triangle at the BL of the transmutation circle); `grimoire` (☉ Sun mid-edge sigil) |
| Pure orange / amber | red + yellow at 1/2 : 1/2 | `dark=red, light=yellow` (default density) | — (was deco's previous recipe; reads as washed-out amber because yellow's higher luminance dominates) |
| Pink / coral | red + white at 1/2 : 1/2 | `dark=red, light=white` | `placard` (thumbtack corner-accent post-pass — weathered hand-painted red); `chalkboard` (eraser-smudge dots along the bottom inner edge — leftover pink eraser-stub residue) |
| Candlelit red | red + white at 3/4 : 1/4 | `dark=red, light=white, light_density=0.25` | `grimoire` (matched phrase only); `gothic` (matched phrase only — shares the candlelit-rubric signature with grimoire, the complementary-polarity blackletter sister) |
| Mint | green + white at 1/2 : 1/2 | `dark=green, light=white` | `nightvision` (body / attribution / ornament); `marker` (left mid-edge dot — highlighter wash) |
| Purple / violet | red + blue at 1/2 : 1/2 | `dark=red, light=blue` | `alchemy` (matched phrase; 🜁 Air element triangle); `grimoire` (♀ Venus mid-edge sigil); `illuminated` (matched phrase — Tyrian purple of the medieval scriptorium); `risograph` (matched phrase — authentic riso double-pass overprint, preserves no-black-ink invariant); `marker` (right mid-edge dot — "second marker dragged over first" overlap) |
| Sky blue | blue + white at 1/2 : 1/2 | `dark=blue, light=white` | `glacier` (corner frost-crystal diagonal-shard tip post-pass); `alchemy` (🜄 Water element triangle at the TR of the transmutation circle); `grimoire` (☽ Moon mid-edge sigil — disc painted in blue sentinel, post-passed for the cool argent / silver-blue of lunar work) |
| Cyan | green + blue at 1/2 : 1/2 | `dark=green, light=blue` | `glacier` (matched phrase — body green fill rerouted in `_draw_text_body` to a 50/50 G+B stipple, reads as aurora teal completing the cool palette gradient body-blue → matched-cyan → ornament-sky) |
| Brown / sepia | red + green at 1/2 : 1/2 (mute further with black) | `dark=red, light=green` | `saloon` (foxing speckles via `(px+py)&1` parity over `_SALOON_FOXING` reads as rust-brown aged-paper foxing; outer 3 px wanted-poster frame painted in red then its 4 edge strips post-passed to flip half to green per parity so the rule reads as rusted iron); `placard` (outer sign-painter's frame — perimeter post-pass flips half of the red 1 px rule's pixels to green so the rule reads as weathered sandwich-board wood); `dispatch` (alternating tractor-feed perforations — every other pair painted as red sentinel circles then bbox-post-passed for "carbon-paper bleed" oxidation); `newsprint` (Layer 0 foxing speckles — 1 red + 1 green pixel per 4×4 Bayer tile at cell values 2 and 3, blends at panel distance into pale lignin-oxidation rust-brown alongside the existing 12.5% black halftone) |
| Dark green | green + black at 1/2 : 1/2 | `dark=green, light=black` | — |
| Olive | yellow + green at 1/2 : 1/2 | `dark=yellow, light=green` | `roman` (laurel-sprig leaves on the corona triumphalis — bbox-post-pass for canonical Mediterranean laurel); `alchemy` (🜃 Earth element triangle at the TL of the transmutation circle — green earth pigment) |
| Lime | yellow + green at 5/8 : 3/8 | `dark=yellow, light=green, light_density=0.375` | `nightvision` (matched phrase — yellow-biased green stipple, reads as brighter tactical-readout neon glow) |
| Sage | green + white at 1/4 : 3/4 (inverted) | `dark=white, light=green, light_density=0.25` | `nightvision` (scanlines — bbox post-pass flips ~25% of the painted green to white, so scanlines read as ambient ground glow rather than crisp CRT lines) |
| Cream | yellow + white at 1/2 : 1/2 | `dark=yellow, light=white` | `dispatch` (Layer 0 ground wash); `gothic` (mid-edge border diamonds — candle-flicker warmth); `illuminated` (Layer 0 ground wash); `deco` (rising-sun fan inner rays — 2-tone gradient post-pass flips remaining red to white near the centre dot, simulating a true sunburst's bright core) |
| Navy | blue + black at 1/2 : 1/2 | `dark=blue, light=black` | `bauhaus` (matched phrase — tighter-contrast deeper-blue against the newly-yellow BL corner triangle) |
| Maroon | red + black at 1/2 : 1/2 | `dark=red, light=black` | `dispatch` (rubber-stamp imprint); `gothic` (corner quatrefoil lobes); `chanbara` (rising-sun disc rim + chop seal); `grimoire` (♂ Mars sigil); `blueprint` (matched phrase); `scholar` (matched phrase) |
| Lavender (3-ink) | red + blue + white at ~1/3 each | (via per-pixel 4×4 Bayer partition: cells 0-4 → red, 5-9 → blue, 10-15 → white) | `risograph` (shifted-accent registration crosses — paler "overprint" register-mark tone, preserves no-black-ink invariant) |
| Plum | red + blue + black at ~1/3 each | (3-ink — via per-pixel 4×4 Bayer partition: cells 0-4 → red, 5-9 → blue, 10-15 → black) | `illuminated` (corner cabochon "jewels" — each filled circle painted in an off-palette sentinel, then bbox-post-passed through the 3-way partition. Reads as the wine-dark lapis cabochons inset on the most precious medieval bindings) |
| Light orange | red + yellow + white at 2/5 : 2/5 : 1/5 | (3-ink — not supported by `draw_text_dithered`; for swatch-rectangle fills use `_fill_swatch_stipple_3way`) | — |

Three-ink mixes (e.g. plum, light orange) need a Bayer partition into three regions rather than two; `draw_text_dithered` only handles the two-ink case. `_fill_swatch_stipple_3way` covers rectangular swatch fills (used by the `diags` theme's reference panel); the `illuminated` corner cabochons inline the same 3-way Bayer pattern at the per-pixel level for ellipse fills via a sentinel-paint-then-post-pass loop. Add a polygon-aware helper if a future theme needs 3-ink text strokes.

**Designing a new themed accent.**

1. **Pick the target.** Sketch it as a sum of two nearby Spectra 6 inks. The table above covers most named tones; if the target isn't listed, pick the two natives that bracket it on the colour wheel.
2. **Estimate the dominance ratio.** If the two inks have asymmetric luminance (yellow >> red, white >> any chroma, black << any chroma), bias toward the *less* luminous ink so the perceived hue lands on the target rather than on the brighter ink. The deco fix is the canonical example: 50/50 red+yellow looked amber, 5/8 red + 3/8 yellow reads as tangerine.
3. **Choose the pattern** from the patterns table. Start at 50/50 if you don't have a strong prior; move to a 4×4 Bayer biased ratio if 50/50 reads washed-out at panel distance.
4. **Wire it in.** Body text accents: extend `_draw_text_body`'s per-theme switch with another `elif theme == "<name>" and fill == SPECTRA6[<dominant>]: draw_text_dithered(...)`. Decorative graphics: paint the shape in the dominant ink, then do a `BAYER_4x4[y%4][x%4] < threshold and pixels[x, y] == dominant` post-pass to flip the minority pixels to the lighter ink (`draw_deco_border`'s final pass is the reference).
5. **Saturation tier.** Also bump `display_inky.THEME_SATURATION["<theme>"]` to `0.7` if the accent needs to stay punchy against a non-white ground; `0.5` is the gentler tier for solid-red-on-white themes (the `deco` recipe deliberately stays at `0.5` because the red-biased Bayer already corrects the perceived hue without a saturation bump).
6. **Test.** Add a `TestDrawTextDithered`-style ratio assertion if the recipe is novel; add the theme to the renderer golden suite (`tests/test_render_golden.py`) if you want a visual regression fence.

### Runtime Loop (`run_clock.py`)

**Config file (`--config PATH`).** `parse_args()` supports a TOML config whose keys mirror the argparse `dest` names one-for-one (snake_case: `display_script`, `quiet_start`, `web_bind`, …). Loaded via `runtime_config.load_config` before the real parse, the file's values are fed into `parser.set_defaults(**config_dict)`; argparse's own rule that "the default is used only when the flag is absent from argv" delivers the three-layer precedence — **CLI flag > config value > argparse default** — without any custom merge layer. `load_config` takes a `choices_map` extracted from `parser._actions` so `choices=`-gated keys (`mode`, `theme`) validate at load time instead of silently propagating a typoed value into the render subprocess; `_valid_hhmm` is injected the same way. One asymmetry: `store_true` flags (`buttons_off`, `quiet_off`) can only be *enabled* by the CLI, since argparse has no paired `--no-*` variant, so a config that sets them `true` can't be overridden from the shell. Three transient flags are deliberately refused in the file (`--config` itself, `--once`, `--skip-preflight`); listing them warns and drops. Malformed TOML, unreadable contents, a non-table root, unknown keys, type mismatches, and choice-miss values all warn to stderr and continue with argparse defaults, mirroring `apply_content_overrides.load_overrides`'s fail-open pattern. The one hard error is pointing `--config` at a non-existent path: that raises `SystemExit(1)` at startup because a typoed unit-file path is a configuration bug the operator wants to hear about, not a silent-defaults signal. The shipped `litclock.service.example` passes `--config %S/litclock/config.toml` exclusively; see `assets/config.toml.example` for every supported key.

Thin orchestrator. Each tick (`--interval-seconds`, default 60) it computes the current fuzzy bucket; only when the bucket *changes* does it consider re-invoking `render_quote.py`. Before launching the renderer it calls `peek_quote_id` — which runs `pick_quote.select_quote` in-process and returns `(source_id, line_number, display_quote, matched_text)` — and compares that identity tuple against `last_quote_id`. `matched_text` is part of the identity because the renderer uses it to choose which phrase gets bolded/coloured, so two picks that share source/line/quote but differ in the matched phrase (e.g. `02:50` vs `02:55` landing on the same row) still produce visibly different frames and must not dedupe together. If the picked quote is unchanged, the redraw is skipped so the eInk panel is not refreshed for a visually-identical frame. Otherwise it re-renders and optionally hands the image to `--display-script` (e.g. `display_inky.py`). `--mode` and `--theme` are passed through to the renderer. `--once` renders a single frame unconditionally and exits — useful for cron, smoke tests, or first bring-up. In loop mode `render_now` and quiet-hours handling are wrapped in `try/except` with timestamped stderr logging so a transient failure (missing corpus row, Pillow blow-up, Inky disconnect) no longer kills the process — the loop just logs and waits for the next tick. `--once` stays strict so cron callers still fail loudly.

**Quiet hours.** Defaults to 22:00–06:00 (`--quiet-start` / `--quiet-end`, validated as `HH:MM` at parse time and supporting overnight ranges where `start > end`). When the loop first enters the window it dispatches on `--quiet-image` (default `assets/goodnight.png`):
- `<path>` (the default) — copies the static PNG to `--output` and pushes it to the display. Backward-compatible with the original goodnight contract; the bundled `assets/goodnight.png` is a pre-rendered dark-theme "sleep" frame.
- `"auto"` — re-renders an in-theme goodnight frame on the fly via `render_quote.py --mode goodnight`. Operators running an operator-choice theme (e.g. `scholar`, or `--theme auto --auto-night-theme nightvision`) opt in here so the goodnight frame matches the rest of the UI rather than always sliding in a black PNG. Routed through `render_now` so the entry telemetrises identically to a normal render (`render_ms` / `display_ms` / `mode=goodnight`).
- `""` (empty string) — renders the picked quote at `quiet_start` (last-quote-of-the-night).

It then sits idle, skipping picks and renders, until the window ends; on exit it clears the bucket/quote-id state so the next normal tick is guaranteed to repaint. `--quiet-off` disables the feature entirely for 24/7 operation. `--startup-image` accepts the same three-way choice (path / `"auto"` / unset).

**Anti-repeat ledger.** After each successful render the loop appends `(timestamp, source_id, line_number)` to `--history-path` (default `~/.litclock/history.jsonl`, 7-day window via `--history-days`). The next `peek_quote_id` / `render_now` pair reads that ledger and filters out rows shown within the window, so the same quote is not repeated that week. The ledger write happens only after the render subprocess returns 0, so a crash mid-render leaves the ledger untouched; quiet-hours renders and dedup-skipped ticks also do not append. Pass `--history-path ""` or `--history-days 0` to disable.

**Auto-dark theme (`--theme auto`).** Picks the night-window theme between 18:00 and 06:00 (`AUTO_DARK_START_HOUR` / `AUTO_DARK_END_HOUR`) and the day-window theme otherwise. The day/night picks are configurable via `--auto-day-theme` / `--auto-night-theme` (defaults `default` / `dark`, matching the legacy binary contract); broaden the rotation by setting one or both, e.g. `--theme auto --auto-day-theme scholar --auto-night-theme nightvision` for a "scholar by day, nightvision by night" appliance. The kwargs reject `"auto"` itself (would be a config typo, not a useful recursion). Each tick re-derives the effective theme from the wall clock via `auto_theme_for(time, day_theme, night_theme)`; a theme change is treated like a bucket change (forces a redraw even if the picked quote is unchanged). The button-B manual cycle (or web-UI dropdown) wins over the wall-clock derivation until the next midnight rollover, when `_maybe_reset_manual_theme_at_midnight` clears `manual_theme` and `auto` resumes. The shared helper `_auto_theme_kwargs(args)` is the single seam every `resolve_effective_theme` call site uses to thread the day/night picks through; `getattr` defaults preserve the legacy contract for ad-hoc test Namespaces that predate these flags.

**Random theme (`--theme random`).** Picks a fresh registered theme each time the displayed quote changes (so every new bucket / un-skip / re-render gets a different look). Picks come from a **shuffled bag** of the full theme cycle held on `RuntimeState.random_theme_bag` — `_maybe_pick_random_theme` drains one entry per quote change, and when the bag empties it's refilled with a fresh `random.shuffle` of `theme_cycle()`. This is the music-player "true shuffle" pattern: every theme is shown exactly once before any repeat. At the refill boundary, if the freshly-shuffled next pick (`bag[-1]`) would replay `RuntimeState.current_random_theme` (the just-played theme), it's swapped with another random index so back-to-back repeats don't sneak across the reshuffle. The pick is held on `RuntimeState.current_random_theme` for the lifetime of the displayed quote — `_maybe_pick_random_theme` is called once per loop tick and only re-rolls when `quote_id != state.last_random_quote_id` (or when `current_random_theme` is still `None` at startup). The gate uses `last_random_quote_id` (advanced synchronously by the picker), **not** `last_quote_id` (advanced only by `commit_render_result` on render success), so a render failure followed by retries on the same `quote_id` is idempotent: without that split, every failed retry would drain another bag entry while no theme had actually been shown, silently losing themes from the visible pass. The theme picked on a failed-render tick is held on `current_random_theme` and used by the eventual successful render, so a bag draw maps 1:1 to a displayed theme even across N failed retries. Neither the bag nor the current pick is **persisted** to `state.json`: a `systemctl restart` therefore starts a fresh pass on the first render rather than redrawing the same panel. The button-B manual override (and the web-UI dropdown) wins over the random pick the same way it wins over `auto`, and `_maybe_reset_manual_theme_at_midnight` clears the manual override at midnight when `theme_arg` is `"auto"` or `"random"` so either mode resumes after an operator's day-long override expires. `action_skip` and `action_unskip` flow through the same gate, so a button-A tap re-rolls the random theme alongside the new quote. The `--once` path and the `resolve_effective_theme` fallback (for callers without bag state) still go through the uniform `pick_random_theme()` since a single-frame render has nothing to no-repeat against.

**Inky buttons (`inky_buttons.py`).** The four capacitive buttons on the Inky Impression are wired to GPIO 5/6/16/24 (labels A/B/C/D) and dispatched by `inky_buttons.start_listener(short_handlers, hold_handlers=..., press_logger=...)` using `gpiozero.Button` with a 0.3-second debounce and a 2-second hold threshold. The hardware import is local to `start_listener` so the module is import-safe on dev hosts. `run_clock.py` builds the short/hold handler dicts in `_build_button_handlers` and stashes the returned keepalive list for the lifetime of the loop — `gpiozero` drops handlers when its `Button` is garbage-collected, so the reference must be held. Handlers act synchronously in the listener thread and serialize against the main loop via `state.render_lock`; mutations of theme/quiet flags are guarded by `state.lock`. Pass `--buttons-off` on dev machines or for headless runs.

Short-press vs long-press dispatch is routed through a tiny `_HoldDispatcher` so the short callback fires on *release* only when the button was not held long enough to trigger the hold callback — a long press therefore fires only the hold action, never both.

**Drop-on-busy press gate.** Every button handler wraps its work in `run_clock._button_render_gate`, which does a *non-blocking* acquire of `state.render_lock`. If a render is already in flight (a Spectra 6 refresh can take 10–20s), the press is logged (`"button {name}: busy (render in flight), press ignored"`) and dropped. Without this, gpiozero queues subsequent events behind the slow eInk refresh and a tap-burst produces unpredictable multi-second delayed actions; with it the UX is "first press wins, subsequent presses during the refresh are no-ops."

**Per-press GPIO logging.** `start_listener` accepts an optional `press_logger(label, gpio_pin)` callback that fires on every hardware press, before short/long dispatch and independent of handler exceptions. `run_clock._maybe_start_buttons` wires it to a `_press_logger` that logs `"press: {label} (GPIO {pin})"`, so a field operator can grep the journal to confirm a physical button actually fired before blaming handler code. For deeper wiring diagnosis use `probe_buttons.py` (standalone — doesn't need the main loop to be running).

**Liveness supervision.** gpiozero runs its event loop on a background thread; if that thread dies or the pin claim is lost (flaky GPIO, post-reboot race, another process grabbing the pin) `Button.closed` flips to `True` and presses silently stop working. Each tick the main loop calls `_check_button_liveness`, which consults `inky_buttons.buttons_alive(state.button_handles)`. On the first failure it logs a loud stderr warning, appends `{"mode": "buttons_dead", "error": "button listener died"}` to telemetry, and latches `state.buttons_dead_logged` so subsequent ticks stay quiet. We deliberately do **not** auto-restart — a listener that died once often dies again immediately and a restart loop would thrash GPIO claims.

**Handler-exception containment.** `_make_press_cb` and `_HoldDispatcher.on_hold`/`on_release` wrap their dispatch calls in `try/except` — a raising handler (press, hold, or release) logs the traceback on stderr and returns instead of propagating into the gpiozero event thread. Without this, a bug in any action handler (e.g. a botched `action_theme` exception path) would silently kill the listener, and because `Button.closed` might not flip in that case, `buttons_alive()` could still report healthy. Loud-and-alive is always preferred to silent-and-dead.

| Button | Short press | Long press (2s) |
|---|---|---|
| **A** | Skip — bans the current quote in the history ledger, picks again, re-renders. Records the just-banned quote as `state.last_skipped`. | Un-skip — removes the last-skipped quote's entry from the history ledger and re-renders. Reverses a fat-fingered tap. |
| **B** | Cycle theme — advances one step through `render_quote.THEME_ORDER` (default → dark → scholar → newsprint → nightvision → blueprint → illuminated → bauhaus → risograph → comic → default), persists to `--state-path`, re-renders. Web UI dropdown jumps to any named theme directly via POST body. | — |
| **C** | Source card — renders a `--mode card` overlay (title / author / Gutenberg ID / matched phrase) for 5 seconds, then the timer thread itself re-renders the original frame (the next loop tick alone could be up to 60s away). | — |
| **D** | Quiet now / wake — toggles `manual_quiet`, persists to `--state-path`. Going quiet pushes `--quiet-image` immediately; going active picks and renders the current time. | Shutdown — shows `--quiet-image`, then runs `--shutdown-command` (default `sudo -n shutdown -h now`). Requires passwordless sudo for shutdown; override or empty the flag if you don't want this behaviour. |

**Persisted runtime state (`--state-path`).** `~/.litclock/state.json` (default) holds `manual_theme`, `manual_quiet`, and the render-identity triple `(last_bucket, last_quote_id, last_effective_theme)`. Loaded at loop startup so the user's last button-B / button-D choices survive a restart AND a mid-bucket `systemctl restart` does not force a redraw of the frame already on the panel — the dedup check at the top of the tick loop now has non-None state to compare against. Pass an empty string to disable. `save_runtime_state` writes atomically via the shared `atomic_io.atomic_write_text` helper: payload → sibling `*.tmp` file → `fsync` → `os.replace` into place → `fsync` of the parent directory. Without that final directory fsync the kernel can return from `os.replace` with the new dirent still in cache, and a crash in that window leaves the old/missing file despite the rename "succeeding." Directory-fsync failures are swallowed on platforms where they aren't meaningful (notably Windows).

The identity triple is persisted **after every successful render** (`_persist_state_after_render` runs at the end of `_render_unlocked` and at the end of the main-loop bucket-change branch), not just on shutdown, because a `SIGKILL` / power loss between renders otherwise reverts `state.json` to the last orderly-shutdown snapshot. The post-render persist is best-effort: a disk error is logged and swallowed so it can't bubble into the render path and trip the outer-loop backoff counter.

**Transient render modes don't commit identity.** `_IDENTITY_RENDER_MODES = frozenset({"production", "debug"})` gates both the `commit_render_result` write and the `_persist_state_after_render` call inside `_render_unlocked`. The button-C source-card overlay (`mode="card"`) is rendered to the panel but its `(bucket, quote_id, theme)` triple is deliberately **not** committed in-memory or persisted: if the process dies in the 5-second window before the restore timer fires, the next boot's dedup check would see the card's bucket match `last_bucket` and skip the redraw — pinning the card on the panel until the next bucket or theme change. Transient modes still reset the outer-loop failure backoff (the render itself succeeded) but neither commit nor persist.

**State validation on load.** `load_runtime_state` checks `state.json` against a small schema (`manual_theme: str|None`, `manual_quiet: bool`, `last_bucket: str|None`, `last_quote_id: list|None`, `last_effective_theme: str|None`). A malformed-but-parseable file (e.g. hand-edited with `manual_theme: 42`) drops the offending field and continues rather than bricking startup, and a validation event is written to the telemetry sidecar as `{"mode": "state_validation", "issues": [...]}` so `litclock_health.py` summaries surface the drift. Unknown top-level keys are flagged but preserved — a newer schema field can round-trip through an older install without being silently dropped.

**Single-instance pidfile (`--pidfile`).** `~/.litclock/run_clock.pid` (default) is locked via `fcntl.flock(LOCK_EX | LOCK_NB)` at main-loop startup. A second `run_clock` detecting the held lock logs the existing pid and exits 1 — overlapping `systemctl restart` cycles (or a botched boot that races a slow-to-die predecessor) otherwise have two processes writing to `state.json` / `history.jsonl` / the telemetry sibling concurrently, which `atomic_io`'s tmp-rename pattern does not protect against (it guards against crashes, not concurrent writers). A stale pidfile (locked by nothing, or pointing to a dead pid) is reclaimed transparently so the appliance can recover from a `SIGKILL` / power loss without manual intervention. Pass an empty string to disable the lock. The `--once` path deliberately skips the pidfile — a one-shot cron invocation should never block on a running loop instance.

**Pre-flight path checks.** `main()` validates that `--render-script`, `--display-script`, `--quiet-image`, and `--startup-image` exist on disk before the loop starts (or the one-shot frame renders). A missing path raises `SystemExit(1)` with a multi-line message listing every offending flag, so a typoed path in the systemd unit file fails fast in the journal instead of surfacing hours later on first bucket change or first quiet-hours entry. `--skip-preflight` bypasses the check entirely for unusual setups (CI smoke tests that don't ship the display script, dev hosts that intentionally point at an empty image, etc).

**Graceful shutdown (`SIGTERM` / `SIGINT`).** `_install_signal_handlers` binds both signals to a handler that flips `state.stop_requested` (a `threading.Event`). The main loop checks the flag at the top of each iteration and waits on it via `_loop_sleep` between ticks, so a `systemctl restart litclock.service` is observed within one tick instead of being escalated to `SIGKILL` mid-render. On loop exit `_shutdown` runs in a `finally`: first it cancels any pending timers (the button-C restore), then it blocks on `state.render_lock` up to 30s so any in-flight render finishes, and it **holds the render lock across ingress teardown** (`stop_web_server` + `gpiozero.Button.close`) so any late web POST or button callback that reaches `_button_render_gate` sees the lock held and drops with a `"busy"` response — without this, a press arriving in the teardown window could kick off a fresh render and reintroduce SIGKILL-mid-render risk under systemd's `TimeoutStopSec`. The lock is released only before the final state persist (which doesn't touch the render path). Every step is wrapped in `contextlib.suppress` — shutdown is best-effort so one teardown failure doesn't block the others. The finally also releases the pidfile lock so a replacement instance can start without operator intervention. `--once` also installs the signal handler (against a throwaway `RuntimeState`) so `atomic_io`'s write→fsync→replace sequence can complete even when systemd sends `SIGTERM` mid-render; a signal observed during the one-shot render produces exit code `143` (canonical SIGTERM exit) so cron / systemd one-shot units can distinguish "rendered cleanly" from "rendered then told to shut down."

**Subprocess timeouts (hang defence).** The render / display / shutdown children are invoked through `subprocess.run(..., check=True, timeout=...)` rather than `check_call`, because `run` kills the child on `TimeoutExpired` before re-raising — `check_call` leaves the zombie. Bounds: `RENDER_TIMEOUT_SECONDS=45`, `DISPLAY_TIMEOUT_SECONDS=60` (generous: a Spectra 6 refresh is 10–20s and `display_inky.py` internally retries 3× with up to ~5s backoff), `SHUTDOWN_TIMEOUT_SECONDS=30`. On timeout, the render/display path telemetrises `{"mode": "render_timeout"|"display_timeout", "timeout_seconds": N}` and re-raises into the main-loop error branch so `last_bucket` stays stale for retry next tick; the shutdown path logs + telemetrises but doesn't raise. `runtime_quiet._display_quiet_image` gets the same treatment (its own `DISPLAY_TIMEOUT_SECONDS` mirror, kept local to avoid circular import).

**Render-failure exponential backoff.** A tight retry loop after hard hardware failure (pulled ribbon, wedged I2C bus) floods the log and starves the GPIO thread. `RuntimeState.consecutive_render_failures` increments on every render/display exception; every `BACKOFF_EVERY_N_FAILURES=3` failures, `_record_render_failure` extends `state.backoff_skip_until` by `min(2**level, BACKOFF_MAX_SECONDS=900)` seconds and appends `{"mode": "backoff", "failures": N, "skip_seconds": S}` to telemetry. The main loop checks `_in_backoff_skip(state)` near the top of each tick and short-circuits to `_loop_sleep` when the deadline hasn't passed. `commit_render_result` (the single success seam) resets both the counter and the deadline so recovery is instant. Heartbeat and button-liveness checks keep running during the backoff window — the appliance is still observably alive.

**Error-log dedup latch.** Inside the backoff window the outer loop still retries every tick, so the same hardware fault would otherwise write an identical `repr(exc)` traceback to journald once a minute until a human intervened. `state.last_logged_error` caches the most recent `repr(exc)`; when the next failure matches, the stderr message and `traceback.print_exc` emission are suppressed — the *structured* telemetry entry is still written every time, so `litclock_health.py`'s `error_count` and `last_error` stay accurate. The latch clears on the next success via `commit_render_result`, so a genuinely new error after a recovery still logs loudly. This only dedupes the journald noise — the backoff counter and the telemetry stream are orthogonal.

**Loop heartbeat.** `runtime_telemetry.append_heartbeat` emits `{"type": "heartbeat"}` entries so `litclock_health.py` can tell "idle but alive" apart from "wedged." The main loop calls `_maybe_emit_heartbeat` each tick, throttled to `HEARTBEAT_INTERVAL_SECONDS=60` of wall-clock spacing via `state.last_heartbeat_monotonic` (so a 1s test loop emits once; a 60s appliance loop also emits ~once per tick). `litclock_health.py --max-heartbeat-age-minutes N` exits 2 when the most-recent heartbeat is older than the cap, or absent entirely (covers pre-heartbeat code and pre-first-emit wedges). Heartbeats are excluded from `render_count` / `error_count` — they answer a different question.

**systemd watchdog (`sd_notify.py`).** The heartbeat call also pets systemd's `WatchdogSec` timer via `sd_notify.notify_watchdog()` ("WATCHDOG=1") when `$NOTIFY_SOCKET` is set in the environment. `sd_notify.py` is a minimal pure-stdlib `AF_UNIX` datagram client — no `systemd-python` dep — so off-systemd (dev hosts, unit tests, `--once` runs outside the supervisor) the call is a no-op. `main()` additionally sends `READY=1` after buttons / web server / signal handlers are armed so a `Type=notify` unit's `systemctl start` only returns once the appliance can actually answer SIGTERM / GPIO / HTTP cleanly. The heartbeat-and-watchdog pairing means a wedged-but-breathing loop produces the same silence that `litclock_health.py` flags AND that `WatchdogSec` restarts on — one liveness signal, two consumers. `litclock.service.example` ships `Type=notify` + `WatchdogSec=180s` (3× the 60s heartbeat cadence) plus `StateDirectory=litclock` (so `--state-path` / `--history-path` / `--telemetry-path` / `--pidfile` resolve under `/var/lib/litclock/` instead of `~/.litclock/`) and a modest sandbox (`NoNewPrivileges=yes`, `ProtectSystem=strict`, `ProtectHome=read-only`, `PrivateTmp=yes`, etc.) — note that `NoNewPrivileges=yes` blocks setuid binaries, so the button-D `sudo -n shutdown` default must be swapped for `systemctl poweroff` under the sandbox (see the service file's "Button-D shutdown vs sandboxing" note). The unit also declares `RestartPreventExitStatus=42` — **not** `RestartForceExitStatus` (which has the opposite semantics) — reserved for a future "configuration error, do not restart" signal so a terminal config bug doesn't flap against `Restart=always`.

**Pending-timer cancellation on shutdown.** The button-C source-card 5s restore `threading.Timer` registers itself on `state.pending_timers` under `state.lock` before `timer.start()`; `_shutdown` drains that list and calls `.cancel()` on each before draining the render lock. Without this, a SIGTERM within 5s of a source-card press would let the daemon Timer fire after `_shutdown` tore down the display handles, racing the systemd restart with a stale frame push. `Timer.cancel` is idempotent, and the timer deregisters itself on normal fire, so double-cancellation is safe.

**Telemetry sidecar (`--telemetry-path`).** `~/.litclock/telemetry.jsonl` (default) is the **base path**; `append_telemetry` actually writes to a date-rotated sibling `<stem>-YYYYMMDD<suffix>` in the same directory (e.g. `~/.litclock/telemetry-20260420.jsonl`). Rotation keeps each file bounded so a multi-year-running appliance doesn't produce a single unbounded JSONL that chokes health checks and stalls append latency. Each entry is one JSON line:

- successful renders write `bucket`, `render_ms`, `display_ms`, `source_id`, `line_number`, `mode`, `theme`;
- loop-level render/display errors write `bucket`, `error`, `mode`; backoff events write `bucket`, `mode="backoff"`, `failures`, `skip_seconds`; timeouts write `mode` suffixed `_timeout` plus `timeout_seconds`;
- loop-liveness markers write `{"type": "heartbeat"}`;
- **operator actions** (button press or web POST) write `mode="action"`, `action` (skip/unskip/theme/quiet/rerender), `label` (`"button A"` / `"web"`), `ok`, optional `error`. Busy-drops coalesced by `_button_render_gate` write a separate `mode="press_dropped"` with `label`, `action`, `reason="render_in_flight"` — a rejected press never double-counts as both an `action` and a `press_dropped`;
- **web auth failures** write `mode="web_auth_fail"` with `remote`, `path`; 4xx/5xx web responses write `mode="web_error"` with `status`, `path`, `error`. Web errors are deliberately kept out of the render `error_count` — the render pipeline and the operator-action pipeline are summarised separately;
- **quiet-hours transitions** write `mode="quiet_enter"` (with `manual: bool`, `bucket`) at the rising edge and `mode="quiet_exit"` at the scheduled falling edge. Manual toggles also surface as `action` entries; the state machine re-triggers enter/exit on the next tick so the counts stay balanced.

Telemetry writes are best-effort — I/O failures log and drop the entry rather than crashing the loop. Pass an empty string to disable.

**Fsync-on-render, no-fsync-on-heartbeat.** `append_telemetry` flushes and `os.fsync`'s the entry before close so a SIGKILL / power loss immediately after a render or wedge event can't leave the line buffered in the kernel — that's exactly when `litclock_health` needs the last few entries to distinguish "wedged" from "idle." `append_heartbeat` deliberately routes through the same `_append_entry` helper with `fsync=False`: heartbeats fire ~once a minute and losing the last minute of "alive" pings to a power cut is recoverable, but fsyncing every one would multiply SD-card write amplification on a long-running appliance. Render / error / action / backoff / timeout / quiet-transition entries all keep the fsync path; only heartbeats opt out. Two regression tests in `tests/test_run_clock.py::TestAppendTelemetry` (`test_render_entry_calls_fsync` and `test_heartbeat_skips_fsync`) pin the split.

**Telemetry retention (`--telemetry-retain-days`, default 90).** Rotation bounds per-file size but not total file count. Once per local-date rollover the loop calls `prune_telemetry`, which globs the base path's parent for `<stem>-YYYYMMDD<suffix>` siblings, parses the date from the filename, and `unlink`s anything older than `today - retain_days`. The trigger is gated by `state.last_pruned_date` so we don't glob every tick. `litclock_health.py`'s summariser walks the same directory on every invocation, so unbounded retention eventually slows it down. Pass `0` to disable pruning entirely (e.g. for long-term forensic retention to external storage).

`litclock_health.py` globs the base path's directory for date-suffixed siblings (plus any legacy unsuffixed file at the exact base path) and stream-reads them in sorted-filename order. It prunes files older than the `--hours` window by filename date alone, with one day of slack so operators east/west of UTC don't accidentally drop the active file near midnight UTC (the per-entry `ts` filter in `load_entries` enforces the exact cutoff). Siblings that match the glob but whose date suffix doesn't parse as `YYYYMMDD` are skipped — pointing `--telemetry-path` at a file directly is the supported way to summarise an arbitrary JSONL. `render_count` is **positively identified** by the presence of an integer `render_ms` field — not by "non-error entry" — so `mode="backoff"` / `render_timeout` / `display_timeout` / `buttons_dead` / `state_validation` and other non-render telemetry modes stay out of the count (previously a backoff entry inflated `render_count` and an "errors but zero renders" appliance could read healthy). Summary output includes render count, error count, heartbeat count + last-heartbeat timestamp, p50/p95 render and display latency, last error message, and the **operator-action breakdown** added in phase 4: `action_count`, `actions_by_type`, `last_action_ts`, `press_dropped_count`, `web_auth_fail_count`, `web_error_count`, `quiet_enter_count`, `quiet_exit_count`. `--json` emits the same fields for cron/systemd integration. `--actions-only` renders an operator-centric "what did the user do?" view (shape-stable even on empty windows for grep-based cron); `--json` output shape is unchanged regardless of the flag. Exit codes: `0` healthy, `1` no telemetry log, `2` unhealthy (errors but zero renders in the window; `--fail-if-no-renders` was set and the window was silent; or `--max-heartbeat-age-minutes N` was set and the most recent heartbeat is older — or absent entirely).

**Startup frame (`--startup-image`).** Optional frame pushed to the display once at loop startup, before the first quote render, so the panel doesn't ghost yesterday's frame during cold boot. Off by default (a Spectra 6 refresh takes 10–20s, so the extra round-trip isn't always worth it). Same three-way semantics as `--quiet-image`: a `<path>` copies a static PNG; `"auto"` re-renders an in-theme goodnight frame on the fly via `render_quote.py --mode goodnight` (honours any persisted `manual_theme` from a prior session so an operator's button-B choice survives reboot); unset skips the startup frame entirely. The pre-flight existence check skips the `"auto"` sentinel so a typoed path still fails loudly while the new sentinel doesn't.

#### Runtime Module Architecture

`run_clock.py` is a thin orchestrator. The logic it used to own is split across seven focused siblings plus the shared `RuntimeState` class — keep the boundaries tight or the "distributed spaghetti" hazard bites back.

| Module | Owns | Imports from siblings |
|---|---|---|
| `runtime_log` | `_log` (timestamped stderr/stdout logger) | — |
| `runtime_state` | `RuntimeState` class, three locks, `commit_render_result` | — (stdlib only) |
| `runtime_store` | `load_runtime_state` / `save_runtime_state` (atomic via `atomic_io`) | `runtime_log` |
| `runtime_telemetry` | `append_telemetry`, `append_heartbeat`, `prune_telemetry`, `daily_telemetry_path`, date-rotated JSONL | `runtime_log` |
| `runtime_quiet` | `in_quiet_hours`, `_display_quiet_image`, `compute_quiet` / `enter_quiet` / `exit_quiet` state machine | `runtime_log`, `runtime_state`, `runtime_theme` (+ lazy `run_clock` for `_display_quiet_image` / `render_now` / `append_telemetry`) |
| `runtime_theme` | `resolve_effective_theme`, `auto_theme_for`, `_maybe_reset_manual_theme_at_midnight` | `runtime_log`, `runtime_state` (+ lazy `run_clock` for midnight persist) |
| `runtime_actions` | `action_skip/unskip/theme/quiet/rerender`, `_button_render_gate` | `runtime_log`, `runtime_state`, `runtime_theme`, `runtime_quiet` (+ lazy `run_clock` for peek/render/telemetry) |

**Invariant:** every `runtime_*` module imports ≤4 siblings at module load (the dispatch layer in `runtime_actions` touches the most — log, state, theme, quiet — because it coordinates them), and only `runtime_actions` / `runtime_theme` / `runtime_quiet` touch `run_clock` — and only via `import run_clock` inside a function body, never at module top.

**Theme-name lookups go through `theme_names`.** `runtime_state` (validating persisted `manual_theme`), `runtime_theme` (gating the manual-override path in `resolve_effective_theme`), `runtime_actions` (advancing the button-B / web cycle), and `web_server._api_themes` all need either the registered-themes set or the curated cycle order. They previously each inlined a `try: from render_quote import THEMES except: ("default", "dark")` block — the fallback types had drifted (`frozenset` vs `tuple`) and the same import logic was reproduced in four places. `theme_names.known_theme_names()` and `theme_names.theme_cycle()` are the single source-of-truth wrappers; the lazy `from render_quote import …` is preserved (inside the helper bodies, not at module top) so importing these helpers still does not pull Pillow into the main-loop import graph.

**Three locks, nested only in the documented direction.** `RuntimeState` exposes exactly three `threading.Lock`s:

- **`render_lock`** — coarse. Serialises anything that pushes a frame to the panel (a Spectra 6 refresh can take 10–20s). The main loop acquires it blocking around `render_now`; button and web handlers acquire it *non-blocking* via `_button_render_gate` so a second press during a refresh drops rather than queues.
- **`state.lock`** — fine. Protects the mutable fields on `RuntimeState` (`manual_theme`, `manual_quiet`, `last_bucket`, `last_quote_id`, `last_effective_theme`, `last_skipped`, `last_seen_date`, `last_pruned_date`). `commit_render_result` is the single seam that writes the `(last_bucket, last_effective_theme, last_quote_id)` triple atomically; the two intentionally-partial writes (the "quote unchanged" branch that only updates `last_bucket`, and the cold-start `last_effective_theme` prime) are inline.
- **`ledger_lock`** — file I/O. Serialises every read-modify-write on `~/.litclock/history.jsonl`. `run_clock._append_history_after_render` is the single seam for ledger appends; button A's long-press un-skip and the skip action both route through it too. `pick_quote.remove_last_history_entry` takes it for the rewrite path.

Nesting discipline: `state.lock` is allowed inside `render_lock` (the main loop holds `render_lock` while `_render_unlocked` → `commit_render_result` briefly takes `state.lock`; the action handlers do the same under `_button_render_gate`). `ledger_lock` is never nested with either of the other two — it's always acquired standalone, after both are released. A subprocess call (the `render_quote.py` fork) is never held under `state.lock` or `ledger_lock`.

**Thread ownership.**

- **Main loop thread** owns tick cadence. Exclusive writer of `state.last_pruned_date`, `state.last_seen_date`, and `state.was_quiet` (the rising/falling-edge tracker for quiet hours). Calls `_append_history_after_render` post-render; *never* holds `render_lock` while calling back into button/web actions.
- **Button listener thread** (started by `inky_buttons.start_listener`). Fires handlers synchronously. Every handler's body is an `action_*` function wrapped in `_button_render_gate` — so a tap during an in-flight render drops cleanly rather than queueing behind a 20s refresh.
- **Web server threads** (spawned by `http.server.ThreadingHTTPServer`). `POST /api/action/*` calls the *same* `action_*` functions with `label="web"`. Result dicts map 1:1 to HTTP status: `{ok: True}` → 200, `{error: "busy"}` → 409, `{error: "<repr>"}` → 500.

All three thread families converge on `action_* → _button_render_gate → _render_unlocked → commit_render_result`. There is no parallel "web render path" or "button render path" — this is the point of the refactor.

**Lazy `import run_clock` pattern.** `runtime_actions`, `runtime_quiet`, and `web_server` do `import run_clock` inside function bodies, not at module top, so Python's module-load graph stays acyclic (`run_clock` imports from each of them, but not vice versa at load time). The lookup resolves at call time against `run_clock`'s module globals — which is exactly where the test suite patches fakes (`patch("run_clock.peek_quote_id")`, `patch("run_clock._display_quiet_image")`, etc.). The re-export block at the top of `run_clock.py` exists *for this contract*: every name a test patches under `run_clock.X` is bound at that name. Names that are neither patched nor used internally have been dropped from the block — audit before adding more.

**Runtime call graph (one tick).**

```
main loop iteration
  ├─ _maybe_reset_manual_theme_at_midnight(args, state)      # runtime_theme
  ├─ _check_button_liveness(state, telemetry_path)
  ├─ _maybe_prune_telemetry(args, state, telemetry_path)     # runtime_telemetry
  ├─ _maybe_emit_heartbeat(state, telemetry_path)            # runtime_telemetry.append_heartbeat, throttled 60s
  ├─ if _in_backoff_skip(state): sleep; continue             # render-failure exponential backoff gate
  ├─ now_quiet, manual_only = compute_quiet(...)             # runtime_quiet
  │
  ├─ if now_quiet:  enter_quiet(...) on rising edge; sleep; continue
  ├─ if was_quiet: exit_quiet(state)                         # falling edge: clears last_bucket/quote_id
  │
  ├─ peek_quote_id(...)                                      # pick_quote
  ├─ with render_lock:  render_now(...)                      # subprocess: render_quote.py (timeout-bounded)
  │     └─ on render exception: _record_render_failure(...)  # increments counter; every N triggers skip window
  ├─ state.commit_render_result(bucket, theme, quote_id)     # runtime_state (takes state.lock; resets backoff)
  └─ _append_history_after_render(state, ...)                # run_clock (takes ledger_lock)

button press / web POST
  ├─ action_X(args, state, label=...)                        # runtime_actions
  ├─ with _button_render_gate(state, ...):                   # non-blocking render_lock
  ├─ [state.lock mutations]                                  # theme/quiet flip, persistence
  ├─ _render_unlocked(...)                                   # run_clock (in-gate)
  │     └─ commit_render_result(...)
  └─ _append_history_after_render(...)                       # skip/unskip/rerender only
```

Theme-toggle and quiet-toggle branches **do not** append to history — they repaint the same `quote_id`, so re-appending would double-record the quote. This is why `_append_history_after_render` lives in `run_clock` (not inside `_render_unlocked`): the caller chooses what (if anything) lands in the ledger. The main loop's bucket-change branch appends the newly-rendered quote; `action_skip` appends the *previous* quote (as a ban) *and* the freshly-picked replacement; `action_unskip` / `action_rerender` append the new pick; `action_theme` / `action_quiet` never append.

**Flip → display → persist ordering.** `action_theme` / `action_quiet` mutate the in-memory flag, push the render to the display, and only *then* `save_runtime_state` to `~/.litclock/state.json`. The two failure paths are split:

- If the render/display fails, the in-memory flip is rolled back so `state.json` stays in sync with what the panel is actually showing (otherwise a restart mid-failure would load the flipped state from disk, re-render, and silently counteract the user's reverted toggle).
- If the *persist* step fails after the panel has already updated, the flip is kept and the error is logged and swallowed. Matches the best-effort pattern in `_persist_state_after_render`: rolling back at this point would revert `manual_theme` / `manual_quiet` in memory even though the panel is already showing the flipped state, letting the next loop tick immediately counteract the operator's toggle — worse UX than an unsynced state file.

### Contact Sheet (`contact_sheet.py`)

Offline QA tool. For each of the 144 `h{1..12}_{state}` buckets, calls `pick_quote.select_quote` at the bucket's canonical `HH:MM` (e.g. `h3_twenty_past` → `03:20`; `h12_*` maps to `00:MM`), renders the full 800×480 frame via `render_quote.render`, and downscales it into a tile on a 12×12 grid. Each tile gets a small `HH:MM  h{hour}_{state}` caption below so you can locate specific buckets at a glance. Flags: `--tile-width`/`--tile-height` (defaults 200×120), `--caption-height` (18), `--margin` (6), `--theme`, and `--mode` — defaults to `production` so the debug footer doesn't dominate small tiles. History filtering is forced off (snapshot of the whole corpus, not anti-repeated picks). Use this to spot regressions after a corpus change: layout bugs, malformed `matched_text`, repeat authors in adjacent buckets, or fallback-bucket frames that look visually wrong.

### Inky Display Bridge (`display_inky.py`)

Minimal Pillow → Pimoroni `inky.auto` bridge. Loads the PNG, resizes to the panel's native size if needed, and calls `inky.set_image(..., saturation=...).show()`. Designed to be called once per render from `run_clock.py`. Only needed on the Pi. Up to `MAX_ATTEMPTS` (3) calls are retried with `RETRY_BACKOFF_SECONDS = (1, 4)` between attempts so a momentary I/O hiccup doesn't crash the caller; if all attempts fail the script raises `SystemExit` so the loop in `run_clock.py` logs and moves on.

**Per-theme saturation.** `THEME_SATURATION` maps every registered theme to a saturation hint the Spectra 6 panel renders differently on light vs dark backgrounds. Light white-ground themes (`default`, `scholar`, `newsprint`, `blueprint`, `illuminated`, `bauhaus`) use `0.5`; dark-background (`dark`, `nightvision`), coloured-ground (`comic` — yellow) and no-black two-colour (`risograph`) themes use `0.7` so their coloured accents stay crisp against a non-white / non-black-anchored ground. A cross-check test (`test_every_render_theme_has_saturation`) fails loudly if a new `THEMES` entry isn't mirrored here, so a fresh theme can't silently inherit the default saturation. `run_clock.render_now` forwards `--theme` to `display_inky.py`, which calls `resolve_saturation(theme, override)` to pick the value to push. An explicit `--saturation` always wins over the per-theme default.

### Curator Web UI (`web_server.py`, `web/`)

Optional in-process HTTP surface for browsing telemetry / coverage / candidates and curating the corpus end-to-end without SSHing into the appliance. As of v2 the UI is the full curation seat: it edits both override sidecars, re-bakes the runtime database, runs full-text search across the corpus, renders side-by-side theme previews, and surfaces empty/sparse buckets with phrase suggestions for the harvester. **Off by default** — only starts when `run_clock.py --web-bind HOST:PORT` is passed. Served from a `ThreadingHTTPServer` on a daemon background thread so the main render loop doesn't share an event loop with HTTP, but the two threads share `state.render_lock` / `state.lock` / `state.ledger_lock` via the same `RuntimeState` instance. **In-process is non-negotiable**: every mutating POST routes through the same `_button_render_gate` (non-blocking `render_lock.acquire`) that GPIO button handlers use, and atomic state/override writes are only safe when one process owns the file.

**Lifecycle.** `run_clock._maybe_start_web_server(args, state)` runs after `_maybe_start_buttons`, imports `web_server` lazily (so unit tests and `--buttons-off` dev hosts never pay for it), and calls `web_server.start_web_server(args, state, token=...)`. The `(server, thread)` handle is stashed so `stop_web_server` can be called by tests for deterministic teardown; the daemon thread flag means the process's own exit tears it down automatically under systemd. A startup failure (malformed bind, port busy, missing token on non-localhost bind) is **logged but not fatal** — the panel keeps rendering.

**Action handlers are shared with buttons.** Each GPIO button's body has been hoisted from `_build_button_handlers` closures into module-level `run_clock.action_skip` / `action_unskip` / `action_theme` / `action_quiet` / `action_rerender` functions. The button dispatcher and the HTTP handler both call them with a `label="button A"` or `label="web"` attribution string. Each function returns `{"ok": True, ...}` on success, `{"ok": False, "error": "busy"}` when the render lock is held, or `{"ok": False, "error": "<repr>"}` on exception; the web handler maps that to 200 / 409 / 500. The source-card restore timer and the shutdown command remain inline in `_build_button_handlers` because neither fits the single-response return-dict contract.

**Endpoints.**

```
# Static
GET  /                                → web/index.html
GET  /main.js, /style.css             → web/main.js, web/style.css
GET  /current.png                     → streams output/current.png

# State + telemetry (read-only)
GET  /api/current                     → {time, bucket, theme, source_id, line_number, ...}
GET  /api/telemetry?hours=24          → {render_count, error_count, p50/p95 latencies, last_error}
GET  /api/coverage                    → assets/bucket-coverage.json payload
GET  /api/themes                      → {themes: [...THEME_ORDER], theme_arg, manual_theme, effective}
GET  /api/history?limit=N             → anti-repeat ledger entries, newest-first
GET  /metrics                         → Prometheus text-format scrape over a 24h window (v2)
GET  /api/setup                       → {setup_complete, themes, quiet_start, quiet_end, ...} (v2; first-run wizard status)

# Curation (read)
GET  /api/bucket/<bucket>?time=HH:MM&top=N → ranked candidates with named score components
GET  /api/overrides                   → assets/selection_overrides.json (defaults ban_quote_keys=[])
GET  /api/content-overrides           → assets/content_overrides.json (v2; fail-open on corrupt file)
GET  /api/search?q=&author=&title=&bucket=&limit=N
                                      → linear-scan search across the raw corpus (v2)
GET  /api/gaps?threshold=N            → empty / sparse buckets + phrase suggestions
                                          from target_sparse_buckets.STATE_TEMPLATES (v2)
GET  /api/preview?theme=&time=HH:MM&width=&height=&mode=
                                      → image/png of the picker's pick rendered in any theme,
                                          history disabled for determinism (v2)

# Curation (write)
POST /api/overrides                   → validate + atomic rewrite (now accepts ban_quote_keys)
POST /api/content-overrides           → validate + atomic rewrite of the per-row sidecar (v2);
                                          empty {} is a legitimate "wipe everything"
POST /api/bake                        → run bake_quote_database.bake_rows in-process under
                                          render_lock; re-applies the content-overrides sidecar
                                          first so save → bake reflects on the next tick (v2);
                                          409 when busy
POST /api/setup                       → mark first-run wizard complete; optional {"theme": "<name>"}
                                          body applies a theme before dismissing (v2);
                                          flips state.setup_complete to True and persists
POST /api/action/{skip,unskip,theme,quiet,rerender} → mirror physical buttons
     (theme accepts optional {"theme": "<name>"} body to jump directly;
      empty body / missing field advances one step through THEME_ORDER)
```

**Security model.** Loopback binds (`127.0.0.1:*`, `localhost:*`, `::1:*`) run without auth — the OS-level trust boundary is sufficient for a single-operator home appliance. Any other bind **requires** `--web-token` or `--web-token-file`; `start_web_server` raises `ValueError` if you try to bind `0.0.0.0` without one, so an operator can't accidentally expose a tokenless POST surface. Tokens are checked against the `X-LitClock-Token` header only — never query strings, which `BaseHTTPRequestHandler` logs to stderr and journald. `_check_token` uses `hmac.compare_digest` for timing-safety. Unknown POST routes return 404 **before** the auth check so a scanner's wrong-token probe doesn't learn the service exists. GETs stay open on every bind (telemetry + coverage + `current.png` are not sensitive and the UI fetches them without credentials). `--web-token-file` is preferred over `--web-token` in production so the secret doesn't show up in `ps`/journald.

**Token hot-reload.** When `--web-token-file` is configured, `WebContext.current_token()` stats the file on every request and re-reads it when `st_mtime` changes, so rotating the secret is a plain file replace — no `systemctl reload` needed. The stat + read is serialised under `WebContext._token_lock` so racing requests can't interleave a partial string into the cached token. If the file goes briefly unreadable (e.g. the operator mid-replace), the previous cached value is returned rather than dropping auth entirely — the replacement is picked up on the next successful stat after the file reappears. Auth failures during the gap surface as `mode="web_auth_fail"` telemetry entries.

**Shared utilities, no duplication.**
- Atomic writes go through `atomic_io.atomic_write_text` / `atomic_write_bytes` / `atomic_write_lines` (tmp → fsync → `os.replace` → dir fsync), the single durability primitive shared between `save_runtime_state`, `web_server.write_overrides_atomic`, the rendered-PNG writer in `render_quote`, the ledger-rewrite path in `pick_quote.remove_last_history_entry`, and the corpus writeback in `apply_content_overrides`.
- Bucket validation uses `pick_quote.valid_bucket_names()` so `POST /api/overrides` rejects the same bad keys that `load_overrides` warns about.
- Telemetry summarisation reuses `litclock_health.load_entries` and `litclock_health.summarise` directly — the endpoint does not reimplement date-window globbing.
- `pick_quote.pick_best(..., return_ranked=True)` and `pick_quote.select_candidates(...)` are the single entry point for the bucket-inspector view; the UI projects the raw `score_row` tuple into named fields via `SCORE_COMPONENTS` so the operator can see "lost by minute_penalty=8" rather than a mystery integer.

**Static assets.** `web/index.html` + `web/main.js` + `web/style.css` are plain HTML/JS/CSS, **no build step** and no framework. Resolved via `BASE_DIR / "web"` so the service file doesn't depend on CWD. `main.js` polls `/api/current`, `/api/telemetry`, and `/api/themes` every 30s; the coverage grid and overrides editor load once and refresh on click. The theme dropdown rebuild skips when it has keyboard/mouse focus so a polled refresh can't clobber an open selection, and the theme-state pill distinguishes three runtime shapes: `manual: X` (override active), `auto: X` (wall-clock-derived), and `fixed: X` (explicit `--theme X` pin with no manual override).

**Mobile-first layout (v2).** The UI is organised as four tabs — **Now** (preview + button mirrors + theme thumbnail grid), **Curate** (search, bucket inspector, dual-sidecar editors, bake button), **Coverage** (12×12 grid + gap finder), **Activity** (telemetry + history). CSS is mobile-first with two breakpoints (768px tablet widens form rows, 1024px desktop puts the Now tab into a two-column layout); buttons and inputs honour the iOS HIG 44px minimum tap target so a phone-on-the-counter operator can curate without zooming. Tabs are kept in `location.hash` so a bookmark like `litclock.local#curate` jumps straight to the editor. Lazy loads: content-overrides + the gap finder + the theme preview grid are only fetched on first activation of their tab — first paint stays snappy on slow phones over LAN. The four tab-state booleans live on a module-level `state` object; tab switches don't re-fetch the same data.

**First-run setup wizard (v2).** A modal overlay shown on the very first visit to a fresh appliance — gated by `state.setup_complete` (a new `bool` field on `RuntimeState`, persisted to `state.json` alongside `manual_theme` / `manual_quiet`). The wizard has three steps: (1) a `/api/preview`-driven theme thumbnail grid where tapping a theme applies it via the same `action_theme` path the dropdown uses; (2) a read-only summary of the configured quiet hours so the operator knows when the panel will sleep; (3) a "I'm ready" button. POST to `/api/setup` flips `setup_complete=True` and persists; subsequent loads skip the overlay entirely. Quiet hours stay configured via `--quiet-start` / `--quiet-end` because dynamic runtime quiet-window changes would need a state-machine refactor we deferred to v2.x — for v2.0 the wizard is intentionally just the discovery surface for the existing knobs.

**Prometheus `/metrics` endpoint (v2).** Standard text-exposition format (Prometheus 0.0.4) over a fixed 24 h window — configurable per-window aggregation belongs on the scraper side via `rate()` / `increase()`, not on the exporter. Reuses `litclock_health.load_entries` + `litclock_health.summarise` so the exposed values match `litclock-health --json` exactly; no parallel aggregation logic to drift. Stays open without auth on every bind (matches the rest of the GET surface) so a Prometheus scraper running on the same LAN can hit it without managing a token. Operators who care bind to 127.0.0.1. Metrics emitted: `litclock_renders_total` / `litclock_errors_total` / `litclock_heartbeats_total` / `litclock_actions_total` / `litclock_press_dropped_total` / `litclock_web_auth_fails_total` / `litclock_web_errors_total` / `litclock_quiet_enter_total` / `litclock_quiet_exit_total` (gauges over the window — we don't have process-lifetime monotonic counters), `litclock_render_p50_ms` / `litclock_render_p95_ms` / `litclock_display_p50_ms` / `litclock_display_p95_ms` (latency gauges; missing values omit the sample line), and `litclock_last_heartbeat_age_seconds` (the loop-liveness alert metric — fires when the loop wedges).

**Webhook fan-out (v2, `runtime_webhook.py`).** `--webhook-url URL` posts a JSON body for each alert-worthy telemetry event. Default filter (`runtime_webhook.ALERT_MODES`): errors, `backoff`, `render_timeout`, `display_timeout`, `shutdown_timeout`, `buttons_dead`, `state_validation`, `web_auth_fail`, `web_error`. **Heartbeats and successful renders are always filtered**, because alerting once a minute is spam, not signal — even when `--webhook-all-events` widens the filter. The fan-out is fire-and-forget on a daemon thread with a 5 s `urllib.request.urlopen` timeout, so a wedged endpoint never blocks the render loop. Failures log to stderr as `webhook: …` but never raise. Configuration is module-level (`runtime_webhook.configure(url, all_events=...)`) and set once at `run_clock.main` startup; `runtime_telemetry.append_telemetry` reads it via lazy import so the no-webhook path pays no import cost. Tests reset the global between cases via an autouse fixture.

**No-op guard on `action_theme`.** The web dropdown pre-selects the active theme, so a "click Apply without changing anything" would otherwise burn a 10–20 s Spectra 6 refresh. Worse, if `manual_theme` was `None` (because `--theme auto` is running) and the target equals the auto-resolved value, setting `state.manual_theme = target` would silently pin auto mode off until the next midnight reset. `action_theme` returns `{"ok": True, "noop": True}` without mutating state when `target is not None and target == current_effective`. The button-B cycle path (`target is None`) deliberately bypasses the guard so it always advances.

**v2 closes the v2.1 carve-out.** The earlier scope boundary — "the curator UI doesn't edit `content_overrides.json`, and there's no way to ban a single row" — is gone. `POST /api/content-overrides` writes the per-row sidecar; `POST /api/bake` re-runs the baker in-process so the runtime picker sees the patched rows on the very next tick (no SSH session, no separate CLI step). Per-row bans land on the same flow: `ban_quote_keys` on the selection-overrides sidecar drops a single `(source_id, line_number)` row, and the UI's "Ban this quote" buttons (Now tab, bucket inspector, search results) read-modify-write the sidecar through the existing `POST /api/overrides`.

**v2 search and gap-finder.** `GET /api/search` is a stdlib linear scan across the raw corpus (~3K rows, <50 ms) supporting `q` / `author` / `title` / `bucket` filters in any combination — at least one is required, all are case-insensitive substring. Hard-caps `limit` at 500 to bound response sizes. Reads the raw corpus (not the baked DB) on purpose so an operator searching for "where did that quote go?" can find rows the baker dropped (low quality / daypart-only) and understand why they're not appearing. `GET /api/gaps` reads `assets/bucket-coverage.json` and joins each below-threshold bucket against `target_sparse_buckets.STATE_TEMPLATES`, so the suggested phrases match what `target_sparse_buckets.py --search-dir data/gutenberg` would actually look for if invoked from the CLI.

**Theme preview endpoint.** `GET /api/preview?theme=...&time=HH:MM` calls `pick_quote.select_quote` (history disabled for determinism), feeds the result into `render_quote.render`, and streams the PNG bytes back. The Now tab's theme thumbnail grid issues one request per registered theme so an operator can compare all twenty-four themes side-by-side on the actual current quote before applying. Width/height are clamped to `800×480` so a hostile/buggy client can't request a slow or high-memory render. Does not touch the panel and never commits to `state` — preview is intentionally side-effect-free.

**`POST /api/bake` semantics.** Runs `bake_quote_database.bake_rows` in-process; non-blocking acquire of `render_lock` returns 409 (busy) when a render is already in flight rather than queueing behind a 10–20 s Spectra 6 refresh. Re-applies `assets/content_overrides.json` to the raw corpus *before* baking so a UI workflow of "edit row → save → bake" round-trips edits onto the panel within seconds. The runtime picker reads the baked DB from disk on every `select_quote` call (it goes through `_resolve_corpus`), so no in-memory cache invalidation is needed — the next tick picks up the new file automatically. Stats are returned in the response (`kept` / `input` / `applied_overrides` / `drops` / `per_bucket`) so the UI can render an operator-readable summary.

### Appliance / Pi Setup

- **Fresh Pi:** `bootstrap_pi_inky.sh` automates apt setup, clones the Pimoroni `inky` installer, and (with `CONTINUE_AFTER_REBOOT=1` on the second run) clones this repo and does a first render + display push.
- **Manual Pi notes:** `pi_setup_inky_impression.md` is the long-form guide (hardware list, OS baseline, Pimoroni install, troubleshooting).
- **Boot-time service:** `litclock.service.example` is a sample systemd unit that runs `run_clock.py --display-script display_inky.py --mode production` as `pi` from `/home/pi/LitClock` under the `~/.virtualenvs/pimoroni` Python. Edit paths to match your install before copying into `/etc/systemd/system/`.
- **Container (v2):** `Dockerfile` is a multi-stage OCI build — stage 1 produces wheels, stage 2 installs them into a Python 3.12-slim runtime as a non-root `litclock` user. ARM64-first for Pi appliance use, multi-arch via `docker buildx build --platform linux/arm64,linux/amd64 -t litclock:2.0 .`. The Pi-only `[pi]` extra (`gpiozero` / `inky`) is **not** installed by default — that's a Pi-runtime concern. The base image renders PNGs and serves the curator UI without GPIO bindings. Run with `docker run --rm -p 8080:8080 -v litclock-state:/state litclock:2.0 litclock run --buttons-off --skip-preflight --web-bind 0.0.0.0:8080 --state-path /state/state.json --history-path /state/history.jsonl --telemetry-path /state/telemetry.jsonl --pidfile /state/run_clock.pid` for a headless dev instance. `.dockerignore` keeps `data/` (cached Gutenberg downloads), `output/`, `.git/`, and `tests/golden/` out of the build context so `buildx` doesn't ship multi-GB caches.

### Testing

The test suite lives in `tests/` and uses pytest with pytest-cov / pytest-xdist. There are 42 test modules covering every pipeline script plus the runtime components — ~2525 test cases at last count (including `test_bake_quote_database.py` for the display-ready DB baker, `test_bake_equivalence.py` which sweeps all 144 canonical buckets to prove baked picks match raw-corpus picks, `test_baked_db_schema.py` for the schema_version contract, plus dedicated suites for the appliance-hardening modules: `test_pidfile.py`, `test_sd_notify.py`, `test_web_server.py`, `test_contact_sheet.py`, `test_buckets.py`, `test_jsonl_io.py`, and `test_packaging.py`). `tests/test_atomic_io.py` exercises the shared durability primitive (`atomic_write_text` / `_bytes` / `_lines`) including monkeypatched `os.replace` failure paths that assert the tmp sibling is cleaned up and the target file is left byte-identical. The reliability branches of every caller are covered in their respective modules: `test_pick_quote.py` for the ledger-rewrite atomicity, `test_apply_content_overrides.py` for fail-open loading and atomic corpus writeback, `test_render_quote.py` for PNG-save crash recovery, `test_run_clock.py` for `_install_signal_handlers` / `_shutdown` / `prune_telemetry` / `_maybe_prune_telemetry`. Cross-cutting suites include `test_pipeline_integration.py` (end-to-end pipeline smoke), `test_corpus_invariants.py` (committed-corpus sanity checks), `test_miner_match_types.py` (regex per match type), `test_buckets_properties.py` (hypothesis-style bucket invariants), `test_concurrency.py` (render-lock and ledger-lock contention), and `test_cli_main_smoke.py` (each script's `if __name__ == "__main__"` entrypoint). `display_inky.py` is exercised via `test_display_inky.py` with `_push_to_panel` mocked out so the retry/error paths run without real hardware; it stays in `tool.coverage.run.omit` so coverage numbers aren't skewed by hardware-only branches. `inky_buttons.py` is tested with `gpiozero.Button` stubbed via a `FakeButton` class injected through `sys.modules`. `probe_buttons.py` has a smoke-test module (`test_probe_buttons.py`) that mocks GPIO interaction.

**Renderer golden-image suite (`tests/test_render_golden.py` + `tests/golden/renderer/*.png`).** Ten committed PNG fixtures spanning every layout × theme × mode combination (hero/standard/dense × default/dark × production/debug/card) plus the `fallback_debug_default` arrow-form footer and a `no_metadata_production` attribution-skipped edge case. Each scenario is re-rendered in-process and compared pixel-by-pixel against its golden via `ImageChops.difference`; `MAX_DIFF_RATIO = 0.001` (0.1% of 384,000 pixels) tolerates a one-pixel antialiasing boundary while catching layout, bold-phrase, and accent-colour regressions that flip thousands of pixels. Robust across FreeType / Pillow drift because `snap_image_to_palette` collapses every output pixel to one of six fixed Spectra 6 triples — subpixel drift generally rounds to the same palette index. Regenerate after an intentional renderer change with `UPDATE_RENDER_GOLDEN=1 pytest tests/test_render_golden.py`; a structure test fails if an orphaned fixture lingers after its scenario is deleted.

**Packaging-boundary tests (`tests/test_packaging.py`).** Two install-time invariants that `pip install -e .` (the developer setup, which puts the repo on `sys.path` regardless of `[tool.setuptools] py-modules`) cannot see: (1) every top-level production `*.py` module is listed in `py-modules` — the wheel ships exactly what's listed there, so a missing entry produces a wheel that crashes on first import on the appliance; (2) importing any production module never pulls hardware deps (`gpiozero` / `inky` / `RPi.GPIO`) into `sys.modules`. The second check runs each module import in a subprocess so prior in-process imports can't pre-populate the namespace and mask the leak. Both invariants are also enforced at CI time by the `package-build` job (see "CI" below).

**Scorer property tests (`tests/test_scorer_properties.py`).** Complements the ordinal checks in `test_scorer_invariants.py` with systematic sweeps that would catch mutations the pairwise tests miss. Locks: tuple layout (length 12, `minute_penalty` at position 2, `override_bonus` at position 7, bake-component parity with `BAKED_SCORE_COMPONENTS`); lexicographic dominance (an earlier-position row wins against any later-position delta, no matter how large); strict monotonicity in quality across the full 0..100 sweep; minute-penalty dominance over metadata / dialogue / quality; `preferred_buckets` beats `boost_source_ids`; position isolation (each component only moves its own tuple slot — a refactor that leaks into two positions fails); request-time recomputation (only `minute_penalty` and `override_bonus` change as `requested_time` / `overrides` vary — the contract baked-row caching relies on); baked/raw interleave equivalence across five corner-case row shapes; exhaustive minute-distance sweep for every (requested, quote) pair in [0..55] step 5; and scoring purity (no mutation of the row dict or the overrides dict). Follows `test_buckets_properties.py`'s pattern — exhaustive enumeration over bounded spaces, no Hypothesis dependency.

**Test structure:**
- `tests/conftest.py` — shared fixtures: `make_row()` factory, `sample_row`, `sample_rows`, and `tmp_jsonl` (a helper that writes a list of dicts to a temp JSONL file). Also installs an autouse `_isolate_home` fixture that monkeypatches `$HOME` to a per-test tmp dir, so tests that use default `--state-path` / `--history-path` / `--pidfile` / `--telemetry-path` values can't leak state into the developer's real `~/.litclock/` or contaminate each other within a run.
- One `test_<script>.py` module per main script; tests are class-based (e.g., `TestCurrentBucket`, `TestRenderNow`)

**pyproject.toml** configures:
- `[project]`: name `litclock`, version, `requires-python >= 3.11`, runtime dep `Pillow`, optional extras `dev = [pytest, pytest-cov, pytest-xdist, ruff]` and `pi = [inky, gpiozero]` (`gpiozero` is needed by `inky_buttons.py` on the Pi). `pip install -e .[dev]` is the intended developer setup.
- `[tool.setuptools] py-modules`: explicit list of every top-level production `*.py` to ship in the wheel. **Keep this in sync with the repo root** — `tests/test_packaging.py::test_py_modules_covers_top_level_modules` enforces the invariant, and the CI `package-build` job catches the same drift at install time. A module on disk that's missing from this list silently breaks `pip install .` (the wheel won't contain it), and the appliance won't start.
- pytest: `testpaths = ["tests"]`, `python_files = ["test_*.py"]`, `python_functions = ["test_*"]`, `filterwarnings = ["ignore::DeprecationWarning"]`
- coverage: source = `.`, omits `tests/` and `bootstrap_pi_inky.sh`. `display_inky.py` deliberately stays in coverage — its module-level defaults + `resolve_saturation` + `main()` retry/backoff logic are exercised by `tests/test_display_inky.py` with the hardware call (`_push_to_panel`, which imports the Pimoroni Inky library) mocked out. `[tool.coverage.report] exclude_lines` keeps the default `pragma: no cover` marker (overriding the list without re-adding it would silently disable hardware-only branch suppression).
- ruff: line-length 130, target Python 3.11, rules E / W / F / I (E501 ignored)

**CI:** `.github/workflows/ci.yml` runs on pushes to `main` and on every pull request — feature branches get checked via the `pull_request` trigger only, so `push` + `pull_request` don't double-run. Four jobs:
- `lint` — single Python 3.12 job running `ruff check --output-format=github .` once, so style feedback lands as inline PR annotations without waiting for the test matrix.
- `test` — matrix across Python 3.11 / 3.12 running `pytest -n auto --dist loadscope --ignore=tests/test_render_golden.py`. Coverage runs only on 3.12 (with `COVERAGE_CORE=sysmon` / PEP 669 — tracer overhead is effectively zero, so the coverage leg is no slower than plain pytest); the 3.11 leg is a regression tripwire for the older interpreter. The 3.12 leg also runs an end-to-end `python run_clock.py --once --skip-preflight` step that verifies the resulting `output/current.png` decodes via `Image.verify()`, so a truncated / partially-snapped PNG surfaces in CI rather than on the appliance. Coverage uploads as `coverage-3.12` artifact with `if-no-files-found: error`.
- `golden-render` — splits the renderer golden-image suite (`tests/test_render_golden.py`) into its own job so its in-process Pillow renders don't serialise behind the main test matrix; run with `-n auto --dist worksteal`.
- `package-build` — builds a wheel + sdist via `python -m build`, installs the wheel into a fresh venv with **no extras** (no `[dev]`, no `[pi]`), then imports every production module from the installed wheel and asserts (a) all imports resolve under `site-packages` (not the source checkout — the import step `cd`s to `/tmp` so `sys.path[0]` doesn't shadow the wheel) and (b) no `gpiozero` / `inky` / `RPi` leaked into `sys.modules`. Finally smoke-tests `python -m run_clock --help`. This catches the three install-time failure modes that `pip install -e .` cannot: missing `py-modules` entries, optional-dep leakage at module import time, and broken `__main__` wiring.

The `lint` / `test` / `golden-render` jobs install via `pip install -e ".[dev]"` (single source of truth with `pyproject.toml` — no hardcoded `pytest pytest-cov ruff Pillow` list to drift); `package-build` is the deliberate exception, installing the built wheel into a fresh venv with no extras so the wheel-install semantics are exercised end-to-end. All four jobs enable `actions/setup-python`'s pip cache keyed on `pyproject.toml`, set `timeout-minutes` as a hang safety-net, and run with `permissions: contents: read` (least-privilege `GITHUB_TOKEN`). A top-level `concurrency` group cancels superseded PR runs (`cancel-in-progress` only when `github.event_name == 'pull_request'`) so `main`-branch history is preserved while rapid PR pushes don't pile up. The test matrix runs with `fail-fast: false` so one Python version failing doesn't hide the other. Keep imports sorted (rule I) — run `ruff check .` locally before pushing.

### Repo Layout

```
buckets.py                         shared bucket primitives (BUCKET_ORDER, minute_bucket, bucket_for_time, neighbor_buckets)
atomic_io.py                       shared atomic-write primitives (text/bytes/lines) — tmp-sibling → fsync → os.replace → dir-fsync; durability for every appliance file the next tick reads
jsonl_io.py                        streaming JSONL reader that logs + skips malformed lines
gutenberg_time_miner.py            harvest regex-matched time phrases from .txt
merge_candidates.py                dedupe harvested JSONL rows
bucket_coverage.py                 coverage report per (hour, minute-state) bucket
target_sparse_buckets.py           targeted regex sweep for empty buckets
import_targeted_hits.py            reshape targeted hits for merge
clean_display_quotes.py            pick a displayable excerpt from each row (expands bare single-sentence hits with up to 2 neighbouring sentences, rejects mid-text chapter headings, splits on sentence boundaries with two abbreviation classes — TITLE_ABBREVIATIONS "Mr./Mrs./Dr./St./J." always merged, SENTENCE_OK_ABBREVIATIONS "etc./p.m./U.S.A." only merged when the next fragment starts lowercase)
quality_filter.py                  score + flag rows
fix_substring_time_matches.py      LEGACY migration tool — repair substring-collision time tags in pre-fix JSONL
fix_legacy_buckets.py              LEGACY migration tool — repair pre-buckets.py legacy 8-state names + matched_text whitespace
enrich_metadata.py                 attach author/title from Gutenberg headers
apply_content_overrides.py         layer assets/content_overrides.json onto candidates-attributed.jsonl
bake_quote_database.py             final pipeline stage — bake the display-ready runtime DB (pre-scored, per-bucket sorted; pick_quote reads by default)
pick_quote.py                      rank candidates, honor overrides, fall back to neighbors (exposes select_quote(); baked DB by default with raw-corpus fallback)
render_quote.py                    Pillow layout → 800×480 Spectra-6 PNG (imports pick_quote in-process)
contact_sheet.py                   12×12 grid of all 144 bucket frames, for offline QA
run_clock.py                       runtime loop (bucket-change-triggered, error-tolerant, quiet-hours-aware, button + auto-theme + telemetry; atomic state writes, date-rotated telemetry with retention sweep, SIGTERM/SIGINT graceful shutdown, button liveness check). Thin orchestrator — delegates state/telemetry/theme/quiet/action helpers to the runtime_* siblings below and re-exports them so existing `run_clock.X` imports and test patches keep resolving.
runtime_log.py                     shared timestamped stderr/stdout logger (_log)
runtime_config.py                  TOML config-file loader (--config PATH on run_clock). Fail-open on malformed content; fails fast only on a typoed --config path. Keys mirror argparse dest names 1:1.
runtime_state.py                   RuntimeState class — locks, mutable shared state between the loop, button listener, and web server
theme_names.py                     PIL-free shim exposing `known_theme_names()` + `theme_cycle()` — three runtime modules and web_server need theme-name lists for state validation, manual-override gating, and dropdown ordering, all without dragging Pillow into their import graph; centralised here to kill the prior near-duplicate lazy-import blocks (which had drifted between `frozenset` and `tuple` return types)
runtime_store.py                   persisted runtime state JSON (manual_theme / manual_quiet + render-identity triple) loaded + validated at startup and saved atomically via atomic_io
pidfile.py                         single-instance fcntl.flock pidfile for run_clock.main (stale-pid reclaim, --pidfile opt-out)
sd_notify.py                       pure-stdlib systemd sd_notify client (READY=1 at startup, WATCHDOG=1 from heartbeat); no-op when $NOTIFY_SOCKET is unset
runtime_telemetry.py               date-rotated JSONL telemetry sidecar (append_telemetry, append_heartbeat, daily_telemetry_path, prune_telemetry; v2 fans out alert-worthy entries to runtime_webhook)
runtime_webhook.py                 v2 — fire-and-forget HTTP webhook for alert-worthy telemetry (errors, backoff, timeouts, button-died). configure() at startup; daemon-thread POST per event; bounded urllib timeout; never raises
runtime_theme.py                   theme resolution — auto-dark window, manual override, midnight reset
runtime_quiet.py                   in_quiet_hours + _display_quiet_image + compute_quiet/enter_quiet/exit_quiet state machine (shared by the main loop's scheduled quiet-hours branch and runtime_actions.action_quiet's manual toggle; --startup-image and button-D shutdown preamble reuse _display_quiet_image directly)
runtime_actions.py                 action_skip/unskip/theme/quiet/rerender + _button_render_gate — shared by GPIO buttons and the web UI; each action does a lazy `import run_clock` internally so tests that patch `run_clock.X` affect the call path (same pattern web_server.py uses)
display_inky.py                    Pi-only image → Inky Impression bridge (retry with backoff, per-theme saturation)
inky_buttons.py                    Pi-only gpiozero button listener (A/B/C/D → run_clock handlers, press_logger + buttons_alive supervision)
probe_buttons.py                   Pi-only GPIO press probe — confirms which pin each physical button actually fires
litclock_health.py                 telemetry summariser (render count, p50/p95 latency, last error; reads date-rotated sidecar)
litclock_cli.py                    v2 — unified `litclock <subcommand>` entry point; lazy-imports each backing module's main() and rewrites sys.argv so existing parse_args() calls still work. pyproject.toml [project.scripts] registers it as the `litclock` console script. Backwards-compatible — `python3 <script>.py` keeps working
web_server.py                      optional curator HTTP UI (off by default, --web-bind to enable; shares render_lock with button handlers; v2 adds /metrics + /api/setup + /api/preview + /api/search + /api/gaps + /api/bake + /api/content-overrides)
web/                               vanilla HTML/JS/CSS served by web_server (index.html, main.js, style.css — no build step; mobile-first, four-tab layout: Now / Curate / Coverage / Activity)
bootstrap_pi_inky.sh               first-time Pi setup helper
litclock.service.example           sample systemd unit
pi_setup_inky_impression.md        long-form Pi setup doc
Dockerfile                         v2 multi-stage OCI image (Python 3.12-slim base, builder produces wheels, runtime installs them as a non-root user). ARM64-first for Pi appliance use; multi-arch via `docker buildx build --platform linux/arm64,linux/amd64`. Bundled fonts/assets/web ship in the image; mount /state for persistence
.dockerignore                      excludes data/, output/, .git/, tests/golden/ and pycache from the build context so `docker buildx build` doesn't ship multi-GB caches
FOLLOWUPS.md                       deferred-work list — items deliberately carved out of larger PRs to keep them focused; not a bug tracker
pyproject.toml                     project metadata + pytest / coverage / ruff configuration
fonts/                             bundled display faces: Playfair Display (default/dark), inter/ (swiss — Helvetica-class grotesque sans, variable, OFL), bitter/ (scholar — slab serif, variable), im-fell-english/ (alchemy + grimoire + herbarium — 17th-century Oxford-press humanist serif with italic, OFL; herbarium reuses the italic for its Latin matched phrase), old-standard-tt/ (newsprint — Didone), space-mono/ (nightvision — retro mono), archivo/ (blueprint — grotesque sans), eb-garamond/ + unifraktur/ (illuminated — humanist serif body + blackletter ornaments; also gothic — same EB Garamond body, UnifrakturMaguntia promoted to both bold and ornament slots), cormorant-garamond/ + berkshire-swash/ (mucha — high-contrast humanist serif body, variable + flourished Belle-Époque script ornament, both OFL), jost/ (bauhaus — geometric-constructed sans, variable), rubik/ (risograph — rounded sans, variable, axis default Light so Regular/Bold pinned explicitly), bangers/ (comic — all-caps comic-book display), special-elite/ (dispatch — slab-mono typewriter, Apache LICENSE not OFL), atomic-age/ (atomic — chunky 1950s display face), permanent-marker/ (marker — hand-drawn Sharpie face, Apache LICENSE not OFL), rye/ (saloon — 19th-century wood-engraved slab serif, OFL), righteous/ (deco — 1930s geometric art-deco display sans, OFL), iceland/ (glacier — geometric techno display face, OFL), playwrite-gb-j-guides/ (chalkboard — UK primary-school joined-cursive handwriting with dotted-outline guide letters, OFL), patrick-hand-sc/ (placard — hand-printed small-caps signage face, OFL), shojumaru/ (chanbara — brush-painted samurai-cinema display face, OFL), bungee-shade/ (fillmore — 3D-blocked psychedelic concert-poster display face, OFL); each subdir ships its own license file (OFL.txt for OFL-licensed faces, LICENSE.txt for the Apache-licensed Special Elite + Permanent Marker)
assets/candidates-attributed.jsonl raw attributed corpus — source-of-truth input to bake_quote_database.py; also served as the curator UI's /api/bucket view and used as pick_quote's defensive fallback if the baked DB is missing
assets/quote_database.jsonl        baked display-ready database — the canonical runtime input that pick_quote / run_clock / render_quote read by default; regenerate via bake_quote_database.py whenever the raw corpus changes
assets/bucket-coverage.md          committed snapshot of the current corpus's bucket coverage
assets/bucket-coverage.json        machine-readable companion to bucket-coverage.md
assets/contact-sheet.png           12×12 visual snapshot of every bucket's current pick (regenerate via contact_sheet.py)
assets/selection_overrides.json    manual bans/boosts/per-bucket preferences (pick_quote default --overrides)
assets/content_overrides.json      per-row content fixes (apply_content_overrides default --overrides)
assets/goodnight.png               static dark-theme "good night" frame; the legacy default for --quiet-image / --startup-image. Operators on operator-choice themes prefer `--quiet-image auto` (renders an in-theme goodnight frame on the fly via `render_quote.py --mode goodnight`).
assets/config.toml.example         annotated example config for run_clock.py --config — appliance-oriented preset (production mode, auto theme, /var/lib paths, systemctl-poweroff)
assets/config.toml.defaults        faithful dump of every argparse default. Copying verbatim is a no-op vs. no --config; diffable reference for deployments pinned to explicit values
assets/preview.png                 README hero image
tests/                             pytest suite — one module per script + conftest.py; tests/golden/renderer/*.png are committed PNG fixtures for the golden-image suite (regenerate with UPDATE_RENDER_GOLDEN=1)
output/                            runtime render target (output/current.png); gitignored except .gitkeep
data/gutenberg/                    cached Gutenberg text downloads (gitignored)
.github/workflows/ci.yml           GitHub Actions CI (lint + test, Python 3.11 & 3.12)
gutenberg_batch_ids.txt            batch list of Gutenberg IDs for run_batch2.sh
gutenberg_dawn_expansion_ids.txt   curated clock-precise Gutenberg ID list for run_dawn_expansion.sh
run_batch2.sh                      bulk harvest driver
run_dawn_expansion.sh              one-shot "mine curated IDs → pipeline → merge into live corpus" driver
```
