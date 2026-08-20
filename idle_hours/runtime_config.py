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
raises :class:`SystemExit` with :data:`EXIT_CONFIG_ERROR` (42) so a
misconfigured unit file fails fast in the journal instead of silently
booting with argparse defaults — and so systemd's
``RestartPreventExitStatus=42`` (see ``ops/idle-hours.service.example``)
stops ``Restart=always`` from flapping on a terminal configuration bug.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Callable

from idle_hours.runtime_log import _log

# Exit code for terminal configuration errors (typoed --config path,
# failed pre-flight path checks in run_clock). Paired with
# ``RestartPreventExitStatus=42`` in the sample systemd unit so a config
# bug halts the service instead of restart-flapping. Deliberately NOT
# used for pidfile contention (a racing restart should retry, exit 1)
# or argparse validation errors (argparse's own exit 2).
EXIT_CONFIG_ERROR = 42

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
    "auto_day_theme": str,
    "auto_night_theme": str,
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
    "webhook_url": str,
    "webhook_all_events": bool,
    # Corpus + curator-owned sidecar locations. Config-settable because the
    # whole point is relocating them off the read-only installed package and
    # onto the writable state dir under a `ProtectSystem=strict` unit, and the
    # systemd deployment configures everything through the config file.
    "overrides": str,
    "content_overrides": str,
    "raw_corpus": str,
    "baked_db": str,
}

# Flags that exist on the CLI but are intentionally refused in the config
# file: ``--config`` itself (loading its own path would be circular), and
# two transient shell-only knobs (``--once`` runs a single render then
# exits; ``--skip-preflight`` is an escape hatch for debugging). Listing
# them in a config file is almost always a mistake, so we warn-and-drop
# rather than silently honour them.
TRANSIENT_KEYS: frozenset[str] = frozenset({"config", "once", "skip_preflight"})


def validate_hhmm(value: str) -> str:
    """Return ``value`` unchanged if it is a valid ``HH:MM`` 24-hour time.

    Raises :class:`ValueError` otherwise. ``run_clock._valid_hhmm`` wraps this
    to re-raise as ``argparse.ArgumentTypeError`` for ``type=`` use; keeping
    the rule itself here means :func:`load_config` can validate ``quiet_start``
    / ``quiet_end`` without an injected callback, so callers that only want one
    key out of a config file (``idle-hours health --config``) don't have to
    either import the orchestrator or restate the rule.
    """
    parts = value.split(":")
    try:
        hour, minute = int(parts[0]), int(parts[1])
        if not (len(parts) == 2 and 0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, IndexError):
        raise ValueError(f"{value!r} is not a valid HH:MM time (expected 00:00–23:59)") from None
    return value


def _warn(msg: str) -> None:
    _log(f"config: {msg}", err=True)


def load_config(
    path: Path | None,
    *,
    hhmm_validator: Callable[[str], str] | None = None,
    choices_map: dict[str, list[str]] | None = None,
) -> dict[str, object]:
    """Load ``path`` and return a mapping of argparse dest → value.

    ``path`` of ``None`` returns ``{}`` (no-op, keeps argparse defaults).

    ``path`` pointing at a non-existent file is treated as a hard error
    (``SystemExit`` with :data:`EXIT_CONFIG_ERROR`) rather than silently
    falling back: the user
    passed ``--config FOO``, so a missing FOO is a typo they want to
    hear about loudly at startup, not an implicit "run with defaults"
    signal.

    Malformed TOML, unreadable file contents, a non-table root, unknown
    keys, and type mismatches all log a stderr warning and are skipped.
    The loader never raises on a file it *could* read; the stream of
    warnings plus the surviving good keys is the contract.

    ``hhmm_validator`` is injected by ``run_clock`` so its argparse
    ``type=`` callable and the config path report identical errors. When
    omitted, :func:`validate_hhmm` is used instead, so a caller that only
    wants one key out of a config file (``idle-hours health --config``) need
    not import the orchestrator. Note the injection direction is load-bearing:
    this module must never import ``run_clock``, or the runtime modules'
    acyclic import graph breaks — which is why the rule itself lives here and
    ``run_clock._valid_hhmm`` wraps it, rather than the reverse.

    ``choices_map`` mirrors argparse's own ``choices=`` gate for the
    subset of keys that declare one (``mode``, ``theme``, …). Without
    this, a typoed ``mode = "produciton"`` would flow through
    ``set_defaults`` unchecked and surface only when the render
    subprocess's own parser rejected it hours later. Built by
    ``run_clock.parse_args`` from the live parser's actions so the
    source of truth stays single-seated.
    """
    if path is None:
        return {}
    if not path.exists():
        _log(f"config: --config {path!s} does not exist", err=True)
        raise SystemExit(EXIT_CONFIG_ERROR)
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
        if choices_map is not None and key in choices_map:
            allowed = choices_map[key]
            if value not in allowed:
                _warn(
                    f"{path}: {key!r}={value!r} not in allowed choices "
                    f"{allowed}; dropped"
                )
                continue
        if kind == "hhmm":
            try:
                resolved[key] = (hhmm_validator or validate_hhmm)(value)
            except Exception as exc:
                _warn(f"{path}: {key!r}={value!r} rejected ({exc}); dropped")
                continue
        else:
            resolved[key] = value
    return resolved
