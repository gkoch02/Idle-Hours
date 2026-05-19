#!/usr/bin/env bash
# Fetch the curated clock-precise books, run them through the pipeline
# in isolation, then merge the attributed result into the existing
# idle_hours/assets/candidates-attributed.jsonl without clobbering it.
#
# Must run on a machine with network access to www.gutenberg.org
# (the CI sandbox blocks it). Safe to re-run: gutenberg_time_miner
# caches downloads in data/gutenberg/ and merge_candidates dedupes.
#
# Usage:  bash scripts/run_dawn_expansion.sh
#         (from the repo root — pipeline output and the data cache resolve
#         against CWD by design)
set -euo pipefail

# Resolve repo root from this script's location so the IDs file (sibling
# under scripts/) can be located independent of the caller's CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

IDS_FILE="$SCRIPT_DIR/gutenberg_dawn_expansion_ids.txt"
EXISTING="idle_hours/assets/candidates-attributed.jsonl"
BAKED_DB="idle_hours/assets/quote_database.jsonl"
COVERAGE_JSON="idle_hours/assets/bucket-coverage.json"
COVERAGE_MD="idle_hours/assets/bucket-coverage.md"
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

mkdir -p output
echo ">>> Harvesting $(( ${#ID_ARGS[@]} / 2 )) Gutenberg IDs..."
python3 -m idle_hours.gutenberg_time_miner "${ID_ARGS[@]}" \
  --strict --skip-fetch-errors \
  --output "$RAW_OUT"

echo ">>> Running dawn harvest through the pipeline (standalone)..."
python3 -m idle_hours.merge_candidates "$RAW_OUT" --output "$DAWN_MERGED"
python3 -m idle_hours.clean_display_quotes "$DAWN_MERGED" --output "$DAWN_CLEANED"
python3 -m idle_hours.quality_filter "$DAWN_CLEANED" --output "$DAWN_QUALITY"
python3 -m idle_hours.fix_substring_time_matches "$DAWN_QUALITY"
python3 -m idle_hours.enrich_metadata "$DAWN_QUALITY" --output "$DAWN_ATTRIBUTED"

echo ">>> Merging attributed dawn rows into existing corpus..."
# Write to a tmp file first so we never read and write the same file simultaneously.
TMP_OUT=$(mktemp output/candidates-attributed.XXXXXX.jsonl)
python3 -m idle_hours.merge_candidates "$EXISTING" "$DAWN_ATTRIBUTED" --output "$TMP_OUT"
mv "$TMP_OUT" "$EXISTING"
final_rows=$(wc -l < "$EXISTING" | tr -d ' ')
echo ">>> Corpus grew from $baseline_rows to $final_rows rows (+$(( final_rows - baseline_rows )))"

if (( final_rows < baseline_rows )); then
  echo "ERROR: corpus shrank — something went wrong. Restore with:" >&2
  echo "  git checkout $EXISTING" >&2
  exit 1
fi

echo ">>> Regenerating coverage snapshot..."
python3 -m idle_hours.bucket_coverage "$EXISTING" \
  --output-json "$COVERAGE_JSON" \
  --output-md "$COVERAGE_MD"

echo ">>> Re-baking the runtime quote database..."
# bake_quote_database reads the (now-updated) attributed corpus and writes
# the baked DB consulted at runtime. Must be re-run any time the raw corpus
# changes — otherwise the picker sees stale baked rows and ignores newly
# merged quotes.
python3 -m idle_hours.bake_quote_database "$EXISTING" --output "$BAKED_DB"

echo
echo "Done. Review the diff, then:"
echo "  git add $EXISTING $COVERAGE_JSON $COVERAGE_MD $BAKED_DB"
echo "  git commit -m 'Expand corpus with clock-precise authors'"
echo "  git push"
