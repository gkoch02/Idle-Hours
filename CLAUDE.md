# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

LitClock is an end-to-end literary-clock system: it harvests time-related quotes from Project Gutenberg, scores and cleans them, then picks and renders a quote for any clock time. The render is designed for a Pimoroni Inky Impression 7.3 Spectra 6 eInk panel (800×480, 6-color palette) but writes a plain PNG first, so it runs fine on any machine.

Every stage is a standalone Python 3 CLI script that reads/writes JSONL. The mining/selection pipeline is stdlib-only; `render_quote.py` pulls in Pillow, and `display_inky.py` additionally needs the Pimoroni `inky` package (Pi only).

## Common Commands

### Testing & linting

```bash
# Run the full test suite
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
render-HHMM.png  or  output/current.png
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
| `~/.litclock/telemetry-YYYYMMDD.jsonl` | render / error telemetry | — | runtime, per-appliance | `run_clock.py` |

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

### Rendering (`render_quote.py`)

Imports `pick_quote` in-process (`pick_quote_module.select_quote`) and lays out an 800×480 RGB PNG — no subprocess, no stdout-JSON contract. Key details:

- **Palette.** Colors are drawn from the 6-color Spectra 6 palette (white/black/red/yellow/blue/green) and the final image is re-snapped to that palette via `snap_image_to_palette` so the Inky dithering stays predictable.
- **Themes.** The `THEMES` dict defines two color sets: `default` (white page, black text, red accent) and `dark` (black page, white text, yellow accent). `--theme` selects one; `run_clock.py` forwards it via `--theme`. The matched time phrase is rendered in the theme's accent color; everything else uses the theme's text/source colors.
- **Fonts.** Prefers Playfair Display (from the repo-local `fonts/` directory, then common Pi/Linux paths) with Noto Serif / DejaVu Serif / Liberation Serif as fallbacks, and DejaVu/Noto/Liberation Sans for metadata. Install via `apt install fonts-noto-core fonts-dejavu-core` if the bundled fonts aren't found. When every TTF candidate is missing, `load_font` logs a one-shot warning to stderr before returning `ImageFont.load_default()` so a misconfigured install surfaces instead of silently producing an 8-pixel bitmap render.
- **Layouts.** Three named layouts (`hero` ≤90 chars, `standard` ≤170, `dense` otherwise) each define their own `max_width`, `quote_height`, font size range, line-height multiplier, and quote-mark sizing. See the `LAYOUTS` dict.
- **Bold time phrase.** `resolve_display_match` tries to grow a multi-word time phrase ("five minutes past", etc.) inside the display text, then `tokenize_quote`/`wrap_styled_text` render it in bold + accent color while keeping word wrap correct across the bold boundary.
- **Text cleanup.** `strip_underscore_emphasis` drops Gutenberg's `_emphasis_` markers and `normalize_dashes` converts bare `--` to em-dashes before layout.
- **Fit loop.** `fit_quote` shrinks the quote font in 2pt steps from the layout's `font_max` down to `font_min` until all lines fit within `quote_height`.
- **Justification.** Non-last lines are fully justified by distributing leftover slack across inter-word spaces — but only when slack is ≤25% of the layout's `max_width`. Loose lines fall back to ragged-right because wide forced gaps look worse than uneven right edges.
- **Modes.** `--mode debug` (default) draws a top-right `DEBUG MODE` banner (rendered in sans-bold to match the footer strip, in the theme's accent color) plus a centered bottom strip (`HH:MM · bucket[ → resolved] · layout X · quality N · id source:Lline`) separated from the quote block by a dotted horizontal rule. `--mode production` hides all of that for a clean appliance look.
- **Outputs.** `--output` defaults to `output/render-HHMM.png`; `run_clock.py` overrides this to `output/current.png` so the Inky bridge has a stable filename. The PNG is encoded to a `BytesIO` and written via `atomic_io.atomic_write_bytes` so a power cut mid-save can't leave a truncated frame for the next tick (and for `display_inky.py`) to read. The underlying PIL `Image` is explicitly `close()`d after encoding to release the file handle — important over months of continuous operation.

### Runtime Loop (`run_clock.py`)

Thin orchestrator. Each tick (`--interval-seconds`, default 60) it computes the current fuzzy bucket; only when the bucket *changes* does it consider re-invoking `render_quote.py`. Before launching the renderer it calls `peek_quote_id` — which runs `pick_quote.select_quote` in-process and returns `(source_id, line_number, display_quote, matched_text)` — and compares that identity tuple against `last_quote_id`. `matched_text` is part of the identity because the renderer uses it to choose which phrase gets bolded/coloured, so two picks that share source/line/quote but differ in the matched phrase (e.g. `02:50` vs `02:55` landing on the same row) still produce visibly different frames and must not dedupe together. If the picked quote is unchanged, the redraw is skipped so the eInk panel is not refreshed for a visually-identical frame. Otherwise it re-renders and optionally hands the image to `--display-script` (e.g. `display_inky.py`). `--mode` and `--theme` are passed through to the renderer. `--once` renders a single frame unconditionally and exits — useful for cron, smoke tests, or first bring-up. In loop mode `render_now` and quiet-hours handling are wrapped in `try/except` with timestamped stderr logging so a transient failure (missing corpus row, Pillow blow-up, Inky disconnect) no longer kills the process — the loop just logs and waits for the next tick. `--once` stays strict so cron callers still fail loudly.

**Quiet hours.** Defaults to 22:00–06:00 (`--quiet-start` / `--quiet-end`, validated as `HH:MM` at parse time and supporting overnight ranges where `start > end`). When the loop first enters the window it either copies `--quiet-image` (default `assets/goodnight.png`, a pre-rendered dark-theme "good night / sleep" frame) to the output path and pushes it to the display, or — if `--quiet-image ""` is passed — re-renders the start time via `render_quote.py`. It then sits idle, skipping picks and renders, until the window ends; on exit it clears the bucket/quote-id state so the next normal tick is guaranteed to repaint. `--quiet-off` disables the feature entirely for 24/7 operation.

**Anti-repeat ledger.** After each successful render the loop appends `(timestamp, source_id, line_number)` to `--history-path` (default `~/.litclock/history.jsonl`, 7-day window via `--history-days`). The next `peek_quote_id` / `render_now` pair reads that ledger and filters out rows shown within the window, so the same quote is not repeated that week. The ledger write happens only after the render subprocess returns 0, so a crash mid-render leaves the ledger untouched; quiet-hours renders and dedup-skipped ticks also do not append. Pass `--history-path ""` or `--history-days 0` to disable.

**Auto-dark theme (`--theme auto`).** Picks `dark` between 18:00 and 06:00 (`AUTO_DARK_START_HOUR` / `AUTO_DARK_END_HOUR`) and `default` otherwise. Each tick re-derives the effective theme from the wall clock; a theme change is treated like a bucket change (forces a redraw even if the picked quote is unchanged). The button-B manual toggle wins until the next midnight rollover, when `_maybe_reset_manual_theme_at_midnight` clears it so `auto` resumes.

**Inky buttons (`inky_buttons.py`).** The four capacitive buttons on the Inky Impression are wired to GPIO 5/6/16/24 (labels A/B/C/D) and dispatched by `inky_buttons.start_listener(short_handlers, hold_handlers=..., press_logger=...)` using `gpiozero.Button` with a 0.3-second debounce and a 2-second hold threshold. The hardware import is local to `start_listener` so the module is import-safe on dev hosts. `run_clock.py` builds the short/hold handler dicts in `_build_button_handlers` and stashes the returned keepalive list for the lifetime of the loop — `gpiozero` drops handlers when its `Button` is garbage-collected, so the reference must be held. Handlers act synchronously in the listener thread and serialize against the main loop via `state.render_lock`; mutations of theme/quiet flags are guarded by `state.lock`. Pass `--buttons-off` on dev machines or for headless runs.

Short-press vs long-press dispatch is routed through a tiny `_HoldDispatcher` so the short callback fires on *release* only when the button was not held long enough to trigger the hold callback — a long press therefore fires only the hold action, never both.

**Drop-on-busy press gate.** Every button handler wraps its work in `run_clock._button_render_gate`, which does a *non-blocking* acquire of `state.render_lock`. If a render is already in flight (a Spectra 6 refresh can take 10–20s), the press is logged (`"button {name}: busy (render in flight), press ignored"`) and dropped. Without this, gpiozero queues subsequent events behind the slow eInk refresh and a tap-burst produces unpredictable multi-second delayed actions; with it the UX is "first press wins, subsequent presses during the refresh are no-ops."

**Per-press GPIO logging.** `start_listener` accepts an optional `press_logger(label, gpio_pin)` callback that fires on every hardware press, before short/long dispatch and independent of handler exceptions. `run_clock._maybe_start_buttons` wires it to a `_press_logger` that logs `"press: {label} (GPIO {pin})"`, so a field operator can grep the journal to confirm a physical button actually fired before blaming handler code. For deeper wiring diagnosis use `probe_buttons.py` (standalone — doesn't need the main loop to be running).

**Liveness supervision.** gpiozero runs its event loop on a background thread; if that thread dies or the pin claim is lost (flaky GPIO, post-reboot race, another process grabbing the pin) `Button.closed` flips to `True` and presses silently stop working. Each tick the main loop calls `_check_button_liveness`, which consults `inky_buttons.buttons_alive(state.button_handles)`. On the first failure it logs a loud stderr warning, appends `{"mode": "buttons_dead", "error": "button listener died"}` to telemetry, and latches `state.buttons_dead_logged` so subsequent ticks stay quiet. We deliberately do **not** auto-restart — a listener that died once often dies again immediately and a restart loop would thrash GPIO claims.

| Button | Short press | Long press (2s) |
|---|---|---|
| **A** | Skip — bans the current quote in the history ledger, picks again, re-renders. Records the just-banned quote as `state.last_skipped`. | Un-skip — removes the last-skipped quote's entry from the history ledger and re-renders. Reverses a fat-fingered tap. |
| **B** | Toggle theme — flips default ↔ dark, persists to `--state-path`, re-renders. | — |
| **C** | Source card — renders a `--mode card` overlay (title / author / Gutenberg ID / matched phrase) for 5 seconds, then the timer thread itself re-renders the original frame (the next loop tick alone could be up to 60s away). | — |
| **D** | Quiet now / wake — toggles `manual_quiet`, persists to `--state-path`. Going quiet pushes `--quiet-image` immediately; going active picks and renders the current time. | Shutdown — shows `--quiet-image`, then runs `--shutdown-command` (default `sudo -n shutdown -h now`). Requires passwordless sudo for shutdown; override or empty the flag if you don't want this behaviour. |

**Persisted runtime state (`--state-path`).** `~/.litclock/state.json` (default) holds `manual_theme` and `manual_quiet`. Loaded at loop startup so the user's last button-B / button-D choices survive a restart. Pass an empty string to disable. `save_runtime_state` writes atomically via the shared `atomic_io.atomic_write_text` helper: payload → sibling `*.tmp` file → `fsync` → `os.replace` into place → `fsync` of the parent directory. Without that final directory fsync the kernel can return from `os.replace` with the new dirent still in cache, and a crash in that window leaves the old/missing file despite the rename "succeeding." Directory-fsync failures are swallowed on platforms where they aren't meaningful (notably Windows).

**Graceful shutdown (`SIGTERM` / `SIGINT`).** `_install_signal_handlers` binds both signals to a handler that flips `state.stop_requested` (a `threading.Event`). The main loop checks the flag at the top of each iteration and waits on it via `_loop_sleep` between ticks, so a `systemctl restart litclock.service` is observed within one tick instead of being escalated to `SIGKILL` mid-render. On loop exit `_shutdown` runs in a `finally`: it blocks on `state.render_lock` up to 30s so any in-flight render finishes, stops the web server, closes every `gpiozero.Button` handle so the GPIO listener thread exits, and persists state once more. Every step is wrapped in `contextlib.suppress` — shutdown is best-effort so one teardown failure doesn't block the others. `--once` keeps its strict-exit behaviour; signal handling only activates on the long-running loop path.

**Telemetry sidecar (`--telemetry-path`).** `~/.litclock/telemetry.jsonl` (default) is the **base path**; `append_telemetry` actually writes to a date-rotated sibling `<stem>-YYYYMMDD<suffix>` in the same directory (e.g. `~/.litclock/telemetry-20260420.jsonl`). Rotation keeps each file bounded so a multi-year-running appliance doesn't produce a single unbounded JSONL that chokes health checks and stalls append latency. Each entry is one JSON line: successful renders write `bucket`, `render_ms`, `display_ms`, `source_id`, `line_number`, `mode`, `theme`; loop-level errors write `bucket`, `error`, `mode`. Telemetry writes are best-effort — I/O failures log and drop the entry rather than crashing the loop. Pass an empty string to disable.

**Telemetry retention (`--telemetry-retain-days`, default 90).** Rotation bounds per-file size but not total file count. Once per local-date rollover the loop calls `prune_telemetry`, which globs the base path's parent for `<stem>-YYYYMMDD<suffix>` siblings, parses the date from the filename, and `unlink`s anything older than `today - retain_days`. The trigger is gated by `state.last_pruned_date` so we don't glob every tick. `litclock_health.py`'s summariser walks the same directory on every invocation, so unbounded retention eventually slows it down. Pass `0` to disable pruning entirely (e.g. for long-term forensic retention to external storage).

`litclock_health.py` globs the base path's directory for date-suffixed siblings (plus any legacy unsuffixed file at the exact base path) and stream-reads them in sorted-filename order. It prunes files older than the `--hours` window by filename date alone, with one day of slack so operators east/west of UTC don't accidentally drop the active file near midnight UTC (the per-entry `ts` filter in `load_entries` enforces the exact cutoff). Siblings that match the glob but whose date suffix doesn't parse as `YYYYMMDD` are skipped — pointing `--telemetry-path` at a file directly is the supported way to summarise an arbitrary JSONL. Summary output includes render count, error count, p50/p95 render and display latency, last error message; `--json` emits the same fields for cron/systemd integration. Exit codes: `0` healthy, `1` no telemetry log, `2` unhealthy (errors but zero renders in the window, or `--fail-if-no-renders` was set and the window was silent).

**Startup frame (`--startup-image`).** Optional PNG pushed to the display once at loop startup, before the first quote render, so the panel doesn't ghost yesterday's frame during cold boot. Off by default (a Spectra 6 refresh takes 10–20s, so the extra round-trip isn't always worth it). Point at any PNG that encodes to the panel's 6-colour palette cleanly.

### Contact Sheet (`contact_sheet.py`)

Offline QA tool. For each of the 144 `h{1..12}_{state}` buckets, calls `pick_quote.select_quote` at the bucket's canonical `HH:MM` (e.g. `h3_twenty_past` → `03:20`; `h12_*` maps to `00:MM`), renders the full 800×480 frame via `render_quote.render`, and downscales it into a tile on a 12×12 grid. Each tile gets a small `HH:MM  h{hour}_{state}` caption below so you can locate specific buckets at a glance. Flags: `--tile-width`/`--tile-height` (defaults 200×120), `--caption-height` (18), `--margin` (6), `--theme`, and `--mode` — defaults to `production` so the debug footer doesn't dominate small tiles. History filtering is forced off (snapshot of the whole corpus, not anti-repeated picks). Use this to spot regressions after a corpus change: layout bugs, malformed `matched_text`, repeat authors in adjacent buckets, or fallback-bucket frames that look visually wrong.

### Inky Display Bridge (`display_inky.py`)

Minimal Pillow → Pimoroni `inky.auto` bridge. Loads the PNG, resizes to the panel's native size if needed, and calls `inky.set_image(..., saturation=...).show()`. Designed to be called once per render from `run_clock.py`. Only needed on the Pi. Up to `MAX_ATTEMPTS` (3) calls are retried with `RETRY_BACKOFF_SECONDS = (1, 4)` between attempts so a momentary I/O hiccup doesn't crash the caller; if all attempts fail the script raises `SystemExit` so the loop in `run_clock.py` logs and moves on.

**Per-theme saturation.** `THEME_SATURATION` defaults to `{default: 0.5, dark: 0.7}` — the Spectra 6 panel renders dark backgrounds with a different waveform than light ones, so pushing saturation slightly higher on dark keeps accent colours from looking muddy. `run_clock.render_now` forwards `--theme` to `display_inky.py`, which calls `resolve_saturation(theme, override)` to pick the value to push. An explicit `--saturation` always wins over the per-theme default.

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
GET  /api/bucket/<bucket>?time=HH:MM&top=N → ranked candidates with named score components
GET  /api/overrides                   → assets/selection_overrides.json
GET  /api/history?limit=N             → anti-repeat ledger entries, newest-first
POST /api/overrides                   → validate + atomic rewrite
POST /api/action/{skip,unskip,theme,quiet,rerender} → mirror physical buttons
```

**Security model.** Loopback binds (`127.0.0.1:*`, `localhost:*`, `::1:*`) run without auth — the OS-level trust boundary is sufficient for a single-operator home appliance. Any other bind **requires** `--web-token` or `--web-token-file`; `start_web_server` raises `ValueError` if you try to bind `0.0.0.0` without one, so an operator can't accidentally expose a tokenless POST surface. Tokens are checked against the `X-LitClock-Token` header only — never query strings, which `BaseHTTPRequestHandler` logs to stderr and journald. `_check_token` uses `hmac.compare_digest` for timing-safety. Unknown POST routes return 404 **before** the auth check so a scanner's wrong-token probe doesn't learn the service exists. GETs stay open on every bind (telemetry + coverage + `current.png` are not sensitive and the UI fetches them without credentials). `--web-token-file` is preferred over `--web-token` in production so the secret doesn't show up in `ps`/journald.

**Shared utilities, no duplication.**
- Atomic writes go through `atomic_io.atomic_write_text` / `atomic_write_bytes` / `atomic_write_lines` (tmp → fsync → `os.replace` → dir fsync), the single durability primitive shared between `save_runtime_state`, `web_server.write_overrides_atomic`, the rendered-PNG writer in `render_quote`, the ledger-rewrite path in `pick_quote.remove_last_history_entry`, and the corpus writeback in `apply_content_overrides`. `run_clock._atomic_write_text` is a thin compatibility shim over the shared helper.
- Bucket validation uses `pick_quote.valid_bucket_names()` so `POST /api/overrides` rejects the same bad keys that `load_overrides` warns about.
- Telemetry summarisation reuses `litclock_health.load_entries` and `litclock_health.summarise` directly — the endpoint does not reimplement date-window globbing.
- `pick_quote.pick_best(..., return_ranked=True)` and `pick_quote.select_candidates(...)` are the single entry point for the bucket-inspector view; the UI projects the raw `score_row` tuple into named fields via `SCORE_COMPONENTS` so the operator can see "lost by minute_penalty=8" rather than a mystery integer.

**Static assets.** `web/index.html` + `web/main.js` + `web/style.css` are plain HTML/JS/CSS, **no build step** and no framework. Resolved via `BASE_DIR / "web"` so the service file doesn't depend on CWD. `main.js` polls `/api/current` and `/api/telemetry` every 30s; the coverage grid and overrides editor load once and refresh on click.

**Scope boundary — what the curator UI doesn't (yet) edit.** `POST /api/overrides` writes `assets/selection_overrides.json` (source-level bans/boosts/preferred buckets). It does **not** edit `assets/content_overrides.json` — the per-row content sidecar applied by `apply_content_overrides.py` at corpus-build time is still SSH-and-editor-only, because its fixes have to be re-applied through the pipeline rather than picked up at next render. A UI editor for per-`(source_id, line_number)` content patches (and a separate "permanent ban this exact row" action) is the natural v2.1 extension — `/api/bucket/<bucket>` already surfaces the `source_id:line_number` key that the sidecar is keyed on.

### Appliance / Pi Setup

- **Fresh Pi:** `bootstrap_pi_inky.sh` automates apt setup, clones the Pimoroni `inky` installer, and (with `CONTINUE_AFTER_REBOOT=1` on the second run) clones this repo and does a first render + display push.
- **Manual Pi notes:** `pi_setup_inky_impression.md` is the long-form guide (hardware list, OS baseline, Pimoroni install, troubleshooting).
- **Boot-time service:** `litclock.service.example` is a sample systemd unit that runs `run_clock.py --display-script display_inky.py --mode production` as `pi` from `/home/pi/LitClock` under the `~/.virtualenvs/pimoroni` Python. Edit paths to match your install before copying into `/etc/systemd/system/`.

### Testing

The test suite lives in `tests/` and uses pytest with pytest-cov. There are 31 test modules covering every pipeline script plus the runtime components — ~1855 tests at last count (including `test_bake_quote_database.py` for the display-ready DB baker and `test_bake_equivalence.py` which sweeps all 144 canonical buckets to prove baked picks match raw-corpus picks). `tests/test_atomic_io.py` exercises the shared durability primitive (`atomic_write_text` / `_bytes` / `_lines`) including monkeypatched `os.replace` failure paths that assert the tmp sibling is cleaned up and the target file is left byte-identical. The reliability branches of every caller are covered in their respective modules: `test_pick_quote.py` for the ledger-rewrite atomicity, `test_apply_content_overrides.py` for fail-open loading and atomic corpus writeback, `test_render_quote.py` for PNG-save crash recovery, `test_run_clock.py` for `_install_signal_handlers` / `_shutdown` / `prune_telemetry` / `_maybe_prune_telemetry`. Cross-cutting suites include `test_pipeline_integration.py` (end-to-end pipeline smoke), `test_corpus_invariants.py` (committed-corpus sanity checks), `test_miner_match_types.py` (regex per match type), `test_buckets_properties.py` (hypothesis-style bucket invariants), `test_concurrency.py` (render-lock and ledger-lock contention), and `test_cli_main_smoke.py` (each script's `if __name__ == "__main__"` entrypoint). `display_inky.py` is exercised via `test_display_inky.py` with `_push_to_panel` mocked out so the retry/error paths run without real hardware; it stays in `tool.coverage.run.omit` so coverage numbers aren't skewed by hardware-only branches. `inky_buttons.py` is tested with `gpiozero.Button` stubbed via a `FakeButton` class injected through `sys.modules`. `probe_buttons.py` has a smoke-test module (`test_probe_buttons.py`) that mocks GPIO interaction.

**Test structure:**
- `tests/conftest.py` — shared fixtures: `make_row()` factory, `sample_row`, `sample_rows`, and `tmp_jsonl` (a helper that writes a list of dicts to a temp JSONL file)
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
clean_display_quotes.py            pick a displayable excerpt from each row (expands bare single-sentence hits with up to 2 neighbouring sentences, rejects mid-text chapter headings)
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
runtime_state.py                   RuntimeState class — locks, mutable shared state between the loop, button listener, and web server
runtime_store.py                   persisted runtime state JSON (manual_theme / manual_quiet) loaded at startup and saved atomically via atomic_io
runtime_telemetry.py               date-rotated JSONL telemetry sidecar (append_telemetry, daily_telemetry_path, prune_telemetry)
runtime_theme.py                   theme resolution — auto-dark window, manual override, midnight reset
runtime_quiet.py                   in_quiet_hours + _display_quiet_image (shared by quiet hours, --startup-image, and button-D shutdown preamble)
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
pyproject.toml                     project metadata + pytest / coverage / ruff configuration
fonts/                             bundled Playfair Display family
assets/candidates-attributed.jsonl raw attributed corpus — source-of-truth input to bake_quote_database.py; also served as the curator UI's /api/bucket view and used as pick_quote's defensive fallback if the baked DB is missing
assets/quote_database.jsonl        baked display-ready database — the canonical runtime input that pick_quote / run_clock / render_quote read by default; regenerate via bake_quote_database.py whenever the raw corpus changes
assets/bucket-coverage.md          committed snapshot of the current corpus's bucket coverage
assets/bucket-coverage.json        machine-readable companion to bucket-coverage.md
assets/contact-sheet.png           12×12 visual snapshot of every bucket's current pick (regenerate via contact_sheet.py)
assets/selection_overrides.json    manual bans/boosts/per-bucket preferences (pick_quote default --overrides)
assets/content_overrides.json      per-row content fixes (apply_content_overrides default --overrides)
assets/goodnight.png               static dark-theme "good night" frame shown during quiet hours
assets/preview.png                 README hero image
tests/                             pytest suite — one module per script + conftest.py
output/                            runtime render target (output/current.png); gitignored except .gitkeep
data/gutenberg/                    cached Gutenberg text downloads (gitignored)
.github/workflows/ci.yml           GitHub Actions CI (lint + test, Python 3.11 & 3.12)
gutenberg_batch_ids.txt            batch list of Gutenberg IDs for run_batch2.sh
gutenberg_dawn_expansion_ids.txt   curated clock-precise Gutenberg ID list for run_dawn_expansion.sh
run_batch2.sh                      bulk harvest driver
run_dawn_expansion.sh              one-shot "mine curated IDs → pipeline → merge into live corpus" driver
```
