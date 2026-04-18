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

# Render a specific time directly (bypasses the loop)
python3 render_quote.py --time 22:54

# Show the picker's JSON for a given time or explicit bucket
python3 pick_quote.py --time 14:30
python3 pick_quote.py --bucket h2_half_pastish

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

# Attach title/author from Gutenberg headers — produces the picker's default input
python3 enrich_metadata.py output/candidates-quality.jsonl
# → output/candidates-attributed.jsonl
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
  ↓ fix_substring_time_matches.py (in place)
  ↓ enrich_metadata.py
candidates-attributed.jsonl    ← pick_quote.py --input default
  ↓ pick_quote.py
JSON quote for requested time
  ↓ render_quote.py (shells out to pick_quote.py)
render-HHMM.png  or  output/current.png
  ↓ display_inky.py (optional, Pi-only)
Inky Impression eInk panel
  ↑ run_clock.py orchestrates the render→display loop
```

## Architecture

### Fuzzy Bucket System

The core abstraction. Each of 12 hours is divided into 8 minute-state buckets (96 total), named `h{HOUR}_{STATE}`. Plus `daypart` buckets (midnight, small_hours, dawn, morning, noon, afternoon, dusk, evening, night) for time references that don't specify an hour.

**Heads-up: the minute→bucket mapping is redefined in four places, and two definitions disagree.**

Miner-side (`gutenberg_time_miner.py::minute_bucket` and `fix_substring_time_matches.py::BUCKET_ORDER`):

| State | Minutes |
|---|---|
| `exact` | 0 |
| `just_after` | 1–5 |
| `early_past` | 6–14 |
| `quarter_pastish` | 15–19 |
| `half_pastish` | 20–39 |
| `late_past` | 40–44 |
| `quarter_toish` | 45–49 |
| `just_before` | 50–59 |

Runtime-side (`pick_quote.py::minute_bucket` and `run_clock.py::current_bucket`):

| State | Minutes |
|---|---|
| `exact` | 0 |
| `just_after` | 1–5 |
| `early_past` | 6–14 |
| `quarter_pastish` | 15–19 |
| `half_pastish` | 20–34 |
| `late_past` | 35–39 |
| `quarter_toish` | 40–49 |
| `just_before` | 50–59 |

Rows are *tagged* with the miner-side boundaries at harvest time, but *queried* with the runtime-side boundaries at display time. The picker's neighbor-walk fallback (see below) papers over the mismatch in practice, but if you change either table you must change all four sites and consider re-running the miner.

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
display_quote, display_fragment (bool), cleanup_status ("complete_sentence" | "fragment_fallback" | "empty")

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
- Cleanup status other than `complete_sentence`: −20
- `digit_heavy` (≥6 digits): −25, `uppercase_heavy` (>18% uppercase): −15
- `weak_ending` (no terminal punct/quote): −10

Penalty reasons are appended to `quality_flags`. The score is floored at 0.

### Substring-Collision Fix

`fix_substring_time_matches.py` scans `display_quote` for the full pattern `<minute-word> minutes (past|to) <hour-word>`; if the row's stored `matched_text` is a strict substring of that longer phrase, the row's `matched_text`, `hour`, `minute`, `normalized_time`, and `fuzzy_bucket` are rewritten. Writes in-place by default (pass `--output` to redirect).

### Metadata Enrichment

`enrich_metadata.py` walks each row's `source_id`, opens the cached `data/gutenberg/pg<id>.txt`, and scans the first 120 lines for `Title: ` and `Author: ` headers. Results are cached per `source_id` so each file is parsed once. Fills `title`/`author` only when missing — existing values on a row are preserved. Output: `output/candidates-attributed.jsonl`, which `pick_quote.py` consumes by default.

### Quote Selection (`pick_quote.py`)

Default input: `output/candidates-attributed.jsonl`. Rows below `--min-quality` (default 60) are filtered out before scoring; banned `source_id`s (from `selection_overrides.json`) are dropped entirely.

Candidates in a bucket are ranked by a long lexicographic tuple (lower is better at every position):

```
(fragment_penalty,           # 0 if display_fragment is False, else 1
 cleanup_penalty,             # 0 if cleanup_status == "complete_sentence", else 1
 metadata_bonus,              # -3 both author+title, -1 one, +2 neither
 dialogue_penalty,            # +2 if text contains "he said" / "she said" / etc.
 opening_penalty,             # +2 weak opener (and/but/so/…), +1 pronoun opener
 source_bonus,                # +1 if no source_id
 override_bonus,              # -5 preferred_buckets[bucket] hit, -3 boost_source_ids hit
 -quality_score,              # higher quality wins
 length_penalty + exactness_bonus,
                              # |len(display_quote) - 140| plus:
                              #   -2 for "five/ten minutes to" or "fifty-five minutes past"
                              #   -1 for "quarter"/"half" matches
 len(display_quote))          # final tiebreak
```

If no candidate in the target bucket qualifies, it walks outward through sibling minute-states of the same hour in alternating ±distance order (see `neighbor_buckets`); the chosen bucket is returned as `resolved_bucket` with `used_fallback: true`.

Among equally top-scoring rows, a seeded `random.Random(seed)` picks one so results are stable for a given `--seed`.

### Selection Overrides (`selection_overrides.json`)

A small editable JSON doc consulted by `pick_quote.py`:

```json
{
  "ban_source_ids": [],        // source_ids excluded entirely
  "boost_source_ids": [],      // −3 in the ranking tuple
  "preferred_buckets": {}      // { "h3_late_past": 12345 } → that source_id wins in that bucket (−5)
}
```

IDs are compared as strings. Edit this file rather than editing the scorer when you want to manually curate a specific bucket.

### Rendering (`render_quote.py`)

Shells out to `pick_quote.py` via `subprocess`, parses the returned JSON, and lays out an 800×480 RGB PNG. Key details:

- **Palette.** Colors are drawn from the 6-color Spectra 6 palette (white/black/red/yellow/blue/green) and the final image is re-snapped to that palette via `snap_image_to_palette` so the Inky dithering stays predictable. The matched time phrase is rendered in `ACCENT` (red), everything else in black on white.
- **Fonts.** Prefers Playfair Display (from the repo-local `fonts/` directory, then common Pi/Linux paths) with Noto Serif / DejaVu Serif / Liberation Serif as fallbacks, and DejaVu/Noto/Liberation Sans for metadata. Install via `apt install fonts-noto-core fonts-dejavu-core` if the bundled fonts aren't found.
- **Layouts.** Three named layouts (`hero` ≤90 chars, `standard` ≤170, `dense` otherwise) each define their own `max_width`, `quote_height`, font size range, line-height multiplier, and quote-mark sizing. See the `LAYOUTS` dict.
- **Bold time phrase.** `resolve_display_match` tries to grow a multi-word time phrase ("five minutes past", etc.) inside the display text, then `tokenize_quote`/`wrap_styled_text` render it in bold + accent color while keeping word wrap correct across the bold boundary.
- **Fit loop.** `fit_quote` shrinks the quote font in 2pt steps from the layout's `font_max` down to `font_min` until all lines fit within `quote_height`.
- **Modes.** `--mode debug` (default) shows wall-clock time top-left, the resolved bucket, and a bottom-right footer (`layout • fallback? • quality N • shown HH:MM`). `--mode production` hides all of that for a clean appliance look.
- **Outputs.** `--output` defaults to `output/render-HHMM.png`; `run_clock.py` overrides this to `output/current.png` so the Inky bridge has a stable filename.

### Runtime Loop (`run_clock.py`)

Thin orchestrator. Each tick (`--interval-seconds`, default 60) it computes the current fuzzy bucket; only when the bucket *changes* does it re-invoke `render_quote.py` with the current time, and then optionally hand the image to `--display-script` (e.g. `display_inky.py`). `--once` renders a single frame and exits — useful for cron, smoke tests, or first bring-up. `--mode` is passed through to the renderer.

### Inky Display Bridge (`display_inky.py`)

Minimal Pillow → Pimoroni `inky.auto` bridge. Loads the PNG, resizes to the panel's native size if needed, and calls `inky.set_image(..., saturation=0.5).show()`. Designed to be called once per render from `run_clock.py`. Only needed on the Pi.

### Appliance / Pi Setup

- **Fresh Pi:** `bootstrap_pi_inky.sh` automates apt setup, clones the Pimoroni `inky` installer, and (with `CONTINUE_AFTER_REBOOT=1` on the second run) clones this repo and does a first render + display push.
- **Manual Pi notes:** `pi_setup_inky_impression.md` is the long-form guide (hardware list, OS baseline, Pimoroni install, troubleshooting).
- **Boot-time service:** `litclock.service.example` is a sample systemd unit that runs `run_clock.py --display-script display_inky.py --mode production` as `pi` from `/home/pi/LitClock` under the `~/.virtualenvs/pimoroni` Python. Edit paths to match your install before copying into `/etc/systemd/system/`.

### Testing

The test suite lives in `tests/` and uses pytest with pytest-cov. There are 13 test modules covering every pipeline script plus the runtime components — roughly 200 tests total.

**Test structure:**
- `tests/conftest.py` — shared fixtures: `make_row()` factory, `sample_row`, `sample_rows`, and `tmp_jsonl` (a helper that writes a list of dicts to a temp JSONL file)
- One `test_<script>.py` module per main script; tests are class-based (e.g., `TestCurrentBucket`, `TestRenderNow`)

**pyproject.toml** configures:
- pytest: `testpaths = ["tests"]`, `python_files = ["test_*.py"]`
- coverage: source = `.`, omits `tests/` and `bootstrap_pi_inky.sh`
- ruff: line-length 130, target Python 3.11, rules E / W / F / I

**CI:** `.github/workflows/ci.yml` runs on every push and PR against Python 3.11 and 3.12. It installs `pytest pytest-cov ruff Pillow`, runs `ruff check .` then `pytest --cov`, and uploads a coverage artifact. Keep the lint clean — ruff enforces import ordering (rule I) so imports must be sorted.

### Repo Layout

```
gutenberg_time_miner.py      harvest regex-matched time phrases from .txt
merge_candidates.py          dedupe harvested JSONL rows
bucket_coverage.py           coverage report per (hour, minute-state) bucket
target_sparse_buckets.py     targeted regex sweep for empty buckets
import_targeted_hits.py      reshape targeted hits for merge
clean_display_quotes.py      pick a displayable excerpt from each row
quality_filter.py            score + flag rows
fix_substring_time_matches.py  repair substring-collision time tags
enrich_metadata.py           attach author/title from Gutenberg headers
pick_quote.py                rank candidates, honor overrides, fall back to neighbors
selection_overrides.json     manual bans/boosts/per-bucket preferences
render_quote.py              Pillow layout → 800×480 Spectra-6 PNG
run_clock.py                 runtime loop (bucket-change-triggered)
display_inky.py              Pi-only image → Inky Impression bridge
bootstrap_pi_inky.sh         first-time Pi setup helper
litclock.service.example     sample systemd unit
pi_setup_inky_impression.md  long-form Pi setup doc
pyproject.toml               pytest / coverage / ruff configuration
fonts/                       bundled Playfair Display family
tests/                       pytest suite — one module per script + conftest.py
output/                      JSONL pipeline artifacts + rendered PNGs
research/output-archive/     historical pipeline outputs retained for reference
data/gutenberg/              cached Gutenberg text downloads (gitignored)
.github/workflows/ci.yml     GitHub Actions CI (lint + test, Python 3.11 & 3.12)
gutenberg_batch_ids.txt      batch list of Gutenberg IDs
run_batch2.sh                bulk harvest driver
```
