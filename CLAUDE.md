# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

LitClock is a pipeline for harvesting time-related literary quotes from Project Gutenberg texts to populate a "literary clock" display (a quote per clock time). It has no external dependencies — stdlib only.

## Common Commands

```bash
# Mine a Gutenberg ebook by ID
python3 gutenberg_time_miner.py --gutenberg-id 1342 --strict --output output/candidates.jsonl

# Mine multiple IDs (batch script)
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

# Demo: pick a quote for a given time
python3 pick_quote.py --time 14:30
python3 pick_quote.py --bucket h2_half_pastish
```

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
  ↓ pick_quote.py
JSON quote for requested time
```

Default output directory: `projects/author-clock/output/`. Gutenberg downloads are cached in `data/gutenberg/`.

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

Use `--strict` for production runs to reduce false positives (excludes `daypart` and `digital` matches).

### JSONL Record Schema

Fields added progressively through the pipeline:

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
```

### Deduplication Key

`merge_candidates.py` deduplicates on `(normalized_time, fuzzy_bucket, daypart_bucket, canonical_quote)` where `canonical_quote` is lowercased with smart quotes and excess whitespace normalized. On collision, keeps the entry with longer `context_text`.

### Quality Scoring

`quality_filter.py` starts at 100 and applies penalties. Notable heavy penalties:
- Contains "work" (-45), "a.m."/"p.m." (-45), time range like "3:00–5:00" (-55), copyright/ebook metadata (-55), structural labels like "chapter"/"act" (-35)
- Fragment (-30), not a complete sentence (-20)

### Quote Selection (`pick_quote.py`)

Ranks candidates within a bucket by: non-fragment > complete sentence > ebook source > quality score > length near 140 chars. If no candidates meet `--min-quality` (default 60), falls back to adjacent buckets in alternating ±distance order.
