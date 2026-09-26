#!/usr/bin/env python3
"""Fix substring-collision time metadata like 'five minutes' inside 'thirty-five minutes'.

MIGRATION / REPAIR TOOL. The current ``gutenberg_time_miner.py`` regex
captures the longest *standard* time phrase (regex alternation tries compound
number forms like ``thirty-five`` before the bare ``five``), so fresh harvests
mostly do not produce substring-collision rows — but the archaic reversed
compound ("five-and-twenty minutes past eight" = 8:25) still slips through as
the bare trailing phrase ("twenty minutes past eight" = 8:20), so this script
stays in the pipeline to repair that class.

It also repairs the quarter / half class: legacy ``oclock_word`` rows mined
on "ten o'clock" inside "half-past ten o'clock" / "a quarter after eight
o'clock" / "quarter to nine o'clock", filed at the top of the hour with only
the bare hour bolded while the quote states a time 15-30 minutes away. Such a
row is rewritten to the quarter / half phrase (``match_type`` becomes
``quarter_half`` or ``quarter_to``, as the miner would have produced), and a
repaired row that duplicates a correct twin already in the file is dropped. New hand-curated content fixes
should go in ``assets/content_overrides.json`` (applied by
``apply_content_overrides.py``) so they survive pipeline re-runs.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from idle_hours.atomic_io import atomic_write_lines
from idle_hours.buckets import minute_bucket as bucket_for_minute
from idle_hours.jsonl_io import iter_jsonl

BASE_DIR = Path(__file__).resolve().parent


NUMBER_WORDS = {
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

TIME_PATTERN = re.compile(
    r"\b(?P<minute_word>"
    # Archaic reversed compound first: "five-and-twenty minutes past seven"
    # (= 25). Victorian-era texts use this form heavily; capturing only the
    # trailing "twenty minutes past seven" mis-tags the row by five minutes.
    r"(?:one|two|three|four|five|six|seven|eight|nine)[-\s]+and[-\s]+(?:twenty|thirty|forty|fifty)"
    r"|(?:twenty|thirty|forty|fifty)(?:[- ]\s*(?:one|two|three|four|five|six|seven|eight|nine))?"
    r"|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
    r"|sixteen|seventeen|eighteen|nineteen"
    r")\s+minutes?\s+(?P<relation>past|to)\s+(?P<hour_word>one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
    re.IGNORECASE,
)

# A quarter / half phrase that can swallow a bare hour phrase: a row mined as
# ``oclock_word`` on "ten o'clock" whose text reads "half-past ten o'clock"
# (or "a quarter after eight o'clock", "quarter to nine o'clock") sits at the
# top of the hour while its quote states another time. Legacy rows of that
# shape were filed at :00 with only "ten o'clock" bolded. ``core`` is the
# phrase the miner's ``quarter_half`` / ``quarter_to`` patterns capture (no
# leading "a", no trailing "o'clock"), so a repaired row gets the same
# ``matched_text`` — and therefore the same dedupe key — as a twin the
# current miner produced. "half to" is not a time, so only a quarter may
# run to / before its hour.
QUARTER_HALF_PATTERN = re.compile(
    r"\b(?:a\s+)?"
    r"(?P<core>(?:(?P<half>half)[-\s]+(?:past|after)"
    r"|(?P<quarter>quarter)[-\s]+(?P<relation>past|after|to|before))"
    r"[-\s]+(?P<hour_word>one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve))"
    r"(?:\s+o['’]?clock)?\b",
    re.IGNORECASE,
)

# The fields a content override may set that this repair would also write.
# A row whose override owns them is left alone: the next
# ``apply_content_overrides`` run would overwrite the repair anyway, and its
# ``override_originals`` ledger would record the repaired value as the one
# to restore.
_TIME_FIELDS = ("matched_text", "hour", "minute", "normalized_time")


def daypart_for_hour(hour: int) -> str:
    """The miner's hour → daypart rule (``gutenberg_time_miner.daypart_for_hour``)."""
    from idle_hours.gutenberg_time_miner import daypart_for_hour as _miner_daypart

    return _miner_daypart(hour)


def infer_quarter_half_from_quote(display_quote: str, current_matched: str | None):
    """Return the quarter / half phrase that swallows ``current_matched``.

    ``current_matched`` (e.g. "ten o'clock") must be a strict substring of a
    quarter / half phrase in ``display_quote`` ("half-past ten o'clock") at
    *every* place it occurs — if it also stands alone somewhere, the row may
    well have been mined on that occurrence, and rewriting it would move a
    correct row. Returns a partial row (with ``match_type``) or ``None``.
    """
    text = ' '.join((display_quote or '').split())
    needle = ' '.join((current_matched or '').split()).lower()
    if not text or not needle:
        return None
    lowered = text.lower()
    spans = [m for m in QUARTER_HALF_PATTERN.finditer(text)]
    if not spans:
        return None
    chosen = None
    start = lowered.find(needle)
    if start < 0:
        return None
    while start >= 0:
        end = start + len(needle)
        covering = next(
            (m for m in spans if m.start() <= start and end <= m.end() and (m.end() - m.start()) > len(needle)),
            None,
        )
        if covering is None:
            return None
        if chosen is None:
            chosen = covering
        start = lowered.find(needle, start + 1)
    core = chosen.group('core')
    if ' '.join(core.split()).lower() == needle:
        return None
    hour_value = parse_number_word(chosen.group('hour_word'))
    if hour_value is None:
        return None
    if chosen.group('half'):
        hour, minute, match_type = hour_value, 30, 'quarter_half'
    elif chosen.group('relation').lower() in ('past', 'after'):
        hour, minute, match_type = hour_value, 15, 'quarter_half'
    else:
        hour, minute, match_type = (12 if hour_value == 1 else hour_value - 1), 45, 'quarter_to'
    return {
        'match_type': match_type,
        'matched_text': ' '.join(core.split()),
        'hour': hour,
        'minute': minute,
        'normalized_time': f"{hour:02d}:{minute:02d}",
        'fuzzy_bucket': f"h{hour}_{bucket_for_minute(minute)}",
        'daypart_bucket': daypart_for_hour(hour),
    }


def repair_row(row: dict) -> dict | None:
    """Return the fields to update on ``row``, or ``None`` when it is fine.

    Tries the ``<minutes> past/to <hour>`` collision first, then the quarter
    / half one. Rows whose content override owns a time field are skipped
    (see ``_TIME_FIELDS``). A row whose override replaced its
    ``display_quote`` is repaired only when its *original* text yields the
    same repair, so deleting the override later cannot strand a
    ``matched_text`` its restored quote no longer contains.
    """
    originals = row.get('override_originals') or {}
    if any(field in originals for field in _TIME_FIELDS):
        return None
    display_quote = row.get('display_quote') or ''
    current_matched = ' '.join((row.get('matched_text') or '').split()).lower()
    if not current_matched:
        return None

    def _infer(quote: str):
        inferred = infer_time_from_quote(quote, current_matched)
        if inferred:
            inferred_matched = inferred['matched_text'].lower()
            if current_matched in inferred_matched and current_matched != inferred_matched:
                return inferred
        return infer_quarter_half_from_quote(quote, current_matched)

    repair = _infer(display_quote)
    if repair and 'display_quote' in originals:
        original = _infer(originals.get('display_quote') or '')
        if not original or original['normalized_time'] != repair['normalized_time']:
            return None
    return repair


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fix substring-collision time matches in JSONL corpus rows.")
    parser.add_argument("input", help="Input JSONL file")
    parser.add_argument("--output", default=None, help="Output path; defaults to in-place overwrite")
    return parser.parse_args()


def parse_number_word(text: str) -> int | None:
    text = text.lower().replace('-', ' ').strip()
    if text in NUMBER_WORDS:
        return NUMBER_WORDS[text]
    parts = text.split()
    if len(parts) == 2 and parts[0] in NUMBER_WORDS and parts[1] in NUMBER_WORDS:
        return NUMBER_WORDS[parts[0]] + NUMBER_WORDS[parts[1]]
    # Archaic reversed compound: "five and twenty" = 25.
    if (
        len(parts) == 3
        and parts[1] == 'and'
        and parts[0] in NUMBER_WORDS
        and parts[2] in NUMBER_WORDS
    ):
        return NUMBER_WORDS[parts[0]] + NUMBER_WORDS[parts[2]]
    return None


def infer_time_from_quote(display_quote: str, current_matched: str | None = None):
    """Return the time phrase in ``display_quote`` as a partial row, or None.

    A quote can carry several ``<minutes> past/to <hour>`` phrases. When
    ``current_matched`` (the row's stored ``matched_text``) is given, the
    phrase that *contains* it is preferred — repairing a row against the
    first phrase in the quote rather than the one it was actually mined on
    rewrote its time to an unrelated phrase (issue #301). Without it, or when
    no phrase contains it, the first phrase wins as before.
    """
    matches = list(TIME_PATTERN.finditer(' '.join(display_quote.split())))
    if not matches:
        return None
    match = matches[0]
    needle = ' '.join((current_matched or '').split()).lower()
    if needle:
        for candidate in matches:
            if needle in candidate.group(0).lower():
                match = candidate
                break
    minute_word = match.group('minute_word')
    relation = match.group('relation').lower()
    hour_word = match.group('hour_word').lower()
    minute_value = parse_number_word(minute_word)
    hour_value = parse_number_word(hour_word)
    if minute_value is None or hour_value is None:
        return None
    if relation == 'past':
        hour = hour_value
        minute = minute_value
    else:
        hour = 12 if hour_value == 1 else hour_value - 1
        minute = 60 - minute_value
    bucket_hour = hour
    if ((minute + 2) // 5) * 5 == 60:
        bucket_hour = (hour % 12) + 1
    return {
        'matched_text': match.group(0),
        'hour': hour,
        'minute': minute,
        'normalized_time': f"{hour:02d}:{minute:02d}",
        'fuzzy_bucket': f"h{bucket_hour}_{bucket_for_minute(minute)}",
    }


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = (Path(args.output).expanduser().resolve()) if args.output else input_path
    rows = list(iter_jsonl(input_path))
    fixed = 0
    repaired: set[int] = set()
    for index, row in enumerate(rows):
        repair = repair_row(row)
        if repair:
            row.update(repair)
            repaired.add(index)
            fixed += 1
            print(f"repaired {row.get('source_id')}:{row.get('line_number')} → "
                  f"{row['matched_text']!r} {row['normalized_time']}")
    # A repaired row can land on the exact identity of a twin the current
    # miner already produced correctly (same source line, same phrase, same
    # time). Keep the untouched twin and drop the repaired copy, rather than
    # shipping an exact duplicate ``merge_candidates`` would have collapsed.
    from idle_hours.merge_candidates import dedupe_key

    kept_keys = {
        dedupe_key(row, '') for index, row in enumerate(rows)
        if index not in repaired and row.get('source_id') is not None and row.get('line_number') is not None
    }
    out = []
    dropped = 0
    for index, row in enumerate(rows):
        if index in repaired and row.get('source_id') is not None and row.get('line_number') is not None:
            key = dedupe_key(row, '')
            if key in kept_keys:
                dropped += 1
                print(f"dropped repaired twin {row.get('source_id')}:{row.get('line_number')} "
                      f"(a correct {row['matched_text']!r} row already exists)")
                continue
            kept_keys.add(key)
        out.append(row)
    # Atomic: in-place is the default, so a crash mid-write must leave the
    # input corpus byte-identical rather than truncated (issue #306).
    atomic_write_lines(output_path, (json.dumps(row, ensure_ascii=False) for row in out))
    print(f'Fixed {fixed} substring-collision rows ({dropped} dropped as duplicates of a correct twin)')
    print(f'Wrote {len(out)} rows to {output_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
