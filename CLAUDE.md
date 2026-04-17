# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

LitClock is a pipeline for harvesting time-related literary quotes from Project Gutenberg texts to populate a "literary clock" display (a quote per clock time). Every stage is a standalone Python 3 CLI script that reads/writes JSONL. The mining/selection pipeline is stdlib-only; only `render_quote.py` pulls in a third-party dep (Pillow) for PNG output.

## Common Commands

```bash
# Mine a Gutenberg ebook by ID
python3 gutenberg_time_miner.py --gutenberg-id 1342 --strict --output output/candidates.jsonl

# Mine multiple IDs (batch script — references projects/author-clock/ paths)
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

# Demo: pick a quote for a given time
python3 pick_quote.py --time 14:30
python3 pick_quote.py --bucket h2_half_pastish

# Render a PNG for a given time (requires Pillow + Noto/DejaVu fonts on disk)
python3 render_quote.py --time 22:54 --picker pick_quote.py
```

## Default paths

Every script's `--output`/`--input` defaults hardcode `projects/author-clock/...` paths (from when this lived inside a larger `~/workspace` tree). This repo is the author-clock project in isolation, so in practice you either:
- run from a parent dir that has `projects/author-clock/` symlinked/copied, or
- pass explicit `--input`/`--output` pointing at the top-level `output/` directory in this repo.

Gutenberg downloads are cached in `data/gutenberg/` (relative to CWD). The batch list in `gutenberg_batch_ids.txt` mirrors the `--gutenberg-id` args baked into `run_batch2.sh`.

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
  ↓ pick_quote.py
JSON quote for requested time
  ↓ render_quote.py (shells out to pick_quote.py)
render-HHMM.png
```

## Architecture

### Fuzzy Bucket System

The core abstraction. Each of 12 hours is divided into 8 minute-state buckets (96 total), named `h{HOUR}_{STATE}`:

| State | Minute range |
|---|---|
| `exact` | :00 |
| `just_after` | 1–5 |
| `early_past` | 6–14 |
| `quarter_pastish` | 15–19 |
| `half_pastish` | 20–39 |
| `late_past` | 40–44 |
| `quarter_toish` | 45–49 |
| `just_before` | 50–59 |

Plus `daypart` buckets (midnight, small_hours, dawn, morning, noon, afternoon, dusk, evening, night) for time references that don't specify an hour.

The same bucket boundaries are redefined inline in `pick_quote.py`, `fix_substring_time_matches.py`, and `gutenberg_time_miner.py` — changing the scheme means editing all three.

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

# Optional downstream (consumed but not produced by any committed script)
author, title  # read by render_quote.py if present on the row
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

### Quote Selection (`pick_quote.py`)

Ranks candidates in a bucket by the tuple:
`(fragment?, not complete sentence?, no source_id?, −quality_score, |len − 140| + exactness_bonus, len)`

Lower is better at every position. `exactness_bonus` is −2 when `matched_text` mentions "five/ten minutes to" or "fifty-five minutes past", and −1 for "quarter"/"half" matches — so these are preferred over vaguer matches at the same quality.

If no candidate in the target bucket clears `--min-quality` (default 60), it walks outward through sibling minute-states of the same hour in alternating ±distance order (see `neighbor_buckets`) until one is found; the chosen bucket is returned as `resolved_bucket` with `used_fallback: true`.

Among equally top-scoring rows, a seeded `random.Random(seed)` picks one so results are stable for a given `--seed`.

### Rendering (`render_quote.py`)

Shells out to `pick_quote.py` via `subprocess`, parses the JSON, then lays out an 800×480 grayscale PNG with Noto Serif + DejaVu Sans (hardcoded Linux font paths at `/usr/share/fonts/...`). The matched time phrase inside the quote is rendered in bold via a token-by-token styled wrapper (`tokenize_quote` + `wrap_styled_text`). Quote font size auto-shrinks from 34pt down to 20pt to fit the box. Bottom strip shows `author — title` when those fields exist on the picked row, plus a "fallback • quality N" footer.
