"""Minimal ``sd_notify`` client for systemd ``Type=notify`` integration.

systemd's notify protocol is a datagram-to-``$NOTIFY_SOCKET`` conversation with
tiny ASCII payloads (``READY=1``, ``WATCHDOG=1``, etc.). We speak it via stdlib
``socket.AF_UNIX`` rather than pulling in the ``systemd-python`` package so
``run_clock`` has no new runtime deps — the Pi image only needs ``Pillow`` and
the Pimoroni Inky stack.

Semantics:

- ``notify(...)`` is a no-op when ``$NOTIFY_SOCKET`` is not set in the
  environment (dev hosts, unit tests, ``--once`` runs outside systemd). It
  returns ``True`` if the datagram was sent, ``False`` otherwise, so callers
  can telemetrise socket failures if they care; ``run_clock`` doesn't.
- Socket failures (missing socket file, permission denied, buffer full) are
  swallowed and logged once via ``runtime_log._log`` — the loop's primary job
  is still rendering to the panel, and a dead supervisor link must never kill
  the clock. systemd's ``WatchdogSec`` will catch the silence regardless.
- Abstract-namespace sockets (``@...``) and filesystem-path sockets are both
  supported; systemd picks the kind based on the first byte.

See sd_notify(3) for the full protocol. We only implement the two verbs phase 3
of the appliance-hardening track actually needs: ``READY=1`` at startup and
``WATCHDOG=1`` from the heartbeat.
"""
from __future__ import annotations

import os
import socket

from idle_hours.runtime_log import _log

_NOTIFY_SOCKET_ENV = "NOTIFY_SOCKET"
_warned_once = False


def _send(payload: bytes) -> bool:
    """Send ``payload`` to ``$NOTIFY_SOCKET`` as a single datagram.

    Returns True on successful send, False otherwise (including "socket not
    set" — the common dev-host case). A one-shot stderr warning is emitted
    the first time a send fails while the env var *is* set, so operators
    can tell "sandboxing stripped the socket" apart from "just no systemd."
    """
    global _warned_once
    address = os.environ.get(_NOTIFY_SOCKET_ENV)
    if not address:
        return False
    # systemd uses a leading NUL to flag abstract-namespace sockets.
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload, address)
        return True
    except OSError as exc:
        if not _warned_once:
            _warned_once = True
            _log(
                f"sd_notify send to {_NOTIFY_SOCKET_ENV}={address!r} failed: {exc!r}; "
                "further failures will be suppressed",
                err=True,
            )
        return False


def notify(state: str) -> bool:
    """Send a single sd_notify state line, e.g. ``"READY=1"`` or ``"WATCHDOG=1"``.

    Multi-line payloads (e.g. ``"READY=1\\nSTATUS=..."``) are allowed by the
    protocol; this helper passes ``state`` through verbatim.
    """
    if not state:
        return False
    return _send(state.encode("utf-8"))


def notify_ready() -> bool:
    """Tell systemd the service is fully started (``Type=notify`` gate lifts)."""
    return notify("READY=1")


def notify_watchdog() -> bool:
    """Pet systemd's ``WatchdogSec`` timer. No-op when not supervised."""
    return notify("WATCHDOG=1")


def reset_warning_state_for_tests() -> None:
    """Clear the ``_warned_once`` latch. Test-only seam."""
    global _warned_once
    _warned_once = False
