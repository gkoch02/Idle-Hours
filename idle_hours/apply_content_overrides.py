#!/usr/bin/env python3
"""Apply per-row content overrides on top of the enriched corpus.

Final pipeline stage. Reads ``assets/content_overrides.json`` — a sidecar
keyed by ``"<source_id>:<line_number>"`` — and patches matching rows from the
input JSONL. This is how hand-curated fixes (a miscaptured time phrase, a bad
display excerpt, a broken attribution) are kept *durable* across pipeline
re-runs: the fix lives in the sidecar and re-applies every time, instead of
being written into a derivable artifact and silently overwritten by the next
miner run.

The sidecar format is a flat dict:

    {
      "141:482":  {"display_quote": "..."},
      "1342:99":  {"matched_text": "half past two", "normalized_time": "02:30"}
    }

Allowed override fields: ``display_quote``, ``matched_text``, ``author``,
``title``, ``quality_score``, ``hour``, ``minute``, ``normalized_time``. Any
other key in the sidecar is ignored with a stderr warning. After applying,
``fuzzy_bucket`` is re-derived from the post-override ``normalized_time`` so
time-affecting overrides can't drift the bucket. Patched rows are stamped
``override_applied: true`` so downstream debugging can tell which rows came
from the sidecar, and carry ``override_originals`` — the values the sidecar
replaced — so deleting an entry and re-running restores the row.

Keys that don't match any row in the input are logged to stderr so typos and
overrides for rows that later got dedup-dropped surface loudly rather than
silently no-op'ing.

Writes in-place by default (pass ``--output`` to redirect).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from idle_hours import atomic_io
from idle_hours.buckets import bucket_for_time
from idle_hours.jsonl_io import iter_jsonl
from idle_hours.runtime_config import validate_hhmm

BASE_DIR = Path(__file__).resolve().parent

# Bundled location of the per-row content-overrides sidecar. Exported so
# ``run_clock`` (which exposes ``--content-overrides``) and ``web_server``
# (which serves + rewrites it) share one definition instead of each
# re-deriving ``BASE_DIR / "assets/content_overrides.json"``.
DEFAULT_OVERRIDES_PATH = BASE_DIR / "assets" / "content_overrides.json"

ALLOWED_FIELDS: frozenset[str] = frozenset({
    "display_quote",
    "matched_text",
    "author",
    "title",
    "quality_score",
    "hour",
    "minute",
    "normalized_time",
})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply per-row content overrides to corpus rows.")
    parser.add_argument("input", help="Input JSONL file (typically assets/candidates-attributed.jsonl)")
    parser.add_argument(
        "--overrides",
        default=str(DEFAULT_OVERRIDES_PATH),
        help="Path to the content overrides sidecar JSON",
    )
    parser.add_argument("--output", default=None, help="Output path; defaults to in-place overwrite")
    return parser.parse_args()


def _resolve(path_str: str) -> Path:
    """Resolve an operator-supplied path against the CWD (issue #295).

    ``DEFAULT_OVERRIDES_PATH`` is already absolute, so only paths the operator
    typed reach the relative branch — and those must mean what they mean in
    the shell that ran the command, not a location inside the package.
    """
    return Path(path_str).expanduser().resolve()


def row_key(row: dict) -> str | None:
    source_id = row.get("source_id")
    line_number = row.get("line_number")
    if source_id is None or line_number is None:
        return None
    return f"{source_id}:{line_number}"


def load_overrides(path: Path) -> dict[str, dict]:
    """Load the sidecar, fail-open on corruption.

    The sidecar is hand-edited; an editor crash or a partial save can leave it
    truncated, which would otherwise abort the entire pipeline's final stage
    with a ``JSONDecodeError``. Warn loudly and return ``{}`` so the rest of
    the bake completes — better to ship the corpus with no overrides than to
    block the picker on a malformed JSON file.
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _warn(f"{path}: overrides unreadable ({exc!r}); treating as empty")
        return {}
    try:
        raw = json.loads(text)
    except (ValueError, json.JSONDecodeError) as exc:
        _warn(f"{path}: overrides not valid JSON ({exc}); treating as empty")
        return {}
    if not isinstance(raw, dict):
        _warn(f"{path}: overrides root must be a JSON object; treating as empty")
        return {}
    return raw


def _warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr, flush=True)


# Pre-override values of every field the sidecar has written on a row, kept
# on the row itself so removing an override can put them back. See
# ``apply_overrides``.
ORIGINALS_FIELD = "override_originals"
_TIME_FIELDS = frozenset({"hour", "minute", "normalized_time"})
_HHMM_RE = re.compile(r"\d{2}:\d{2}")


def _invalid_value(field: str, value) -> str | None:
    """Return why ``value`` can't be written to ``field``, or ``None`` if it can.

    ``bool`` is rejected explicitly: it is an ``int`` subclass, so ``True``
    would otherwise pass as hour 1.
    """
    if field in {"hour", "minute", "quality_score"}:
        if not isinstance(value, int) or isinstance(value, bool):
            return "must be an integer"
        bounds = {"hour": (0, 23), "minute": (0, 59), "quality_score": (0, 100)}[field]
        if not bounds[0] <= value <= bounds[1]:
            return f"must be {bounds[0]}..{bounds[1]}"
    elif field == "normalized_time":
        if not isinstance(value, str):
            return "must be an HH:MM string"
        try:
            validate_hhmm(value)
        except ValueError:
            return "must be HH:MM, 00:00-23:59"
        if not _HHMM_RE.fullmatch(value):
            return "must be zero-padded HH:MM"
    return None


def _restore(row: dict, field: str, original) -> None:
    # ``None`` records "absent or null" — the two are equivalent for every
    # overridable field — and restores to absent.
    if original is None:
        row.pop(field, None)
    else:
        row[field] = original


def apply_overrides(
    rows: list[dict],
    overrides: dict[str, dict],
    *,
    overrides_path: str = "content_overrides.json",
    stats: dict | None = None,
) -> tuple[list[dict], int]:
    """Return ``(patched_rows, applied_count)`` after layering ``overrides`` onto ``rows``.

    Mutates row copies, not the inputs. Warns on stderr for unknown fields and
    dangling keys (overrides that didn't match any row).

    **Reversible.** This stage writes its output back over its input by
    default, and so does the curator UI's "Bake now" (issue #288), so an
    override is baked into the raw corpus. Without a record of what it
    replaced, deleting the sidecar entry and re-running changed nothing —
    the patched text was permanent, and on an appliance whose relocated
    corpus has no git history, unrecoverable. So the first time the sidecar
    writes a field, the row's previous value goes into ``override_originals``;
    a field the sidecar no longer writes is restored from it and dropped.
    A row left with no originals loses both ``override_originals`` and the
    ``override_applied`` stamp. Rows patched before the ledger existed record
    their already-patched value as the original, since the true one is gone.

    ``stats``, when given, is filled with ``applied`` and ``reverted`` counts,
    so a caller can tell whether anything changed.
    """
    patched_rows = [dict(row) for row in rows]
    unseen_keys = set(overrides.keys())
    applied = 0
    reverted = 0

    for row in patched_rows:
        key = row_key(row)
        originals = dict(row.get(ORIGINALS_FIELD) or {})
        patch = overrides.get(key) if key is not None else None
        if key is not None and key in overrides:
            unseen_keys.discard(key)
            if not isinstance(patch, dict):
                # Leave the row exactly as it is. Treating a present-but-
                # malformed entry like a deleted one would restore the row's
                # originals, so a hand-edit typo ("141:482": null) would
                # silently undo the override it was meant to adjust.
                _warn(f"{overrides_path}: override for {key} is not an object; row left unchanged")
                continue
        if patch is None and not originals:
            continue
        patch = patch or {}

        unknown = sorted(f for f in patch if f not in ALLOWED_FIELDS)
        if unknown:
            _warn(f"{overrides_path}: override for {key} has unsupported fields: {', '.join(unknown)}")
        writes = {}
        for field, value in patch.items():
            if field not in ALLOWED_FIELDS:
                continue
            problem = _invalid_value(field, value)
            if problem:
                # Skip just this field: a string minute ("30") or an
                # out-of-range hour would otherwise land on the row and break
                # every consumer that does arithmetic on it (issue #305).
                _warn(f"{overrides_path}: override for {key} has invalid {field} {value!r} ({problem}); field skipped")
                continue
            writes[field] = value
        # hour/minute without normalized_time re-derive it, so it is written too.
        derive_time = bool(_TIME_FIELDS & writes.keys()) and "normalized_time" not in writes
        # ...and normalized_time re-derives whichever of hour/minute the patch
        # left out, or they would go on describing the old time (issue #305).
        # Derived fields count as written so their originals are recorded and
        # removing the override restores them.
        derive_parts = (
            {"hour", "minute"} - writes.keys() if "normalized_time" in writes else set()
        )
        written = set(writes) | ({"normalized_time"} if derive_time else set()) | derive_parts

        # Put back every field the sidecar used to write and no longer does.
        restored_any = False
        for field in [f for f in originals if f not in written]:
            _restore(row, field, originals.pop(field))
            restored_any = True

        for field in written:
            originals.setdefault(field, row.get(field))
        for field, value in writes.items():
            row[field] = value

        if derive_parts:
            parsed_hour, parsed_minute = (int(p) for p in writes["normalized_time"].split(":"))
            if "hour" in derive_parts:
                row["hour"] = parsed_hour
            if "minute" in derive_parts:
                row["minute"] = parsed_minute

        if derive_time:
            hour = row.get("hour")
            minute = row.get("minute")
            # If hour/minute were touched but normalized_time wasn't, keep them in sync.
            if isinstance(hour, int) and isinstance(minute, int):
                row["normalized_time"] = f"{hour:02d}:{minute:02d}"
            else:
                _warn(
                    f"{overrides_path}: override for {key} touches hour/minute but "
                    f"leaves them inconsistent (hour={hour!r}, minute={minute!r}); "
                    f"bucket will not be re-derived. Provide both, or set normalized_time."
                )

        # Re-derived for every row this stage touches, as it always was; a
        # restored time field makes it matter on the revert path too.
        normalized = row.get("normalized_time")
        if isinstance(normalized, str) and ":" in normalized:
            try:
                row["fuzzy_bucket"] = bucket_for_time(normalized)
            except (ValueError, KeyError):
                _warn(
                    f"{overrides_path}: override for {key} produced invalid "
                    f"normalized_time {normalized!r}; fuzzy_bucket left unchanged."
                )

        if originals:
            row[ORIGINALS_FIELD] = originals
            row["override_applied"] = True
        else:
            row.pop(ORIGINALS_FIELD, None)
            row.pop("override_applied", None)
        if writes:
            applied += 1
        elif restored_any:
            reverted += 1

    if unseen_keys:
        dangling = ", ".join(sorted(unseen_keys))
        _warn(
            f"{overrides_path}: {len(unseen_keys)} override key(s) did not match any row "
            f"(dropped row or typo?): {dangling}"
        )

    if stats is not None:
        stats["applied"] = applied
        stats["reverted"] = reverted
    return patched_rows, applied


def main() -> int:
    args = parse_args()
    input_path = _resolve(args.input)
    overrides_path = _resolve(args.overrides)
    output_path = _resolve(args.output) if args.output else input_path

    rows = list(iter_jsonl(input_path))
    overrides = load_overrides(overrides_path)
    stats: dict = {}
    patched, applied = apply_overrides(rows, overrides, overrides_path=str(overrides_path), stats=stats)

    # Atomic write: ``output_path == input_path`` when --output is omitted
    # (the default), so an in-place crash here would otherwise truncate the
    # picker's live runtime corpus. Streaming so we don't have to materialise
    # the whole file in memory first.
    atomic_io.atomic_write_lines(
        output_path,
        (json.dumps(row, ensure_ascii=False) for row in patched),
    )

    print(f"Applied {applied} override(s) across {len(overrides)} sidecar entries")
    if stats["reverted"]:
        print(f"Reverted {stats['reverted']} row(s) whose override was removed from the sidecar")
    print(f"Wrote {len(patched)} rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
