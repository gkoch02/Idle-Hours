#!/usr/bin/env bash
# Fetch the curated clock-precise books, run them through the pipeline,
# and regenerate assets/candidates-attributed.jsonl.
#
# Must run on a machine with network access to www.gutenberg.org
# (the CI sandbox blocks it). Safe to re-run: gutenberg_time_miner
# caches downloads in data/gutenberg/ and merge_candidates dedupes.
#
# Usage:  bash run_dawn_expansion.sh
set -euo pipefail

cd "$(dirname "$0")"

IDS_FILE="gutenberg_dawn_expansion_ids.txt"
RAW_OUT="output/raw-candidates-dawn-expansion.jsonl"
MERGED="output/candidates-merged.jsonl"

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

echo ">>> Merging with existing harvest..."
if [[ -f "$MERGED" ]]; then
  python3 merge_candidates.py "$MERGED" "$RAW_OUT" --output "$MERGED"
else
  echo "    $MERGED not found; seeding from the dawn harvest only."
  cp "$RAW_OUT" "$MERGED"
fi

echo ">>> Cleaning, quality-scoring, substring-fixing, enriching..."
python3 clean_display_quotes.py "$MERGED"
python3 quality_filter.py output/candidates-cleaned.jsonl
python3 fix_substring_time_matches.py output/candidates-quality.jsonl
python3 enrich_metadata.py output/candidates-quality.jsonl

echo ">>> Regenerating coverage snapshot..."
python3 bucket_coverage.py assets/candidates-attributed.jsonl \
  --output-json assets/bucket-coverage.json \
  --output-md assets/bucket-coverage.md

echo
echo "Done. Review the diff, then:"
echo "  git add assets/candidates-attributed.jsonl assets/bucket-coverage.{md,json}"
echo "  git commit -m 'Expand corpus with clock-precise authors'"
echo "  git push"
