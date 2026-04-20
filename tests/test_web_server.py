"""Tests for the curator web UI (``web_server.py``).

Every test binds an ephemeral-port ``_LitClockHTTPServer`` on 127.0.0.1, drives
it via ``http.client`` in the same process, and tears it down in teardown.
Real GPIO, real Inky hardware, and real subprocesses are never touched — the
rendering action endpoints stub ``run_clock._render_unlocked`` and the picker.
"""
from __future__ import annotations

import argparse
import http.client
import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

import pick_quote
import run_clock
import web_server


def _make_args(tmp_path: Path, **overrides) -> argparse.Namespace:
    """Build a plausible argparse.Namespace for run_clock/web_server wiring."""
    defaults = dict(
        render_script="render_quote.py",
        output=str(tmp_path / "current.png"),
        once=False,
        interval_seconds=60,
        width=800,
        height=480,
        display_script=None,
        mode="debug",
        theme="default",
        buttons_off=True,
        shutdown_command="",
        startup_image=None,
        state_path=str(tmp_path / "state.json"),
        telemetry_path=str(tmp_path / "telemetry.jsonl"),
        quiet_start="22:00",
        quiet_end="06:00",
        quiet_image="assets/goodnight.png",
        quiet_off=True,
        history_path=str(tmp_path / "history.jsonl"),
        history_days=7,
        web_bind="127.0.0.1:0",
        web_token="",
        web_token_file="",
        overrides=str(tmp_path / "selection_overrides.json"),
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _start(tmp_path: Path, *, token: str = "", args: argparse.Namespace | None = None,
           state: run_clock.RuntimeState | None = None):
    """Spin up a ``_LitClockHTTPServer`` on an ephemeral port and return (server, state, args)."""
    args = args or _make_args(tmp_path)
    state = state or run_clock.RuntimeState(args.theme)
    server, thread = web_server.start_web_server(args, state, token=token)
    return server, thread, state, args


def _client(server) -> http.client.HTTPConnection:
    host, port = server.server_address[:2]
    return http.client.HTTPConnection(host, port, timeout=3)


def _get(server, path: str, headers: dict | None = None):
    conn = _client(server)
    conn.request("GET", path, headers=headers or {})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


def _post(server, path: str, payload: dict | None = None, headers: dict | None = None):
    conn = _client(server)
    data = b""
    h = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
        h["Content-Length"] = str(len(data))
    else:
        h.setdefault("Content-Length", "0")
    conn.request("POST", path, body=data, headers=h)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


def _json_body(body: bytes) -> dict:
    return json.loads(body.decode("utf-8"))


@pytest.fixture
def live_server(tmp_path):
    server, thread, state, args = _start(tmp_path)
    yield server, state, args
    run_clock.stop_web_server((server, thread))


# ============================================================================
# Lifecycle
# ============================================================================

class TestWebServerLifecycle:
    def test_server_starts_and_stops_on_ephemeral_port(self, tmp_path):
        server, thread, _state, _args = _start(tmp_path)
        try:
            host, port = server.server_address[:2]
            assert host == "127.0.0.1"
            assert port > 0
            assert thread.is_alive()
            status, _ = _get(server, "/api/current")
            assert status == 200
        finally:
            run_clock.stop_web_server((server, thread))
        assert not thread.is_alive()

    def test_parse_bind_accepts_host_port(self):
        assert web_server._parse_bind("127.0.0.1:8080") == ("127.0.0.1", 8080)
        assert web_server._parse_bind(":8080") == ("127.0.0.1", 8080)
        assert web_server._parse_bind("0.0.0.0:9090") == ("0.0.0.0", 9090)

    def test_parse_bind_rejects_garbage(self):
        with pytest.raises(ValueError):
            web_server._parse_bind("not-a-bind")
        with pytest.raises(ValueError):
            web_server._parse_bind("host:notaport")

    def test_non_localhost_bind_without_token_refused(self, tmp_path):
        args = _make_args(tmp_path, web_bind="0.0.0.0:0")
        state = run_clock.RuntimeState(args.theme)
        with pytest.raises(ValueError, match="no --web-token"):
            web_server.start_web_server(args, state, token="")

    def test_non_localhost_bind_with_token_allowed(self, tmp_path):
        args = _make_args(tmp_path, web_bind="0.0.0.0:0")
        state = run_clock.RuntimeState(args.theme)
        server, thread = web_server.start_web_server(args, state, token="secret")
        try:
            assert thread.is_alive()
        finally:
            run_clock.stop_web_server((server, thread))

    def test_stop_web_server_none_is_noop(self):
        run_clock.stop_web_server(None)

    def test_unknown_route_returns_404(self, live_server):
        server, _state, _args = live_server
        status, body = _get(server, "/nope")
        assert status == 404
        assert _json_body(body)["error"] == "not found"


# ============================================================================
# GET endpoints
# ============================================================================

class TestReadEndpoints:
    def test_root_serves_index_html(self, live_server):
        server, _, _ = live_server
        status, body = _get(server, "/")
        assert status == 200
        assert b"<html" in body.lower() or b"<!doctype" in body.lower()
        assert b"LitClock" in body

    def test_static_js_and_css(self, live_server):
        server, _, _ = live_server
        js_status, js_body = _get(server, "/main.js")
        css_status, _ = _get(server, "/style.css")
        assert js_status == 200
        assert css_status == 200
        assert b"jsonFetch" in js_body

    def test_current_png_streams_file(self, tmp_path, live_server):
        server, _, args = live_server
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_bytes(b"\x89PNG\r\n\x1a\nfake-png-bytes")
        status, body = _get(server, "/current.png")
        assert status == 200
        assert body.startswith(b"\x89PNG")

    def test_current_png_404_when_missing(self, live_server):
        server, _, args = live_server
        # Ensure the file really is absent
        p = Path(args.output)
        if p.exists():
            p.unlink()
        status, body = _get(server, "/current.png")
        assert status == 404
        assert "missing" in _json_body(body)["error"]

    def test_api_current_returns_identity_and_theme(self, live_server):
        server, state, _args = live_server
        with state.lock:
            state.last_quote_id = ("141", 482, "hello world", "three o'clock")
            state.last_bucket = "h3_exact"
            state.last_effective_theme = "default"
        with patch("run_clock.current_time_str", return_value="03:00"):
            status, body = _get(server, "/api/current")
        assert status == 200
        data = _json_body(body)
        assert data["time"] == "03:00"
        assert data["source_id"] == "141"
        assert data["line_number"] == 482
        assert data["display_quote"] == "hello world"
        assert data["matched_text"] == "three o'clock"
        assert data["theme"] == "default"
        assert data["bucket"] == "h3_exact"

    def test_api_current_handles_no_quote(self, live_server):
        server, _state, _args = live_server
        with patch("run_clock.current_time_str", return_value="12:00"):
            status, body = _get(server, "/api/current")
        assert status == 200
        data = _json_body(body)
        assert data["source_id"] is None
        assert data["line_number"] is None

    def test_api_telemetry_reuses_health_loader(self, tmp_path, live_server):
        server, _state, args = live_server
        # Write one successful render entry via date-rotated sidecar.
        import datetime as dt

        import litclock_health  # noqa: F401  (sanity that it imports)
        today = dt.datetime.now().strftime("%Y%m%d")
        rotated = Path(args.telemetry_path).with_name(
            f"{Path(args.telemetry_path).stem}-{today}.jsonl"
        )
        rotated.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "bucket": "h3_exact",
            "render_ms": 120,
            "display_ms": 15000,
            "source_id": "141",
            "line_number": 42,
            "mode": "debug",
            "theme": "default",
        }
        rotated.write_text(json.dumps(entry) + "\n")
        status, body = _get(server, "/api/telemetry?hours=1")
        assert status == 200
        data = _json_body(body)
        assert data["render_count"] == 1
        assert data["error_count"] == 0
        assert data["render_p50_ms"] == 120

    def test_api_telemetry_rejects_non_int_hours(self, live_server):
        server, _, _ = live_server
        status, body = _get(server, "/api/telemetry?hours=abc")
        assert status == 400
        assert "hours" in _json_body(body)["error"]

    def test_api_telemetry_disabled_returns_empty(self, tmp_path):
        args = _make_args(tmp_path, telemetry_path="")
        state = run_clock.RuntimeState(args.theme)
        server, thread = web_server.start_web_server(args, state)
        try:
            status, body = _get(server, "/api/telemetry")
            assert status == 200
            data = _json_body(body)
            assert data["render_count"] == 0
            assert data.get("note") == "telemetry disabled"
        finally:
            run_clock.stop_web_server((server, thread))

    def test_api_coverage_from_prebuilt_json(self, tmp_path, live_server, monkeypatch):
        server, _, _ = live_server
        # Redirect the coverage path to a controlled fixture.
        payload = {"total_rows": 12, "bucket_counts": {"h3_exact": 4, "h12_half_past": 0}}
        fake = tmp_path / "coverage.json"
        fake.write_text(json.dumps(payload))
        server.context.coverage_path = fake
        status, body = _get(server, "/api/coverage")
        assert status == 200
        assert _json_body(body) == payload

    def test_api_coverage_missing_file_returns_empty(self, tmp_path, live_server):
        server, _, _ = live_server
        server.context.coverage_path = tmp_path / "does_not_exist.json"
        status, body = _get(server, "/api/coverage")
        assert status == 200
        assert _json_body(body)["bucket_counts"] == {}

    def test_api_bucket_returns_ranked_candidates_with_score_components(self, live_server):
        server, _, _ = live_server
        fake = [
            {
                "row": {"source_id": "141", "line_number": 1, "display_quote": "Hello", "quality_score": 80},
                "score": {comp: 0 for comp in pick_quote.SCORE_COMPONENTS},
                "resolved_bucket": "h3_exact",
                "is_winner": True,
            },
        ]
        with patch("pick_quote.select_candidates", return_value=fake):
            status, body = _get(server, "/api/bucket/h3_exact?top=5")
        assert status == 200
        data = _json_body(body)
        assert data["bucket"] == "h3_exact"
        assert data["candidates"][0]["is_winner"] is True
        assert "fragment_penalty" in data["candidates"][0]["score"]

    def test_api_bucket_rejects_bad_bucket_name(self, live_server):
        server, _, _ = live_server
        status, _ = _get(server, "/api/bucket/not_a_bucket")
        # regex fails → falls through to unknown route
        assert status == 404

    def test_api_bucket_swallows_systemexit(self, live_server):
        server, _, _ = live_server
        with patch("pick_quote.select_candidates", side_effect=SystemExit("no candidates")):
            status, body = _get(server, "/api/bucket/h3_exact")
        assert status == 404
        assert "no candidates" in _json_body(body)["error"]

    def test_api_bucket_rejects_bad_top(self, live_server):
        server, _, _ = live_server
        status, body = _get(server, "/api/bucket/h3_exact?top=abc")
        assert status == 400
        assert "top" in _json_body(body)["error"]

    def test_api_overrides_round_trip(self, tmp_path, live_server):
        server, _, args = live_server
        # Initial GET when file doesn't exist returns empty schema
        status, body = _get(server, "/api/overrides")
        assert status == 200
        assert _json_body(body) == {
            "ban_source_ids": [],
            "boost_source_ids": [],
            "preferred_buckets": {},
        }
        # POST a payload, then GET and confirm it's persisted
        payload = {
            "ban_source_ids": ["141"],
            "boost_source_ids": [1342],
            "preferred_buckets": {"h3_exact": "141"},
        }
        status, body = _post(server, "/api/overrides", payload)
        assert status == 200, _json_body(body)
        assert _json_body(body)["ok"] is True
        status, body = _get(server, "/api/overrides")
        on_disk = _json_body(body)
        assert on_disk["ban_source_ids"] == ["141"]
        assert on_disk["boost_source_ids"] == ["1342"]
        assert on_disk["preferred_buckets"] == {"h3_exact": "141"}

    def test_api_history_limit(self, tmp_path, live_server):
        server, _, args = live_server
        path = Path(args.history_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            {"ts": f"2026-04-{20 + i:02d}T14:30:00+00:00", "source_id": str(i), "line_number": i}
            for i in range(5)
        ]
        path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
        status, body = _get(server, "/api/history?limit=3")
        assert status == 200
        data = _json_body(body)
        assert data["total"] == 5
        assert len(data["entries"]) == 3
        # Newest first
        assert data["entries"][0]["source_id"] == "4"

    def test_api_history_rejects_bad_limit(self, live_server):
        server, _, _ = live_server
        status, _ = _get(server, "/api/history?limit=abc")
        assert status == 400


# ============================================================================
# POST action endpoints + locking
# ============================================================================

class TestActionEndpointsLocking:
    def _patch_render(self):
        """Context that stubs _render_unlocked + pick so actions don't shell out."""
        return patch.multiple(
            "run_clock",
            _render_unlocked=lambda args, state, time_str, history_path, **kw: None,
            peek_quote_id=lambda ts, **kw: ("141", 1, "hello", "three o'clock"),
        )

    def test_skip_returns_200_and_sets_last_skipped(self, live_server):
        server, state, _args = live_server
        with state.lock:
            state.last_quote_id = ("99", 7, "prior", "three")
        with self._patch_render():
            status, body = _post(server, "/api/action/skip")
        assert status == 200
        assert _json_body(body)["ok"] is True
        with state.lock:
            assert state.last_skipped == ("99", 7, "prior", "three")

    def test_unskip_returns_200_with_no_prior(self, live_server):
        server, _state, _args = live_server
        with self._patch_render():
            status, body = _post(server, "/api/action/unskip")
        assert status == 200
        data = _json_body(body)
        assert data["ok"] is True
        assert data["restored"] is None

    def test_theme_toggle_persists_via_save_runtime_state(self, live_server):
        server, state, args = live_server
        with state.lock:
            state.last_effective_theme = "default"
        with self._patch_render():
            status, body = _post(server, "/api/action/theme")
        assert status == 200
        assert _json_body(body)["theme"] == "dark"
        # Persistence check: the state file must exist and hold manual_theme=dark
        persisted = json.loads(Path(args.state_path).read_text())
        assert persisted["manual_theme"] == "dark"

    def test_quiet_toggle_wakes_with_render(self, live_server):
        server, state, _args = live_server
        # Start quiet so the toggle wakes (and hence must re-render)
        with state.lock:
            state.manual_quiet = True
        rendered = {"count": 0}

        def fake_render(*a, **kw):
            rendered["count"] += 1

        with patch("run_clock._render_unlocked", side_effect=fake_render), \
             patch("run_clock.peek_quote_id", return_value=("141", 1, "q", "m")):
            status, body = _post(server, "/api/action/quiet")
        assert status == 200
        assert _json_body(body)["manual_quiet"] is False
        assert rendered["count"] == 1

    def test_rerender_uses_current_time_and_bucket(self, live_server):
        server, _state, _args = live_server
        calls = []

        def fake_render(_args, _state, time_str, _hp, bucket=None, quote_id=None, **_kw):
            calls.append((time_str, bucket, quote_id))

        with patch("run_clock._render_unlocked", side_effect=fake_render), \
             patch("run_clock.peek_quote_id", return_value=("141", 1, "q", "m")), \
             patch("run_clock.current_time_str", return_value="03:15"):
            status, body = _post(server, "/api/action/rerender")
        assert status == 200
        data = _json_body(body)
        assert data["bucket"] == "h3_quarter_past"
        assert data["quote_id"] == ["141", 1, "q", "m"]
        assert calls and calls[0][0] == "03:15"

    def test_action_returns_409_when_render_in_flight(self, live_server):
        server, state, _args = live_server
        # Simulate a render already in progress by acquiring render_lock from a
        # helper thread and holding it until this test finishes.
        release = threading.Event()
        held = threading.Event()

        def hold_lock():
            with state.render_lock:
                held.set()
                release.wait(timeout=3)

        t = threading.Thread(target=hold_lock, daemon=True)
        t.start()
        held.wait(timeout=1)
        try:
            status, body = _post(server, "/api/action/theme")
            assert status == 409
            assert _json_body(body)["error"] == "busy"
        finally:
            release.set()
            t.join(timeout=2)

    def test_action_exception_returns_500(self, live_server):
        server, _state, _args = live_server
        with patch("run_clock._render_unlocked", side_effect=RuntimeError("boom")):
            status, body = _post(server, "/api/action/theme")
        assert status == 500
        assert "boom" in _json_body(body)["error"]


# ============================================================================
# Overrides validation + atomic write
# ============================================================================

class TestOverrideValidation:
    def test_accepts_valid_payload(self):
        out = web_server.validate_overrides_payload({
            "ban_source_ids": ["141"],
            "boost_source_ids": [1342],
            "preferred_buckets": {"h3_exact": "141"},
        })
        assert out["ban_source_ids"] == ["141"]
        assert out["boost_source_ids"] == ["1342"]

    def test_reject_non_object_payload(self):
        with pytest.raises(ValueError):
            web_server.validate_overrides_payload([])
        with pytest.raises(ValueError):
            web_server.validate_overrides_payload("string")

    def test_reject_empty_object_payload(self):
        """{} must NOT be treated as 'wipe everything' — guards against empty-body POSTs."""
        with pytest.raises(ValueError, match="at least one"):
            web_server.validate_overrides_payload({})

    def test_explicit_empty_collections_are_allowed(self):
        """Callers who really want to clear state spell it out explicitly."""
        out = web_server.validate_overrides_payload({
            "ban_source_ids": [],
            "boost_source_ids": [],
            "preferred_buckets": {},
        })
        assert out == {"ban_source_ids": [], "boost_source_ids": [], "preferred_buckets": {}}

    def test_reject_bool_in_id_list(self):
        """bool is a subclass of int — make sure we don't silently coerce True/False to strings."""
        with pytest.raises(ValueError, match="ban_source_ids"):
            web_server.validate_overrides_payload({"ban_source_ids": [True]})
        with pytest.raises(ValueError, match="boost_source_ids"):
            web_server.validate_overrides_payload({"boost_source_ids": [False]})
        with pytest.raises(ValueError, match="must be a string/int"):
            web_server.validate_overrides_payload({"preferred_buckets": {"h3_exact": True}})

    def test_reject_bad_bucket_key(self):
        with pytest.raises(ValueError, match="not a valid bucket"):
            web_server.validate_overrides_payload({"preferred_buckets": {"h13_exact": "141"}})

    def test_reject_non_list_ban_ids(self):
        with pytest.raises(ValueError, match="ban_source_ids"):
            web_server.validate_overrides_payload({"ban_source_ids": "141"})

    def test_reject_non_list_boost_ids(self):
        with pytest.raises(ValueError, match="boost_source_ids"):
            web_server.validate_overrides_payload({"boost_source_ids": {"nope": 1}})

    def test_reject_dict_items_of_wrong_type(self):
        with pytest.raises(ValueError, match="ban_source_ids"):
            web_server.validate_overrides_payload({"ban_source_ids": [{"nope": 1}]})

    def test_reject_non_string_preferred_value(self):
        with pytest.raises(ValueError, match="must be a string/int"):
            web_server.validate_overrides_payload({"preferred_buckets": {"h3_exact": [1]}})

    def test_write_atomic_uses_shared_helper(self, tmp_path):
        """Write goes through run_clock._atomic_write_text, which tmp+fsync+replace+dir-fsync."""
        called = {"n": 0}

        def fake(path, payload):
            called["n"] += 1
            path.write_text(payload)

        target = tmp_path / "overrides.json"
        with patch("run_clock._atomic_write_text", side_effect=fake):
            web_server.write_overrides_atomic(target, {"ban_source_ids": []})
        assert called["n"] == 1
        assert target.exists()

    def test_bad_payload_returns_400(self, live_server):
        server, _, _ = live_server
        status, body = _post(server, "/api/overrides", {"preferred_buckets": {"h13_exact": "141"}})
        assert status == 400
        assert "valid bucket" in _json_body(body)["error"]

    def test_empty_body_post_does_not_wipe_overrides(self, tmp_path, live_server):
        """Regression: POST with no body (Content-Length: 0) used to silently wipe the file."""
        server, _, args = live_server
        overrides_path = Path(args.overrides)
        overrides_path.parent.mkdir(parents=True, exist_ok=True)
        seed = {
            "ban_source_ids": ["141"],
            "boost_source_ids": ["1342"],
            "preferred_buckets": {"h3_exact": "141"},
        }
        overrides_path.write_text(json.dumps(seed))
        status, body = _post(server, "/api/overrides")  # no payload → Content-Length: 0
        assert status == 400
        assert "at least one" in _json_body(body)["error"]
        # File is unchanged
        assert json.loads(overrides_path.read_text()) == seed

    def test_body_too_large_returns_400(self, live_server):
        server, _, _ = live_server
        # Send an oversized body via raw bytes with Content-Length that trips the cap.
        conn = _client(server)
        huge = b"x" * (web_server.MAX_BODY_BYTES + 1)
        conn.request("POST", "/api/overrides", body=huge, headers={"Content-Length": str(len(huge))})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        assert resp.status == 400
        assert "too large" in _json_body(body)["error"]


# ============================================================================
# Auth
# ============================================================================

class TestAuth:
    def test_localhost_bind_allows_post_without_token(self, live_server):
        server, _, _ = live_server
        with patch("run_clock._render_unlocked"), \
             patch("run_clock.peek_quote_id", return_value=("141", 1, "q", "m")):
            status, _ = _post(server, "/api/action/theme")
        assert status == 200

    def test_token_required_post_without_header_returns_401(self, tmp_path):
        args = _make_args(tmp_path, web_bind="0.0.0.0:0")
        state = run_clock.RuntimeState(args.theme)
        server, thread = web_server.start_web_server(args, state, token="secret")
        try:
            status, body = _post(server, "/api/action/theme")
            assert status == 401
            assert _json_body(body)["error"] == "token required"
        finally:
            run_clock.stop_web_server((server, thread))

    def test_token_required_post_with_wrong_header_returns_401(self, tmp_path):
        args = _make_args(tmp_path, web_bind="0.0.0.0:0")
        state = run_clock.RuntimeState(args.theme)
        server, thread = web_server.start_web_server(args, state, token="secret")
        try:
            status, body = _post(server, "/api/action/theme", headers={"X-LitClock-Token": "nope"})
            assert status == 401
        finally:
            run_clock.stop_web_server((server, thread))

    def test_token_required_post_with_correct_header_allowed(self, tmp_path):
        args = _make_args(tmp_path, web_bind="0.0.0.0:0")
        state = run_clock.RuntimeState(args.theme)
        server, thread = web_server.start_web_server(args, state, token="secret")
        try:
            with patch("run_clock._render_unlocked"), \
                 patch("run_clock.peek_quote_id", return_value=("141", 1, "q", "m")):
                status, _ = _post(
                    server, "/api/action/theme",
                    headers={"X-LitClock-Token": "secret"},
                )
            assert status == 200
        finally:
            run_clock.stop_web_server((server, thread))

    def test_token_required_gets_stay_open(self, tmp_path):
        args = _make_args(tmp_path, web_bind="0.0.0.0:0")
        state = run_clock.RuntimeState(args.theme)
        server, thread = web_server.start_web_server(args, state, token="secret")
        try:
            status, _ = _get(server, "/api/current")
            assert status == 200
        finally:
            run_clock.stop_web_server((server, thread))

    def test_unknown_post_route_returns_404_before_401(self, tmp_path):
        """404 before 401 so a scanner can't learn the service exists via wrong-token probes."""
        args = _make_args(tmp_path, web_bind="0.0.0.0:0")
        state = run_clock.RuntimeState(args.theme)
        server, thread = web_server.start_web_server(args, state, token="secret")
        try:
            status, _ = _post(server, "/api/nope")  # no token header
            assert status == 404
        finally:
            run_clock.stop_web_server((server, thread))


# ============================================================================
# Token resolution helper
# ============================================================================

class TestTokenResolution:
    def test_empty_when_nothing_configured(self, tmp_path):
        args = _make_args(tmp_path, web_token="", web_token_file="")
        assert run_clock._resolve_web_token(args) == ""

    def test_inline_token_used(self, tmp_path):
        args = _make_args(tmp_path, web_token="abc123")
        assert run_clock._resolve_web_token(args) == "abc123"

    def test_file_token_preferred_over_inline(self, tmp_path):
        tf = tmp_path / "token.txt"
        tf.write_text("from-file\n")
        args = _make_args(tmp_path, web_token="from-inline", web_token_file=str(tf))
        assert run_clock._resolve_web_token(args) == "from-file"

    def test_missing_token_file_falls_back_to_inline(self, tmp_path, capsys):
        args = _make_args(tmp_path, web_token="fallback", web_token_file=str(tmp_path / "nope.txt"))
        assert run_clock._resolve_web_token(args) == "fallback"
        assert "unreadable" in capsys.readouterr().err

    def test_maybe_start_web_server_noop_when_unset(self, tmp_path):
        args = _make_args(tmp_path, web_bind="")
        state = run_clock.RuntimeState(args.theme)
        assert run_clock._maybe_start_web_server(args, state) is None

    def test_maybe_start_web_server_logs_on_failure(self, tmp_path, capsys):
        args = _make_args(tmp_path, web_bind="0.0.0.0:0")  # non-localhost without token → refused
        state = run_clock.RuntimeState(args.theme)
        assert run_clock._maybe_start_web_server(args, state) is None
        assert "failed to start" in capsys.readouterr().err
