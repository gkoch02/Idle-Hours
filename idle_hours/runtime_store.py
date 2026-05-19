"""Persistent runtime-state store (manual theme / manual quiet) with atomic writes.

Loads ``~/.idle-hours/state.json`` at loop startup so the user's last button-B /
button-D choices survive a restart, and writes atomically (tmp-sibling →
``fsync`` → ``os.replace`` → dir-``fsync`` via :mod:`atomic_io`) so a crash
mid-write never leaves the file truncated. Extracted from :mod:`run_clock`;
the original names are re-exported from ``run_clock`` for backwards compat.
"""
from __future__ import annotations

import json
from pathlib import Path

from idle_hours import atomic_io
from idle_hours.runtime_log import _log

DEFAULT_STATE_PATH = "~/.idle-hours/state.json"

# Known top-level keys on ``state.json`` and the accepted runtime shape
# for each. Extra keys are flagged but tolerated (forward-compat for a
# future field that an older build hasn't learned yet); wrong-type values
# on a known key are reported and dropped so a hand-edited file can't
# poison ``RuntimeState`` with e.g. ``manual_theme=42``.
_STATE_SCHEMA: dict[str, tuple[type, ...] | tuple] = {
    "manual_theme": (str, type(None)),
    "manual_quiet": (bool,),
    "last_bucket": (str, type(None)),
    "last_quote_id": (list, type(None)),
    "last_effective_theme": (str, type(None)),
    # First-run setup wizard. ``True`` once an operator has dismissed the
    # wizard from the curator UI; absent / ``False`` triggers the wizard
    # overlay on next visit. Plain bool so tests / hand-edits can flip it
    # back to ``False`` to re-trigger the wizard.
    "setup_complete": (bool,),
}


def _resolve_state_path(state_path: str | None) -> Path | None:
    if not state_path:
        return None
    return Path(state_path).expanduser()


def _validate_state_payload(path: Path, parsed: dict, telemetry_path: str | None = None) -> dict:
    """Sanity-check ``parsed`` against :data:`_STATE_SCHEMA`.

    Unknown top-level keys are logged (warn) but preserved so a newer
    schema version can roundtrip through an older install. Known keys
    with wrong-type values are stripped — ``RuntimeState.__init__`` treats
    a missing key as "use the default", which is safer than letting a
    bogus value propagate (``manual_theme=42`` would survive an ``in``
    check and silently pin the panel to an invalid theme).

    Malformed fields are telemetrised as ``mode="state_validation"`` when
    a telemetry path is supplied so operators can see the drift in
    ``idle_hours_health.py`` rather than having to tail stderr.
    """
    cleaned: dict = {}
    issues: list[str] = []
    for key, value in parsed.items():
        expected = _STATE_SCHEMA.get(key)
        if expected is None:
            issues.append(f"unknown key {key!r}")
            cleaned[key] = value
            continue
        if not isinstance(value, expected):
            issues.append(f"{key!r} has wrong type {type(value).__name__}")
            continue
        cleaned[key] = value
    if issues:
        details = "; ".join(issues)
        _log(
            f"runtime state at {path} has validation issues ({details}); "
            f"malformed fields dropped",
            err=True,
        )
        if telemetry_path:
            # Lazy import to avoid a cycle: runtime_telemetry imports
            # runtime_log which... doesn't import us back, but the
            # indirection keeps the module-load graph minimal.
            try:
                from idle_hours import runtime_telemetry
                runtime_telemetry.append_telemetry(
                    telemetry_path,
                    {"mode": "state_validation", "path": str(path), "issues": issues},
                )
            except Exception:
                pass
    return cleaned


def load_runtime_state(state_path: str | None, telemetry_path: str | None = None) -> dict:
    """Load persisted runtime state. Returns ``{}`` when disabled, missing, or malformed.

    We expect the file to contain a JSON object. Anything else (a bare string,
    number, list, or parse error) is treated as unreadable and ignored rather
    than bricking startup with ``AttributeError`` when ``RuntimeState.__init__``
    later calls ``.get()`` on it.

    When ``telemetry_path`` is supplied, malformed-but-parseable entries are
    logged AND recorded to the telemetry sidecar (``mode="state_validation"``)
    so silent drift (a hand-edit with ``manual_theme=42`` or a botched migration)
    surfaces in ``idle_hours_health.py`` output.
    """
    path = _resolve_state_path(state_path)
    if path is None or not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log(f"runtime state at {path} unreadable, ignoring: {exc!r}", err=True)
        if telemetry_path:
            try:
                from idle_hours import runtime_telemetry
                runtime_telemetry.append_telemetry(
                    telemetry_path,
                    {"mode": "state_validation", "path": str(path), "error": repr(exc)},
                )
            except Exception:
                pass
        return {}
    if not isinstance(parsed, dict):
        _log(f"runtime state at {path} is not a JSON object ({type(parsed).__name__}), ignoring", err=True)
        if telemetry_path:
            try:
                from idle_hours import runtime_telemetry
                runtime_telemetry.append_telemetry(
                    telemetry_path,
                    {
                        "mode": "state_validation",
                        "path": str(path),
                        "error": f"not-a-dict:{type(parsed).__name__}",
                    },
                )
            except Exception:
                pass
        return {}
    return _validate_state_payload(path, parsed, telemetry_path=telemetry_path)


def save_runtime_state(state_path: str | None, state: dict) -> None:
    """Persist runtime state atomically. No-op when disabled."""
    path = _resolve_state_path(state_path)
    if path is None:
        return
    atomic_io.atomic_write_text(path, json.dumps(state, ensure_ascii=False, indent=2))
