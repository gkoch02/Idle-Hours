# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

LitClock is an end-to-end literary-clock system: it harvests time-related quotes from Project Gutenberg, scores and cleans them, then picks and renders a quote for any clock time. The render is designed for a Pimoroni Inky Impression 7.3 Spectra 6 eInk panel (800×480, 6-color palette) but writes a plain PNG first, so it runs fine on any machine.

Every stage is a standalone Python 3 CLI script that reads/writes JSONL. The mining/selection pipeline is stdlib-only; `render_quote.py` pulls in Pillow, and `display_inky.py` additionally needs the Pimoroni `inky` package (Pi only).

## Common Commands

### Testing & linting

```bash
# Run the full test suite (2254 tests, ~3 minutes)
pytest

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

# Optional curator web UI (off by default). 127.0.0.1 binds skip auth entirely;
# any other host requires --web-token (or --web-token-file for systemd).
python3 run_clock.py --web-bind 127.0.0.1:8080
python3 run_clock.py --web-bind 0.0.0.0:8080 --web-token-file ~/.litclock/web.token

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

# Override the button-D long-press shutdown command (default: sudo -n shutdown -h now)
python3 run_clock.py --shutdown-command ""             # disable shutdown-on-hold entirely

# Disable the default quiet-hours blackout (defaults 22:00–06:00, shows assets/goodnight.png)
python3 run_clock.py --quiet-off
python3 run_clock.py --quiet-start 23:30 --quiet-end 07:00 --quiet-image assets/goodnight.png

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
| `assets/content_overrides.json` | per-row hand fixes (source-of-truth) | yes | no (build-time only) | hand-edited |
| `assets/selection_overrides.json` | bans / boosts / preferred buckets (runtime-editable) | yes | yes | hand-edited or web UI `POST /api/overrides` |
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
  "preferred_buckets": {}      // { "h3_late_past": 12345 } → that source_id wins in that bucket (−5)
}
```

IDs are compared as strings. Edit this file rather than editing the scorer when you want to manually curate a specific bucket. `pick_quote.load_overrides` warns on stderr if any `preferred_buckets` key is not a valid `h{1..12}_{state}` bucket, so typos surface loudly instead of silently never firing.

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
- **Themes.** The `THEMES` dict defines ten color sets, cycle-ordered by the `THEME_ORDER` tuple: `default` (white/black/red, Playfair Display), `dark` (black/white/yellow, Playfair Display), `scholar` (white/blue/red, Bitter slab serif), `newsprint` (white/black/no-accent — bold-weight differentiation only, Old Standard TT, plus a `draw_newsprint_border` Scotch-rule frame: thick outer rule + hairline inner rule, no corner accents — broadsheet typography lives entirely in ink weight, not chromatic contrast), `nightvision` (black/green/yellow, Space Mono retro-terminal feel, plus a `draw_nightvision_border` HUD-style frame: four L-shaped green corner brackets with NO continuous outer frame between them — the bracket-only composition is the signature camera-viewfinder / weapons-HUD motif), `blueprint` (white/blue/red, Archivo geometric sans — drafting aesthetic, plus a `draw_blueprint_border` decorative frame: thin blue outer rectangle with red crosshair "registration marks" centred on each corner, echoing the print-alignment ticks used on engineering drawings, and a thin blue graph-paper grid painted inside the frame at 20px spacing so the ground reads as engineering paper rather than an empty sheet — text is painted on top so the grid only shows through between glyphs), `illuminated` (white/red-body/blue-accent, EB Garamond + UnifrakturMaguntia blackletter ornaments — rubricated manuscript, plus a `draw_illuminated_border` decorative frame: double rubricated red rule with a blue "jewel" — filled circle — centred on each outer corner, evoking the lapis cabochons inset on medieval bindings), `bauhaus` (white/black/blue-accent + red-ornaments, Jost geometric sans — three primaries simultaneously, plus a `draw_bauhaus_border` decorative frame: thin black outer rectangle with red-circle / blue-square / blue-triangle / red-circle corner accents evoking the canonical Bauhaus vocabulary of primary-colour geometric primitives. The six themes with borders — bauhaus / blueprint / comic / illuminated / newsprint / nightvision — are dispatched via `_paint_theme_border` / `_BORDER_PAINTERS` at the top of both `render` and `render_source_card`; three of them paint in the top-right corner (bauhaus / blueprint / illuminated), so the debug-mode "DEBUG MODE" banner shifts inward for those via the `_DEBUG_LABEL_RIGHT_INSET` dict — extend that dict when adding another theme-specific TR graphic), `risograph` (white/red/blue, Rubik rounded sans — ZERO black ink, two-colour riso print), and `comic` (yellow-ground/black-body/red-accent, Bangers comic-book display, plus a `draw_comic_corner_stripes` decoration: 45° racing stripes cycling through blue / green / red / black, masked to a right-triangle pinned to the bottom-right corner of the canvas — hypotenuse spans the lower-right quadrant from `(width/2, height)` up to `(width, height/2)`, so bands fan out from the corner without obscuring the quote body. The stripe palette is hardcoded at module scope (`_COMIC_STRIPE_PALETTE`) since the cool blue/green half of the chevron isn't reachable from the comic theme dict's two non-bg accents — an exception to the "borders pull from `colors`" pattern that would otherwise force a THEMES-schema extension and re-pin every cross-theme invariant test). Every theme colour must stay on the Spectra 6 palette (enforced by a test). `--theme` selects one (plus `auto` which picks default/dark by wall-clock hour); `run_clock.py` forwards it via `--theme`. Button B advances through `THEME_ORDER` one step per press; the web UI dropdown jumps directly. Adding a new theme: extend `render_quote.THEMES`, add to `THEME_ORDER`, add a `render_quote.THEME_FONTS` entry (see "Fonts" below — missing themes silently fall back to the Playfair chain, defeating the point of per-theme typography), add a `display_inky.THEME_SATURATION` entry, and update `run_clock.py`'s `--theme` argparse choices (the `TestActionThemeCycle::test_cli_theme_choices_match_theme_order` test pins the sync).
- **Fonts.** Typography is per-theme, and each non-default theme deliberately picks a face from a different type *family* so the rendered frame's silhouette changes with the theme — not just its palette. `THEME_FONTS` maps each `THEMES` entry to a dict with `quote_regular` / `quote_bold` / `ornament` candidate chains, each a list of path strings OR `(path, variation_name)` tuples. The tuple form targets variable fonts — `load_font` calls `set_variation_by_name(name)` after the truetype load, so e.g. the scholar theme picks Regular/Bold instances from a single variable `Bitter-Variable.ttf` (whose default axis instance is Thin — a missing variation call would render near-invisible hairlines on the panel). `default` and `dark` share the Playfair Display chain (transitional / high-contrast serif; repo-local `fonts/`, then common Pi/Linux paths, with DejaVu Serif / Liberation Serif / Noto Serif as system fallbacks). `scholar` uses **Bitter** — a slab serif; even-contrast blocky terminals read as "academic textbook" and sit visually far from Playfair's display-serif silhouette, Regular body + Bold accent. `newsprint` uses **Old Standard TT** (vintage broadsheet / scientific-journal Didone revival — Regular body + Bold accent). `nightvision` uses **Space Mono** (retro-terminal monospace — Regular + Bold; DejaVu Sans Mono is the system-font fallback). `blueprint` uses **Archivo** (grotesque sans — the first pure-sans silhouette in the rotation; ships static Regular + Bold TTFs). `illuminated` pairs **EB Garamond** (humanist old-style serif — different family branch from Playfair's transitional / Bitter's slab / Old Standard's Didone) for the body with **UnifrakturMaguntia** (blackletter) confined to the ornament slot for the oversized curly quotation marks — a blackletter body would shred dense-layout legibility on a 4-bit eInk panel. `bauhaus` uses **Jost** (Futura-adjacent geometric-constructed sans — same sans family as blueprint but from the geometric branch rather than the grotesque, so the two sans themes remain distinguishable; variable font, Regular / Bold pinned via `set_variation_by_name`). `risograph` uses **Rubik** (chunky rounded modern geometric sans — variable font whose axis default is Light (300) NOT Regular, so every THEME_FONTS candidate pins Regular / Bold explicitly; a missing `set_variation_by_name` call would render body text noticeably too thin). `comic` uses **Bangers** (all-caps comic-book display hand — the only display / hand-lettered face in the rotation; only one weight ships so the matched-phrase role re-uses the same file and gains differentiation purely through the accent colour). Every per-theme chain ends at the Playfair / DejaVu defaults so a missing-font install degrades to the default face instead of dropping to the PIL bitmap fallback. System metadata / debug strips always use DejaVu / Noto / Liberation Sans regardless of theme. Install `apt install fonts-noto-core fonts-dejavu-core` if the bundled fonts aren't found. When every TTF candidate is missing, `load_font` logs a one-shot warning to stderr before returning `ImageFont.load_default()` so a misconfigured install surfaces instead of silently producing an 8-pixel bitmap render.
- **Layouts.** Three named layouts (`hero` ≤90 chars, `standard` ≤170, `dense` otherwise) each define their own `max_width`, `quote_height`, font size range, line-height multiplier, and quote-mark sizing. See the `LAYOUTS` dict.
- **Bold time phrase.** `resolve_display_match` tries to grow a multi-word time phrase ("five minutes past", etc.) inside the display text, then `tokenize_quote`/`wrap_styled_text` render it in bold + accent color while keeping word wrap correct across the bold boundary.
- **Text cleanup.** `strip_underscore_emphasis` drops Gutenberg's `_emphasis_` markers and `normalize_dashes` converts bare `--` to em-dashes before layout.
- **Fit loop.** `fit_quote` shrinks the quote font in 2pt steps from the layout's `font_max` down to `font_min` until all lines fit within `quote_height`.
- **Justification.** Non-last lines are fully justified by distributing leftover slack across inter-word spaces — but only when slack is ≤25% of the layout's `max_width`. Loose lines fall back to ragged-right because wide forced gaps look worse than uneven right edges.
- **Modes.** `--mode debug` (default) draws a top-right `DEBUG MODE` banner (rendered in sans-bold to match the footer strip, in the theme's accent color) plus a centered bottom strip (`HH:MM · bucket[ → resolved] · layout X · quality N · id source:Lline`) separated from the quote block by a dotted horizontal rule. `--mode production` hides all of that for a clean appliance look.
- **Outputs.** `--output` defaults to `output/current.png` (the same stable filename `run_clock.py` passes explicitly), so repeated ad-hoc CLI invocations overwrite one file instead of leaking up to 1440 `render-HHMM.png` siblings across a day. Pass an explicit path when you want a persistent per-time artifact. The PNG is encoded to a `BytesIO` and written via `atomic_io.atomic_write_bytes` so a power cut mid-save can't leave a truncated frame for the next tick (and for `display_inky.py`) to read. The underlying PIL `Image` is explicitly `close()`d after encoding to release the file handle — important over months of continuous operation.

### Runtime Loop (`run_clock.py`)

**Config file (`--config PATH`).** `parse_args()` supports a TOML config whose keys mirror the argparse `dest` names one-for-one (snake_case: `display_script`, `quiet_start`, `web_bind`, …). Loaded via `runtime_config.load_config` before the real parse, the file's values are fed into `parser.set_defaults(**config_dict)`; argparse's own rule that "the default is used only when the flag is absent from argv" delivers the three-layer precedence — **CLI flag > config value > argparse default** — without any custom merge layer. `load_config` takes a `choices_map` extracted from `parser._actions` so `choices=`-gated keys (`mode`, `theme`) validate at load time instead of silently propagating a typoed value into the render subprocess; `_valid_hhmm` is injected the same way. One asymmetry: `store_true` flags (`buttons_off`, `quiet_off`) can only be *enabled* by the CLI, since argparse has no paired `--no-*` variant, so a config that sets them `true` can't be overridden from the shell. Three transient flags are deliberately refused in the file (`--config` itself, `--once`, `--skip-preflight`); listing them warns and drops. Malformed TOML, unreadable contents, a non-table root, unknown keys, type mismatches, and choice-miss values all warn to stderr and continue with argparse defaults, mirroring `apply_content_overrides.load_overrides`'s fail-open pattern. The one hard error is pointing `--config` at a non-existent path: that raises `SystemExit(1)` at startup because a typoed unit-file path is a configuration bug the operator wants to hear about, not a silent-defaults signal. The shipped `litclock.service.example` passes `--config %S/litclock/config.toml` exclusively; see `assets/config.toml.example` for every supported key.

Thin orchestrator. Each tick (`--interval-seconds`, default 60) it computes the current fuzzy bucket; only when the bucket *changes* does it consider re-invoking `render_quote.py`. Before launching the renderer it calls `peek_quote_id` — which runs `pick_quote.select_quote` in-process and returns `(source_id, line_number, display_quote, matched_text)` — and compares that identity tuple against `last_quote_id`. `matched_text` is part of the identity because the renderer uses it to choose which phrase gets bolded/coloured, so two picks that share source/line/quote but differ in the matched phrase (e.g. `02:50` vs `02:55` landing on the same row) still produce visibly different frames and must not dedupe together. If the picked quote is unchanged, the redraw is skipped so the eInk panel is not refreshed for a visually-identical frame. Otherwise it re-renders and optionally hands the image to `--display-script` (e.g. `display_inky.py`). `--mode` and `--theme` are passed through to the renderer. `--once` renders a single frame unconditionally and exits — useful for cron, smoke tests, or first bring-up. In loop mode `render_now` and quiet-hours handling are wrapped in `try/except` with timestamped stderr logging so a transient failure (missing corpus row, Pillow blow-up, Inky disconnect) no longer kills the process — the loop just logs and waits for the next tick. `--once` stays strict so cron callers still fail loudly.

**Quiet hours.** Defaults to 22:00–06:00 (`--quiet-start` / `--quiet-end`, validated as `HH:MM` at parse time and supporting overnight ranges where `start > end`). When the loop first enters the window it either copies `--quiet-image` (default `assets/goodnight.png`, a pre-rendered dark-theme "good night / sleep" frame) to the output path and pushes it to the display, or — if `--quiet-image ""` is passed — re-renders the start time via `render_quote.py`. It then sits idle, skipping picks and renders, until the window ends; on exit it clears the bucket/quote-id state so the next normal tick is guaranteed to repaint. `--quiet-off` disables the feature entirely for 24/7 operation.

**Anti-repeat ledger.** After each successful render the loop appends `(timestamp, source_id, line_number)` to `--history-path` (default `~/.litclock/history.jsonl`, 7-day window via `--history-days`). The next `peek_quote_id` / `render_now` pair reads that ledger and filters out rows shown within the window, so the same quote is not repeated that week. The ledger write happens only after the render subprocess returns 0, so a crash mid-render leaves the ledger untouched; quiet-hours renders and dedup-skipped ticks also do not append. Pass `--history-path ""` or `--history-days 0` to disable.

**Auto-dark theme (`--theme auto`).** Picks `dark` between 18:00 and 06:00 (`AUTO_DARK_START_HOUR` / `AUTO_DARK_END_HOUR`) and `default` otherwise. `auto` is deliberately binary — the eight "operator-choice" themes (`scholar`, `newsprint`, `nightvision`, `blueprint`, `illuminated`, `bauhaus`, `risograph`, `comic`) are never auto-selected because they're aesthetic decisions, not time-of-day derivations. Each tick re-derives the effective theme from the wall clock; a theme change is treated like a bucket change (forces a redraw even if the picked quote is unchanged). The button-B manual cycle (or web-UI dropdown) wins until the next midnight rollover, when `_maybe_reset_manual_theme_at_midnight` clears `manual_theme` and `auto` resumes.

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

**Telemetry retention (`--telemetry-retain-days`, default 90).** Rotation bounds per-file size but not total file count. Once per local-date rollover the loop calls `prune_telemetry`, which globs the base path's parent for `<stem>-YYYYMMDD<suffix>` siblings, parses the date from the filename, and `unlink`s anything older than `today - retain_days`. The trigger is gated by `state.last_pruned_date` so we don't glob every tick. `litclock_health.py`'s summariser walks the same directory on every invocation, so unbounded retention eventually slows it down. Pass `0` to disable pruning entirely (e.g. for long-term forensic retention to external storage).

`litclock_health.py` globs the base path's directory for date-suffixed siblings (plus any legacy unsuffixed file at the exact base path) and stream-reads them in sorted-filename order. It prunes files older than the `--hours` window by filename date alone, with one day of slack so operators east/west of UTC don't accidentally drop the active file near midnight UTC (the per-entry `ts` filter in `load_entries` enforces the exact cutoff). Siblings that match the glob but whose date suffix doesn't parse as `YYYYMMDD` are skipped — pointing `--telemetry-path` at a file directly is the supported way to summarise an arbitrary JSONL. `render_count` is **positively identified** by the presence of an integer `render_ms` field — not by "non-error entry" — so `mode="backoff"` / `render_timeout` / `display_timeout` / `buttons_dead` / `state_validation` and other non-render telemetry modes stay out of the count (previously a backoff entry inflated `render_count` and an "errors but zero renders" appliance could read healthy). Summary output includes render count, error count, heartbeat count + last-heartbeat timestamp, p50/p95 render and display latency, last error message, and the **operator-action breakdown** added in phase 4: `action_count`, `actions_by_type`, `last_action_ts`, `press_dropped_count`, `web_auth_fail_count`, `web_error_count`, `quiet_enter_count`, `quiet_exit_count`. `--json` emits the same fields for cron/systemd integration. `--actions-only` renders an operator-centric "what did the user do?" view (shape-stable even on empty windows for grep-based cron); `--json` output shape is unchanged regardless of the flag. Exit codes: `0` healthy, `1` no telemetry log, `2` unhealthy (errors but zero renders in the window; `--fail-if-no-renders` was set and the window was silent; or `--max-heartbeat-age-minutes N` was set and the most recent heartbeat is older — or absent entirely).

**Startup frame (`--startup-image`).** Optional PNG pushed to the display once at loop startup, before the first quote render, so the panel doesn't ghost yesterday's frame during cold boot. Off by default (a Spectra 6 refresh takes 10–20s, so the extra round-trip isn't always worth it). Point at any PNG that encodes to the panel's 6-colour palette cleanly.

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

Optional in-process HTTP surface for browsing telemetry/coverage/candidates and curating `selection_overrides.json` without SSHing into the appliance. **Off by default** — only starts when `run_clock.py --web-bind HOST:PORT` is passed. Served from a `ThreadingHTTPServer` on a daemon background thread so the main render loop doesn't share an event loop with HTTP, but the two threads share `state.render_lock` / `state.lock` / `state.ledger_lock` via the same `RuntimeState` instance. **In-process is non-negotiable**: every mutating POST routes through the same `_button_render_gate` (non-blocking `render_lock.acquire`) that GPIO button handlers use, and atomic state/override writes are only safe when one process owns the file.

**Lifecycle.** `run_clock._maybe_start_web_server(args, state)` runs after `_maybe_start_buttons`, imports `web_server` lazily (so unit tests and `--buttons-off` dev hosts never pay for it), and calls `web_server.start_web_server(args, state, token=...)`. The `(server, thread)` handle is stashed so `stop_web_server` can be called by tests for deterministic teardown; the daemon thread flag means the process's own exit tears it down automatically under systemd. A startup failure (malformed bind, port busy, missing token on non-localhost bind) is **logged but not fatal** — the panel keeps rendering.

**Action handlers are shared with buttons.** Each GPIO button's body has been hoisted from `_build_button_handlers` closures into module-level `run_clock.action_skip` / `action_unskip` / `action_theme` / `action_quiet` / `action_rerender` functions. The button dispatcher and the HTTP handler both call them with a `label="button A"` or `label="web"` attribution string. Each function returns `{"ok": True, ...}` on success, `{"ok": False, "error": "busy"}` when the render lock is held, or `{"ok": False, "error": "<repr>"}` on exception; the web handler maps that to 200 / 409 / 500. The source-card restore timer and the shutdown command remain inline in `_build_button_handlers` because neither fits the single-response return-dict contract.

**Endpoints.**

```
GET  /                                → web/index.html
GET  /main.js, /style.css             → web/main.js, web/style.css
GET  /current.png                     → streams output/current.png
GET  /api/current                     → {time, bucket, theme, source_id, line_number, ...}
GET  /api/telemetry?hours=24          → {render_count, error_count, p50/p95 latencies, last_error}
GET  /api/coverage                    → assets/bucket-coverage.json payload
GET  /api/themes                      → {themes: [...THEME_ORDER], theme_arg, manual_theme, effective}
GET  /api/bucket/<bucket>?time=HH:MM&top=N → ranked candidates with named score components
GET  /api/overrides                   → assets/selection_overrides.json
GET  /api/history?limit=N             → anti-repeat ledger entries, newest-first
POST /api/overrides                   → validate + atomic rewrite
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

**No-op guard on `action_theme`.** The web dropdown pre-selects the active theme, so a "click Apply without changing anything" would otherwise burn a 10–20 s Spectra 6 refresh. Worse, if `manual_theme` was `None` (because `--theme auto` is running) and the target equals the auto-resolved value, setting `state.manual_theme = target` would silently pin auto mode off until the next midnight reset. `action_theme` returns `{"ok": True, "noop": True}` without mutating state when `target is not None and target == current_effective`. The button-B cycle path (`target is None`) deliberately bypasses the guard so it always advances.

**Scope boundary — what the curator UI doesn't (yet) edit.** `POST /api/overrides` writes `assets/selection_overrides.json` (source-level bans/boosts/preferred buckets). It does **not** edit `assets/content_overrides.json` — the per-row content sidecar applied by `apply_content_overrides.py` at corpus-build time is still SSH-and-editor-only, because its fixes have to be re-applied through the pipeline rather than picked up at next render. A UI editor for per-`(source_id, line_number)` content patches (and a separate "permanent ban this exact row" action) is the natural v2.1 extension — `/api/bucket/<bucket>` already surfaces the `source_id:line_number` key that the sidecar is keyed on.

### Appliance / Pi Setup

- **Fresh Pi:** `bootstrap_pi_inky.sh` automates apt setup, clones the Pimoroni `inky` installer, and (with `CONTINUE_AFTER_REBOOT=1` on the second run) clones this repo and does a first render + display push.
- **Manual Pi notes:** `pi_setup_inky_impression.md` is the long-form guide (hardware list, OS baseline, Pimoroni install, troubleshooting).
- **Boot-time service:** `litclock.service.example` is a sample systemd unit that runs `run_clock.py --display-script display_inky.py --mode production` as `pi` from `/home/pi/LitClock` under the `~/.virtualenvs/pimoroni` Python. Edit paths to match your install before copying into `/etc/systemd/system/`.

### Testing

The test suite lives in `tests/` and uses pytest with pytest-cov. There are 35 test modules covering every pipeline script plus the runtime components — ~2100 test cases at last count (including `test_bake_quote_database.py` for the display-ready DB baker, `test_bake_equivalence.py` which sweeps all 144 canonical buckets to prove baked picks match raw-corpus picks, plus dedicated suites for the appliance-hardening modules: `test_pidfile.py`, `test_sd_notify.py`, `test_web_server.py`, `test_contact_sheet.py`, `test_buckets.py`, and `test_jsonl_io.py`). `tests/test_atomic_io.py` exercises the shared durability primitive (`atomic_write_text` / `_bytes` / `_lines`) including monkeypatched `os.replace` failure paths that assert the tmp sibling is cleaned up and the target file is left byte-identical. The reliability branches of every caller are covered in their respective modules: `test_pick_quote.py` for the ledger-rewrite atomicity, `test_apply_content_overrides.py` for fail-open loading and atomic corpus writeback, `test_render_quote.py` for PNG-save crash recovery, `test_run_clock.py` for `_install_signal_handlers` / `_shutdown` / `prune_telemetry` / `_maybe_prune_telemetry`. Cross-cutting suites include `test_pipeline_integration.py` (end-to-end pipeline smoke), `test_corpus_invariants.py` (committed-corpus sanity checks), `test_miner_match_types.py` (regex per match type), `test_buckets_properties.py` (hypothesis-style bucket invariants), `test_concurrency.py` (render-lock and ledger-lock contention), and `test_cli_main_smoke.py` (each script's `if __name__ == "__main__"` entrypoint). `display_inky.py` is exercised via `test_display_inky.py` with `_push_to_panel` mocked out so the retry/error paths run without real hardware; it stays in `tool.coverage.run.omit` so coverage numbers aren't skewed by hardware-only branches. `inky_buttons.py` is tested with `gpiozero.Button` stubbed via a `FakeButton` class injected through `sys.modules`. `probe_buttons.py` has a smoke-test module (`test_probe_buttons.py`) that mocks GPIO interaction.

**Renderer golden-image suite (`tests/test_render_golden.py` + `tests/golden/renderer/*.png`).** Ten committed PNG fixtures spanning every layout × theme × mode combination (hero/standard/dense × default/dark × production/debug/card) plus the `fallback_debug_default` arrow-form footer and a `no_metadata_production` attribution-skipped edge case. Each scenario is re-rendered in-process and compared pixel-by-pixel against its golden via `ImageChops.difference`; `MAX_DIFF_RATIO = 0.001` (0.1% of 384,000 pixels) tolerates a one-pixel antialiasing boundary while catching layout, bold-phrase, and accent-colour regressions that flip thousands of pixels. Robust across FreeType / Pillow drift because `snap_image_to_palette` collapses every output pixel to one of six fixed Spectra 6 triples — subpixel drift generally rounds to the same palette index. Regenerate after an intentional renderer change with `UPDATE_RENDER_GOLDEN=1 pytest tests/test_render_golden.py`; a structure test fails if an orphaned fixture lingers after its scenario is deleted.

**Scorer property tests (`tests/test_scorer_properties.py`).** Complements the ordinal checks in `test_scorer_invariants.py` with systematic sweeps that would catch mutations the pairwise tests miss. Locks: tuple layout (length 12, `minute_penalty` at position 2, `override_bonus` at position 7, bake-component parity with `BAKED_SCORE_COMPONENTS`); lexicographic dominance (an earlier-position row wins against any later-position delta, no matter how large); strict monotonicity in quality across the full 0..100 sweep; minute-penalty dominance over metadata / dialogue / quality; `preferred_buckets` beats `boost_source_ids`; position isolation (each component only moves its own tuple slot — a refactor that leaks into two positions fails); request-time recomputation (only `minute_penalty` and `override_bonus` change as `requested_time` / `overrides` vary — the contract baked-row caching relies on); baked/raw interleave equivalence across five corner-case row shapes; exhaustive minute-distance sweep for every (requested, quote) pair in [0..55] step 5; and scoring purity (no mutation of the row dict or the overrides dict). Follows `test_buckets_properties.py`'s pattern — exhaustive enumeration over bounded spaces, no Hypothesis dependency.

**Test structure:**
- `tests/conftest.py` — shared fixtures: `make_row()` factory, `sample_row`, `sample_rows`, and `tmp_jsonl` (a helper that writes a list of dicts to a temp JSONL file). Also installs an autouse `_isolate_home` fixture that monkeypatches `$HOME` to a per-test tmp dir, so tests that use default `--state-path` / `--history-path` / `--pidfile` / `--telemetry-path` values can't leak state into the developer's real `~/.litclock/` or contaminate each other within a run.
- One `test_<script>.py` module per main script; tests are class-based (e.g., `TestCurrentBucket`, `TestRenderNow`)

**pyproject.toml** configures:
- `[project]`: name `litclock`, version, `requires-python >= 3.11`, runtime dep `Pillow`, optional extras `dev = [pytest, pytest-cov, ruff]` and `pi = [inky, gpiozero]` (`gpiozero` is needed by `inky_buttons.py` on the Pi). `pip install -e .[dev]` is the intended developer setup.
- pytest: `testpaths = ["tests"]`, `python_files = ["test_*.py"]`
- coverage: source = `.`, omits `tests/`, `bootstrap_pi_inky.sh`, and `display_inky.py`
- ruff: line-length 130, target Python 3.11, rules E / W / F / I (E501 ignored)

**CI:** `.github/workflows/ci.yml` runs on pushes to `main` and on every pull request — feature branches get checked via the `pull_request` trigger only, so `push` + `pull_request` don't double-run. Two jobs:
- `lint` — single Python 3.12 job running `ruff check --output-format=github .` once, so style feedback lands as inline PR annotations without waiting for the test matrix.
- `test` — matrix across Python 3.11 / 3.12 running `pytest --cov=. --cov-report=term-missing --cov-report=xml -v`; each matrix cell uploads its `coverage.xml` as `coverage-<py>` with `if-no-files-found: error` so a silent test-collection failure surfaces.

Both jobs install via `pip install -e ".[dev]"` (single source of truth with `pyproject.toml` — no hardcoded `pytest pytest-cov ruff Pillow` list to drift), enable `actions/setup-python`'s pip cache keyed on `pyproject.toml`, set `timeout-minutes` as a hang safety-net, and run with `permissions: contents: read` (least-privilege `GITHUB_TOKEN`). A top-level `concurrency` group cancels superseded PR runs (`cancel-in-progress` only when `github.event_name == 'pull_request'`) so `main`-branch history is preserved while rapid PR pushes don't pile up. The matrix runs with `fail-fast: false` so one Python version failing doesn't hide the other. Keep imports sorted (rule I) — run `ruff check .` locally before pushing.

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
runtime_store.py                   persisted runtime state JSON (manual_theme / manual_quiet + render-identity triple) loaded + validated at startup and saved atomically via atomic_io
pidfile.py                         single-instance fcntl.flock pidfile for run_clock.main (stale-pid reclaim, --pidfile opt-out)
sd_notify.py                       pure-stdlib systemd sd_notify client (READY=1 at startup, WATCHDOG=1 from heartbeat); no-op when $NOTIFY_SOCKET is unset
runtime_telemetry.py               date-rotated JSONL telemetry sidecar (append_telemetry, append_heartbeat, daily_telemetry_path, prune_telemetry)
runtime_theme.py                   theme resolution — auto-dark window, manual override, midnight reset
runtime_quiet.py                   in_quiet_hours + _display_quiet_image + compute_quiet/enter_quiet/exit_quiet state machine (shared by the main loop's scheduled quiet-hours branch and runtime_actions.action_quiet's manual toggle; --startup-image and button-D shutdown preamble reuse _display_quiet_image directly)
runtime_actions.py                 action_skip/unskip/theme/quiet/rerender + _button_render_gate — shared by GPIO buttons and the web UI; each action does a lazy `import run_clock` internally so tests that patch `run_clock.X` affect the call path (same pattern web_server.py uses)
display_inky.py                    Pi-only image → Inky Impression bridge (retry with backoff, per-theme saturation)
inky_buttons.py                    Pi-only gpiozero button listener (A/B/C/D → run_clock handlers, press_logger + buttons_alive supervision)
probe_buttons.py                   Pi-only GPIO press probe — confirms which pin each physical button actually fires
litclock_health.py                 telemetry summariser (render count, p50/p95 latency, last error; reads date-rotated sidecar)
web_server.py                      optional curator HTTP UI (off by default, --web-bind to enable; shares render_lock with button handlers)
web/                               vanilla HTML/JS/CSS served by web_server (index.html, main.js, style.css — no build step)
bootstrap_pi_inky.sh               first-time Pi setup helper
litclock.service.example           sample systemd unit
pi_setup_inky_impression.md        long-form Pi setup doc
FOLLOWUPS.md                       deferred-work list — items deliberately carved out of larger PRs to keep them focused; not a bug tracker
pyproject.toml                     project metadata + pytest / coverage / ruff configuration
fonts/                             bundled display faces: Playfair Display (default/dark), bitter/ (scholar — slab serif, variable), old-standard-tt/ (newsprint — Didone), space-mono/ (nightvision — retro mono), archivo/ (blueprint — grotesque sans), eb-garamond/ + unifraktur/ (illuminated — humanist serif body + blackletter ornaments), jost/ (bauhaus — geometric-constructed sans, variable), rubik/ (risograph — rounded sans, variable, axis default Light so Regular/Bold pinned explicitly), bangers/ (comic — all-caps comic-book display); each subdir ships its own OFL.txt
assets/candidates-attributed.jsonl raw attributed corpus — source-of-truth input to bake_quote_database.py; also served as the curator UI's /api/bucket view and used as pick_quote's defensive fallback if the baked DB is missing
assets/quote_database.jsonl        baked display-ready database — the canonical runtime input that pick_quote / run_clock / render_quote read by default; regenerate via bake_quote_database.py whenever the raw corpus changes
assets/bucket-coverage.md          committed snapshot of the current corpus's bucket coverage
assets/bucket-coverage.json        machine-readable companion to bucket-coverage.md
assets/contact-sheet.png           12×12 visual snapshot of every bucket's current pick (regenerate via contact_sheet.py)
assets/selection_overrides.json    manual bans/boosts/per-bucket preferences (pick_quote default --overrides)
assets/content_overrides.json      per-row content fixes (apply_content_overrides default --overrides)
assets/goodnight.png               static dark-theme "good night" frame shown during quiet hours
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
