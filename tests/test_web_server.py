"""Tests for the curator web UI (``web_server.py``).

Every test binds an ephemeral-port ``_IdleHoursHTTPServer`` on 127.0.0.1, drives
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
from PIL import Image

from idle_hours import pick_quote, run_clock, web_server


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
    """Spin up an ``_IdleHoursHTTPServer`` on an ephemeral port and return (server, state, args)."""
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

class TestOutputPathAlignment:
    """The curator UI's ``/current.png`` endpoint must serve the same file
    ``run_clock`` writes to, otherwise the preview tile shows a stale or
    absent frame.

    Pre-restructure, both resolved relative paths against the same
    ``BASE_DIR`` (the repo root). After the v2.x package move ``BASE_DIR``
    points inside the installed package; ``run_clock`` now resolves
    ``--output output/current.png`` against CWD, and the web server has
    to match.
    """

    def test_relative_output_resolves_to_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Mirror the argparse default exactly — this is what `run_clock`
        # would pass when the operator hasn't overridden --output.
        args = _make_args(tmp_path, output="output/current.png")
        ctx = web_server.WebContext(args, state=run_clock.RuntimeState(args.theme))
        expected = (tmp_path / "output" / "current.png").resolve()
        assert ctx.output_path == expected, (
            f"web_server output_path = {ctx.output_path!r}, "
            f"expected CWD-relative {expected!r} (matching run_clock.main)"
        )

    def test_absolute_output_passes_through(self, tmp_path):
        absolute = tmp_path / "rendered" / "frame.png"
        args = _make_args(tmp_path, output=str(absolute))
        ctx = web_server.WebContext(args, state=run_clock.RuntimeState(args.theme))
        assert ctx.output_path == absolute.resolve()


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
                headers={"X-Idle-Hours-Token": "first-secret"},
            )
            assert status in (200, 400)

            # Rotate: write new contents and bump mtime forward so the stat poll picks it up.
            token_file.write_text("second-secret\n", encoding="utf-8")
            now = time.time()
            os.utime(token_file, (now, now))

            # Old token must now fail.
            status, body = _post(
                server, "/api/overrides", payload={"ban_source_ids": []},
                headers={"X-Idle-Hours-Token": "first-secret"},
            )
            assert status == 401, _json_body(body)

            # New token must succeed — no restart happened.
            status, _ = _post(
                server, "/api/overrides", payload={"ban_source_ids": []},
                headers={"X-Idle-Hours-Token": "second-secret"},
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

    def test_stat_failure_on_hot_reload_logs_and_keeps_previous_token(self, tmp_path, capsys):
        """If stat() raises on a non-initial hot-reload call (file present at startup,
        then permission revoked), the previous token must be kept and the failure logged.
        This covers the ``if not initial: _log(...)`` branch at web_server.py:163-165.
        """
        token_file = tmp_path / "token"
        token_file.write_text("secret\n", encoding="utf-8")

        args = _make_args(tmp_path, web_bind="127.0.0.1:0", web_token_file=str(token_file))
        state = run_clock.RuntimeState(args.theme)
        ctx = web_server.WebContext(args, state, token="", token_file=str(token_file))
        assert ctx.current_token() == "secret"

        # Force mtime to differ so the next call doesn't short-circuit on mtime equality,
        # then make stat() raise on the hot-reload path.
        ctx._cached_token_mtime = -1  # anything != actual mtime

        from pathlib import Path
        from unittest.mock import patch as _patch

        real_stat = Path.stat

        def _bad_stat(self, *args, **kwargs):
            if self == ctx._token_file:
                raise OSError("permission denied")
            return real_stat(self, *args, **kwargs)

        with _patch.object(Path, "stat", _bad_stat):
            result = ctx.current_token()

        # Token unchanged.
        assert result == "secret"
        err = capsys.readouterr().err
        assert "unreadable" in err or "permission" in err

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
        assert b"Idle Hours" in body

    def test_static_js_and_css(self, live_server):
        server, _, _ = live_server
        js_status, js_body = _get(server, "/main.js")
        css_status, _ = _get(server, "/style.css")
        assert js_status == 200
        assert css_status == 200
        assert b"jsonFetch" in js_body

    def test_main_js_attaches_x_idle_hours_token_header(self, live_server):
        """Regression guard for the LAN+token UX gap: the bundled UI must
        attach ``X-Idle-Hours-Token`` from localStorage to every fetch.
        Without this header, every POST on a tokenised LAN bind 401s and
        the documented operator workflow is unusable.

        This is a JS source check rather than an integration test —
        running an actual browser is out of scope for the test suite,
        but a future regression that drops the header from main.js would
        silently break LAN deployments and is worth pinning."""
        server, _, _ = live_server
        _, js_body = _get(server, "/main.js")
        text = js_body.decode("utf-8")
        # Sentinel strings — the implementation may evolve, but these
        # invariants must hold:
        assert "X-Idle-Hours-Token" in text, (
            "main.js no longer references the X-Idle-Hours-Token header — "
            "LAN+token deployments will break. See fix #1 in the v2 review."
        )
        assert "localStorage" in text, (
            "main.js no longer persists the operator's token via localStorage — "
            "every page reload would re-prompt for it."
        )
        # 401 recovery loop: verify the JS at least has the prompt-on-401
        # path so a fresh visit can recover without a manual settings UI.
        assert "401" in text and "promptForToken" in text

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
        with patch("idle_hours.run_clock.current_time_str", return_value="03:00"):
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
        with patch("idle_hours.run_clock.current_time_str", return_value="12:00"):
            status, body = _get(server, "/api/current")
        assert status == 200
        data = _json_body(body)
        assert data["source_id"] is None
        assert data["line_number"] is None

    def test_api_telemetry_reuses_health_loader(self, tmp_path, live_server):
        server, _state, args = live_server
        # Write one successful render entry via date-rotated sidecar.
        import datetime as dt

        from idle_hours import idle_hours_health  # noqa: F401  (sanity that it imports)
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
        from idle_hours.theme_names import theme_cycle
        server, state, _args = live_server
        with state.lock:
            state.manual_theme = "scholar"
            state.last_effective_theme = "scholar"
        status, body = _get(server, "/api/themes")
        assert status == 200
        data = _json_body(body)
        # /api/themes returns theme_cycle() (THEME_ORDER minus CYCLE_EXCLUDED_THEMES),
        # not the raw registration tuple — opt-in-only themes are deliberately absent
        # from the dropdown.
        assert data["themes"] == list(theme_cycle())
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
        with patch("idle_hours.pick_quote.select_candidates", return_value=fake):
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
        with patch("idle_hours.pick_quote.select_candidates", side_effect=SystemExit("no candidates")):
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
        # Initial GET when file doesn't exist returns empty schema (including
        # the v2 ban_quote_keys field defaulted to []).
        status, body = _get(server, "/api/overrides")
        assert status == 200
        assert _json_body(body) == {
            "ban_source_ids": [],
            "boost_source_ids": [],
            "preferred_buckets": {},
            "ban_quote_keys": [],
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

    def test_api_history_empty_ledger_returns_empty_list(self, tmp_path, live_server):
        """When the history ledger is empty or missing, the endpoint returns an
        empty entries list without error (covers web_server.py:1092)."""
        server, _, args = live_server
        # Ensure the ledger does not exist.
        Path(args.history_path).unlink(missing_ok=True)
        status, body = _get(server, "/api/history")
        assert status == 200
        data = _json_body(body)
        assert data["entries"] == []
        assert data["total"] == 0

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
            "idle_hours.run_clock",
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

        with patch("idle_hours.run_clock._render_unlocked", side_effect=fake_render), \
             patch("idle_hours.run_clock.peek_quote_id", return_value=("141", 1, "q", "m")):
            status, body = _post(server, "/api/action/quiet")
        assert status == 200
        assert _json_body(body)["manual_quiet"] is False
        assert rendered["count"] == 1

    def test_rerender_uses_current_time_and_bucket(self, live_server):
        server, _state, _args = live_server
        calls = []

        def fake_render(_args, _state, time_str, _hp, bucket=None, quote_id=None, **_kw):
            calls.append((time_str, bucket, quote_id))

        with patch("idle_hours.run_clock._render_unlocked", side_effect=fake_render), \
             patch("idle_hours.run_clock.peek_quote_id", return_value=("141", 1, "q", "m")), \
             patch("idle_hours.run_clock.current_time_str", return_value="03:15"):
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
        with patch("idle_hours.run_clock._render_unlocked", side_effect=RuntimeError("boom")):
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
        """Callers who really want to clear state spell it out explicitly.
        ban_quote_keys is defaulted to [] when omitted so v1 clients keep working."""
        out = web_server.validate_overrides_payload({
            "ban_source_ids": [],
            "boost_source_ids": [],
            "preferred_buckets": {},
        })
        assert out == {
            "ban_source_ids": [],
            "boost_source_ids": [],
            "preferred_buckets": {},
            "ban_quote_keys": [],
        }

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
        with patch("idle_hours.atomic_io.atomic_write_text", side_effect=fake):
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
        with patch("idle_hours.run_clock._render_unlocked"), \
             patch("idle_hours.run_clock.peek_quote_id", return_value=("141", 1, "q", "m")):
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
            status, body = _post(server, "/api/action/theme", headers={"X-Idle-Hours-Token": "nope"})
            assert status == 401
        finally:
            run_clock.stop_web_server((server, thread))

    def test_token_required_post_with_correct_header_allowed(self, tmp_path):
        args = _make_args(tmp_path, web_bind="0.0.0.0:0")
        state = run_clock.RuntimeState(args.theme)
        server, thread = web_server.start_web_server(args, state, token="secret")
        try:
            with patch("idle_hours.run_clock._render_unlocked"), \
                 patch("idle_hours.run_clock.peek_quote_id", return_value=("141", 1, "q", "m")):
                status, _ = _post(
                    server, "/api/action/theme",
                    headers={"X-Idle-Hours-Token": "secret"},
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
        from idle_hours import run_clock as rc
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
# (github.com/gkoch02/idle-hours issue #55)
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
            status, _ = _post(server, "/api/action/theme", headers={"X-Idle-Hours-Token": "wrong"})
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
        the X-Idle-Hours-Token header) would otherwise plant the secret in the
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
            with patch("idle_hours.run_clock._render_unlocked"), \
                 patch("idle_hours.run_clock.peek_quote_id", return_value=("141", 1, "q", "m")):
                status, _ = _post(
                    server, "/api/action/theme",
                    headers={"X-Idle-Hours-Token": "secret"},
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
            with patch("idle_hours.run_clock._render_unlocked"), \
                 patch("idle_hours.run_clock.peek_quote_id", return_value=("141", 1, "q", "m")):
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

            monkeypatch.setattr("idle_hours.web_server.hmac.compare_digest", spy)

            status, _ = _post(
                server, "/api/action/theme",
                headers={"X-Idle-Hours-Token": "secret"},
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
            with patch("idle_hours.run_clock._render_unlocked"), \
                 patch("idle_hours.run_clock.peek_quote_id", return_value=("141", 1, "q", "m")):
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


# ============================================================================
# v2: Per-row content overrides
# ============================================================================

def _make_args_v2(tmp_path: Path, **overrides) -> argparse.Namespace:
    """Args helper that also wires the v2 corpus / sidecar / baked-DB paths.

    Kept separate from the v1 ``_make_args`` to keep existing tests untouched.
    """
    args = _make_args(tmp_path, **overrides)
    args.content_overrides = overrides.get(
        "content_overrides", str(tmp_path / "content_overrides.json"),
    )
    args.raw_corpus = overrides.get("raw_corpus", str(tmp_path / "candidates-attributed.jsonl"))
    args.baked_db = overrides.get("baked_db", str(tmp_path / "quote_database.jsonl"))
    return args


def _start_v2(tmp_path: Path, *, token: str = "", args: argparse.Namespace | None = None,
              state: run_clock.RuntimeState | None = None):
    args = args or _make_args_v2(tmp_path)
    state = state or run_clock.RuntimeState(args.theme)
    server, thread = web_server.start_web_server(args, state, token=token)
    return server, thread, state, args


@pytest.fixture
def v2_server(tmp_path):
    server, thread, state, args = _start_v2(tmp_path)
    yield server, state, args
    run_clock.stop_web_server((server, thread))


class TestApiContentOverrides:
    def test_get_returns_empty_when_sidecar_missing(self, v2_server):
        server, _state, _args = v2_server
        status, body = _get(server, "/api/content-overrides")
        assert status == 200
        assert _json_body(body) == {}

    def test_get_returns_existing_sidecar(self, v2_server):
        server, _state, args = v2_server
        Path(args.content_overrides).write_text(json.dumps(
            {"141:482": {"display_quote": "patched text"}},
        ), encoding="utf-8")
        status, body = _get(server, "/api/content-overrides")
        assert status == 200
        assert _json_body(body) == {"141:482": {"display_quote": "patched text"}}

    def test_get_fail_open_on_corrupt_sidecar(self, v2_server):
        server, _state, args = v2_server
        Path(args.content_overrides).write_text("not-valid-json{", encoding="utf-8")
        # apply_content_overrides.load_overrides logs and returns {} — UI never 500s.
        status, body = _get(server, "/api/content-overrides")
        assert status == 200
        assert _json_body(body) == {}

    def test_post_round_trip(self, v2_server):
        server, _state, args = v2_server
        payload = {"141:482": {"display_quote": "It was three o'clock."}}
        status, body = _post(server, "/api/content-overrides", payload)
        assert status == 200, _json_body(body)
        on_disk = json.loads(Path(args.content_overrides).read_text(encoding="utf-8"))
        assert on_disk == payload

    def test_post_empty_payload_wipes_sidecar(self, v2_server):
        """An empty {} POST is a legitimate "wipe all per-row overrides" action
        — different from selection_overrides where the keys must be present
        because their absence couldn't be distinguished from a wipe."""
        server, _state, args = v2_server
        Path(args.content_overrides).write_text(
            json.dumps({"141:482": {"display_quote": "old"}}), encoding="utf-8",
        )
        status, _ = _post(server, "/api/content-overrides", {})
        assert status == 200
        on_disk = json.loads(Path(args.content_overrides).read_text(encoding="utf-8"))
        assert on_disk == {}

    def test_post_rejects_bad_key_shape(self, v2_server):
        server, _state, _args = v2_server
        status, body = _post(server, "/api/content-overrides",
                             {"not-a-valid-key": {"display_quote": "x"}})
        assert status == 400
        assert "source_id" in _json_body(body)["error"]

    def test_post_rejects_unknown_field(self, v2_server):
        server, _state, _args = v2_server
        status, body = _post(server, "/api/content-overrides",
                             {"141:482": {"unknown_field": "x"}})
        assert status == 400
        assert "unsupported" in _json_body(body)["error"]

    def test_post_rejects_wrong_field_type_for_string(self, v2_server):
        server, _state, _args = v2_server
        status, body = _post(server, "/api/content-overrides",
                             {"141:482": {"display_quote": 123}})
        assert status == 400
        assert "must be a string" in _json_body(body)["error"]

    def test_post_rejects_wrong_field_type_for_int(self, v2_server):
        server, _state, _args = v2_server
        status, body = _post(server, "/api/content-overrides",
                             {"141:482": {"hour": "not an int"}})
        assert status == 400
        assert "must be an int" in _json_body(body)["error"]

    def test_post_body_too_large_returns_400(self, v2_server):
        """A POST body exceeding MAX_BODY_BYTES must be rejected with 400.
        Exercises the ``length > MAX_BODY_BYTES`` branch in _read_json_body
        (web_server.py:441)."""
        server, _state, _args = v2_server
        conn = _client(server)
        # Send a Content-Length that exceeds the limit but don't send the body —
        # the handler should reject before reading.
        big = web_server.MAX_BODY_BYTES + 1
        conn.request(
            "POST", "/api/content-overrides",
            headers={"Content-Length": str(big), "Content-Type": "application/json"},
            body=b"",
        )
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        assert resp.status == 400
        assert "too large" in _json_body(body)["error"].lower()


# ============================================================================
# v2: ban_quote_keys
# ============================================================================

class TestBanQuoteKeys:
    def test_get_overrides_surfaces_default_ban_quote_keys(self, live_server):
        """Legacy on-disk files don't have ban_quote_keys; the GET endpoint
        defaults the field so the UI editor doesn't need to special-case it."""
        server, _, args = live_server
        Path(args.overrides).write_text(json.dumps({
            "ban_source_ids": [],
            "boost_source_ids": [],
            "preferred_buckets": {},
        }), encoding="utf-8")
        status, body = _get(server, "/api/overrides")
        assert status == 200
        assert _json_body(body)["ban_quote_keys"] == []

    def test_post_round_trip_ban_quote_keys(self, live_server):
        server, _, args = live_server
        payload = {
            "ban_source_ids": [],
            "boost_source_ids": [],
            "preferred_buckets": {},
            "ban_quote_keys": ["141:482", "1342:99"],
        }
        status, body = _post(server, "/api/overrides", payload)
        assert status == 200, _json_body(body)
        on_disk = json.loads(Path(args.overrides).read_text(encoding="utf-8"))
        assert on_disk["ban_quote_keys"] == ["141:482", "1342:99"]

    def test_post_rejects_bad_ban_quote_key_shape(self, live_server):
        server, _, _ = live_server
        status, body = _post(server, "/api/overrides", {
            "ban_source_ids": [],
            "boost_source_ids": [],
            "preferred_buckets": {},
            "ban_quote_keys": ["not-valid"],
        })
        assert status == 400
        assert "source_id" in _json_body(body)["error"]

    def test_post_rejects_non_list_ban_quote_keys(self, live_server):
        server, _, _ = live_server
        status, body = _post(server, "/api/overrides", {
            "ban_source_ids": [],
            "boost_source_ids": [],
            "preferred_buckets": {},
            "ban_quote_keys": "141:482",  # string, not list
        })
        assert status == 400
        assert "list" in _json_body(body)["error"]

    def test_payload_with_only_ban_quote_keys_is_accepted(self, live_server):
        """OVERRIDES_KEYS includes ban_quote_keys, so a POST that only sets it
        is valid (the validator's "at least one key" guard accepts it)."""
        server, _, args = live_server
        status, _ = _post(server, "/api/overrides", {"ban_quote_keys": ["141:482"]})
        assert status == 200
        on_disk = json.loads(Path(args.overrides).read_text(encoding="utf-8"))
        assert on_disk["ban_quote_keys"] == ["141:482"]


# ============================================================================
# v2: /api/bake
# ============================================================================

class TestApiBake:
    def _write_corpus(self, args, rows):
        Path(args.raw_corpus).write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8",
        )

    def test_bake_succeeds_and_writes_baked_db(self, v2_server):
        server, _state, args = v2_server
        rows = [
            {
                "source_id": "141", "line_number": 1,
                "display_quote": "It was three o'clock in the afternoon, exactly.",
                "matched_text": "three o'clock", "normalized_time": "03:00",
                "fuzzy_bucket": "h3_exact", "quality_score": 80,
                "display_fragment": False, "cleanup_status": "complete_sentence",
                "author": "Jane Austen", "title": "Mansfield Park",
            },
        ]
        self._write_corpus(args, rows)
        status, body = _post(server, "/api/bake", None)
        assert status == 200, _json_body(body)
        data = _json_body(body)
        assert data["ok"] is True
        assert data["kept"] == 1
        assert Path(args.baked_db).exists()
        baked = [json.loads(line) for line in Path(args.baked_db).read_text(encoding="utf-8").splitlines() if line]
        assert len(baked) == 1
        assert "baked_score" in baked[0]

    def test_bake_applies_content_overrides_first(self, v2_server):
        """Overrides edited just before the bake must be reflected in the
        baked DB on the very next render — that's the whole point of in-UI bake."""
        server, _state, args = v2_server
        rows = [{
            "source_id": "141", "line_number": 1,
            "display_quote": "ORIGINAL TEXT.",
            "matched_text": "three o'clock", "normalized_time": "03:00",
            "fuzzy_bucket": "h3_exact", "quality_score": 80,
            "display_fragment": False, "cleanup_status": "complete_sentence",
        }]
        self._write_corpus(args, rows)
        Path(args.content_overrides).write_text(json.dumps({
            "141:1": {"display_quote": "PATCHED TEXT."},
        }), encoding="utf-8")
        status, body = _post(server, "/api/bake", None)
        assert status == 200, _json_body(body)
        baked = [json.loads(line) for line in Path(args.baked_db).read_text(encoding="utf-8").splitlines() if line]
        assert baked[0]["display_quote"] == "PATCHED TEXT."
        assert _json_body(body)["applied_overrides"] == 1

    def test_bake_returns_409_when_render_in_flight(self, v2_server):
        server, state, _args = v2_server
        # Hold the lock to simulate an in-flight render.
        state.render_lock.acquire()
        try:
            status, body = _post(server, "/api/bake", None)
        finally:
            state.render_lock.release()
        assert status == 409
        assert _json_body(body)["error"] == "busy"

    def test_bake_500_when_corpus_missing(self, v2_server):
        server, _state, args = v2_server
        # Make sure the raw corpus really is absent.
        p = Path(args.raw_corpus)
        if p.exists():
            p.unlink()
        status, body = _post(server, "/api/bake", None)
        assert status == 500
        assert "missing" in _json_body(body)["error"]


# ============================================================================
# v2: /api/search
# ============================================================================

class TestApiSearch:
    def _write_corpus(self, args, rows):
        Path(args.raw_corpus).write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8",
        )

    def test_search_by_text(self, v2_server):
        server, _state, args = v2_server
        self._write_corpus(args, [
            {"source_id": "141", "line_number": 1, "display_quote": "Tea at three.",
             "author": "Jane Austen", "title": "Emma", "fuzzy_bucket": "h3_exact"},
            {"source_id": "141", "line_number": 2, "display_quote": "Coffee at four.",
             "author": "Jane Austen", "title": "Emma", "fuzzy_bucket": "h4_exact"},
        ])
        status, body = _get(server, "/api/search?q=tea")
        assert status == 200
        data = _json_body(body)
        assert data["total"] == 1
        assert data["results"][0]["display_quote"] == "Tea at three."

    def test_search_by_author_and_bucket(self, v2_server):
        server, _state, args = v2_server
        self._write_corpus(args, [
            {"source_id": "141", "line_number": 1, "display_quote": "x",
             "author": "Dickens", "title": "Bleak House", "fuzzy_bucket": "h3_exact"},
            {"source_id": "200", "line_number": 1, "display_quote": "y",
             "author": "Austen", "title": "Emma", "fuzzy_bucket": "h3_exact"},
            {"source_id": "141", "line_number": 2, "display_quote": "z",
             "author": "Dickens", "title": "Bleak House", "fuzzy_bucket": "h4_exact"},
        ])
        status, body = _get(server, "/api/search?author=dickens&bucket=h3_exact")
        assert status == 200
        data = _json_body(body)
        assert data["total"] == 1
        assert data["results"][0]["source_id"] == "141"

    def test_search_requires_at_least_one_filter(self, v2_server):
        server, _state, _args = v2_server
        status, body = _get(server, "/api/search")
        assert status == 400
        assert "required" in _json_body(body)["error"]

    def test_search_rejects_bad_bucket(self, v2_server):
        server, _state, _args = v2_server
        status, body = _get(server, "/api/search?bucket=not_a_bucket")
        assert status == 400
        assert "unknown bucket" in _json_body(body)["error"]

    def test_search_clamps_limit(self, v2_server):
        server, _state, args = v2_server
        self._write_corpus(args, [
            {"source_id": str(i), "line_number": 1, "display_quote": "match me",
             "fuzzy_bucket": "h3_exact"} for i in range(20)
        ])
        status, body = _get(server, "/api/search?q=match&limit=5")
        assert status == 200
        assert len(_json_body(body)["results"]) == 5

    def test_search_handles_missing_corpus(self, v2_server):
        server, _state, args = v2_server
        p = Path(args.raw_corpus)
        if p.exists():
            p.unlink()
        status, body = _get(server, "/api/search?q=anything")
        assert status == 200
        data = _json_body(body)
        assert data["total"] == 0
        assert "missing" in data.get("note", "")


# ============================================================================
# v2: /api/preview
# ============================================================================

class TestApiPreview:
    def test_preview_returns_png(self, v2_server):
        server, _state, _args = v2_server
        # Mock the picker so the test doesn't depend on the full corpus being baked.
        fake_row = {
            "display_quote": "It was three o'clock in the afternoon, exactly.",
            "matched_text": "three o'clock",
            "author": "Jane Austen", "title": "Emma",
            "normalized_time": "03:00", "fuzzy_bucket": "h3_exact",
            "source_id": "141", "line_number": 42,
        }
        with patch("idle_hours.pick_quote.select_quote", return_value=fake_row):
            status, body = _get(server, "/api/preview?theme=default&time=03:00&width=400&height=240")
        assert status == 200
        # Spectra 6 PNG signature.
        assert body.startswith(b"\x89PNG\r\n\x1a\n")

    def test_preview_rejects_unknown_theme(self, v2_server):
        server, _state, _args = v2_server
        status, body = _get(server, "/api/preview?theme=not-a-theme")
        assert status == 400
        assert "unknown theme" in _json_body(body)["error"]

    def test_preview_rejects_bad_time(self, v2_server):
        server, _state, _args = v2_server
        status, body = _get(server, "/api/preview?theme=default&time=garbage")
        assert status == 400
        assert "HH:MM" in _json_body(body)["error"]

    def test_preview_rejects_out_of_range_minute(self, v2_server):
        """``time=03:99`` parses as two ints but is out of range. Without
        explicit bound checking, the request reaches ``bucket_for_time``,
        which raises ``KeyError`` from ``minute_bucket`` and surfaces as
        a 500 instead of a 400 client error. Regression guard for the
        Codex review finding on PR #96."""
        server, _state, _args = v2_server
        status, body = _get(server, "/api/preview?theme=default&time=03:99")
        assert status == 400, _json_body(body)
        assert "HH:MM" in _json_body(body)["error"]

    def test_preview_rejects_out_of_range_hour(self, v2_server):
        """``time=25:00`` doesn't crash bucket_for_time today (hour wraps
        modulo 12) but the minute_distance penalty math has no bound, so
        a future change could turn this into a crash. Reject at the API
        boundary regardless."""
        server, _state, _args = v2_server
        status, body = _get(server, "/api/preview?theme=default&time=25:00")
        assert status == 400
        assert "HH:MM" in _json_body(body)["error"]

    def test_preview_rejects_negative_minute(self, v2_server):
        """``time=03:-1`` parses as two ints; without the lower-bound check
        we'd index BUCKET_ORDER with a negative wrap and silently return
        the wrong bucket."""
        server, _state, _args = v2_server
        status, body = _get(server, "/api/preview?theme=default&time=03:-1")
        assert status == 400
        assert "HH:MM" in _json_body(body)["error"]

    def test_preview_accepts_boundary_times(self, v2_server):
        """00:00 and 23:59 are both inclusive bounds — they must pass."""
        server, _state, _args = v2_server
        fake_row = {
            "display_quote": "x", "matched_text": "x",
            "normalized_time": "00:00", "fuzzy_bucket": "h12_exact",
            "source_id": "1", "line_number": 1,
        }
        with patch("idle_hours.pick_quote.select_quote", return_value=fake_row):
            for boundary in ("00:00", "23:59"):
                # Small width/height keeps each real PIL render well under the
                # 3 s ``_client`` timeout — at 800×480 with coverage tracing
                # on a contended CI runner, a single render can exceed it and
                # flake the assertion. Matches the size ``test_preview_returns_png``
                # already uses for the same reason.
                status, _body = _get(server, f"/api/preview?theme=default&time={boundary}&width=400&height=240")
                assert status == 200, f"{boundary} should be accepted"

    def test_preview_swallows_picker_failure(self, v2_server):
        server, _state, _args = v2_server
        with patch("idle_hours.pick_quote.select_quote", side_effect=SystemExit("no picks")):
            status, body = _get(server, "/api/preview?theme=default&time=03:00")
        assert status == 404

    def test_preview_render_failure_returns_500(self, v2_server):
        """If render_quote.render raises after a successful pick, the endpoint
        must return 500 — not propagate the exception to the HTTP layer.
        Covers web_server.py:1049-1050."""
        server, _state, _args = v2_server
        fake_row = {
            "display_quote": "It was three.", "matched_text": "three",
            "normalized_time": "03:00", "fuzzy_bucket": "h3_exact",
            "source_id": "1", "line_number": 1,
        }
        with patch("idle_hours.pick_quote.select_quote", return_value=fake_row), \
             patch("idle_hours.render_quote.render", side_effect=RuntimeError("pillow exploded")):
            status, body = _get(server, "/api/preview?theme=default&time=03:00")
        assert status == 500

    def test_preview_clamps_dimensions(self, v2_server):
        """A scanner asking for 100000x100000 must not be honoured."""
        server, _state, _args = v2_server
        fake_row = {
            "display_quote": "x", "matched_text": "x",
            "normalized_time": "03:00", "fuzzy_bucket": "h3_exact",
            "source_id": "1", "line_number": 1,
        }
        image = Image.new("RGB", (1, 1), "white")
        with (
            patch("idle_hours.pick_quote.select_quote", return_value=fake_row),
            patch("idle_hours.render_quote.render", return_value=image) as render,
        ):
            status, body = _get(server, "/api/preview?theme=default&time=03:00&width=100000&height=100000")
        # Should not OOM — verify the untrusted request was capped before render.
        assert status == 200
        assert body.startswith(b"\x89PNG")
        render.assert_called_once()
        assert render.call_args.args[:4] == ("03:00", fake_row, 800, 480)


# ============================================================================
# v2: /api/gaps
# ============================================================================

class TestApiGaps:
    def test_gaps_lists_empty_buckets(self, v2_server):
        server, _state, _args = v2_server
        coverage = {
            "bucket_counts": {
                "h1_exact": 100, "h1_five_past": 0, "h1_ten_past": 2,
                "h2_quarter_to": 5, "h3_twenty_to": 0,
            },
        }
        fake = Path(_args.state_path).parent / "coverage.json"
        fake.write_text(json.dumps(coverage), encoding="utf-8")
        server.context.coverage_path = fake
        status, body = _get(server, "/api/gaps?threshold=3")
        assert status == 200
        data = _json_body(body)
        # Three buckets at-or-below threshold of 3: 1×0 (h1_five_past),
        # 1×0 (h3_twenty_to), 1×2 (h1_ten_past)
        assert data["total"] == 3
        # Sorted emptiest-first.
        assert data["buckets"][0]["count"] == 0
        # Phrases populated for non-exact states.
        twenty_to = next(b for b in data["buckets"] if b["bucket"] == "h3_twenty_to")
        assert any("twenty to" in p for p in twenty_to["phrases"])

    def test_gaps_handles_missing_coverage(self, v2_server):
        server, _state, _args = v2_server
        server.context.coverage_path = Path(_args.state_path).parent / "no_such_coverage.json"
        status, body = _get(server, "/api/gaps")
        assert status == 200
        assert _json_body(body)["buckets"] == []

    def test_gaps_rejects_bad_threshold(self, v2_server):
        server, _state, _args = v2_server
        status, body = _get(server, "/api/gaps?threshold=abc")
        assert status == 400
        assert "threshold" in _json_body(body)["error"]


# ============================================================================
# v2: validators
# ============================================================================

class TestContentOverridesValidator:
    def test_accepts_minimal(self):
        cleaned = web_server.validate_content_overrides_payload({"141:42": {"display_quote": "x"}})
        assert cleaned == {"141:42": {"display_quote": "x"}}

    def test_accepts_empty(self):
        # Wipe semantics: explicit choice, allowed.
        assert web_server.validate_content_overrides_payload({}) == {}

    def test_rejects_non_dict(self):
        with pytest.raises(ValueError, match="JSON object"):
            web_server.validate_content_overrides_payload([])

    def test_rejects_bad_key(self):
        with pytest.raises(ValueError, match="source_id"):
            web_server.validate_content_overrides_payload({"abc": {"display_quote": "x"}})

    def test_rejects_non_dict_value(self):
        with pytest.raises(ValueError, match="object"):
            web_server.validate_content_overrides_payload({"141:42": "not an object"})

    def test_rejects_unknown_field(self):
        with pytest.raises(ValueError, match="unsupported"):
            web_server.validate_content_overrides_payload({"141:42": {"bogus": "x"}})

    def test_validates_field_types(self):
        # display_quote must be a string
        with pytest.raises(ValueError, match="must be a string"):
            web_server.validate_content_overrides_payload({"141:42": {"display_quote": 5}})
        # hour must be an int (not bool)
        with pytest.raises(ValueError, match="must be an int"):
            web_server.validate_content_overrides_payload({"141:42": {"hour": True}})


# ============================================================================
# v2: /metrics (Prometheus text format)
# ============================================================================

class TestMetricsEndpoint:
    def _write_telemetry(self, args, entries):
        import datetime as dt
        today = dt.datetime.now().strftime("%Y%m%d")
        rotated = Path(args.telemetry_path).with_name(
            f"{Path(args.telemetry_path).stem}-{today}.jsonl",
        )
        rotated.parent.mkdir(parents=True, exist_ok=True)
        rotated.write_text(
            "\n".join(json.dumps({"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **e}) for e in entries) + "\n",
        )

    def test_metrics_returns_text_exposition_format(self, live_server):
        server, _state, args = live_server
        self._write_telemetry(args, [
            {"render_ms": 120, "display_ms": 15000, "bucket": "h3_exact", "mode": "debug"},
            {"render_ms": 130, "display_ms": 14000, "bucket": "h3_exact", "mode": "debug"},
            {"error": "boom", "bucket": "h3_exact", "mode": "debug"},
        ])
        status, body = _get(server, "/metrics")
        assert status == 200
        text = body.decode("utf-8")
        # Required Prometheus header lines must appear for every metric.
        assert "# HELP idle_hours_renders_total" in text
        assert "# TYPE idle_hours_renders_total" in text
        # The render count comes from idle_hours_health.summarise — the same
        # source as /api/telemetry, so the values must match exactly.
        assert "idle_hours_renders_total 2" in text
        assert "idle_hours_errors_total 1" in text
        # p50 / p95 latencies are gauges with integer milliseconds.
        assert "idle_hours_render_p50_ms" in text
        assert "idle_hours_display_p50_ms" in text

    def test_metrics_no_telemetry_returns_zeros(self, tmp_path):
        """A telemetry-disabled appliance still exposes the metric names so
        Prometheus's first-scrape doesn't see missing series. Otherwise rate()
        would silently return no data on a fresh install."""
        args = _make_args(tmp_path, telemetry_path="")
        state = run_clock.RuntimeState(args.theme)
        server, thread = web_server.start_web_server(args, state)
        try:
            status, body = _get(server, "/metrics")
            assert status == 200
            text = body.decode("utf-8")
            assert "idle_hours_renders_total 0" in text
            assert "idle_hours_errors_total 0" in text
        finally:
            run_clock.stop_web_server((server, thread))

    def test_metrics_content_type_is_prometheus_format(self, live_server):
        """Prometheus identifies the parser by Content-Type version. Must end
        with ``version=0.0.4`` for the standard text-exposition parser."""
        server, _, _ = live_server
        conn = _client(server)
        conn.request("GET", "/metrics")
        resp = conn.getresponse()
        resp.read()
        ctype = resp.getheader("Content-Type")
        conn.close()
        assert ctype is not None
        assert "text/plain" in ctype
        assert "version=0.0.4" in ctype

    def test_metrics_no_auth_required(self, tmp_path):
        """The metrics endpoint stays open on every bind so Prometheus can
        scrape without managing a token. Other GETs follow the same convention."""
        args = _make_args(tmp_path, web_bind="127.0.0.1:0")
        state = run_clock.RuntimeState(args.theme)
        server, thread = web_server.start_web_server(args, state, token="secret-token")
        try:
            # No X-Idle-Hours-Token header.
            status, _ = _get(server, "/metrics")
            assert status == 200
        finally:
            run_clock.stop_web_server((server, thread))


# ============================================================================
# v2: First-run setup wizard
# ============================================================================

class TestApiSetup:
    def test_get_setup_returns_complete_false_initially(self, live_server):
        server, state, _args = live_server
        # Default RuntimeState has setup_complete = False so the wizard fires.
        assert state.setup_complete is False
        status, body = _get(server, "/api/setup")
        assert status == 200
        data = _json_body(body)
        assert data["setup_complete"] is False
        assert "themes" in data
        assert isinstance(data["themes"], list)
        assert "quiet_start" in data and "quiet_end" in data

    def test_post_dismiss_marks_setup_complete(self, live_server):
        server, state, args = live_server
        # No body == "I'm ready" without changing the theme.
        status, body = _post(server, "/api/setup", {})
        assert status == 200
        data = _json_body(body)
        assert data["ok"] is True
        assert data["setup_complete"] is True
        # In-memory flag flipped.
        with state.lock:
            assert state.setup_complete is True
        # Persisted to state.json so a reload doesn't re-trigger the wizard.
        on_disk = json.loads(Path(args.state_path).read_text(encoding="utf-8"))
        assert on_disk["setup_complete"] is True

    def test_post_with_theme_applies_and_completes(self, live_server):
        server, state, args = live_server
        # action_theme returns ok=True only if it can render — patch the
        # render path (run_clock._render_unlocked) so we don't actually
        # invoke pillow / pick_quote here.
        with patch("idle_hours.run_clock._render_unlocked"), \
             patch("idle_hours.run_clock.peek_quote_id", return_value=("141", 1, "q", "m")):
            status, body = _post(server, "/api/setup", {"theme": "scholar"})
        assert status == 200, _json_body(body)
        data = _json_body(body)
        assert data["setup_complete"] is True
        assert data["applied_theme"] is not None
        with state.lock:
            assert state.manual_theme == "scholar"

    def test_post_rejects_unknown_theme(self, live_server):
        server, _state, _args = live_server
        with patch("idle_hours.run_clock._render_unlocked"), \
             patch("idle_hours.run_clock.peek_quote_id", return_value=("141", 1, "q", "m")):
            status, body = _post(server, "/api/setup", {"theme": "imaginary-theme"})
        assert status == 400
        assert "unknown theme" in _json_body(body)["error"]

    def test_post_rejects_non_string_theme(self, live_server):
        server, _state, _args = live_server
        status, body = _post(server, "/api/setup", {"theme": 42})
        assert status == 400
        assert "string" in _json_body(body)["error"]

    def test_get_after_post_reflects_complete_true(self, live_server):
        """Once dismissed, subsequent GETs report the wizard is done so the
        UI doesn't re-overlay it on every page reload."""
        server, _state, _args = live_server
        _post(server, "/api/setup", {})
        status, body = _get(server, "/api/setup")
        assert status == 200
        assert _json_body(body)["setup_complete"] is True

    def test_post_does_not_complete_when_theme_apply_busy(self, live_server):
        """If a render is in flight when the wizard tries to apply a theme,
        ``action_theme`` returns ``error="busy"``. We must NOT flip
        ``setup_complete`` — closing the wizard while the panel still shows
        the old theme is confusing UX. Operator's next click retries."""
        server, state, args = live_server
        with patch("idle_hours.run_clock.action_theme", return_value={"ok": False, "error": "busy"}):
            status, body = _post(server, "/api/setup", {"theme": "scholar"})
        assert status == 409, _json_body(body)
        data = _json_body(body)
        assert data["setup_complete"] is False
        assert data["applied_theme"]["error"] == "busy"
        # In-memory flag must not have flipped.
        with state.lock:
            assert state.setup_complete is False
        # state.json must not have a setup_complete=True written either.
        if Path(args.state_path).exists():
            on_disk = json.loads(Path(args.state_path).read_text(encoding="utf-8"))
            assert on_disk.get("setup_complete", False) is False

    def test_post_does_not_complete_when_theme_apply_5xx(self, live_server):
        """Generic theme-handler exception → 500 + setup stays incomplete."""
        server, state, _args = live_server
        with patch("idle_hours.run_clock.action_theme",
                   return_value={"ok": False, "error": "RuntimeError('boom')"}):
            status, body = _post(server, "/api/setup", {"theme": "scholar"})
        assert status == 500
        data = _json_body(body)
        assert data["setup_complete"] is False
        with state.lock:
            assert state.setup_complete is False

    def test_post_persist_failure_does_not_block_in_memory_flip(self, live_server):
        """If state.json write fails, we keep the in-memory flag flipped
        for the current session and log. Operator can fix the disk later."""
        server, state, _args = live_server
        with patch("idle_hours.runtime_store.save_runtime_state", side_effect=OSError("disk full")):
            status, body = _post(server, "/api/setup", {})
        assert status == 200, _json_body(body)
        assert _json_body(body)["setup_complete"] is True
        with state.lock:
            assert state.setup_complete is True


# ============================================================================
# v2: webhook fan-out from append_telemetry
# ============================================================================

class TestTelemetryWebhookFanout:
    def test_append_telemetry_calls_webhook_when_configured(self, tmp_path):
        """append_telemetry reads the module-level webhook config; an error
        entry should fan out to the webhook on a daemon thread."""
        from idle_hours import runtime_telemetry, runtime_webhook
        runtime_webhook.configure("https://x.test/h")
        try:
            with patch("idle_hours.runtime_webhook.post_event") as post:
                runtime_telemetry.append_telemetry(
                    str(tmp_path / "telemetry.jsonl"),
                    {"error": "boom", "bucket": "h3_exact"},
                )
            post.assert_called_once()
            args, kwargs = post.call_args
            assert args[0] == "https://x.test/h"
            assert args[1]["error"] == "boom"
        finally:
            runtime_webhook.configure(None)

    def test_append_telemetry_skips_webhook_when_unconfigured(self, tmp_path):
        """An unconfigured webhook URL must not fire post_event at all."""
        from idle_hours import runtime_telemetry, runtime_webhook
        runtime_webhook.configure(None)
        with patch("idle_hours.runtime_webhook.post_event") as post:
            runtime_telemetry.append_telemetry(
                str(tmp_path / "telemetry.jsonl"),
                {"error": "boom"},
            )
        post.assert_not_called()
