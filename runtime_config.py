"""TOML config-file loader for ``run_clock.py``.

Sibling of the argparse definition in :mod:`run_clock`. The entry point
:func:`load_config` returns a dict keyed by argparse ``dest`` names
(snake_case, matching ``args.display_script`` etc.), which ``run_clock``
feeds into :meth:`argparse.ArgumentParser.set_defaults` before parsing
the real CLI. argparse's own rule — "the default is used only when the
flag is absent from argv" — then delivers the three-layer precedence
the feature was designed for: **CLI flag > config file > argparse
default**.

Loading is fail-open on a malformed or unreadable file, mirroring the
durability pattern :func:`apply_content_overrides.load_overrides` uses
for its sidecar. A typoed ``--config`` path is the one exception: that
raises :class:`SystemExit` so a misconfigured unit file fails fast in
the journal instead of silently booting with argparse defaults.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Callable

from runtime_log import _log

# Every key understood by the config file. The value is either a Python
# type (``int`` / ``str`` / ``bool``) or a two-tuple ``(type, validator)``
# where ``validator`` is called with the already type-checked value and
# returns the coerced value, raising ``ValueError`` on rejection.
#
# Mirrors the argparse ``dest`` surface of :func:`run_clock.parse_args`
# verbatim, minus the three transient shell-only flags excluded below.
# The test ``tests/test_runtime_config.py::TestSchemaSync`` cross-checks
# this table against the live parser so a new argparse flag that wants
# to be config-settable cannot be silently forgotten here.
CONFIG_SCHEMA: dict[str, object] = {
    "render_script": str,
    "output": str,
    "interval_seconds": int,
    "width": int,
    "height": int,
    "display_script": str,
    "mode": str,
    "theme": str,
    "buttons_off": bool,
    "shutdown_command": str,
    "startup_image": str,
    "state_path": str,
    "telemetry_path": str,
    "telemetry_retain_days": int,
    "quiet_start": (str, "hhmm"),
    "quiet_end": (str, "hhmm"),
    "quiet_image": str,
    "quiet_off": bool,
    "history_path": str,
    "history_days": int,
    "web_bind": str,
    "web_token": str,
    "web_token_file": str,
    "pidfile": str,
}

# Flags that exist on the CLI but are intentionally refused in the config
# file: ``--config`` itself (loading its own path would be circular), and
# two transient shell-only knobs (``--once`` runs a single render then
# exits; ``--skip-preflight`` is an escape hatch for debugging). Listing
# them in a config file is almost always a mistake, so we warn-and-drop
# rather than silently honour them.
TRANSIENT_KEYS: frozenset[str] = frozenset({"config", "once", "skip_preflight"})


def _warn(msg: str) -> None:
    _log(f"config: {msg}", err=True)


def load_config(
    path: Path | None,
    *,
    hhmm_validator: Callable[[str], str] | None = None,
) -> dict[str, object]:
    """Load ``path`` and return a mapping of argparse dest → value.

    ``path`` of ``None`` returns ``{}`` (no-op, keeps argparse defaults).

    ``path`` pointing at a non-existent file is treated as a hard error
    (``SystemExit(1)``) rather than silently falling back: the user
    passed ``--config FOO``, so a missing FOO is a typo they want to
    hear about loudly at startup, not an implicit "run with defaults"
    signal.

    Malformed TOML, unreadable file contents, a non-table root, unknown
    keys, and type mismatches all log a stderr warning and are skipped.
    The loader never raises on a file it *could* read; the stream of
    warnings plus the surviving good keys is the contract.

    ``hhmm_validator`` is injected by ``run_clock`` so this module does
    not import back into the orchestrator at load time (keeps the
    runtime-module acyclic import graph intact — same pattern
    ``runtime_actions`` uses).
    """
    if path is None:
        return {}
    if not path.exists():
        _log(f"config: --config {path!s} does not exist", err=True)
        raise SystemExit(1)
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        _warn(f"{path}: unreadable ({exc!r}); using argparse defaults")
        return {}
    try:
        raw = tomllib.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        _warn(f"{path}: not valid TOML ({exc}); using argparse defaults")
        return {}
    if not isinstance(raw, dict):
        _warn(f"{path}: root must be a TOML table; using argparse defaults")
        return {}

    resolved: dict[str, object] = {}
    for key, value in raw.items():
        if key in TRANSIENT_KEYS:
            _warn(
                f"{path}: {key!r} is a transient CLI flag and cannot be set in a "
                f"config file; dropped"
            )
            continue
        spec = CONFIG_SCHEMA.get(key)
        if spec is None:
            _warn(f"{path}: unknown key {key!r}; dropped")
            continue
        if isinstance(spec, tuple):
            expected_type, kind = spec
        else:
            expected_type, kind = spec, None
        # ``bool`` is a subclass of ``int`` in Python — guard against a
        # TOML ``true`` sneaking into an ``int`` slot like
        # ``interval_seconds``.
        if expected_type is int and isinstance(value, bool):
            _warn(
                f"{path}: {key!r} expected int, got bool; dropped"
            )
            continue
        if not isinstance(value, expected_type):
            _warn(
                f"{path}: {key!r} expected {expected_type.__name__}, "
                f"got {type(value).__name__}; dropped"
            )
            continue
        if kind == "hhmm":
            if hhmm_validator is None:
                # Defensive; should not happen because ``run_clock``
                # always injects one. If it does, keep the string as-is
                # and let downstream handling catch a bad value.
                resolved[key] = value
                continue
            try:
                resolved[key] = hhmm_validator(value)
            except Exception as exc:
                _warn(f"{path}: {key!r}={value!r} rejected ({exc}); dropped")
                continue
        else:
            resolved[key] = value
    return resolved
