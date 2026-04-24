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


class TestTokenFileHotReload:
    """The --web-token-file contents must re-read on mtime change, no restart needed."""

    def test_new_token_accepted_after_file_rewrite(self, tmp_path):
        """Acceptance: rotate the file under a running server; next POST with the new
        token succeeds without restart, while the old token returns 401."""
        import os
        import time

        token_file = tmp_path / "token"
        token_file.write_text("first-secret\n", encoding="utf-8")

        # Make sure the mtime detection has room to fire — filesystems with
        # second-granularity mtimes could otherwise see the second write as
        # "same mtime" if both happen inside one second.
        past = time.time() - 10
        os.utime(token_file, (past, past))

        args = _make_args(tmp_path, web_bind="127.0.0.1:0", web_token_file=str(token_file))
        state = run_clock.RuntimeState(args.theme)
        server, thread = web_server.start_web_server(
            args, state, token="", token_file=str(token_file),
        )
        try:
            # First token works; payload validation failure returns 400 which proves auth passed.
            status, _ = _post(
                server, "/api/overrides", payload={"ban_source_ids": []},
                headers={"X-LitClock-Token": "first-secret"},
            )
            assert status in (200, 400)

            # Rotate: write new contents and bump mtime forward so the stat poll picks it up.
            token_file.write_text("second-secret\n", encoding="utf-8")
            now = time.time()
            os.utime(token_file, (now, now))

            # Old token must now fail.
            status, body = _post(
                server, "/api/overrides", payload={"ban_source_ids": []},
                headers={"X-LitClock-Token": "first-secret"},
            )
            assert status == 401, _json_body(body)

            # New token must succeed — no restart happened.
            status, _ = _post(
                server, "/api/overrides", payload={"ban_source_ids": []},
                headers={"X-LitClock-Token": "second-secret"},
            )
            assert status in (200, 400)
        finally:
            run_clock.stop_web_server((server, thread))

    def test_unreadable_file_falls_back_to_previous_token(self, tmp_path):
        """A transient unlink / permission hiccup keeps the previous token valid
        instead of silently dropping auth to "any token accepted"."""
        token_file = tmp_path / "token"
        token_file.write_text("original\n", encoding="utf-8")

        args = _make_args(tmp_path, web_bind="127.0.0.1:0", web_token_file=str(token_file))
        state = run_clock.RuntimeState(args.theme)
        ctx = web_server.WebContext(args, state, token="", token_file=str(token_file))
        assert ctx.current_token() == "original"

        # Remove the file — current_token() should keep returning the cached value.
        token_file.unlink()
        assert ctx.current_token() == "original"

    def test_missing_file_at_startup_does_not_raise(self, tmp_path):
        """A typo in --web-token-file at startup is logged, not crashed — the
        inline --web-token (if any) still works, and a later fix to the path
        will be picked up on next request."""
        missing = tmp_path / "never-existed"
        args = _make_args(tmp_path, web_bind="127.0.0.1:0", web_token_file=str(missing))
        state = run_clock.RuntimeState(args.theme)
        ctx = web_server.WebContext(args, state, token="fallback-inline", token_file=str(missing))
        # No crash; the inline fallback is what we get back.
        assert ctx.current_token() == "fallback-inline"

    def test_rotation_to_empty_file_keeps_previous_token(self, tmp_path, capsys):
        """Security: if the token file is accidentally truncated to empty at
        runtime, we keep the previous token instead of silently disabling
        auth. Rotation to a new non-empty value still works; this only guards
        the empty-string edge case that an operator typo could otherwise open."""
        import os
        import time

        token_file = tmp_path / "token"
        token_file.write_text("valid-secret\n", encoding="utf-8")
        past = time.time() - 10
        os.utime(token_file, (past, past))

        args = _make_args(tmp_path, web_bind="127.0.0.1:0", web_token_file=str(token_file))
        state = run_clock.RuntimeState(args.theme)
        ctx = web_server.WebContext(args, state, token="", token_file=str(token_file))
        assert ctx.current_token() == "valid-secret"

        # Simulate a botched rotation that emptied the file.
        token_file.write_text("", encoding="utf-8")
        now = time.time()
        os.utime(token_file, (now, now))

        # Must NOT have dropped to "" (which would disable auth).
        assert ctx.current_token() == "valid-secret"
        assert "refusing to downgrade to no-auth" in capsys.readouterr().err


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

    def test_api_themes_returns_cycle_and_current_state(self, live_server):
        """The themes endpoint feeds the UI dropdown: it returns the full
        cycle list, the CLI ``theme_arg``, and either the manual override
        or the auto-resolved effective theme. Pin the shape so the UI
        doesn't silently break when a new field is added or renamed."""
        import render_quote as rq
        server, state, _args = live_server
        with state.lock:
            state.manual_theme = "scholar"
            state.last_effective_theme = "scholar"
        status, body = _get(server, "/api/themes")
        assert status == 200
        data = _json_body(body)
        assert data["themes"] == list(rq.THEME_ORDER)
        assert data["manual_theme"] == "scholar"
        assert data["effective"] == "scholar"
        assert "theme_arg" in data

    def test_api_themes_reflects_auto_when_no_manual_override(self, live_server):
        server, state, _args = live_server
        with state.lock:
            state.manual_theme = None
            state.last_effective_theme = "default"
        status, body = _get(server, "/api/themes")
        assert status == 200
        data = _json_body(body)
        assert data["manual_theme"] is None
        assert data["effective"] in ("default", "dark", "scholar", "newsprint", "nightvision")

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

    def test_theme_post_with_body_jumps_to_named_theme(self, live_server):
        """POST /api/action/theme with {"theme": "<name>"} jumps straight to
        the named theme without stepping through the cycle. Mirrors the
        web UI dropdown's direct-selection behaviour."""
        server, state, args = live_server
        with state.lock:
            state.last_effective_theme = "default"
        with self._patch_render():
            status, body = _post(server, "/api/action/theme", payload={"theme": "nightvision"})
        assert status == 200
        data = _json_body(body)
        assert data["ok"] is True
        assert data["theme"] == "nightvision"
        persisted = json.loads(Path(args.state_path).read_text())
        assert persisted["manual_theme"] == "nightvision"

    def test_theme_post_unknown_name_returns_400(self, live_server):
        """A typo in ``theme`` comes back as 400 with ``error: unknown_theme``
        rather than a 500 or a silent no-op; ``manual_theme`` stays put."""
        server, state, _args = live_server
        with state.lock:
            state.last_effective_theme = "default"
            state.manual_theme = None
        with self._patch_render():
            status, body = _post(server, "/api/action/theme", payload={"theme": "chartreuse"})
        assert status == 400
        data = _json_body(body)
        assert data["ok"] is False
        assert data["error"] == "unknown_theme"
        with state.lock:
            assert state.manual_theme is None

    def test_theme_post_without_body_cycles(self, live_server):
        """POST /api/action/theme with no body / empty body must cycle to
        the next theme — mirrors a physical button-B press. The action
        endpoint accepts missing Content-Length, empty bodies, and `{}`
        all as "cycle". Explicitly tests the missing-body branch that the
        dropdown's Apply-flow doesn't exercise."""
        server, state, args = live_server
        with state.lock:
            state.last_effective_theme = "default"
        with self._patch_render():
            status, body = _post(server, "/api/action/theme")  # no payload at all
        assert status == 200
        data = _json_body(body)
        assert data["ok"] is True
        assert data["theme"] == "dark"  # default → dark is step 1 of THEME_ORDER
        persisted = json.loads(Path(args.state_path).read_text())
        assert persisted["manual_theme"] == "dark"

    def test_theme_post_with_empty_dict_cycles(self, live_server):
        """Same behaviour when the UI sends an empty JSON object."""
        server, state, _args = live_server
        with state.lock:
            state.last_effective_theme = "default"
        with self._patch_render():
            status, body = _post(server, "/api/action/theme", payload={})
        assert status == 200
        assert _json_body(body)["theme"] == "dark"

    def test_theme_post_with_non_string_theme_returns_400(self, live_server):
        """A numeric / list ``theme`` value must be rejected without any
        state mutation — defence in depth against a malformed client."""
        server, state, _args = live_server
        with state.lock:
            state.last_effective_theme = "default"
            state.manual_theme = None
        status, body = _post(server, "/api/action/theme", payload={"theme": 42})
        assert status == 400
        assert _json_body(body)["ok"] is False

    def test_theme_post_with_malformed_json_returns_400(self, live_server):
        """A malformed JSON body must come back as 400 — not silently fall
        back to ``{}`` and cycle. Previously ``_action_theme`` caught
        ``ValueError`` and defaulted to an empty dict, which meant a bad
        client (or a corrupt request mid-flight) could unintentionally
        advance the theme on the panel. Regression guard for the P1
        comment on PR #72.
        """
        server, state, _args = live_server
        with state.lock:
            state.last_effective_theme = "default"
            state.manual_theme = None
        # Craft a handcrafted POST with invalid JSON bytes.
        conn = _client(server)
        data = b"{not valid json"
        headers = {"Content-Type": "application/json", "Content-Length": str(len(data))}
        conn.request("POST", "/api/action/theme", body=data, headers=headers)
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 400
        # State must be untouched — no silent cycle advance from bad input.
        with state.lock:
            assert state.manual_theme is None

    def test_theme_post_with_oversized_body_returns_400(self, live_server):
        """An oversized body (larger than ``MAX_BODY_BYTES``) raises
        ``ValueError`` from ``_read_json_body`` and must propagate to 400
        rather than being swallowed into a silent cycle. Same P1 regression
        guard as the malformed-JSON test above.
        """
        server, state, _args = live_server
        with state.lock:
            state.last_effective_theme = "default"
            state.manual_theme = None
        # Fabricate a Content-Length that exceeds the server's cap without
        # actually shipping that many bytes — the guard fires on the header
        # check before the body read.
        oversize = web_server.MAX_BODY_BYTES + 1
        conn = _client(server)
        headers = {"Content-Type": "application/json", "Content-Length": str(oversize)}
        conn.request("POST", "/api/action/theme", body=b"", headers=headers)
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 400
        with state.lock:
            assert state.manual_theme is None

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
        """Write goes through atomic_io.atomic_write_text, which tmp+fsync+replace+dir-fsync."""
        called = {"n": 0}

        def fake(path, payload):
            called["n"] += 1
            path.write_text(payload)

        target = tmp_path / "overrides.json"
        with patch("atomic_io.atomic_write_text", side_effect=fake):
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


class TestErrorBranches:
    """Explicit coverage of the defensive branches that return 4xx/5xx."""

    def test_post_body_too_large_returns_400(self, tmp_path):
        # MAX_BODY_BYTES is 64KB. A Content-Length header above that must be
        # rejected by _read_json_body before we allocate anything.
        server, thread, _state, _args = _start(tmp_path)
        try:
            conn = _client(server)
            # We cannot easily send a huge body in CI, but declaring an oversized
            # Content-Length via the header is enough — the server reads the int
            # and raises ValueError before draining the socket.
            conn.request(
                "POST", "/api/overrides",
                body=b"",  # no real body; the Content-Length header is what trips the check
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(web_server.MAX_BODY_BYTES + 1),
                },
            )
            resp = conn.getresponse()
            assert resp.status == 400
            body = json.loads(resp.read().decode("utf-8"))
            assert "body too large" in body["error"]
            conn.close()
        finally:
            run_clock.stop_web_server((server, thread))

    def test_api_coverage_malformed_json_returns_500(self, tmp_path, live_server):
        server, _, _ = live_server
        bad = tmp_path / "bucket-coverage.json"
        bad.write_text("not { valid json", encoding="utf-8")
        server.context.coverage_path = bad
        status, body = _get(server, "/api/coverage")
        assert status == 500
        assert "error" in _json_body(body)

    def test_current_png_missing_returns_404(self, tmp_path, live_server):
        server, _, args = live_server
        # Point at a file that doesn't exist.
        server.context.output_path = tmp_path / "nonexistent.png"
        status, body = _get(server, "/current.png")
        assert status == 404

    def test_unknown_get_returns_404(self, live_server):
        server, _, _ = live_server
        status, _ = _get(server, "/api/does-not-exist")
        assert status == 404

    def test_unknown_post_returns_404_before_token_check(self, tmp_path):
        # Token is required, but an unknown POST path must 404 without revealing
        # that a token check even happens (avoids fingerprinting by scanners).
        server, thread, _state, _args = _start(tmp_path, token="sekret")
        try:
            status, body = _post(server, "/api/action/bogus", {"x": 1})
            assert status == 404
            assert _json_body(body)["error"] == "not found"
        finally:
            run_clock.stop_web_server((server, thread))

    def test_get_handler_exception_returns_500(self, tmp_path, live_server, monkeypatch):
        """Force _api_current to blow up and assert we return 500 (not crash the server)."""
        server, _, _ = live_server
        import run_clock as rc
        monkeypatch.setattr(rc, "current_time_str", lambda: (_ for _ in ()).throw(RuntimeError("clock fail")))
        status, body = _get(server, "/api/current")
        assert status == 500
        assert "clock fail" in _json_body(body)["error"]

    def test_post_handler_exception_returns_500(self, tmp_path, live_server, monkeypatch):
        """A non-ValueError in a POST handler surfaces as 500, not as a bare 200."""
        server, _, _ = live_server
        monkeypatch.setattr(
            run_clock, "action_rerender",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("explode")),
        )
        status, body = _post(server, "/api/action/rerender", {})
        assert status == 500
        assert "explode" in _json_body(body)["error"]

    def test_api_telemetry_non_int_hours_returns_400(self, live_server):
        server, _, _ = live_server
        status, body = _get(server, "/api/telemetry?hours=notanumber")
        assert status == 400
        assert "hours" in _json_body(body)["error"]

    def test_api_history_non_int_limit_returns_400(self, live_server):
        server, _, _ = live_server
        status, body = _get(server, "/api/history?limit=notanumber")
        assert status == 400
        assert "limit" in _json_body(body)["error"]

    def test_api_bucket_non_int_top_returns_400(self, live_server):
        server, _, _ = live_server
        status, body = _get(server, "/api/bucket/h3_exact?top=notanumber")
        assert status == 400
        assert "top" in _json_body(body)["error"]


# ============================================================================
# Phase 4 observability — structured web telemetry
# (github.com/gkoch02/litclock issue #55)
# ============================================================================


def _read_web_telemetry(tmp_path: Path) -> list[dict]:
    """Read all date-rotated telemetry siblings written by the web server."""
    entries = []
    for path in tmp_path.glob("telemetry-*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
    return entries


class TestWebAuthFailTelemetry:
    def test_bad_token_post_emits_web_auth_fail(self, tmp_path):
        """A 401 on a POST lays down a ``mode="web_auth_fail"`` entry so an
        operator can see "was the web UI hammered with bad tokens yesterday?"
        without scraping journald."""
        args = _make_args(tmp_path, web_bind="0.0.0.0:0")
        state = run_clock.RuntimeState(args.theme)
        server, thread = web_server.start_web_server(args, state, token="secret")
        try:
            status, _ = _post(server, "/api/action/theme", headers={"X-LitClock-Token": "wrong"})
            assert status == 401
        finally:
            run_clock.stop_web_server((server, thread))
        entries = _read_web_telemetry(tmp_path)
        matching = [e for e in entries if e.get("mode") == "web_auth_fail"]
        assert matching, entries
        assert matching[0]["path"] == "/api/action/theme"
        # remote is present (127.0.0.1 in the test loopback)
        assert "remote" in matching[0]

    def test_missing_token_header_emits_web_auth_fail(self, tmp_path):
        args = _make_args(tmp_path, web_bind="0.0.0.0:0")
        state = run_clock.RuntimeState(args.theme)
        server, thread = web_server.start_web_server(args, state, token="secret")
        try:
            status, _ = _post(server, "/api/action/theme")
            assert status == 401
        finally:
            run_clock.stop_web_server((server, thread))
        entries = _read_web_telemetry(tmp_path)
        assert any(e.get("mode") == "web_auth_fail" for e in entries)

    def test_auth_fail_strips_query_string_from_path(self, tmp_path):
        """Security: a fat-finger client putting a token in the URL (instead of
        the X-LitClock-Token header) would otherwise plant the secret in the
        telemetry sidecar. ``log_message`` is silenced for the same reason."""
        args = _make_args(tmp_path, web_bind="0.0.0.0:0")
        state = run_clock.RuntimeState(args.theme)
        server, thread = web_server.start_web_server(args, state, token="secret")
        try:
            # Deliberately embed a "secret" in the query to simulate misuse.
            conn = _client(server)
            conn.request("POST", "/api/action/theme?token=leaked", body=b"",
                         headers={"Content-Length": "0"})
            resp = conn.getresponse()
            resp.read()
            conn.close()
            assert resp.status == 401
        finally:
            run_clock.stop_web_server((server, thread))
        entries = _read_web_telemetry(tmp_path)
        matching = [e for e in entries if e.get("mode") == "web_auth_fail"]
        assert matching
        # Path must be just the route, without the query — no "leaked" token.
        assert matching[0]["path"] == "/api/action/theme"
        assert "leaked" not in json.dumps(matching[0])

    def test_successful_post_does_not_emit_auth_fail(self, tmp_path):
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
        entries = _read_web_telemetry(tmp_path)
        assert not any(e.get("mode") == "web_auth_fail" for e in entries)


class TestWebErrorTelemetry:
    def test_bad_post_body_emits_web_error(self, live_server):
        """A malformed overrides payload returns 400 and emits a structured
        ``mode="web_error"`` entry with the status and error string."""
        server, _, args = live_server
        status, _ = _post(server, "/api/overrides", {"preferred_buckets": {"h13_exact": "141"}})
        assert status == 400
        entries = _read_web_telemetry(Path(args.telemetry_path).parent)
        matching = [e for e in entries if e.get("mode") == "web_error"]
        assert matching, entries
        assert matching[0]["status"] == 400
        assert matching[0]["path"] == "/api/overrides"

    def test_exception_in_handler_emits_web_error_500(self, live_server, monkeypatch):
        server, _, args = live_server
        monkeypatch.setattr(
            run_clock, "action_rerender",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("explode")),
        )
        status, _ = _post(server, "/api/action/rerender", {})
        assert status == 500
        entries = _read_web_telemetry(Path(args.telemetry_path).parent)
        matching = [e for e in entries if e.get("mode") == "web_error" and e.get("status") == 500]
        assert matching
        assert "explode" in matching[0]["error"]


# ============================================================================
# Security edges — unsupported verbs, render-lock contention, token comparison
# ============================================================================


class TestUnsupportedVerbs:
    """``BaseHTTPRequestHandler`` responds with 501 for verbs we didn't define.

    We exercise this explicitly so the "someone added a do_HEAD that leaks
    data" class of regression fails a test, not a pen-test.
    """

    def _raw_request(self, server, verb: str, path: str = "/api/current"):
        conn = _client(server)
        # ``http.client.HTTPConnection.request`` refuses unknown verbs in some
        # Python versions; build the raw line ourselves to bypass that.
        conn.putrequest(verb, path, skip_host=False, skip_accept_encoding=True)
        conn.putheader("Content-Length", "0")
        conn.endheaders()
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    @pytest.mark.parametrize("verb", ["PUT", "DELETE", "PATCH"])
    def test_unsupported_verb_returns_501(self, live_server, verb):
        server, _, _ = live_server
        status, _ = self._raw_request(server, verb)
        # http.server's default do_* fallback is 501 Unsupported Method.
        assert status == 501

    def test_head_does_not_leak_body(self, live_server):
        # We don't define do_HEAD, so the base handler responds 501 — a new
        # do_HEAD must not accidentally return a body that duplicates do_GET's
        # response without the caching / token protections.
        server, _, _ = live_server
        status, body = self._raw_request(server, "HEAD", "/api/current")
        assert status == 501
        assert body == b"" or b"current_time" not in body


class TestRenderLockContention:
    """Regression guard for the ``_button_render_gate`` non-blocking acquire.

    A web POST arriving during an in-flight render (or another action still
    holding ``render_lock``) must drop with ``{"error": "busy"}`` at HTTP 409
    instead of queueing behind the 10–20s Spectra 6 refresh.
    """

    def test_concurrent_action_during_held_render_lock_returns_409(self, tmp_path):
        server, thread, state, args = _start(tmp_path)
        try:
            # Simulate an in-flight render by grabbing the lock from the test
            # thread. The action handler uses the same non-blocking pattern
            # GPIO presses use, so a held lock must surface as "busy".
            state.render_lock.acquire()
            try:
                status, body = _post(server, "/api/action/rerender", {})
                assert status == 409, f"expected 409 busy, got {status}: {body!r}"
                assert _json_body(body)["error"] == "busy"
            finally:
                state.render_lock.release()
        finally:
            run_clock.stop_web_server((server, thread))

    def test_action_succeeds_once_render_lock_is_released(self, tmp_path):
        server, thread, state, args = _start(tmp_path)
        try:
            state.render_lock.acquire()
            state.render_lock.release()
            with patch("run_clock._render_unlocked"), \
                 patch("run_clock.peek_quote_id", return_value=("141", 1, "q", "m")):
                status, body = _post(server, "/api/action/rerender", {})
            assert status == 200, f"expected 200 after release, got {status}: {body!r}"
        finally:
            run_clock.stop_web_server((server, thread))


class TestTokenComparison:
    """The token check must be constant-time (``hmac.compare_digest``) so a
    remote attacker can't time-probe one byte at a time.

    We can't test timing directly without flakiness, but we can assert the
    code path actually calls ``hmac.compare_digest`` rather than ``==`` — a
    regression that downgrades to ``==`` fails here instead of only failing
    to a motivated attacker.
    """

    def test_token_comparison_uses_hmac_compare_digest(self, tmp_path, monkeypatch):
        args = _make_args(tmp_path, web_bind="0.0.0.0:0")
        state = run_clock.RuntimeState(args.theme)
        server, thread = web_server.start_web_server(args, state, token="secret")
        try:
            calls: list[tuple[str, str]] = []

            import hmac as hmac_mod
            real_compare = hmac_mod.compare_digest

            def spy(a, b):
                calls.append((a, b))
                return real_compare(a, b)

            monkeypatch.setattr("web_server.hmac.compare_digest", spy)

            status, _ = _post(
                server, "/api/action/theme",
                headers={"X-LitClock-Token": "secret"},
            )
            # We don't care about the status here (it may 200 or 500 without
            # the peek stub) — only that compare_digest was invoked.
            assert calls, "token comparison did not go through hmac.compare_digest"
            assert calls[0] == ("secret", "secret")
        finally:
            run_clock.stop_web_server((server, thread))

    def test_empty_token_bypasses_auth(self, tmp_path):
        """Loopback binds without a token allow every POST — a regression that
        suddenly requires a token would break every existing local install."""
        server, thread, _state, _args = _start(tmp_path, token="")
        try:
            with patch("run_clock._render_unlocked"), \
                 patch("run_clock.peek_quote_id", return_value=("141", 1, "q", "m")):
                status, _ = _post(server, "/api/action/rerender", {})
            assert status == 200
        finally:
            run_clock.stop_web_server((server, thread))


class TestContentLengthEdges:
    def test_negative_content_length_is_treated_as_empty(self, tmp_path):
        # A signed integer parse of "-1" would underflow the body read — the
        # handler guards via ``length <= 0`` so the body is simply empty.
        server, thread, _state, _args = _start(tmp_path)
        try:
            conn = _client(server)
            conn.request("POST", "/api/overrides", body=b"",
                         headers={"Content-Length": "-1"})
            resp = conn.getresponse()
            body = resp.read()
            conn.close()
            # Empty body → validator rejects the payload (not an object with
            # the required keys). We care that the server doesn't crash or
            # attempt a negative read, not the exact error text.
            assert resp.status in {200, 400}
            assert body  # the server responded with *some* JSON error/payload
        finally:
            run_clock.stop_web_server((server, thread))

    def test_non_numeric_content_length_rejected(self, tmp_path):
        server, thread, _state, _args = _start(tmp_path)
        try:
            conn = _client(server)
            conn.request("POST", "/api/overrides", body=b"",
                         headers={"Content-Length": "not-a-number"})
            resp = conn.getresponse()
            resp.read()
            conn.close()
            # int() raises ValueError, which the outer do_POST except catches
            # and returns 500. That's acceptable — the key property is that we
            # don't attempt ``rfile.read(<bogus>)``.
            assert resp.status in {400, 500}
        finally:
            run_clock.stop_web_server((server, thread))
