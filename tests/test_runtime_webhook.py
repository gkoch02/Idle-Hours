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
    prevents.

    Also resets the in-flight semaphore: a test that exercises the
    concurrency cap might leave permits acquired if a thread leak occurs;
    re-creating the semaphore between tests guarantees a known starting
    state regardless of leftovers.
    """
    runtime_webhook.configure(None, all_events=False)
    runtime_webhook._inflight_semaphore = threading.BoundedSemaphore(
        runtime_webhook._WEBHOOK_MAX_INFLIGHT,
    )
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


class TestUrlSchemeValidation:
    """``configure`` rejects URL schemes other than http/https.

    Without this guard, an operator typo (``--webhook-url file:///tmp/x``)
    would be accepted at startup and silently fail per-event in the log;
    worse, ``urllib.urlopen`` is happy to read/write to those schemes.
    """

    def test_http_url_accepted(self):
        runtime_webhook.configure("http://example.test/hook")
        url, _ = runtime_webhook.get_config()
        assert url == "http://example.test/hook"

    def test_https_url_accepted(self):
        runtime_webhook.configure("https://example.test/hook")
        url, _ = runtime_webhook.get_config()
        assert url == "https://example.test/hook"

    def test_file_url_rejected(self, capsys):
        runtime_webhook.configure("file:///tmp/x")
        url, _ = runtime_webhook.get_config()
        assert url == ""
        assert "refusing URL scheme" in capsys.readouterr().err

    def test_ftp_url_rejected(self, capsys):
        runtime_webhook.configure("ftp://example.test/hook")
        url, _ = runtime_webhook.get_config()
        assert url == ""
        assert "refusing URL scheme" in capsys.readouterr().err

    def test_data_url_rejected(self, capsys):
        runtime_webhook.configure("data:text/plain,hello")
        url, _ = runtime_webhook.get_config()
        assert url == ""
        assert "refusing URL scheme" in capsys.readouterr().err

    def test_url_without_host_rejected(self, capsys):
        """``http:///path`` parses as a valid scheme but no netloc — would
        crash on send. Caught at configure time."""
        runtime_webhook.configure("http:///no-host")
        url, _ = runtime_webhook.get_config()
        assert url == ""
        assert "no host" in capsys.readouterr().err

    def test_empty_url_disables_silently(self, capsys):
        """Empty / None is the documented "disabled" sentinel — no warning."""
        runtime_webhook.configure(None)
        runtime_webhook.configure("")
        runtime_webhook.configure("   ")
        assert capsys.readouterr().err == ""


class TestConcurrencyCap:
    """A fault storm must not pile up unbounded daemon threads."""

    def test_drops_event_when_at_cap(self, capsys):
        """When :data:`_WEBHOOK_MAX_INFLIGHT` permits are held, additional
        events drop with a log line instead of spawning fresh threads."""
        # Acquire every permit so the next post_event finds the semaphore empty.
        for _ in range(runtime_webhook._WEBHOOK_MAX_INFLIGHT):
            assert runtime_webhook._inflight_semaphore.acquire(blocking=False)
        try:
            with patch("runtime_webhook._post_blocking") as blocking:
                runtime_webhook.post_event(
                    "https://x.test/h", {"error": "storm"},
                )
            blocking.assert_not_called()
            assert "concurrency cap" in capsys.readouterr().err
        finally:
            # Release the permits we acquired so the autouse fixture's
            # re-creation doesn't race anything.
            for _ in range(runtime_webhook._WEBHOOK_MAX_INFLIGHT):
                runtime_webhook._inflight_semaphore.release()

    def test_releases_permit_after_post(self):
        """After a post completes (success or failure), the permit goes back.
        Otherwise a few errors would permanently exhaust the cap."""
        completed = threading.Event()

        def fake_blocking(url, entry, timeout):
            completed.set()

        with patch("runtime_webhook._post_blocking", side_effect=fake_blocking):
            runtime_webhook.post_event("https://x.test/h", {"error": "x"})
            assert completed.wait(timeout=2)
        # Wait for the wrapper's finally to run — give the thread a moment
        # to release after _post_blocking returns.
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if runtime_webhook._inflight_semaphore.acquire(blocking=False):
                runtime_webhook._inflight_semaphore.release()
                return
            time.sleep(0.01)
        pytest.fail("permit was never released back to the semaphore")

    def test_releases_permit_when_post_raises(self):
        """If _post_blocking somehow raises through the try/except, the
        permit must still be returned (defensive — _post_blocking already
        swallows everything internally, but the wrapper's finally is the
        safety net)."""
        with patch("runtime_webhook._post_blocking", side_effect=RuntimeError("boom")):
            runtime_webhook.post_event("https://x.test/h", {"error": "x"})
        # Permit eventually returned.
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if runtime_webhook._inflight_semaphore.acquire(blocking=False):
                runtime_webhook._inflight_semaphore.release()
                return
            time.sleep(0.01)
        pytest.fail("permit leaked on exception")


class TestRenderEntryFloatHandling:
    """``_is_render_entry`` must accept both int and float render_ms but
    NOT bool, regardless of whether bool is technically a subclass of int."""

    def test_int_render_ms_treated_as_render(self):
        assert runtime_webhook._is_render_entry({"render_ms": 120})

    def test_float_render_ms_treated_as_render(self):
        """Future-proof: a perf-sensitive timer that returns floats must
        not start spamming the webhook."""
        assert runtime_webhook._is_render_entry({"render_ms": 119.5})

    def test_bool_render_ms_not_treated_as_render(self):
        """isinstance(True, int) is True in Python; the explicit bool
        guard means a bogus render_ms=True doesn't masquerade as success
        and accidentally suppress a real alert."""
        assert not runtime_webhook._is_render_entry({"render_ms": True})

    def test_missing_render_ms(self):
        assert not runtime_webhook._is_render_entry({})

    def test_none_render_ms(self):
        assert not runtime_webhook._is_render_entry({"render_ms": None})

    def test_alert_filter_skips_float_render(self):
        """Integration: float render_ms passes through _is_alert as
        a non-alert, both default and send_all paths."""
        entry = {"render_ms": 119.5, "mode": "debug"}
        assert not runtime_webhook._is_alert(entry, send_all=False)
        assert not runtime_webhook._is_alert(entry, send_all=True)
