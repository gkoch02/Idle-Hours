#!/usr/bin/env python3
"""Improve raw harvested quotes into cleaner display-ready excerpts."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from jsonl_io import iter_jsonl

BASE_DIR = Path(__file__).resolve().parent


TERMINAL_PUNCT = ".!?\"'”’)]"
LEADING_JUNK = re.compile(r'^[\s\[\("“”‘’\-,:;]+')
TRAILING_JUNK = re.compile(r'[\s\[\("“”‘’\-,:;]+$')

# Common English abbreviations whose trailing period must NOT be treated as a
# sentence boundary. Without this guard, `split_sentences` cuts "Mr. Smith" into
# two fake sentences and `best_display_quote` happily picks the "…, said Mr."
# prefix as a complete sentence — producing display quotes truncated mid-name.
ABBREVIATIONS = frozenset({
    "Mr", "Mrs", "Ms", "Mx", "Dr", "St", "Sr", "Jr",
    "Rev", "Hon", "Gen", "Col", "Capt", "Lt", "Sgt", "Maj", "Cpl", "Adm",
    "Mme", "Mlle", "M", "Mons", "Messrs", "Prof",
    "Mt", "Ave", "Rd", "Blvd",
    "No", "Nos", "vs", "etc", "viz", "approx",
})
_LAST_TOKEN_RE = re.compile(r"([A-Za-z][A-Za-z.]*)\.$")
HEADING_PREFIX = re.compile(
    r"^(?:"
    r"(?:[A-Z][A-Z'.-]+(?:\s+[A-Z][A-Z'.-]+){0,5})\s+"
    r"(?:NARRATIVE|CHAPTER|BOOK|PART|SCENE|LETTER|PREFACE|INTRODUCTION)\b"
    r"|"
    r"CHAPTER\s+[IVXLCDM0-9]+[.:]?"
    r"(?:\s+IN\s+WHICH\s+[A-Z ,'-]+?(?=\s+[A-Z][a-z]))?"
    r"|"
    r"BOOK\s+[IVXLCDM0-9]+[.:]?"
    r"|"
    r"PART\s+[IVXLCDM0-9]+[.:]?"
    r"|"
    r"IN\s+WHICH\s+[A-Z ,'-]+?(?=\s+[A-Z][a-z])"
    r")\s*",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean raw quote candidates into better display excerpts.")
    parser.add_argument("input", help="Merged candidate JSONL input")
    parser.add_argument(
        "--output",
        default="output/candidates-cleaned.jsonl",
        help="Output JSONL path",
    )
    return parser.parse_args()


def _ends_with_abbreviation(text: str) -> bool:
    """Return True if `text` ends with a known abbreviation like "Mr." or "Dr."

    Also treats a lone trailing capital-letter initial (e.g. "J.", "R.") as an
    abbreviation so we don't split "J. R. R. Tolkien" into four fake sentences,
    and treats short multi-period tokens like "A.M.", "P.M.", "e.g.", "i.e."
    the same way — without this a "nine o'clock P.M." sentence gets cut at the
    `P.` and a display quote of "…at nine o'clock P." ships to the panel.
    """
    match = _LAST_TOKEN_RE.search(text)
    if not match:
        return False
    token = match.group(1)
    head = token.rstrip(".")
    if head in ABBREVIATIONS:
        return True
    if len(head) == 1 and head.isupper():
        return True
    # Short dotted acronym: "P.M", "A.M", "e.g", "i.e", "U.S", "U.S.A", etc.
    # Interior periods alone don't make it an abbreviation — "Jones." would
    # match — so require at least one interior period and cap length.
    if "." in head and len(head) <= 5:
        return True
    return False


def split_sentences(text: str) -> list[str]:
    text = text.replace("\r", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    text = re.sub(r'([.!?]["”’\]\)]?)\s+', r'\1\n', text)
    parts = [part.strip() for part in text.splitlines() if part.strip()]
    # Un-split false boundaries left by abbreviations: if part N ends with
    # "Mr.", "Mrs.", "Dr." etc., glue part N+1 back on. The period there is
    # part of the abbreviation, not the end of a sentence.
    merged: list[str] = []
    for part in parts:
        if merged and _ends_with_abbreviation(merged[-1]):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


def clean_edges(text: str) -> str:
    text = LEADING_JUNK.sub("", text)
    text = TRAILING_JUNK.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    while True:
        stripped = HEADING_PREFIX.sub("", text).strip()
        if stripped == text:
            break
        text = stripped
    return text


def strip_heading_prefix(text: str) -> str:
    """Iteratively strip leading HEADING_PREFIX matches without touching quote
    marks or other content-bearing punctuation. Used for interior sentences in
    ``expand_candidates``: ``clean_edges`` would strip a leading ``"`` or ``'``
    via ``LEADING_JUNK``, which destroys the opening of dialogue when joined
    sentences like ``He paused. "All is ready," she replied.`` are concatenated
    into a run — the interior sentence would become ``All is ready,"`` and
    render with an orphan close-quote.
    """
    while True:
        stripped = HEADING_PREFIX.sub("", text).strip()
        if stripped == text:
            break
        text = stripped
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
    # Trailing "Mr." / "Mrs." / "A.M." etc. looks like a terminal period but
    # is almost always the miner's context window cutting a sentence short.
    # Flag as a fragment so quality_filter heavily penalises it and the picker
    # drops it below its default --min-quality threshold.
    if _ends_with_abbreviation(text):
        return True
    return False


EXPANSION_MAX_CHARS = 260  # matches quality_filter's `too_long` ceiling — keep in lockstep.
EXPANSION_NEIGHBOURS = 2

# Catches chapter/book/part/scene/volume/letter markers *anywhere* in a candidate.
# Case-sensitive (ALL CAPS or Title Case only) so we don't flag prose like
# "garden-scene it had". Numerals must be uppercase roman or arabic, so "part 3"
# in lowercase prose does not match either. Used post-join to reject joined runs
# whose neighbour sentence bled a heading into the middle of the display quote.
INTERIOR_HEADING = re.compile(
    r"\b(?:CHAPTER|BOOK|PART|SCENE|VOLUME|LETTER|Chapter|Book|Part|Scene|Volume|Letter)"
    r"\s+(?:[IVXLCDM]+|\d+)(?:[.:]|\b)",
)


def expand_candidates(text: str, matched_text: str) -> tuple[list[str], set[str]]:
    """Build multi-sentence runs centered on sentences containing ``matched_text``.

    Returns ``(runs, single_hits)`` — ``single_hits`` is the subset that are a
    lone hit sentence (no neighbours joined), kept separate so the caller can
    distinguish a naturally-complete sentence from an expanded run.
    """
    if not text:
        return [], set()
    needle = (matched_text or "").replace("\n", " ").strip().lower()
    if not needle:
        return [], set()
    # Use the quote-preserving heading-stripper here, not clean_edges: joined
    # runs must keep opening ``"`` / ``'`` characters on interior dialogue.
    sentences = [strip_heading_prefix(s) for s in split_sentences(text)]
    sentences = [s for s in sentences if s]
    if not sentences:
        return [], set()
    hits = [i for i, s in enumerate(sentences) if needle in s.lower()]
    runs: list[str] = []
    singles: set[str] = set()
    for i in hits:
        for before in range(EXPANSION_NEIGHBOURS + 1):
            for after in range(EXPANSION_NEIGHBOURS + 1):
                lo = i - before
                hi = i + after
                if lo < 0 or hi >= len(sentences):
                    continue
                run = " ".join(sentences[lo:hi + 1]).strip()
                if not run or len(run) > EXPANSION_MAX_CHARS:
                    continue
                runs.append(run)
                if before == 0 and after == 0:
                    singles.add(run)
    return runs, singles


def best_display_quote(row: dict) -> tuple[str, bool, str]:
    candidates = []
    single_hits: set[str] = set()
    for field in ("quote_text", "context_text"):
        value = clean_edges(row.get(field) or "")
        if not value:
            continue
        runs, singles = expand_candidates(value, row.get("matched_text") or "")
        candidates.extend(runs)
        single_hits.update(singles)
        candidates.append(value)
        # A full field value that is itself a single sentence must also count
        # as a single-hit, otherwise rows with no/empty matched_text (or where
        # the blob is the winning candidate) get mislabelled "expanded".
        if len(split_sentences(value)) == 1:
            single_hits.add(value)

    seen = list(dict.fromkeys(candidates))
    non_fragments = [c for c in seen if not looks_fragment(c)]
    # Prefer candidates whose interior is heading-free, but only if any survive.
    # Sparse buckets where every candidate bleeds a heading still render something.
    clean_non_fragments = [c for c in non_fragments if not INTERIOR_HEADING.search(c)]
    pool = clean_non_fragments or non_fragments
    if pool:
        best = min(pool, key=lambda c: (abs(len(c) - 140), len(c)))
        status = "complete_sentence" if best in single_hits else "expanded_with_context"
        return best, False, status

    if seen:
        best = max(seen, key=len)
        return best, True, "fragment_fallback"

    return "", True, "empty"


def main() -> int:
    args = parse_args()
    input_path = (BASE_DIR / args.input).expanduser() if not Path(args.input).is_absolute() else Path(args.input).expanduser()
    output_path = (BASE_DIR / args.output).expanduser() if not Path(args.output).is_absolute() else Path(args.output).expanduser()
    rows = []
    for row in iter_jsonl(input_path):
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
