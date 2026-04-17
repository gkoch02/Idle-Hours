#!/usr/bin/env python3
"""Improve raw harvested quotes into cleaner display-ready excerpts."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


TERMINAL_PUNCT = ".!?\"'”’)]"
LEADING_JUNK = re.compile(r'^[\s\[\("“”‘’\-,:;]+')
TRAILING_JUNK = re.compile(r'[\s\[\("“”‘’\-,:;]+$')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean raw quote candidates into better display excerpts.")
    parser.add_argument("input", help="Merged candidate JSONL input")
    parser.add_argument(
        "--output",
        default="output/candidates-cleaned.jsonl",
        help="Output JSONL path",
    )
    return parser.parse_args()


def split_sentences(text: str) -> list[str]:
    text = text.replace("\r", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    text = re.sub(r'([.!?]["”’\]\)]?)\s+', r'\1\n', text)
    parts = text.splitlines()
    return [part.strip() for part in parts if part.strip()]


def clean_edges(text: str) -> str:
    text = LEADING_JUNK.sub("", text)
    text = TRAILING_JUNK.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def looks_fragment(text: str) -> bool:
    if not text:
        return True
    if len(text.split()) < 4:
        return True
    if not any(text.endswith(ch) for ch in TERMINAL_PUNCT):
        return True
    if text[0].islower():
        return True
    return False


def best_display_quote(row: dict) -> tuple[str, bool, str]:
    candidates = []
    for field in ("quote_text", "context_text"):
        value = clean_edges(row.get(field) or "")
        if not value:
            continue
        for sentence in split_sentences(value):
            sentence = clean_edges(sentence)
            if row.get("matched_text") and row["matched_text"].replace("\n", " ").strip().lower() in sentence.lower():
                candidates.append(sentence)
        candidates.append(value)

    seen = []
    for candidate in candidates:
        if candidate not in seen:
            seen.append(candidate)

    non_fragments = [c for c in seen if not looks_fragment(c)]
    if non_fragments:
        best = min(non_fragments, key=lambda c: (abs(len(c) - 140), len(c)))
        return best, False, "complete_sentence"

    if seen:
        best = max(seen, key=len)
        return best, True, "fragment_fallback"

    return "", True, "empty"


def main() -> int:
    args = parse_args()
    input_path = (BASE_DIR / args.input).expanduser() if not Path(args.input).is_absolute() else Path(args.input).expanduser()
    output_path = (BASE_DIR / args.output).expanduser() if not Path(args.output).is_absolute() else Path(args.output).expanduser()
    rows = []
    for line in input_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        display_quote, is_fragment, cleanup_status = best_display_quote(row)
        row["display_quote"] = display_quote
        row["display_fragment"] = is_fragment
        row["cleanup_status"] = cleanup_status
        rows.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    fragments = sum(1 for row in rows if row["display_fragment"])
    print(f"Wrote {len(rows)} cleaned candidates to {output_path}")
    print(f"Fragment fallbacks: {fragments}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
