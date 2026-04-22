"""Persistent runtime-state store (manual theme / manual quiet) with atomic writes.

Loads ``~/.litclock/state.json`` at loop startup so the user's last button-B /
button-D choices survive a restart, and writes atomically (tmp-sibling →
``fsync`` → ``os.replace`` → dir-``fsync`` via :mod:`atomic_io`) so a crash
mid-write never leaves the file truncated. Extracted from :mod:`run_clock`;
the original names are re-exported from ``run_clock`` for backwards compat.
"""
from __future__ import annotations

import json
from pathlib import Path

import atomic_io
from runtime_log import _log

DEFAULT_STATE_PATH = "~/.litclock/state.json"


def _resolve_state_path(state_path: str | None) -> Path | None:
    if not state_path:
        return None
    return Path(state_path).expanduser()


def load_runtime_state(state_path: str | None) -> dict:
    """Load persisted runtime state. Returns ``{}`` when disabled, missing, or malformed.

    We expect the file to contain a JSON object. Anything else (a bare string,
    number, list, or parse error) is treated as unreadable and ignored rather
    than bricking startup with ``AttributeError`` when ``RuntimeState.__init__``
    later calls ``.get()`` on it.
    """
    path = _resolve_state_path(state_path)
    if path is None or not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log(f"runtime state at {path} unreadable, ignoring: {exc!r}", err=True)
        return {}
    if not isinstance(parsed, dict):
        _log(f"runtime state at {path} is not a JSON object ({type(parsed).__name__}), ignoring", err=True)
        return {}
    return parsed


def save_runtime_state(state_path: str | None, state: dict) -> None:
    """Persist runtime state atomically. No-op when disabled."""
    path = _resolve_state_path(state_path)
    if path is None:
        return
    atomic_io.atomic_write_text(path, json.dumps(state, ensure_ascii=False, indent=2))
