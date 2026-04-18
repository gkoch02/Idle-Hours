"""Streaming JSONL reader used across the mining and selection pipeline stages.

Prior to this helper each stage reimplemented the same two-step read —
``read_text().splitlines()`` then ``json.loads(line)`` — with no error handling,
so one malformed row in the middle of a multi-MB corpus killed the entire run.
``iter_jsonl`` streams line-by-line and logs+skips malformed lines instead.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path


def iter_jsonl(path: Path) -> Iterator[dict]:
    """Yield parsed JSONL rows from ``path``.

    Blank lines are skipped silently. Malformed lines are logged to stderr
    (with a ``path:lineno`` prefix) and skipped so a single bad row cannot
    abort a long-running pipeline stage.
    """
    with path.open(encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                print(
                    f"{path}:{line_num}: skipping malformed JSON ({exc.msg})",
                    file=sys.stderr,
                    flush=True,
                )
