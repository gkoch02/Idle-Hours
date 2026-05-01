"""Tests for ``runtime_webhook`` — the optional alert-firehose for telemetry events.

Pins five behaviours:

* The default filter posts errors / backoff / timeouts but skips heartbeats
  and successful renders (otherwise a healthy appliance fires alert spam).
* ``--webhook-all-events`` widens the filter but still skips heartbeats and
  ``render_ms`` entries.
* The POST runs on a daemon thread so a slow endpoint doesn't block the
  render path.
* A failing endpoint logs but never raises into the caller.
* Configure / get_config round-trip.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

import runtime_webhook


@pytest.fixture(autouse=True)
def _reset_webhook_config():
    """Each test runs against a clean global config — leaking config between
    tests is exactly the kind of cross-test pollution the autouse fixture
    prevents."""
    runtime_webhook.configure(None, all_events=False)
    yield
    runtime_webhook.configure(None, all_events=False)


def _wait_for_threads():
    """The webhook posts on a daemon thread; give them a moment to finish so
    assertions on patched mocks see the call."""
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        if threading.active_count() <= 2:  # main + pytest
            return
        time.sleep(0.02)


class TestConfigure:
    def test_configure_sets_url_and_all_events(self):
        runtime_webhook.configure("https://example.test/hook", all_events=True)
        url, all_events = runtime_webhook.get_config()
        assert url == "https://example.test/hook"
        assert all_events is True

    def test_configure_strips_whitespace(self):
        runtime_webhook.configure("  https://example.test/hook  ")
        url, _ = runtime_webhook.get_config()
        assert url == "https://example.test/hook"

    def test_configure_none_disables(self):
        runtime_webhook.configure("https://x.test/h", all_events=True)
        runtime_webhook.configure(None)
        url, all_events = runtime_webhook.get_config()
        assert url == ""
        assert all_events is False


class TestAlertFilter:
    def test_error_entry_alerts(self):
        assert runtime_webhook._is_alert({"error": "blew up", "mode": "debug"}, send_all=False)

    def test_backoff_entry_alerts(self):
        assert runtime_webhook._is_alert({"mode": "backoff", "failures": 6}, send_all=False)

    def test_render_timeout_alerts(self):
        assert runtime_webhook._is_alert({"mode": "render_timeout"}, send_all=False)

    def test_buttons_dead_alerts(self):
        assert runtime_webhook._is_alert({"mode": "buttons_dead"}, send_all=False)

    def test_successful_render_does_not_alert(self):
        assert not runtime_webhook._is_alert(
            {"render_ms": 120, "mode": "debug", "bucket": "h3_exact"}, send_all=False,
        )

    def test_heartbeat_does_not_alert(self):
        assert not runtime_webhook._is_alert({"type": "heartbeat"}, send_all=False)

    def test_heartbeat_does_not_alert_even_with_send_all(self):
        """``send_all`` widens the filter but heartbeats are always filtered
        — alerting once a minute is spam, not signal."""
        assert not runtime_webhook._is_alert({"type": "heartbeat"}, send_all=True)

    def test_render_ms_does_not_alert_even_with_send_all(self):
        """Successful renders bypass send_all for the same reason — alerting
        on every successful render would flood the firehose."""
        assert not runtime_webhook._is_alert(
            {"render_ms": 120, "mode": "production"}, send_all=True,
        )

    def test_action_filtered_by_default(self):
        """Operator actions (button presses / web POSTs) aren't alert-worthy;
        they're already in the telemetry log for forensics."""
        assert not runtime_webhook._is_alert(
            {"mode": "action", "action": "skip", "label": "button A"}, send_all=False,
        )

    def test_action_alerts_with_send_all(self):
        """``send_all`` does pull through actions for operators who want a
        full audit log via webhook."""
        assert runtime_webhook._is_alert(
            {"mode": "action", "action": "skip", "label": "button A"}, send_all=True,
        )


class TestPostEvent:
    def test_no_url_is_noop(self):
        """Empty URL must not spawn a thread or call urlopen."""
        with patch("runtime_webhook._post_blocking") as blocking:
            runtime_webhook.post_event(None, {"error": "x"})
        blocking.assert_not_called()

    def test_filtered_event_is_noop(self):
        """A successful render must not POST even when a URL is configured."""
        with patch("runtime_webhook._post_blocking") as blocking:
            runtime_webhook.post_event(
                "https://x.test/h", {"render_ms": 120, "mode": "debug"},
            )
        blocking.assert_not_called()

    def test_alert_event_posts(self):
        """A real error spawns a daemon thread that calls _post_blocking."""
        # Use an Event so we can wait deterministically for the spawned thread
        # rather than relying on a sleep-and-hope pattern.
        called = threading.Event()

        def fake_blocking(url, entry, timeout):
            called.set()

        with patch("runtime_webhook._post_blocking", side_effect=fake_blocking):
            runtime_webhook.post_event("https://x.test/h", {"error": "render failed"})
            assert called.wait(timeout=2), "_post_blocking was not called within timeout"

    def test_post_runs_on_daemon_thread(self):
        """The thread must be marked daemon so process exit tears it down
        without waiting on it. A non-daemon thread blocking on a slow webhook
        endpoint would otherwise hold up systemd shutdown indefinitely."""
        seen_daemon: list[bool] = []

        def fake_blocking(url, entry, timeout):
            seen_daemon.append(threading.current_thread().daemon)

        with patch("runtime_webhook._post_blocking", side_effect=fake_blocking):
            runtime_webhook.post_event("https://x.test/h", {"error": "x"})
            _wait_for_threads()
        assert seen_daemon == [True]

    def test_alert_modes_override(self):
        """Operators can pass an explicit alert_modes list to widen / narrow
        which modes pass the filter."""
        called = []

        def fake_blocking(url, entry, timeout):
            called.append(entry)

        # Custom alert_modes that ONLY listens for "skip" actions; a real
        # backoff entry should be filtered out.
        with patch("runtime_webhook._post_blocking", side_effect=fake_blocking):
            runtime_webhook.post_event(
                "https://x.test/h",
                {"mode": "backoff", "failures": 6},
                alert_modes=["skip"],
            )
            _wait_for_threads()
        assert called == []  # backoff did not match the operator's whitelist


class TestPostBlocking:
    def test_post_includes_json_body_and_headers(self):
        """The blocking call must produce a POST with a JSON body and the
        right Content-Type so the receiving endpoint can parse it."""
        captured = {}

        class FakeResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self, n=None): return b""

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["data"] = request.data
            captured["method"] = request.get_method()
            captured["content_type"] = request.headers.get("Content-type")
            captured["timeout"] = timeout
            return FakeResponse()

        with patch("runtime_webhook.urllib.request.urlopen", side_effect=fake_urlopen):
            runtime_webhook._post_blocking("https://x.test/h", {"error": "boom"}, 5.0)

        assert captured["url"] == "https://x.test/h"
        assert captured["method"] == "POST"
        assert captured["content_type"].startswith("application/json")
        assert b"boom" in captured["data"]
        assert captured["timeout"] == 5.0

    def test_endpoint_failure_is_logged_not_raised(self, capsys):
        """A network error or 5xx response must NOT propagate — webhooks are
        best-effort observability, not a render-critical path."""
        import urllib.error

        def fake_urlopen(request, timeout=None):
            raise urllib.error.URLError("connection refused")

        # Should not raise.
        with patch("runtime_webhook.urllib.request.urlopen", side_effect=fake_urlopen):
            runtime_webhook._post_blocking("https://x.test/h", {"error": "boom"}, 5.0)

        # Stderr should mention the failure so an operator can grep for it.
        err = capsys.readouterr().err
        assert "webhook:" in err

    def test_unserialisable_payload_is_logged_not_raised(self, capsys):
        """A payload with a non-JSON-serialisable field (object()) should
        log and drop, not raise. Payloads come from telemetry which
        nominally only contains primitives, but a defensive check costs
        nothing and protects against future schema drift."""
        runtime_webhook._post_blocking("https://x.test/h", {"obj": object()}, 5.0)
        err = capsys.readouterr().err
        assert "webhook" in err and "JSON" in err
