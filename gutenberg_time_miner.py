#!/usr/bin/env python3
"""Harvest time-related quote candidates from Gutenberg texts or plain text files.

This first-pass CLI can:
- download Gutenberg plaintext by ebook id
- scan local text files or directories
- detect exact/fuzzy time phrases with regexes
- normalize hits into fuzzy clock buckets
- emit JSONL/CSV review output

It is intentionally biased toward harvesting candidates fast rather than being
perfectly linguistically complete.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import textwrap
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from buckets import minute_bucket

BASE_DIR = Path(__file__).resolve().parent

NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}

HOUR_WORDS = {k: v for k, v in NUMBER_WORDS.items() if 1 <= v <= 12}
MINUTE_WORDS = NUMBER_WORDS.copy()
DAYPART_KEYWORDS = {
    "dawn": "dawn",
    "daybreak": "dawn",
    "sunrise": "dawn",
    "morning": "morning",
    "noon": "noon",
    "midday": "noon",
    "afternoon": "afternoon",
    "dusk": "dusk",
    "sunset": "dusk",
    "evening": "evening",
    "night": "night",
    "midnight": "midnight",
    "small hours": "small_hours",
}

GUTENBERG_URL_PATTERNS = [
    "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt",
    "https://www.gutenberg.org/files/{id}/{id}-0.txt",
    "https://www.gutenberg.org/files/{id}/{id}.txt",
]

TIME_PATTERNS = [
    (
        "digital",
        re.compile(
            r"(?<![A-Za-z0-9])(?P<hour>[0-2]?\d):(?P<minute>[0-5]\d)(?!:\d)(?!\s+[A-Z][a-z])",
            re.IGNORECASE,
        ),
    ),
    (
        "oclock_word",
        re.compile(
            r"\b(?P<hourword>one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+o['’]?clock\b",
            re.IGNORECASE,
        ),
    ),
    (
        "quarter_half",
        re.compile(
            r"\b(?P<phrase>quarter|half)\s+past\s+(?P<hourword>one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "quarter_to",
        re.compile(
            r"\bquarter\s+to\s+(?P<hourword>one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "minutes_past_to",
        re.compile(
            r"\b(?P<minuteword>(?:twenty|thirty|forty|fifty)(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)\s+minutes?\s+(?P<relation>past|to)\s+(?P<hourword>one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "just_after_before",
        re.compile(
            r"\b(?P<prefix>just after|a little after|shortly after|just before|almost|nearly|close on|towards)\s+(?:(?P<hourword>one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+o['’]?clock|(?P<daypart>dawn|daybreak|sunrise|morning|noon|midday|afternoon|dusk|sunset|evening|night|midnight))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "clock_struck",
        re.compile(
            r"\b(?:the\s+clock\s+struck|struck)\s+(?P<hourword>one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|midnight|noon)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "daypart",
        re.compile(
            r"\b(?P<daypart>small hours|dawn|daybreak|sunrise|morning|noon|midday|afternoon|dusk|sunset|evening|night|midnight)\b",
            re.IGNORECASE,
        ),
    ),
]


@dataclass
class Candidate:
    source_path: str
    source_id: str | None
    match_type: str
    matched_text: str
    quote_text: str
    context_text: str
    hour: int | None
    minute: int | None
    normalized_time: str | None
    fuzzy_bucket: str | None
    daypart_bucket: str | None
    line_number: int
    match_start: int
    match_end: int

    def as_dict(self) -> dict[str, object]:
        return {
            "source_path": self.source_path,
            "source_id": self.source_id,
            "match_type": self.match_type,
            "matched_text": self.matched_text,
            "quote_text": self.quote_text,
            "context_text": self.context_text,
            "hour": self.hour,
            "minute": self.minute,
            "normalized_time": self.normalized_time,
            "fuzzy_bucket": self.fuzzy_bucket,
            "daypart_bucket": self.daypart_bucket,
            "line_number": self.line_number,
            "match_start": self.match_start,
            "match_end": self.match_end,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mine Gutenberg or local texts for time-related quote candidates."
    )
    parser.add_argument(
        "--gutenberg-id",
        action="append",
        default=[],
        help="Project Gutenberg ebook id to download. Repeatable.",
    )
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="Text file or directory to scan. Repeatable.",
    )
    parser.add_argument(
        "--download-dir",
        default="data/gutenberg",
        help="Where downloaded Gutenberg files should be stored.",
    )
    parser.add_argument(
        "--output",
        default="output/candidates.jsonl",
        help="Output path for JSONL or CSV.",
    )
    parser.add_argument(
        "--format",
        choices=["jsonl", "csv"],
        default="jsonl",
        help="Output format.",
    )
    parser.add_argument(
        "--context-chars",
        type=int,
        default=220,
        help="Characters of context on each side of a hit.",
    )
    parser.add_argument(
        "--max-per-file",
        type=int,
        default=0,
        help="Optional cap per file. 0 means unlimited.",
    )
    parser.add_argument(
        "--max-total",
        type=int,
        default=0,
        help="Optional overall cap. 0 means unlimited.",
    )
    parser.add_argument(
        "--print-sample",
        type=int,
        default=0,
        help="Print the first N candidates to stdout after mining.",
    )
    parser.add_argument(
        "--exclude-match-type",
        action="append",
        default=[],
        help="Exclude one or more match types from output. Repeatable.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Shortcut for precision-first harvesting. Excludes generic daypart-only matches.",
    )
    parser.add_argument(
        "--skip-fetch-errors",
        action="store_true",
        help="Skip Gutenberg ids that fail to download instead of aborting the whole run.",
    )
    return parser.parse_args()


def text_files_from_inputs(inputs: Sequence[str]) -> Iterator[Path]:
    for raw in inputs:
        path = Path(raw).expanduser()
        if path.is_dir():
            for child in sorted(path.rglob("*.txt")):
                yield child
        elif path.is_file():
            yield path
        else:
            raise FileNotFoundError(f"Input path not found: {raw}")


def fetch_gutenberg_text(ebook_id: str, download_dir: Path) -> Path:
    download_dir.mkdir(parents=True, exist_ok=True)
    destination = download_dir / f"pg{ebook_id}.txt"
    if destination.exists() and destination.stat().st_size > 0:
        return destination

    errors: list[str] = []
    for pattern in GUTENBERG_URL_PATTERNS:
        url = pattern.format(id=ebook_id)
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                text = response.read().decode("utf-8", errors="replace")
            destination.write_text(text, encoding="utf-8")
            return destination
        except (urllib.error.URLError, TimeoutError) as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError(f"Failed to fetch Gutenberg id {ebook_id}\n" + "\n".join(errors))


def normalize_number_phrase(phrase: str) -> int | None:
    cleaned = phrase.lower().replace("-", " ").strip()
    if cleaned in NUMBER_WORDS:
        return NUMBER_WORDS[cleaned]
    parts = cleaned.split()
    if len(parts) == 2 and parts[0] in NUMBER_WORDS and parts[1] in NUMBER_WORDS:
        return NUMBER_WORDS[parts[0]] + NUMBER_WORDS[parts[1]]
    return None


def hour_word_to_int(word: str) -> int | None:
    value = HOUR_WORDS.get(word.lower())
    return value


def sentence_window(text: str, start: int, end: int, context_chars: int) -> tuple[str, str, int]:
    left = max(0, start - context_chars)
    right = min(len(text), end + context_chars)
    context = text[left:right].strip()

    sentence_start = max(text.rfind(".", 0, start), text.rfind("\n", 0, start), text.rfind("!", 0, start), text.rfind("?", 0, start))
    sentence_end_candidates = [text.find(tok, end) for tok in (".", "\n", "!", "?") if text.find(tok, end) != -1]
    sentence_end = min(sentence_end_candidates) if sentence_end_candidates else len(text)
    quote = text[sentence_start + 1 : sentence_end + 1].strip() if sentence_end > sentence_start else context
    line_number = text.count("\n", 0, start) + 1
    return quote, context, line_number


def daypart_for_hour(hour: int | None) -> str | None:
    if hour is None:
        return None
    hour = hour % 24
    if 5 <= hour <= 6:
        return "dawn"
    if 7 <= hour <= 11:
        return "morning"
    if hour == 12:
        return "noon"
    if 13 <= hour <= 17:
        return "afternoon"
    if 18 <= hour <= 19:
        return "dusk"
    if 20 <= hour <= 22:
        return "evening"
    if hour == 0:
        return "midnight"
    return "night"


def build_bucket(hour: int | None, minute: int | None, explicit_daypart: str | None = None) -> tuple[str | None, str | None, str | None]:
    if explicit_daypart:
        normalized = DAYPART_KEYWORDS.get(explicit_daypart.lower(), explicit_daypart.lower().replace(" ", "_"))
        return None, None, normalized
    if hour is None or minute is None:
        return None, None, None
    normalized_time = f"{hour:02d}:{minute:02d}"
    rounded = ((minute + 2) // 5) * 5
    bucket_hour = hour
    if rounded == 60:
        rounded = 0
        bucket_hour = (hour + 1) % 24
    fuzzy = f"h{((bucket_hour - 1) % 12) + 1}_{minute_bucket(minute)}"
    daypart = daypart_for_hour(hour)
    return normalized_time, fuzzy, daypart


def candidate_from_match(source_path: str, source_id: str | None, text: str, match_type: str, match: re.Match[str], context_chars: int) -> Candidate | None:
    groups = match.groupdict()
    # Collapse any internal whitespace (e.g. a line break splitting "thirty-five\nminutes")
    # so matched_text is always a single clean phrase. Previously handled post-hoc by
    # fix_legacy_buckets.py.
    matched_text = " ".join(match.group(0).split())
    hour: int | None = None
    minute: int | None = None
    explicit_daypart = groups.get("daypart")

    if match_type == "digital":
        hour = int(groups["hour"])
        minute = int(groups["minute"])
        if hour > 23:
            return None
        context_probe = text[max(0, match.start() - 24) : min(len(text), match.end() + 24)]
        if re.search(r"\b(?:chapter|psalm|verse|book|epistle)\b", context_probe, re.IGNORECASE):
            return None
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        if line_end == -1:
            line_end = len(text)
        line_text = text[line_start:line_end].strip()
        if re.fullmatch(r"\d{1,2}:\d{1,2}\s*\(?[A-Z][^.]{0,120}", line_text):
            return None
    elif match_type == "oclock_word":
        hour = hour_word_to_int(groups["hourword"])
        minute = 0
    elif match_type == "quarter_half":
        hour = hour_word_to_int(groups["hourword"])
        phrase = groups["phrase"].lower()
        minute = 15 if phrase == "quarter" else 30
    elif match_type == "quarter_to":
        hour = hour_word_to_int(groups["hourword"])
        if hour is None:
            return None
        hour = 12 if hour == 1 else hour - 1
        minute = 45
    elif match_type == "minutes_past_to":
        hour = hour_word_to_int(groups["hourword"])
        minute_value = normalize_number_phrase(groups["minuteword"])
        if hour is None or minute_value is None:
            return None
        if groups["relation"].lower() == "past":
            minute = minute_value
        else:
            hour = 12 if hour == 1 else hour - 1
            minute = 60 - minute_value
    elif match_type == "just_after_before":
        prefix = groups["prefix"].lower()
        if explicit_daypart:
            pass
        else:
            hour = hour_word_to_int(groups["hourword"])
            if hour is None:
                return None
            if prefix in {"just after", "a little after", "shortly after"}:
                minute = 3
            elif prefix in {"just before", "almost", "nearly", "close on", "towards"}:
                minute = 57
    elif match_type == "clock_struck":
        hw = groups["hourword"].lower()
        if hw == "midnight":
            hour, minute = 0, 0
        elif hw == "noon":
            hour, minute = 12, 0
        else:
            hour = hour_word_to_int(hw)
            minute = 0
    elif match_type == "daypart":
        pass

    normalized_time, fuzzy_bucket, daypart_bucket = build_bucket(hour, minute, explicit_daypart)
    quote, context, line_number = sentence_window(text, match.start(), match.end(), context_chars)
    quote = " ".join(quote.split())
    context = " ".join(context.split())
    return Candidate(
        source_path=source_path,
        source_id=source_id,
        match_type=match_type,
        matched_text=matched_text,
        quote_text=quote,
        context_text=context,
        hour=hour,
        minute=minute,
        normalized_time=normalized_time,
        fuzzy_bucket=fuzzy_bucket,
        daypart_bucket=daypart_bucket,
        line_number=line_number,
        match_start=match.start(),
        match_end=match.end(),
    )


def iter_candidates(source_path: Path, source_id: str | None, text: str, context_chars: int, max_per_file: int) -> Iterator[Candidate]:
    yielded = 0
    for match_type, pattern in TIME_PATTERNS:
        for match in pattern.finditer(text):
            candidate = candidate_from_match(str(source_path), source_id, text, match_type, match, context_chars)
            if candidate is None:
                continue
            yield candidate
            yielded += 1
            if max_per_file and yielded >= max_per_file:
                return


def write_jsonl(path: Path, candidates: Iterable[Candidate]) -> int:
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for candidate in candidates:
            handle.write(json.dumps(candidate.as_dict(), ensure_ascii=False) + "\n")
            count += 1
    return count


def write_csv(path: Path, candidates: Iterable[Candidate]) -> int:
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(Candidate.__dataclass_fields__.keys()))
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(candidate.as_dict())
            count += 1
    return count


def mine(args: argparse.Namespace) -> list[Candidate]:
    files: list[tuple[Path, str | None]] = []
    download_dir = Path(args.download_dir).expanduser()
    excluded_match_types = set(args.exclude_match_type)
    if args.strict:
        excluded_match_types.update({"daypart", "digital"})

    for ebook_id in args.gutenberg_id:
        try:
            path = fetch_gutenberg_text(ebook_id, download_dir)
        except RuntimeError as exc:
            if args.skip_fetch_errors:
                print(f"Skipping Gutenberg id {ebook_id}: {exc}", file=sys.stderr)
                continue
            raise
        files.append((path, ebook_id))

    for path in text_files_from_inputs(args.input):
        files.append((path, None))

    if not files:
        raise SystemExit("No inputs provided. Use --gutenberg-id and/or --input.")

    candidates: list[Candidate] = []
    for path, source_id in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for candidate in iter_candidates(path, source_id, text, args.context_chars, args.max_per_file):
            if candidate.match_type in excluded_match_types:
                continue
            candidates.append(candidate)
            if args.max_total and len(candidates) >= args.max_total:
                return candidates
    return candidates


def print_sample(candidates: Sequence[Candidate], limit: int) -> None:
    for index, candidate in enumerate(candidates[:limit], start=1):
        print(f"[{index}] {candidate.source_path} :: {candidate.matched_text}")
        print(f"    bucket={candidate.fuzzy_bucket} time={candidate.normalized_time} daypart={candidate.daypart_bucket}")
        print(textwrap.fill(candidate.quote_text, width=100, initial_indent="    ", subsequent_indent="    "))
        print()


def main() -> int:
    args = parse_args()
    candidates = mine(args)
    output_path = (BASE_DIR / args.output).expanduser() if not Path(args.output).is_absolute() else Path(args.output).expanduser()

    if args.format == "jsonl":
        count = write_jsonl(output_path, candidates)
    else:
        count = write_csv(output_path, candidates)

    print(f"Wrote {count} candidates to {output_path}")
    if args.print_sample:
        print_sample(candidates, args.print_sample)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
