#!/usr/bin/env bash
# Fetch the curated clock-precise books, run them through the pipeline
# in isolation, then merge the attributed result into the existing
# assets/candidates-attributed.jsonl without clobbering it.
#
# Must run on a machine with network access to www.gutenberg.org
# (the CI sandbox blocks it). Safe to re-run: gutenberg_time_miner
# caches downloads in data/gutenberg/ and merge_candidates dedupes.
#
# Usage:  bash run_dawn_expansion.sh
set -euo pipefail

cd "$(dirname "$0")"

IDS_FILE="gutenberg_dawn_expansion_ids.txt"
EXISTING="assets/candidates-attributed.jsonl"
RAW_OUT="output/raw-candidates-dawn-expansion.jsonl"
DAWN_MERGED="output/dawn-merged.jsonl"
DAWN_CLEANED="output/dawn-cleaned.jsonl"
DAWN_QUALITY="output/dawn-quality.jsonl"
DAWN_ATTRIBUTED="output/dawn-attributed.jsonl"

if [[ ! -f "$EXISTING" ]]; then
  echo "ERROR: $EXISTING missing — refusing to run." >&2
  echo "Checkout the baseline corpus first: git checkout $EXISTING" >&2
  exit 1
fi
baseline_rows=$(wc -l < "$EXISTING" | tr -d ' ')
echo ">>> Baseline corpus: $baseline_rows rows"

# Build the --gutenberg-id args (skipping comments/blank lines).
ID_ARGS=()
while IFS= read -r line; do
  line="${line%%#*}"
  line="${line//[[:space:]]/}"
  [[ -z "$line" ]] && continue
  ID_ARGS+=(--gutenberg-id "$line")
done < "$IDS_FILE"

echo ">>> Harvesting $(( ${#ID_ARGS[@]} / 2 )) Gutenberg IDs..."
python3 gutenberg_time_miner.py "${ID_ARGS[@]}" \
  --strict --skip-fetch-errors \
  --output "$RAW_OUT"

echo ">>> Running dawn harvest through the pipeline (standalone)..."
python3 merge_candidates.py "$RAW_OUT" --output "$DAWN_MERGED"
python3 clean_display_quotes.py "$DAWN_MERGED" --output "$DAWN_CLEANED"
python3 quality_filter.py "$DAWN_CLEANED" --output "$DAWN_QUALITY"
python3 fix_substring_time_matches.py "$DAWN_QUALITY"
python3 enrich_metadata.py "$DAWN_QUALITY" --output "$DAWN_ATTRIBUTED"

echo ">>> Merging attributed dawn rows into existing corpus..."
# Write to a tmp file first so we never read and write the same file simultaneously.
TMP_OUT=$(mktemp output/candidates-attributed.XXXXXX.jsonl)
python3 merge_candidates.py "$EXISTING" "$DAWN_ATTRIBUTED" --output "$TMP_OUT"
mv "$TMP_OUT" "$EXISTING"
final_rows=$(wc -l < "$EXISTING" | tr -d ' ')
echo ">>> Corpus grew from $baseline_rows to $final_rows rows (+$(( final_rows - baseline_rows )))"

if (( final_rows < baseline_rows )); then
  echo "ERROR: corpus shrank — something went wrong. Restore with:" >&2
  echo "  git checkout $EXISTING" >&2
  exit 1
fi

echo ">>> Regenerating coverage snapshot..."
python3 bucket_coverage.py "$EXISTING" \
  --output-json assets/bucket-coverage.json \
  --output-md assets/bucket-coverage.md

echo ">>> Re-baking the runtime quote database..."
# bake_quote_database.py reads the (now-updated) attributed corpus and writes
# assets/quote_database.jsonl, the display-ready DB consulted at runtime. Must
# be re-run any time the raw corpus changes — otherwise the picker sees stale
# baked rows and ignores newly merged quotes.
python3 bake_quote_database.py "$EXISTING" --output assets/quote_database.jsonl

echo
echo "Done. Review the diff, then:"
echo "  git add $EXISTING assets/bucket-coverage.{md,json} assets/quote_database.jsonl"
echo "  git commit -m 'Expand corpus with clock-precise authors'"
echo "  git push"
