#!/usr/bin/env bash
# Bulk strict harvest over the batch-2 Gutenberg ID list in
# scripts/gutenberg_batch_ids.txt. Downloads cache in data/gutenberg/,
# so re-runs are offline once the texts are fetched.
set -euo pipefail

# Resolve repo root from this script's location so output/ and the
# data/gutenberg/ cache resolve consistently regardless of caller CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."
mkdir -p output

IDS_FILE="$SCRIPT_DIR/gutenberg_batch_ids.txt"

# Build the --gutenberg-id args (skipping comments/blank lines).
ID_ARGS=()
while IFS= read -r line; do
  line="${line%%#*}"
  line="${line//[[:space:]]/}"
  [[ -z "$line" ]] && continue
  ID_ARGS+=(--gutenberg-id "$line")
done < "$IDS_FILE"

python3 -m idle_hours.gutenberg_time_miner "${ID_ARGS[@]}" --strict --skip-fetch-errors --output output/raw-candidates-strict-batch2.jsonl
