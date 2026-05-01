"""Webhook notifier for telemetry events.

Posts a subset of ``runtime_telemetry`` events to an operator-configured
HTTP endpoint so a fleet operator can wire LitClock into their existing
alerting (Slack, Discord, n8n, plain HTTP listener — we don't care).

Why a webhook and not a push-notification SDK: the appliance is a
single-operator home device; the operator is already running their own
plumbing for everything else (HomeAssistant, ntfy, etc.). A plain
``POST <url>`` with a JSON body is the minimum viable surface that
plumbs into any of those without binding LitClock to a specific
provider's SDK.

**Fire-and-forget on a daemon thread.** The webhook MUST NOT block the
render path: a hanging POST against an unreachable endpoint would
otherwise pause the main loop on every error tick. We dispatch each
post on a fresh ``threading.Thread(daemon=True)`` so the loop returns
immediately. Process exit tears the thread down without waiting (worst
case: one in-flight POST is dropped — acceptable for "alert me when
things break"). A bounded ``urllib.request.urlopen`` timeout guards
against the thread itself wedging forever and pinning resources.

**Filtered event subset.** We don't post heartbeats — the whole point is
"alert me when something interesting happens", and a 60s heartbeat
firehose would defeat that. The default filter is ``ALERT_MODES``
(errors, backoff, timeouts, button-died, state-validation issues);
operators who want everything can pass ``--webhook-all-events`` or set
the env-var version.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Iterable

from runtime_log import _log

# Telemetry ``mode`` values that surface real operational concerns. Heartbeats
# and routine renders are excluded — a webhook firing every 60s is alert spam.
# ``action`` and ``press_dropped`` are user-driven and don't need to wake an
# operator at 3am.
ALERT_MODES: frozenset[str] = frozenset({
    "backoff",
    "render_timeout",
    "display_timeout",
    "shutdown_timeout",
    "buttons_dead",
    "state_validation",
    "web_auth_fail",
    "web_error",
})

# Bounded so a wedged endpoint can't pin the worker thread forever. Five
# seconds is generous for a JSON POST and tight enough that an unreachable
# host doesn't accumulate stuck threads on a fault-storm appliance.
_DEFAULT_TIMEOUT_SECONDS = 5.0

# Module-level config set once at ``run_clock.main`` startup. Read by
# :func:`append_telemetry` (in ``runtime_telemetry``) without plumbing the
# webhook flags through every call site. The pattern matches ``logging``'s
# basicConfig: a global "set once at startup, read everywhere" knob is
# acceptable when reconfiguration is rare and there's no test that needs
# to interleave multiple configs (each test sets, runs, resets).
_CONFIG: dict[str, object] = {"url": "", "all_events": False}


def configure(url: str | None, *, all_events: bool = False) -> None:
    """Set the global webhook destination. Call once from ``main()`` startup.

    An empty / ``None`` URL disables webhook fan-out without touching the
    rest of the telemetry path. ``all_events`` widens the alert filter from
    "operationally interesting modes" to "everything except heartbeats and
    successful renders." Tests that exercise the webhook reset the config
    after themselves to avoid polluting sibling tests.
    """
    _CONFIG["url"] = (url or "").strip()
    _CONFIG["all_events"] = bool(all_events)


def get_config() -> tuple[str, bool]:
    """Return ``(url, all_events)`` from the module-level config.

    Used by :func:`runtime_telemetry.append_telemetry` to decide whether
    to fan out a given entry to the webhook. A separate accessor (rather
    than direct dict reads) so a future implementation could swap to
    thread-local config without changing call sites.
    """
    return str(_CONFIG.get("url", "")), bool(_CONFIG.get("all_events", False))


def _is_alert(entry: dict, *, send_all: bool) -> bool:
    """Decide whether ``entry`` is interesting enough for a webhook POST.

    Render entries are positively identified by a numeric ``render_ms``
    (matches ``litclock_health.summarise``'s rule) — we never alert on a
    successful render even when ``send_all`` is set, because that would
    mean one POST per minute on a healthy appliance. Errors (presence of
    ``error`` key) always alert. Otherwise we consult the mode whitelist.
    """
    if "render_ms" in entry and isinstance(entry.get("render_ms"), int):
        return False
    if entry.get("type") == "heartbeat":
        return False
    if "error" in entry:
        return True
    if send_all:
        return True
    return entry.get("mode") in ALERT_MODES


def post_event(
    webhook_url: str | None,
    entry: dict,
    *,
    send_all: bool = False,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    alert_modes: Iterable[str] | None = None,
) -> None:
    """Maybe POST ``entry`` to ``webhook_url`` on a background thread.

    No-op when ``webhook_url`` is empty/None or ``entry`` doesn't pass the
    filter. The actual network call runs on a daemon thread so the caller
    (typically inside the render hot path) returns immediately. Failures
    are logged but never re-raised — webhooks are best-effort observability,
    not a render-critical path.

    ``send_all`` widens the filter to "everything except heartbeats and
    successful renders." ``alert_modes`` overrides the default whitelist
    entirely (passing ``[]`` with ``send_all=False`` effectively disables
    notifications without un-setting the URL).
    """
    if not webhook_url:
        return
    if alert_modes is not None:
        modes = frozenset(alert_modes)
        is_alert = (
            "error" in entry
            or (send_all and entry.get("type") != "heartbeat" and "render_ms" not in entry)
            or entry.get("mode") in modes
        )
        if not is_alert:
            return
    elif not _is_alert(entry, send_all=send_all):
        return
    thread = threading.Thread(
        target=_post_blocking,
        args=(webhook_url, entry, timeout_seconds),
        name="litclock-webhook",
        daemon=True,
    )
    thread.start()


def _post_blocking(webhook_url: str, entry: dict, timeout_seconds: float) -> None:
    """Send a single POST. Runs on a daemon worker thread."""
    try:
        body = json.dumps(entry, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _log(f"webhook: payload not JSON-serialisable, dropping: {exc!r}", err=True)
        return
    request = urllib.request.Request(
        webhook_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "LitClock/2.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            # Drain the body so the connection can be released cleanly. We
            # don't act on the status code — a 200/202/204 is success and a
            # 4xx/5xx is logged but doesn't trigger a retry; this is alert
            # plumbing, not a guaranteed-delivery queue.
            response.read(1024)
            if response.status >= 400:
                _log(
                    f"webhook: {webhook_url!r} returned HTTP {response.status}; entry dropped",
                    err=True,
                )
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        # urllib raises URLError for DNS / connection refused / timeout, OSError
        # for socket-level issues. We collapse all of them into one log line —
        # operator can grep "webhook:" to see endpoint health.
        _log(f"webhook: POST to {webhook_url!r} failed: {exc!r}", err=True)
