#!/usr/bin/env python3
"""Pick the best cleaned quote for a given time or fuzzy bucket."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import sys
import threading
from collections import Counter, defaultdict
from pathlib import Path

from idle_hours import atomic_io
from idle_hours.buckets import (
    BUCKET_ORDER,
    DEFAULT_BUCKET_MINUTES,
    bucket_for_time,
    neighbor_buckets,
    rederive_buckets,
)
from idle_hours.jsonl_io import iter_jsonl

DEFAULT_HISTORY_PATH = "~/.idle-hours/history.jsonl"
DEFAULT_HISTORY_DAYS = 7

# Paths of the two corpus artifacts shipped inside ``idle_hours/assets/`` as
# package-data. ``DEFAULT_DATABASE_PATH`` is the baked, display-ready corpus
# produced by ``bake_quote_database.py`` and consulted at runtime;
# ``DEFAULT_INPUT_PATH`` is the raw attributed corpus, used by the curator UI's
# bucket-inspector (``select_candidates``) plus as a defensive fallback when
# the baked file is missing.
#
# These are absolute paths anchored on the package directory so they resolve
# correctly whether the operator runs from a checkout or against an installed
# wheel — ``resolve_path`` below treats operator-supplied relative values as
# CWD-relative, so anchoring the bundled defaults on ``BASE_DIR`` is the only
# way to keep them stable regardless of where the operator's CWD points.
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATABASE_PATH = str(BASE_DIR / "assets" / "quote_database.jsonl")
DEFAULT_INPUT_PATH = str(BASE_DIR / "assets" / "candidates-attributed.jsonl")
DEFAULT_OVERRIDES_PATH = str(BASE_DIR / "assets" / "selection_overrides.json")

# Order of the ten row-intrinsic score components stored in ``row["baked_score"]``.
# Kept in sync with ``bake_quote_database.BAKED_SCORE_COMPONENTS``; reordering
# either list in isolation breaks pick equivalence.
BAKED_SCORE_COMPONENTS: tuple[str, ...] = (
    "fragment_penalty",
    "cleanup_penalty",
    "metadata_bonus",
    "dialogue_penalty",
    "opening_penalty",
    "source_bonus",
    "quality_component",
    "length_exactness",
    "source_rarity_penalty",
    "length_tiebreak",
)

# Schema version that :mod:`bake_quote_database` stamps onto every baked row.
# Must match ``bake_quote_database.BAKED_SCORE_SCHEMA_VERSION``; a mismatch
# between the two means the baked file on disk was produced by a different
# scoring pipeline than the one loaded here, so :func:`_resolve_corpus` falls
# back to the raw corpus with a stderr warning rather than silently scoring
# with a drifted ``baked_score`` layout.
BAKED_SCORE_SCHEMA_VERSION: int = 1

EXACT_MINUTE_PATTERNS = {
    "zero": ["o’clock", "oclock", "struck"],
    5: ["five minutes past", "five minutes after", "five past"],
    10: ["ten minutes past", "ten minutes after", "ten past"],
    15: ["quarter past"],
    20: ["twenty minutes past", "twenty past"],
    25: ["twenty-five minutes past", "twenty five minutes past", "twenty-five past", "twenty five past"],
    30: ["half past", "half-past", "11:30", "12:30"],
    35: ["thirty-five minutes past", "thirty five minutes past", "twenty-five minutes to", "twenty five minutes to", "twenty-five to", "twenty five to"],
    40: ["twenty minutes to", "twenty to"],
    45: ["quarter to"],
    50: ["ten minutes to", "ten to"],
    # "fifty-five minutes past" must be listed explicitly: it embeds the
    # 5-minute pattern "five minutes past", so without its own entry the
    # longest-first scan below infers minute 5 for it — the same
    # shorter-sibling collision the sort order exists to prevent.
    55: ["fifty-five minutes past", "fifty five minutes past", "five minutes to", "five to"],
}

# Flattened longest-first view of ``EXACT_MINUTE_PATTERNS``. Plain substring
# matching in dict order mis-infers phrases whose pattern contains a shorter
# sibling — "twenty-five minutes past" contains the 5-minute pattern
# "five minutes past", so iteration order used to return minute 5 for it.
# Trying the longest pattern first means the most specific phrase always wins.
_MINUTE_PATTERNS_LONGEST_FIRST = sorted(
    (
        (pattern, minute)
        for minute, patterns in EXACT_MINUTE_PATTERNS.items()
        for pattern in patterns
    ),
    key=lambda item: len(item[0]),
    reverse=True,
)

# "five minutes to" earns the strong exactness bonus only as a standalone
# phrase — inside "twenty-five minutes to three" it is a fragment of a
# 35-minute phrase, not an x:55 marker. The fixed-width lookbehinds reject
# the tens-word prefixes (hyphenated or spaced) that embed it.
_FIVE_MINUTES_TO_RE = re.compile(
    r"(?<!twenty-)(?<!twenty )(?<!thirty-)(?<!thirty )"
    r"(?<!forty-)(?<!forty )(?<!fifty-)(?<!fifty )"
    r"\bfive minutes to"
)

DIALOGUE_FILLER_PATTERNS = [
    "he said",
    "she said",
    "they said",
    "i said",
    "replied ",
    "asked ",
    "cried ",
    "answered ",
    "returned ",
]
WEAK_OPENING_PATTERNS = [
    "and ",
    "but ",
    "for ",
    "then ",
    "so ",
    "yet ",
    "or ",
]
PRONOUN_HEAVY_OPENINGS = [
    "he ",
    "she ",
    "they ",
    "it ",
    "his ",
    "her ",
    "their ",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pick the best Idle Hours quote for a time.")
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT_PATH,
        help="Attributed and quality-scored raw candidate JSONL file (fallback when --database is missing).",
    )
    parser.add_argument(
        "--database",
        default=DEFAULT_DATABASE_PATH,
        help=(
            "Baked display-ready quote database (output of bake_quote_database.py). "
            "Preferred over --input at runtime; empty string forces the raw-corpus path."
        ),
    )
    parser.add_argument(
        "--time",
        help="Time in HH:MM 24-hour format, for example 22:54.",
    )
    parser.add_argument(
        "--bucket",
        help="Explicit bucket like h10_just_before.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Optional random seed for stable picks among similarly scored quotes.",
    )
    parser.add_argument(
        "--min-quality",
        type=int,
        default=60,
        help="Minimum acceptable quality score before falling back to nearby buckets.",
    )
    parser.add_argument(
        "--overrides",
        default=DEFAULT_OVERRIDES_PATH,
        help="JSON overrides for manual boosts/bans/preferred bucket picks.",
    )
    parser.add_argument(
        "--history-path",
        default=DEFAULT_HISTORY_PATH,
        help=(
            "Path to the anti-repeat display history JSONL. "
            "Recently-shown quotes are filtered out of the candidate pool. "
            "Pass an empty string to disable."
        ),
    )
    parser.add_argument(
        "--history-days",
        type=int,
        default=DEFAULT_HISTORY_DAYS,
        help="Number of days of history to consider when filtering repeats. 0 disables the filter.",
    )
    return parser.parse_args()


def resolve_path(path_str: str) -> Path:
    """Resolve a CLI / kwarg path string.

    Relative values anchor on CWD so operator-supplied paths land where the
    operator expects (next to their working tree). Bundled defaults that
    need to point inside the installed package — the baked corpus, the raw
    attributed corpus, the selection-overrides sidecar — are exposed as the
    ``DEFAULT_*_PATH`` module constants which are already absolute,
    anchored on ``BASE_DIR``.

    Pre v2.x this helper joined relatives with ``BASE_DIR`` (the repo root),
    which silently buried operator outputs inside the package directory
    once the codebase moved under ``idle_hours/``.
    """
    return Path(path_str).expanduser().resolve()


def load_rows(path: Path) -> list[dict]:
    return rederive_buckets(list(iter_jsonl(path)))


# In-process corpus cache (#192). Every select_quote used to re-read and
# re-parse the multi-MB corpus JSONL per pick — once per tick in the main
# loop, twice within 5 s on a button-C source card, and once per /api/preview
# request (the Now tab fires ~45 of those). The corpus files only change via
# atomic replace (bake, pipeline writeback), which changes (mtime_ns, size),
# so a stat-keyed cache invalidates automatically and a hit costs one stat.
#
# Callers share the cached row objects: the scoring path is pure (fenced by
# the scorer-purity tests) and the writers (bake_quote_database,
# apply_content_overrides) load their own copies. ``tests/conftest.py``
# clears the cache around every test so same-stamp rewrites in fast test
# loops can't serve stale rows.
_CORPUS_CACHE: dict[str, tuple[tuple[int, int], list[dict]]] = {}
_CORPUS_CACHE_LOCK = threading.Lock()

# Schema verdict for a baked corpus, memoised on the same (mtime_ns, size)
# stamp the row cache uses (#234). ``_rows_schema_mismatch`` only returns
# after walking the *entire* row list in the healthy case — ~3,200 dict
# lookups per pick for an answer that cannot change while the file doesn't.
# Keying the memo on the stat stamp also gives the degradation warning its
# documented "one-shot" behaviour for free: we warn exactly when the verdict
# is (re)computed, which is the first pick after the file changes — so a
# re-bake that is *still* wrong warns again, which is what an operator wants.
_SCHEMA_VERDICT_CACHE: dict[str, tuple[tuple[int, int], int | None]] = {}
# Latch for the missing / empty branches, which have no cached row list to
# hang a stamp on. Maps resolved path -> the reason last warned about, so a
# file that goes missing → reappears → goes missing again warns each time
# rather than being permanently suppressed by a stale entry.
_DEGRADED_WARNED: dict[str, str] = {}


def clear_corpus_cache() -> None:
    """Drop all cached corpus rows, schema verdicts, and warning latches.

    Test isolation / manual invalidation. The warning latches are cleared
    alongside the rows so a test asserting on a degradation warning isn't
    silenced by a previous test having already tripped it.
    """
    with _CORPUS_CACHE_LOCK:
        _CORPUS_CACHE.clear()
        _SCHEMA_VERDICT_CACHE.clear()
        _DEGRADED_WARNED.clear()


def _warn_degraded_once(path_key: str, reason: str, message: str) -> None:
    """Print ``message`` only when ``path_key`` isn't already latched at ``reason``."""
    with _CORPUS_CACHE_LOCK:
        if _DEGRADED_WARNED.get(path_key) == reason:
            return
        _DEGRADED_WARNED[path_key] = reason
    print(message, file=sys.stderr, flush=True)


def _clear_degraded_latch(path_key: str) -> None:
    """Forget any latched warning for ``path_key`` (the file is healthy again)."""
    with _CORPUS_CACHE_LOCK:
        _DEGRADED_WARNED.pop(path_key, None)


def _load_rows_cached(path: Path) -> list[dict]:
    key = str(path)
    try:
        st = os.stat(path)
    except OSError:
        # Missing/unreadable — take (and don't cache) the normal load path so
        # its behaviour (empty list / caller's fallback warnings) is unchanged.
        return load_rows(path)
    stamp = (st.st_mtime_ns, st.st_size)
    with _CORPUS_CACHE_LOCK:
        hit = _CORPUS_CACHE.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
    rows = load_rows(path)
    with _CORPUS_CACHE_LOCK:
        _CORPUS_CACHE[key] = (stamp, rows)
    return rows


# Public alias. Out-of-module readers (the curator UI's live coverage view)
# want the same stat-keyed cache the picker uses rather than re-parsing the
# corpus per request; they should not have to reach for a private name.
load_rows_cached = _load_rows_cached


def valid_bucket_names() -> set[str]:
    """Return the full set of ``h{1..12}_{state}`` bucket names."""
    return {f"h{hour}_{state}" for hour in range(1, 13) for state in BUCKET_ORDER}


# Backwards-compatible alias. External callers (e.g. web_server) use the public name.
_valid_bucket_names = valid_bucket_names


def _warn_unknown_preferred_buckets(overrides: dict) -> None:
    preferred = overrides.get("preferred_buckets") or {}
    if not isinstance(preferred, dict):
        return
    valid = valid_bucket_names()
    unknown = sorted(key for key in preferred if key not in valid)
    if unknown:
        print(
            f"warning: assets/selection_overrides.json preferred_buckets has unknown buckets: {', '.join(unknown)}",
            file=sys.stderr,
            flush=True,
        )


def _empty_overrides() -> dict:
    return {
        "ban_source_ids": [],
        "boost_source_ids": [],
        "preferred_buckets": {},
        "ban_quote_keys": [],
    }


def load_overrides(path: Path) -> dict:
    """Load the selection-overrides sidecar, failing open on any defect.

    Hand-editing this file is the documented curation workflow, and this
    loader sits on the per-tick render hot path — a truncated save or a
    non-object root must degrade to "no bans/boosts applied" with a stderr
    warning, not raise and freeze the panel in render-failure backoff
    (issue #186). Mirrors ``apply_content_overrides.load_overrides``.
    """
    if not path.exists():
        return _empty_overrides()
    try:
        overrides = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(
            f"warning: selection overrides {path}: unreadable or invalid JSON ({exc}); "
            "continuing with no overrides",
            file=sys.stderr,
        )
        return _empty_overrides()
    if not isinstance(overrides, dict):
        print(
            f"warning: selection overrides {path}: root is not a JSON object; "
            "continuing with no overrides",
            file=sys.stderr,
        )
        return _empty_overrides()
    _warn_unknown_preferred_buckets(overrides)
    # Older v1 sidecar files predate ban_quote_keys; default it so the rest of
    # the picker doesn't have to special-case its absence.
    overrides.setdefault("ban_quote_keys", [])
    return overrides


def metadata_bonus(row: dict) -> int:
    has_author = bool(row.get("author"))
    has_title = bool(row.get("title"))
    if has_author and has_title:
        return -3
    if has_author or has_title:
        return -1
    return 2


def dialogue_penalty(row: dict) -> int:
    text = (row.get("display_quote") or "").lower()
    return 2 if any(pattern in text for pattern in DIALOGUE_FILLER_PATTERNS) else 0


def opening_penalty(row: dict) -> int:
    text = (row.get("display_quote") or "").strip().lower()
    if any(text.startswith(pattern) for pattern in WEAK_OPENING_PATTERNS):
        return 2
    if any(text.startswith(pattern) for pattern in PRONOUN_HEAVY_OPENINGS):
        return 1
    return 0


def override_bonus(row: dict, overrides: dict, bucket: str) -> int:
    source_id = str(row.get("source_id") or "")
    preferred = overrides.get("preferred_buckets", {}).get(bucket)
    if preferred and source_id == str(preferred):
        return -5
    if source_id in {str(x) for x in overrides.get("boost_source_ids", [])}:
        return -3
    return 0


def is_banned(row: dict, overrides: dict) -> bool:
    """True when ``row`` should be excluded from picking entirely.

    Two ban tiers:

    * ``ban_source_ids`` — coarse, drops every row from the named Gutenberg ID.
      The original v1 mechanism, kept for "this whole book is unsuitable."
    * ``ban_quote_keys`` — fine, drops one specific row by
      ``"<source_id>:<line_number>"``. Added in v2 to let the curator UI
      blacklist a single quote without nuking the rest of its source. Keys are
      strings; the line_number portion is compared as text so we match what the
      web UI's "Ban this quote" button writes.
    """
    source_id = str(row.get("source_id") or "")
    if source_id in {str(x) for x in overrides.get("ban_source_ids", [])}:
        return True
    line_number = row.get("line_number")
    if line_number is None or not source_id:
        return False
    row_key = f"{source_id}:{line_number}"
    return row_key in {str(x) for x in overrides.get("ban_quote_keys", [])}


def parse_requested_minute(bucket: str, requested_time: str | None) -> int | None:
    if requested_time:
        # Operator-supplied times reach here via the web /api/bucket?time= path,
        # so a malformed string (no colon, non-numeric minute) must degrade to
        # the bucket default rather than crashing scoring with IndexError/ValueError.
        if ":" in requested_time:
            try:
                minute = int(requested_time.split(":", 1)[1])
            except ValueError:
                minute = None
            if minute is not None:
                rounded_minute = ((minute + 2) // 5) * 5
                return 0 if rounded_minute == 60 else rounded_minute
    state = bucket.split("_", 1)[1]
    return DEFAULT_BUCKET_MINUTES.get(state)


def infer_quote_minute(row: dict) -> int | None:
    normalized = row.get("normalized_time")
    if isinstance(normalized, str) and ":" in normalized:
        try:
            return int(normalized.split(":", 1)[1])
        except ValueError:
            pass

    lowered = (row.get("matched_text") or "").lower().replace("\n", " ")
    for pattern, minute in _MINUTE_PATTERNS_LONGEST_FIRST:
        if pattern in lowered:
            return 0 if minute == "zero" else minute
    return None


def circular_minute_distance(a: int, b: int) -> int:
    """Distance between two minutes on the 60-minute clock face.

    Plain ``abs(a - b)`` penalises an 11:58 quote 58 minutes away from a
    12:00 request even though it is 2 minutes early — minute distance must
    wrap at the top of the hour.
    """
    d = abs(a - b)
    return min(d, 60 - d)


def minute_distance_penalty(row: dict, bucket: str, requested_time: str | None) -> int:
    requested_minute = parse_requested_minute(bucket, requested_time)
    quote_minute = infer_quote_minute(row)
    if requested_minute is None or quote_minute is None:
        return 99
    return circular_minute_distance(requested_minute, quote_minute)


def count_sources(rows: list[dict]) -> Counter:
    return Counter(str(row.get("source_id")) for row in rows if row.get("source_id"))


def source_rarity_penalty(row: dict, source_counts: Counter) -> int:
    source_id = row.get("source_id")
    if not source_id:
        return 0
    return source_counts.get(str(source_id), 0)


def compose_baked_score_key(row: dict, bucket: str, overrides: dict, requested_time: str | None) -> tuple:
    """Reconstruct the full 12-component sort key for a baked row.

    ``row["baked_score"]`` holds the ten row-intrinsic components in
    :data:`BAKED_SCORE_COMPONENTS` order. We interleave back in the two
    request-time components (``minute_penalty`` at position 2 and
    ``override_bonus`` at position 7) so the resulting tuple has the same
    layout as :func:`score_row`'s output — that is what guarantees bit-for-bit
    pick-equivalence between the baked and the raw-corpus paths.

    Uses ``row["inferred_quote_minute"]`` (baked once by
    ``bake_quote_database``) instead of re-running the regex sweep per tick.
    """
    baked = row["baked_score"]
    requested_minute = parse_requested_minute(bucket, requested_time)
    quote_minute = row.get("inferred_quote_minute")
    if requested_minute is None or quote_minute is None:
        minute_penalty = 99
    else:
        minute_penalty = circular_minute_distance(requested_minute, quote_minute)
    ovr = override_bonus(row, overrides, bucket)
    return (
        baked[0], baked[1], minute_penalty,
        baked[2], baked[3], baked[4], baked[5],
        ovr,
        baked[6], baked[7], baked[8], baked[9],
    )


def score_row(row: dict, bucket: str, overrides: dict, requested_time: str | None = None, source_counts: Counter | None = None) -> tuple:
    # Fast path: baked rows carry their nine row-intrinsic components and a
    # pre-computed source rarity in ``baked_score``. Recomputing here would
    # burn CPU per-tick on logic the bake stage already ran — and if the two
    # code paths drift, baked picks silently diverge from raw picks.
    if "baked_score" in row:
        return compose_baked_score_key(row, bucket, overrides, requested_time)
    display = row.get("display_quote") or ""
    fragment_penalty = 1 if row.get("display_fragment") else 0
    cleanup_penalty = 0 if row.get("cleanup_status") in {"complete_sentence", "expanded_with_context"} else 1
    matched = row.get("matched_text") or ""
    length_penalty = abs(len(display) - 140)
    if len(display) < 60:
        length_penalty += 80
    exactness_bonus = 0
    lowered = matched.lower().replace("\n", " ")
    if _FIVE_MINUTES_TO_RE.search(lowered) or "ten minutes to" in lowered or "fifty-five minutes past" in lowered:
        exactness_bonus = -2
    elif "quarter" in lowered or "half" in lowered:
        exactness_bonus = -1
    source_bonus = 0 if row.get("source_id") else 1
    quality_component = -(row.get("quality_score") or 0)
    minute_penalty = minute_distance_penalty(row, bucket, requested_time)
    rarity_penalty = source_rarity_penalty(row, source_counts) if source_counts is not None else 0
    return (
        fragment_penalty,
        cleanup_penalty,
        minute_penalty,
        metadata_bonus(row),
        dialogue_penalty(row),
        opening_penalty(row),
        source_bonus,
        override_bonus(row, overrides, bucket),
        quality_component,
        length_penalty + exactness_bonus,
        rarity_penalty,
        len(display),
    )


def load_recent_history(history_path: str | None, days: int) -> set[tuple]:
    """Return the set of (source_id, line_number) tuples shown within the last ``days``.

    Returns an empty set when the feature is disabled (``days <= 0`` or empty path)
    or the ledger does not exist. Malformed lines are skipped, and the first such
    line per call is logged to stderr so corruption from a partial-write crash
    surfaces instead of silently defeating the anti-repeat filter.
    Non-existent parent directories are treated as "no history yet" (empty set).
    """
    if not history_path or days <= 0:
        return set()
    path = Path(history_path).expanduser()
    if not path.exists():
        return set()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    recent: set[tuple] = set()
    warned = False
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = dt.datetime.fromisoformat(entry["ts"])
            except (ValueError, KeyError, json.JSONDecodeError):
                if not warned:
                    print(
                        f"history ledger {path}: malformed line skipped (corrupt or partial write); "
                        f"subsequent bad lines in this read will be suppressed",
                        file=sys.stderr,
                        flush=True,
                    )
                    warned = True
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.timezone.utc)
            if ts < cutoff:
                continue
            source_id = entry.get("source_id")
            line_number = entry.get("line_number")
            if source_id is None or line_number is None:
                continue
            recent.add((str(source_id), line_number))
    return recent


def append_history(history_path: str | None, source_id, line_number) -> None:
    """Append one ledger entry. No-op if path is empty/None or required fields are missing.

    fsyncs before close so a power loss immediately after the call can't leave
    the JSON line buffered in the kernel and lost. We keep the simple
    append-only pattern (rather than tmp+rename) because the ledger is
    append-heavy and read-tail-heavy; rewriting it on every entry would be
    O(n) and defeat streaming reads. ``load_recent_history`` tolerates
    (and warns about) half-written tails, so the worst case is one lost
    entry instead of ledger-wide corruption.
    """
    if not history_path or source_id is None or line_number is None:
        return
    path = Path(history_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source_id": str(source_id),
        "line_number": line_number,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def compact_history(history_path: str | None, days: int) -> int:
    """Drop ledger entries older than ``2 × days``. Returns the number of lines dropped.

    The anti-repeat filter only consults entries within the configured window
    (``--history-days``), so anything older than that is dead weight that still
    gets streamed through :func:`load_recent_history` on every pick. A long-
    lived appliance accumulates ~288 entries per week; over years the linear
    scan is cheap but the file grows into tens of KB of expired rows.

    We keep ``2 × days`` of slack so a short clock drift or an operator
    bumping ``--history-days`` up a day or two doesn't immediately evict rows
    that are about to be re-consulted. No-op if the path is empty, the file
    doesn't exist, ``days <= 0``, or every entry is still fresh (the common
    case — avoids a pointless rewrite). Routes the rewrite through
    :mod:`atomic_io` so a crash mid-compact leaves the original ledger intact.

    Malformed lines are preserved as-is rather than silently dropped: the
    compact pass is about bounded growth, not corruption repair — callers who
    need the warn-and-skip behaviour should rely on :func:`load_recent_history`.
    """
    if not history_path or days <= 0:
        return 0
    path = Path(history_path).expanduser()
    if not path.exists():
        return 0
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2 * days)
    original = path.read_text(encoding="utf-8").splitlines()
    kept: list[str] = []
    dropped = 0
    for line in original:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            ts = dt.datetime.fromisoformat(entry["ts"])
        except (ValueError, KeyError, json.JSONDecodeError):
            kept.append(line)
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        if ts < cutoff:
            dropped += 1
            continue
        kept.append(line)
    if dropped == 0:
        return 0
    payload = ("\n".join(kept) + "\n") if kept else ""
    atomic_io.atomic_write_text(path, payload)
    return dropped


def remove_history_entries(history_path: str | None, source_id, line_number) -> int:
    """Remove every ledger entry matching ``(source_id, line_number)``.

    Powers the "un-skip" button long-press. A skipped quote has (at least)
    two ledger entries — the original render-time append plus the ban append
    from ``action_skip`` — and *all* of them must go, or the fresh-first
    history filter still excludes the quote and the restore renders a third
    quote instead of bringing the skipped one back (issue #183). Removing
    every match is safe: the restore render re-appends the quote once.

    Malformed lines are preserved as-is (corruption repair is
    ``load_recent_history``'s job). Returns the number of entries removed —
    0 when there is no path, no file, or nothing matched.
    """
    if not history_path or source_id is None or line_number is None:
        return 0
    path = Path(history_path).expanduser()
    if not path.exists():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    target = (str(source_id), line_number)
    kept: list[str] = []
    removed = 0
    for line in lines:
        try:
            entry = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            kept.append(line)
            continue
        if (str(entry.get("source_id")), entry.get("line_number")) == target:
            removed += 1
            continue
        kept.append(line)
    if removed:
        # Atomic rewrite: a SIGKILL between truncate and write-back would
        # otherwise wipe the ledger entirely, since this is the only path
        # that can change history.jsonl without the append-only guarantee
        # append_history relies on.
        payload = ("\n".join(kept) + "\n") if kept else ""
        atomic_io.atomic_write_text(path, payload)
    return removed


def _row_history_key(row: dict) -> tuple | None:
    source_id = row.get("source_id")
    line_number = row.get("line_number")
    if source_id is None or line_number is None:
        return None
    return (str(source_id), line_number)


# Positional labels for the tuple returned by :func:`score_row`. The web UI's
# candidate browser (``GET /api/bucket/<bucket>``) uses this to explode the raw
# tuple into named fields so the operator can see *why* a candidate ranked
# where it did (e.g. "lost by minute_penalty=8").
SCORE_COMPONENTS = (
    "fragment_penalty",
    "cleanup_penalty",
    "minute_penalty",
    "metadata_bonus",
    "dialogue_penalty",
    "opening_penalty",
    "source_bonus",
    "override_bonus",
    "quality_component",
    "length_exactness",
    "source_rarity_penalty",
    "length_tiebreak",
)


def pick_best(
    rows: list[dict],
    bucket: str,
    seed: int,
    min_quality: int,
    overrides: dict,
    requested_time: str | None = None,
    recent_history: set[tuple] | None = None,
    return_ranked: bool = False,
):
    """Pick the highest-ranked row for ``bucket`` (walking neighbour buckets on empty).

    Returns ``(chosen_row, resolved_bucket)`` by default. When ``return_ranked``
    is True, returns ``(chosen_row, resolved_bucket, ranked)`` where ``ranked``
    is a list of ``{"row": dict, "score": tuple}`` ordered by ascending score
    (best first). This variant powers the curator UI's bucket-inspector view.
    """
    # Rarity is the only score component that needs a view of the whole
    # corpus, and baked rows already carry it inside ``baked_score`` — so on
    # the runtime path (baked DB) the Counter over every row was built once
    # per pick and never read. Build it lazily, and only when a non-baked row
    # actually reaches the scorer. ``count_sources`` still counts *all* rows,
    # not just the candidates, so the penalty a raw row gets is unchanged.
    source_counts: Counter | None = None
    counts_built = False

    def counts_for(pool: list[dict]) -> Counter | None:
        nonlocal source_counts, counts_built
        if all("baked_score" in row for row in pool):
            return None
        if not counts_built:
            source_counts = count_sources(rows)
            counts_built = True
        return source_counts

    # Index by bucket once. The neighbour walk visits up to 12 buckets for a
    # sparse hour, and each visit used to re-scan the entire row list.
    # Grouping preserves input order, so each bucket's candidate list — and
    # therefore the seeded tie-break below — is byte-identical to the
    # per-bucket filter it replaces.
    # Only string buckets are indexed. ``neighbor_buckets`` always yields
    # strings, so the ``fuzzy_bucket == candidate_bucket`` test this replaces
    # could never match a non-string value either — but that test *tolerated*
    # one, whereas using the raw value as a dict key raises TypeError on any
    # unhashable shape (a corpus row whose fuzzy_bucket is a list). The
    # picker runs on the per-tick render path, where an exception costs a
    # frozen panel and a backoff window, so a single malformed row must
    # degrade the way it always did: silently ignored.
    rows_by_bucket: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        bucket_name = row.get("fuzzy_bucket")
        if isinstance(bucket_name, str):
            rows_by_bucket[bucket_name].append(row)

    recent = recent_history or set()
    for candidate_bucket in neighbor_buckets(bucket):
        candidates = [
            row for row in rows_by_bucket.get(candidate_bucket, ())
            if row.get("display_quote")
            and not is_banned(row, overrides)
            and (row.get("quality_score") is None or row.get("quality_score", 0) >= min_quality)
        ]
        if not candidates:
            continue
        # Strict fresh-first: exclude recently-shown rows. If that empties the pool,
        # fall back to the full candidate list so a sparse bucket still renders.
        fresh = [row for row in candidates if _row_history_key(row) not in recent] if recent else candidates
        pool = fresh or candidates
        # score_row is pure, so compute each candidate's score once and derive
        # the sort, the top-score filter, and the ranked view from it rather
        # than re-scoring 3-4× per row on this per-tick path. A stable sort over
        # the precomputed keys preserves pool order, so the seeded choice below
        # stays byte-identical to the prior repeated-score_row implementation.
        pool_counts = counts_for(pool)
        scored = sorted(
            (
                (score_row(row, candidate_bucket, overrides, requested_time, pool_counts), row)
                for row in pool
            ),
            key=lambda sr: sr[0],
        )
        top_score = scored[0][0]
        top = [row for score, row in scored if score == top_score]
        rng = random.Random(seed)
        chosen = rng.choice(top)
        if return_ranked:
            ranked = [{"row": row, "score": score} for score, row in scored]
            return chosen, candidate_bucket, ranked
        return chosen, candidate_bucket
    raise SystemExit(f"No candidates found for bucket {bucket} or nearby buckets above quality {min_quality}")


def select_candidates(
    time_str: str | None = None,
    bucket: str | None = None,
    top_n: int = 10,
    input_path: str = DEFAULT_INPUT_PATH,
    # BASE_DIR-anchored — see the matching note on ``select_quote``. The bare
    # relative literal this defaulted to hasn't existed since the v2.x package
    # restructure, so the curator UI's bucket inspector was ranking candidates
    # against an empty overrides sidecar and showing an ``override_bonus`` of 0
    # for rows the operator had explicitly boosted or banned.
    overrides_path: str = DEFAULT_OVERRIDES_PATH,
    seed: int = 0,
    min_quality: int = 60,
    history_path: str | None = None,
    history_days: int = DEFAULT_HISTORY_DAYS,
) -> list[dict]:
    """Return up to ``top_n`` ranked candidates for a time or bucket.

    Each entry is ``{"row": <full candidate row>, "score": {component: int, ...},
    "is_winner": bool}`` where ``score`` explodes the :func:`score_row` tuple
    into :data:`SCORE_COMPONENTS`-keyed fields so the curator UI can render
    per-component comparisons. Lower score is better at every position.

    The winner (what :func:`select_quote` would have returned) is marked with
    ``is_winner: true`` for the UI. Ties on top score are broken by a seeded
    ``random.Random(seed)`` — same as the live picker — so the UI shows the
    same frame the clock would.

    Reads the raw corpus (``DEFAULT_INPUT_PATH``) by design rather than the
    baked DB: the curator UI surfaces rows the baker dropped (daypart-only,
    below the quality floor) so an operator can see *why* a quote never
    appeared. Switching this to the baked path would silently hide those rows.
    """
    if not time_str and not bucket:
        raise ValueError("select_candidates requires time_str or bucket")
    target_bucket = bucket or bucket_for_time(time_str)
    rows = load_rows(resolve_path(input_path))
    overrides = load_overrides(resolve_path(overrides_path))
    recent = load_recent_history(history_path, history_days)
    chosen, resolved_bucket, ranked = pick_best(
        rows, target_bucket, seed, min_quality, overrides, time_str, recent, return_ranked=True,
    )
    chosen_key = (chosen.get("source_id"), chosen.get("line_number"))
    result: list[dict] = []
    for entry in ranked[: max(0, top_n)]:
        row = entry["row"]
        score_tuple = entry["score"]
        score_map = dict(zip(SCORE_COMPONENTS, score_tuple))
        result.append({
            "row": row,
            "score": score_map,
            "resolved_bucket": resolved_bucket,
            "is_winner": (row.get("source_id"), row.get("line_number")) == chosen_key,
        })
    return result


def _rows_schema_mismatch(rows: list[dict]) -> int | None:
    """Return the first rogue ``schema_version`` seen on a baked row, or ``None`` if in sync.

    A baked corpus pre-dating the schema-version field will have no
    ``schema_version`` on any row — we treat that as version 0 and report it
    so an upgrade surfaces loudly on first boot (the operator is expected to
    re-bake). A row with a *different* integer schema means the baker that
    produced this file stamped a layout that the current ``pick_quote`` can't
    interpret — ditto falls back.

    Only rows that actually carry ``baked_score`` are checked; a raw-corpus
    passthrough will have none, so the schema check skips harmlessly.
    """
    for row in rows:
        if "baked_score" not in row:
            continue
        version = row.get("schema_version", 0)
        if not isinstance(version, int) or version != BAKED_SCORE_SCHEMA_VERSION:
            return version
    return None


def _schema_mismatch_cached(path: Path, rows: list[dict]) -> tuple[int | None, bool]:
    """Return ``(verdict, computed_now)`` for ``path``'s baked rows.

    ``verdict`` is what :func:`_rows_schema_mismatch` returns; ``computed_now``
    is True only on the pick that actually ran the scan — i.e. the first pick
    after the file's ``(mtime_ns, size)`` changed. Callers use it to decide
    whether to emit the degradation warning, which is what makes that warning
    genuinely one-shot per version of the file instead of per pick.

    An unstattable path falls through to an uncached scan so behaviour matches
    :func:`_load_rows_cached`'s own missing-file passthrough.
    """
    key = str(path)
    try:
        st = os.stat(path)
    except OSError:
        return _rows_schema_mismatch(rows), True
    stamp = (st.st_mtime_ns, st.st_size)
    with _CORPUS_CACHE_LOCK:
        hit = _SCHEMA_VERDICT_CACHE.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1], False
    verdict = _rows_schema_mismatch(rows)
    with _CORPUS_CACHE_LOCK:
        _SCHEMA_VERDICT_CACHE[key] = (stamp, verdict)
    return verdict, True


def _resolve_corpus(database_path: str | None, input_path: str) -> list[dict]:
    """Prefer the baked database; fall back to the raw corpus if missing or schema-mismatched.

    The baked DB (``DEFAULT_DATABASE_PATH``) is the canonical runtime input and
    ships committed in the repo, so on a healthy install this always hits the
    first branch. The fallback exists as a defensive guardrail for three cases:

    * the baked file is missing entirely (e.g. someone pointed ``--database``
      at a stale path, or a partial checkout);
    * the baked file exists but is empty (e.g. a crashed bake left a zero-byte
      placeholder); and
    * the baked file's ``schema_version`` disagrees with
      :data:`BAKED_SCORE_SCHEMA_VERSION` — the baker that produced the file
      stamped a ``baked_score`` layout this ``pick_quote`` doesn't understand,
      so scoring it would produce drifted picks without crashing.

    All three fall back to the raw corpus rather than crashing the loop, and
    all three log a stderr warning so the operator notices they're running on
    the slower raw-scoring path. That warning is emitted **once per version of
    the file**, not once per pick (#234): the appliance picks twice per tick
    (the in-process ``peek_quote_id`` plus the ``render_quote.py`` subprocess),
    so an unlatched warning wrote ~2,900 identical lines a day into the same
    journald stream the loop uses for real events. Latching on the file's
    identity rather than latching forever is deliberate — a re-bake that is
    still wrong warns again, which is the signal an operator is waiting for.

    A falsy ``database_path`` (empty string / ``None``) skips the baked path
    entirely without warning — the bake-equivalence tests use this to exercise
    the raw path on purpose.
    """
    if database_path:
        path = resolve_path(database_path)
        key = str(path)
        if path.exists() and path.stat().st_size > 0:
            rows = _load_rows_cached(path)
            stale, computed_now = _schema_mismatch_cached(path, rows)
            if stale is not None:
                # The file EXISTS, so any latched "missing" / "empty" warning
                # for this path is now stale. Clearing it here as well as on
                # the healthy path is what makes the documented
                # missing -> restored -> missing sequence warn each time even
                # when the middle state was a bad bake rather than a good one.
                _clear_degraded_latch(key)
                if computed_now:
                    print(
                        f"warning: baked database {path} has schema_version={stale!r} "
                        f"but this pick_quote expects {BAKED_SCORE_SCHEMA_VERSION}; "
                        f"falling back to raw corpus (re-run bake_quote_database.py)",
                        file=sys.stderr,
                        flush=True,
                    )
                return _load_rows_cached(resolve_path(input_path))
            # Healthy: drop any missing/empty latch so a later regression on
            # this same path warns again instead of being suppressed.
            _clear_degraded_latch(key)
            return rows
        if path.exists():
            _warn_degraded_once(
                key,
                "empty",
                f"warning: baked database {path} is empty; falling back to raw corpus",
            )
        else:
            _warn_degraded_once(
                key,
                "missing",
                f"warning: baked database {path} not found; falling back to raw corpus",
            )
    return _load_rows_cached(resolve_path(input_path))


def select_quote(
    time_str: str | None = None,
    bucket: str | None = None,
    input_path: str = DEFAULT_INPUT_PATH,
    database_path: str | None = None,
    # BASE_DIR-anchored, NOT the bare relative "assets/selection_overrides.json"
    # this defaulted to before. That literal predates the v2.x package
    # restructure that moved the tree to ``idle_hours/assets/``, so it resolved
    # against CWD to a path that no longer exists — and ``load_overrides``
    # fail-opens to an empty sidecar on a missing file. Every in-process caller
    # that relied on the default (notably ``render_quote.pick_quote``, i.e. the
    # actual runtime render path) therefore silently applied NO bans, boosts, or
    # preferred buckets: the curator UI's "Ban this quote" button wrote a ban
    # that the panel then ignored forever.
    overrides_path: str = DEFAULT_OVERRIDES_PATH,
    seed: int = 0,
    min_quality: int = 60,
    history_path: str | None = None,
    history_days: int = DEFAULT_HISTORY_DAYS,
    rows: list[dict] | None = None,
    overrides: dict | None = None,
    pin_key: tuple | None = None,
) -> dict:
    """Pick the best quote for a time or bucket and return the result dict.

    Mirrors the JSON printed by ``main`` so ``render_quote`` can call this in-process
    instead of shelling out and re-parsing stdout.

    Callers that invoke this many times in a tight loop (e.g. the contact-sheet
    renderer) can pass pre-loaded ``rows`` and ``overrides`` to skip re-parsing
    the JSONL/JSON files on every call.

    Pass ``database_path=DEFAULT_DATABASE_PATH`` to use the baked display-ready
    DB — the canonical runtime input, which is what the CLI, ``run_clock``, and
    ``render_quote`` all do. Pass ``database_path=""`` (or ``None``) to force
    the raw-corpus path; that's reserved for the bake-equivalence tests and for
    callers that want the unfiltered corpus view. When a baked path is set but
    the file is missing or empty, the picker logs a stderr warning and falls
    back to ``input_path`` so a stale/absent bake degrades gracefully instead
    of crashing the loop.
    """
    if not time_str and not bucket:
        raise ValueError("select_quote requires time_str or bucket")
    target_bucket = bucket or bucket_for_time(time_str)
    if rows is None:
        rows = _resolve_corpus(database_path, input_path)
    if overrides is None:
        overrides = load_overrides(resolve_path(overrides_path))
    if pin_key is not None:
        # Repaint contract: the caller (run_clock's theme-only repaint, or any
        # render whose peek already committed to a row) wants THIS exact row —
        # bypassing scoring and, crucially, the anti-repeat history filter,
        # which would otherwise exclude the currently-displayed quote and
        # silently swap it on a theme change (issue #190). Falls through to a
        # normal pick when the pinned row no longer exists (re-bake, ban).
        #
        # (source_id, line_number) alone does NOT identify a row: one source
        # line can carry several time phrases, so the committed corpus has 128
        # duplicate (source_id, line_number) keys — many spanning different
        # buckets ("ten o'clock" in h10_exact vs "close on ten o'clock" in
        # h9_five_to). Matching on the key alone returned whichever copy came
        # first in file order, so ~8% of clock times rendered a row the peek
        # never chose — the panel bolted the wrong phrase and reported the
        # wrong bucket. The optional third element carries the peeked
        # ``matched_text``, which is exactly the discriminator peek_quote_id
        # already tracks for this reason; when it is supplied a row must match
        # it too, and a miss falls through to a normal pick rather than
        # rendering an arbitrary sibling.
        want = (str(pin_key[0]), pin_key[1])
        want_matched = pin_key[2] if len(pin_key) > 2 else None
        candidates = [
            row for row in rows
            if (str(row.get("source_id")), row.get("line_number")) == want
            and row.get("display_quote")
            and (want_matched is None or row.get("matched_text") == want_matched)
            # An operator ban must win over a repaint: otherwise the curator
            # UI's "Ban this quote" button looks broken, because the very next
            # theme change repaints the row the operator just banned.
            and not is_banned(row, overrides)
        ]
        if candidates:
            # A handful of rows still tie on (key, matched_text) while
            # disagreeing about fuzzy_bucket — the same phrase mis-bucketed
            # twice in the corpus. Taking the first on disk would report a
            # resolved_bucket the natural pick never would (and a bogus
            # used_fallback in the debug footer), so break the tie with the
            # picker's own bucket-preference order: the target bucket first,
            # then its siblings in alternating outward-distance order. That
            # reproduces exactly which copy pick_best would have landed on.
            try:
                order = {b: i for i, b in enumerate(neighbor_buckets(target_bucket))}
            except (ValueError, KeyError):
                order = {}
            best = min(
                candidates,
                key=lambda row: order.get(row.get("fuzzy_bucket"), len(order)),
            )
            return _select_result(
                time_str, target_bucket, best.get("fuzzy_bucket") or target_bucket, best,
            )
        print(
            f"warning: pinned quote {want[0]}:{want[1]} not available "
            "(missing, banned, or matched-text mismatch); picking normally",
            file=sys.stderr,
        )
    recent = load_recent_history(history_path, history_days)
    best, resolved_bucket = pick_best(rows, target_bucket, seed, min_quality, overrides, time_str, recent)
    return _select_result(time_str, target_bucket, resolved_bucket, best)


def _select_result(time_str: str | None, target_bucket: str, resolved_bucket: str, best: dict) -> dict:
    return {
        "requested_time": time_str,
        "bucket": target_bucket,
        "resolved_bucket": resolved_bucket,
        "used_fallback": resolved_bucket != target_bucket,
        "display_quote": best.get("display_quote"),
        "matched_text": best.get("matched_text"),
        "source_id": best.get("source_id"),
        "source_path": best.get("source_path"),
        "line_number": best.get("line_number"),
        "author": best.get("author"),
        "title": best.get("title"),
        "display_fragment": best.get("display_fragment"),
        "cleanup_status": best.get("cleanup_status"),
        "normalized_time": best.get("normalized_time"),
        "quality_score": best.get("quality_score"),
        "quality_flags": best.get("quality_flags"),
    }


def main() -> int:
    args = parse_args()
    if not args.time and not args.bucket:
        raise SystemExit("Provide --time or --bucket")
    output = select_quote(
        time_str=args.time,
        bucket=args.bucket,
        input_path=args.input,
        database_path=args.database or None,
        overrides_path=args.overrides,
        seed=args.seed,
        min_quality=args.min_quality,
        history_path=args.history_path,
        history_days=args.history_days,
    )
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
