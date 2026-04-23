"""Tests for run_clock.py"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from unittest.mock import patch

import pytest

import run_clock


class TestCurrentBucket:
    def _bucket_for(self, hhmm: str) -> str:
        with patch("run_clock.current_time_str", return_value=hhmm):
            return run_clock.current_bucket()

    def test_midnight_exact(self):
        assert self._bucket_for("00:00") == "h12_exact"

    def test_noon_exact(self):
        assert self._bucket_for("12:00") == "h12_exact"

    def test_1pm_exact(self):
        assert self._bucket_for("13:00") == "h1_exact"

    def test_rounding_windows(self):
        assert self._bucket_for("03:01") == "h3_exact"
        assert self._bucket_for("03:03") == "h3_five_past"
        assert self._bucket_for("03:08") == "h3_ten_past"
        assert self._bucket_for("03:13") == "h3_quarter_past"
        assert self._bucket_for("03:18") == "h3_twenty_past"
        assert self._bucket_for("03:23") == "h3_twenty_five_past"
        assert self._bucket_for("03:28") == "h3_half_past"
        assert self._bucket_for("03:33") == "h3_twenty_five_to"
        assert self._bucket_for("03:38") == "h3_twenty_to"
        assert self._bucket_for("03:43") == "h3_quarter_to"
        assert self._bucket_for("03:48") == "h3_ten_to"
        assert self._bucket_for("03:53") == "h3_five_to"
        assert self._bucket_for("03:58") == "h4_exact"

    def test_hour12_maps_correctly(self):
        assert self._bucket_for("12:30") == "h12_half_past"

    def test_hour_wraps_at_24(self):
        assert self._bucket_for("23:00") == "h11_exact"

    def test_midnight_hour12(self):
        assert self._bucket_for("00:30") == "h12_half_past"


class TestRenderNow:
    def test_calls_render_script(self, tmp_path):
        with patch("subprocess.run") as mock_call, \
             patch("run_clock.current_time_str", return_value="14:30"):
            run_clock.render_now(
                render_script="render_quote.py",
                output_path=str(tmp_path / "current.png"),
                width=800,
                height=480,
            )
        assert mock_call.called
        cmd = mock_call.call_args[0][0]
        assert "--time" in cmd
        assert "14:30" in cmd
        assert "--output" in cmd
        assert "--width" in cmd
        assert "800" in cmd
        assert "--height" in cmd
        assert "480" in cmd

    def test_mode_passed_through(self, tmp_path):
        with patch("subprocess.run") as mock_call, \
             patch("run_clock.current_time_str", return_value="10:00"):
            run_clock.render_now(
                render_script="render_quote.py",
                output_path=str(tmp_path / "current.png"),
                width=800,
                height=480,
                mode="production",
            )
        cmd = mock_call.call_args[0][0]
        assert "--mode" in cmd
        assert "production" in cmd

    def test_theme_passed_through(self, tmp_path):
        with patch("subprocess.run") as mock_call, \
             patch("run_clock.current_time_str", return_value="10:00"):
            run_clock.render_now(
                render_script="render_quote.py",
                output_path=str(tmp_path / "current.png"),
                width=800,
                height=480,
                theme="dark",
            )
        cmd = mock_call.call_args[0][0]
        assert "--theme" in cmd
        assert "dark" in cmd

    def test_display_script_called_when_provided(self, tmp_path):
        calls = []
        with patch("subprocess.run", side_effect=lambda cmd, **kw: calls.append(cmd)), \
             patch("run_clock.current_time_str", return_value="10:00"):
            run_clock.render_now(
                render_script="render_quote.py",
                output_path=str(tmp_path / "current.png"),
                width=800,
                height=480,
                display_script="display_inky.py",
            )
        assert len(calls) == 2
        # Second call is the display script
        assert "display_inky.py" in calls[1][-1] or any("display_inky" in str(arg) for arg in calls[1])

    def test_no_display_script_one_call(self, tmp_path):
        with patch("subprocess.run") as mock_call, \
             patch("run_clock.current_time_str", return_value="10:00"):
            run_clock.render_now(
                render_script="render_quote.py",
                output_path=str(tmp_path / "current.png"),
                width=800,
                height=480,
                display_script=None,
            )
        assert mock_call.call_count == 1


class TestMainLoopResilience:
    """A render failure must not kill the clock loop."""

    def _drive_loop(self, tmp_path, render_side_effects: list, tick_count: int):
        """Drive run_clock.main for ``tick_count`` ticks then bail out via KeyboardInterrupt.

        Each tick sees a different ``current_bucket`` so render_now is always invoked.
        Returns the ordered list of render_now invocation arguments.
        """
        render_calls: list = []

        def fake_render(*args, **kwargs):
            idx = len(render_calls)
            render_calls.append((args, kwargs))
            side = render_side_effects[idx] if idx < len(render_side_effects) else None
            if isinstance(side, Exception):
                raise side

        # Distinct bucket per tick, followed by a KeyboardInterrupt on the next call
        # so the infinite loop terminates for the test.
        buckets = [f"h{i}_exact" for i in range(1, tick_count + 1)]

        sleep_count = {"n": 0}

        def stop_after_ticks(_):
            sleep_count["n"] += 1
            if sleep_count["n"] >= tick_count:
                raise KeyboardInterrupt

        argv = ["run_clock.py", "--output", str(tmp_path / "current.png"), "--interval-seconds", "0"]
        # Return a distinct quote-identity per tick so the dedup path in main does not
        # swallow the render call this test is measuring.
        peek_ids = iter((f"id-{i}", i, f"q-{i}") for i in range(tick_count + 1))
        # Pin wall clock outside the default 22:00–06:00 quiet window; otherwise the
        # loop enters the quiet-hours branch when tests run in the evening.
        with patch("sys.argv", argv), \
             patch("run_clock.render_now", side_effect=fake_render), \
             patch("run_clock.current_bucket", side_effect=buckets), \
             patch("run_clock.current_time_str", return_value="12:00"), \
             patch("run_clock.peek_quote_id", side_effect=lambda _ts, **_kw: next(peek_ids)), \
             patch("run_clock._loop_sleep", side_effect=lambda _s, _sec: stop_after_ticks(_sec)):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()
        return render_calls

    def test_render_exception_keeps_loop_alive(self, tmp_path, capsys):
        # First render raises CalledProcessError; second and third succeed.
        err = subprocess.CalledProcessError(1, ["render_quote.py"])
        calls = self._drive_loop(tmp_path, [err, None, None], tick_count=3)
        assert len(calls) == 3, "loop must keep invoking render after a failure"
        assert "render/display failed" in capsys.readouterr().err

    def test_generic_exception_keeps_loop_alive(self, tmp_path, capsys):
        # Anything (not just CalledProcessError) must be caught.
        calls = self._drive_loop(tmp_path, [RuntimeError("boom"), None], tick_count=2)
        assert len(calls) == 2
        assert "render/display failed" in capsys.readouterr().err

    def test_repeated_error_logs_once_and_traceback_once(self, tmp_path, capsys):
        # Three identical failures in a row should log only once (dedup latch),
        # so journald doesn't fill with the same traceback while the backoff
        # retries the same hardware fault. Telemetry still gets every entry
        # (the counter is authoritative).
        err = RuntimeError("identical error")
        self._drive_loop(tmp_path, [err, err, err], tick_count=3)
        captured = capsys.readouterr().err
        assert captured.count("render/display failed") == 1, (
            "dedup latch should suppress repeat stderr emissions of the same error"
        )
        # Traceback emitted exactly once.
        assert captured.count("Traceback") == 1

    def test_distinct_errors_log_each_time(self, tmp_path, capsys):
        # When the error text changes the latch must NOT suppress — a genuinely
        # new failure after a transient recovery is exactly what the operator
        # needs to see.
        errs = [RuntimeError("first"), RuntimeError("second"), RuntimeError("third")]
        self._drive_loop(tmp_path, errs, tick_count=3)
        captured = capsys.readouterr().err
        assert captured.count("render/display failed") == 3

    def test_once_mode_still_propagates_failure(self, tmp_path):
        # --once must NOT swallow errors — cron/smoke tests need a non-zero exit.
        argv = ["run_clock.py", "--once", "--output", str(tmp_path / "current.png")]
        err = subprocess.CalledProcessError(1, ["render_quote.py"])
        with patch("sys.argv", argv), \
             patch("run_clock.render_now", side_effect=err):
            with pytest.raises(subprocess.CalledProcessError):
                run_clock.main()


class TestPeekQuoteId:
    def test_returns_identity_tuple(self):
        with patch(
            "run_clock.pick_quote_module.select_quote",
            return_value={
                "source_id": "141",
                "line_number": 482,
                "display_quote": "hello",
                "matched_text": "ten minutes to three",
            },
        ):
            assert run_clock.peek_quote_id("10:00") == ("141", 482, "hello", "ten minutes to three")

    def test_identity_includes_matched_text(self):
        # Two rows that share (source_id, line_number, display_quote) but differ in
        # matched_text must NOT produce the same identity — the highlighted phrase differs
        # on screen.
        base = {"source_id": "6133", "line_number": 6906, "display_quote": "…"}
        with patch("run_clock.pick_quote_module.select_quote", return_value={**base, "matched_text": "Ten minutes to three"}):
            first = run_clock.peek_quote_id("02:50")
        with patch("run_clock.pick_quote_module.select_quote", return_value={**base, "matched_text": "Five minutes to three"}):
            second = run_clock.peek_quote_id("02:55")
        assert first != second

    def test_returns_none_on_pick_failure(self, capsys):
        with patch("run_clock.pick_quote_module.select_quote", side_effect=RuntimeError("no corpus")):
            assert run_clock.peek_quote_id("10:00") is None
        assert "pick_quote failed" in capsys.readouterr().err

    def test_returns_none_on_systemexit(self, capsys):
        # pick_quote.pick_best raises SystemExit when no candidate clears the quality gate
        # in the target bucket or its neighbours. The loop must survive that.
        with patch(
            "run_clock.pick_quote_module.select_quote",
            side_effect=SystemExit("No candidates found"),
        ):
            assert run_clock.peek_quote_id("10:00") is None

    def test_uses_baked_database_path(self):
        """The runtime loop must pass ``database_path=DEFAULT_DATABASE_PATH`` so
        ``select_quote`` takes the fast baked-DB path. Without this, ``database_path``
        defaults to ``None`` and the loop silently keeps reading the raw corpus."""
        import pick_quote as pq
        captured: dict = {}

        def fake_select_quote(**kwargs):
            captured.update(kwargs)
            return {
                "source_id": "1", "line_number": 2,
                "display_quote": "x", "matched_text": "y",
            }

        with patch("run_clock.pick_quote_module.select_quote", side_effect=fake_select_quote):
            run_clock.peek_quote_id("10:00")
        assert captured.get("database_path") == pq.DEFAULT_DATABASE_PATH


class TestLoopQuoteDedup:
    """When the bucket changes but the picked quote doesn't, skip the redraw."""

    def _drive(self, tmp_path, buckets, peek_ids, tick_count):
        render_calls: list = []

        def fake_render(*args, **kwargs):
            render_calls.append((args, kwargs))

        sleep_count = {"n": 0}

        def stop_after_ticks(_):
            sleep_count["n"] += 1
            if sleep_count["n"] >= tick_count:
                raise KeyboardInterrupt

        peek_iter = iter(peek_ids)
        argv = ["run_clock.py", "--output", str(tmp_path / "current.png"), "--interval-seconds", "0"]
        # Pin wall clock outside the default 22:00–06:00 quiet window; otherwise the
        # loop enters the quiet-hours branch when tests run in the evening.
        with patch("sys.argv", argv), \
             patch("run_clock.render_now", side_effect=fake_render), \
             patch("run_clock.current_bucket", side_effect=buckets), \
             patch("run_clock.current_time_str", return_value="12:00"), \
             patch("run_clock.peek_quote_id", side_effect=lambda _ts, **_kw: next(peek_iter)), \
             patch("run_clock._loop_sleep", side_effect=lambda _s, _sec: stop_after_ticks(_sec)):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()
        return render_calls

    def test_bucket_change_same_quote_skips_render(self, tmp_path, capsys):
        buckets = ["h3_exact", "h3_five_past", "h3_ten_past"]
        peek_ids = [("141", 1, "q"), ("141", 1, "q"), ("141", 1, "q")]
        calls = self._drive(tmp_path, buckets, peek_ids, tick_count=3)
        # Only the first tick renders; subsequent ticks see unchanged quote and skip.
        assert len(calls) == 1
        assert "skipping redraw" in capsys.readouterr().out

    def test_bucket_change_new_quote_triggers_render(self, tmp_path):
        buckets = ["h3_exact", "h3_five_past", "h3_ten_past"]
        peek_ids = [("141", 1, "a"), ("141", 2, "b"), ("141", 3, "c")]
        calls = self._drive(tmp_path, buckets, peek_ids, tick_count=3)
        assert len(calls) == 3

    def test_pick_failure_does_not_block_render(self, tmp_path):
        # peek returns None (pick failed); we should still try to render so the
        # subprocess can surface its own error output.
        buckets = ["h3_exact", "h3_five_past"]
        peek_ids = [None, None]
        calls = self._drive(tmp_path, buckets, peek_ids, tick_count=2)
        assert len(calls) == 2


class TestValidHhmm:
    def test_valid_times(self):
        for t in ("00:00", "22:00", "06:00", "23:59", "12:30"):
            assert run_clock._valid_hhmm(t) == t

    def test_rejects_non_numeric(self):
        with pytest.raises(argparse.ArgumentTypeError):
            run_clock._valid_hhmm("nope")

    def test_rejects_out_of_range_hour(self):
        with pytest.raises(argparse.ArgumentTypeError):
            run_clock._valid_hhmm("24:00")

    def test_rejects_out_of_range_minute(self):
        with pytest.raises(argparse.ArgumentTypeError):
            run_clock._valid_hhmm("12:60")

    def test_rejects_missing_colon(self):
        with pytest.raises(argparse.ArgumentTypeError):
            run_clock._valid_hhmm("1200")


class TestQuietHours:
    # --- unit tests for in_quiet_hours ---

    def test_same_day_range_inside(self):
        assert run_clock.in_quiet_hours("03:00", "01:00", "06:00") is True

    def test_same_day_range_outside_before(self):
        assert run_clock.in_quiet_hours("00:30", "01:00", "06:00") is False

    def test_same_day_range_outside_after(self):
        assert run_clock.in_quiet_hours("08:00", "01:00", "06:00") is False

    def test_overnight_range_inside_before_midnight(self):
        assert run_clock.in_quiet_hours("23:00", "22:00", "07:00") is True

    def test_overnight_range_inside_after_midnight(self):
        assert run_clock.in_quiet_hours("03:00", "22:00", "07:00") is True

    def test_overnight_range_outside(self):
        assert run_clock.in_quiet_hours("12:00", "22:00", "07:00") is False

    def test_no_quiet_hours_returns_false(self):
        assert run_clock.in_quiet_hours("03:00", None, None) is False

    def test_boundary_start_is_quiet(self):
        assert run_clock.in_quiet_hours("22:00", "22:00", "07:00") is True

    def test_boundary_end_is_not_quiet(self):
        assert run_clock.in_quiet_hours("07:00", "22:00", "07:00") is False

    # --- loop integration tests ---

    def test_loop_renders_once_on_quiet_entry(self, tmp_path):
        """Entering quiet hours renders once with quiet_start as the display time; subsequent quiet ticks skip."""
        render_calls = []

        def fake_render(*args, **kwargs):
            render_calls.append(kwargs.get("time_str"))

        time_strs = iter(["22:00", "22:05"])
        sleep_count = {"n": 0}

        def stop_after(_):
            sleep_count["n"] += 1
            if sleep_count["n"] >= 2:
                raise KeyboardInterrupt

        argv = [
            "run_clock.py", "--output", str(tmp_path / "current.png"),
            "--interval-seconds", "0",
            "--quiet-start", "22:00", "--quiet-end", "07:00", "--quiet-image", "",
        ]
        with patch("sys.argv", argv), \
             patch("run_clock.render_now", side_effect=fake_render), \
             patch("run_clock.current_time_str", side_effect=lambda: next(time_strs)), \
             patch("run_clock._loop_sleep", side_effect=lambda _s, _sec: stop_after(_sec)):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()

        assert len(render_calls) == 1
        assert render_calls[0] == "22:00"

    def test_loop_rerenders_after_quiet_exit(self, tmp_path):
        """After quiet hours end the first bucket change triggers a normal render."""
        render_calls = []

        def fake_render(*args, **kwargs):
            render_calls.append(kwargs.get("time_str"))

        # Tick 1: quiet (22:00) → quiet-start render
        # Tick 2: active (08:00) → bucket changed → normal render
        # Tick 3: active (08:05) → same bucket → no render
        time_strs = iter(["22:00", "08:00", "08:05"])
        bucket_seq = iter(["h8_exact", "h8_exact"])
        peek_seq = iter([("id", 1, "q", "mt")])
        sleep_count = {"n": 0}

        def stop_after(_):
            sleep_count["n"] += 1
            if sleep_count["n"] >= 3:
                raise KeyboardInterrupt

        argv = [
            "run_clock.py", "--output", str(tmp_path / "current.png"),
            "--interval-seconds", "0",
            "--quiet-start", "22:00", "--quiet-end", "07:00", "--quiet-image", "",
        ]
        with patch("sys.argv", argv), \
             patch("run_clock.render_now", side_effect=fake_render), \
             patch("run_clock.current_time_str", side_effect=lambda: next(time_strs)), \
             patch("run_clock.current_bucket", side_effect=lambda: next(bucket_seq)), \
             patch("run_clock.peek_quote_id", side_effect=lambda _ts, **_kw: next(peek_seq)), \
             patch("run_clock._loop_sleep", side_effect=lambda _s, _sec: stop_after(_sec)):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()

        # quiet-start render + one normal render; third tick same bucket → no render
        assert len(render_calls) == 2
        assert render_calls[0] == "22:00"
        assert render_calls[1] == "08:00"

    def test_quiet_off_disables_quiet_hours(self, tmp_path):
        """--quiet-off keeps the loop rendering even during the configured quiet window."""
        render_calls = []

        def fake_render(*args, **kwargs):
            render_calls.append(kwargs.get("time_str"))

        # Two ticks that would normally be inside the 22:00–06:00 window.
        time_strs = iter(["23:00", "23:05"])
        bucket_seq = iter(["h11_exact", "h11_five_past"])
        peek_seq = iter([("id", 1, "q", "mt"), ("id", 2, "q2", "mt2")])
        sleep_count = {"n": 0}

        def stop_after(_):
            sleep_count["n"] += 1
            if sleep_count["n"] >= 2:
                raise KeyboardInterrupt

        argv = [
            "run_clock.py", "--output", str(tmp_path / "current.png"),
            "--interval-seconds", "0", "--quiet-off",
        ]
        with patch("sys.argv", argv), \
             patch("run_clock.render_now", side_effect=fake_render), \
             patch("run_clock.current_time_str", side_effect=lambda: next(time_strs)), \
             patch("run_clock.current_bucket", side_effect=lambda: next(bucket_seq)), \
             patch("run_clock.peek_quote_id", side_effect=lambda _ts, **_kw: next(peek_seq)), \
             patch("run_clock._loop_sleep", side_effect=lambda _s, _sec: stop_after(_sec)):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()

        assert len(render_calls) == 2

    def test_once_ignores_quiet_hours(self, tmp_path):
        """--once renders immediately regardless of the quiet window."""
        argv = [
            "run_clock.py", "--once", "--output", str(tmp_path / "current.png"),
            "--quiet-start", "00:00", "--quiet-end", "23:59",
        ]
        with patch("sys.argv", argv), \
             patch("run_clock.render_now") as mock_render, \
             patch("run_clock.current_time_str", return_value="12:00"):
            run_clock.main()
        assert mock_render.called


class TestLedgerWrite:
    """run_clock must append to the history ledger after a successful render."""

    def test_once_appends_ledger_entry(self, tmp_path):
        ledger = tmp_path / "history.jsonl"
        argv = [
            "run_clock.py", "--once",
            "--output", str(tmp_path / "current.png"),
            "--history-path", str(ledger),
        ]
        with patch("sys.argv", argv), \
             patch("run_clock.render_now"), \
             patch("run_clock.current_time_str", return_value="14:30"), \
             patch(
                 "run_clock.peek_quote_id",
                 return_value=("src-42", 101, "quote text", "two thirty"),
             ), \
             patch("run_clock.pick_quote_module.append_history") as mock_append:
            run_clock.main()
        mock_append.assert_called_once()
        args, _kwargs = mock_append.call_args
        assert args[0] == str(ledger)
        assert args[1] == "src-42"
        assert args[2] == 101

    def test_once_no_append_when_peek_returns_none(self, tmp_path):
        argv = [
            "run_clock.py", "--once",
            "--output", str(tmp_path / "current.png"),
            "--history-path", str(tmp_path / "history.jsonl"),
        ]
        with patch("sys.argv", argv), \
             patch("run_clock.render_now"), \
             patch("run_clock.current_time_str", return_value="14:30"), \
             patch("run_clock.peek_quote_id", return_value=None), \
             patch("run_clock.pick_quote_module.append_history") as mock_append:
            run_clock.main()
        mock_append.assert_not_called()

    def test_once_empty_history_path_disables_append(self, tmp_path):
        argv = [
            "run_clock.py", "--once",
            "--output", str(tmp_path / "current.png"),
            "--history-path", "",
        ]
        with patch("sys.argv", argv), \
             patch("run_clock.render_now"), \
             patch("run_clock.current_time_str", return_value="14:30"), \
             patch(
                 "run_clock.peek_quote_id",
                 return_value=("src-42", 101, "quote text", "two thirty"),
             ), \
             patch("run_clock.pick_quote_module.append_history") as mock_append:
            run_clock.main()
        # append_history is still called (to be safe), but with None as the path so it no-ops.
        if mock_append.called:
            assert mock_append.call_args[0][0] is None

    def test_loop_appends_on_successful_render(self, tmp_path):
        ledger = tmp_path / "history.jsonl"
        buckets = ["h3_exact", "h3_five_past"]
        peek_ids = [("src-1", 1, "q1", "mt1"), ("src-2", 2, "q2", "mt2")]
        sleep_count = {"n": 0}

        def stop_after(_):
            sleep_count["n"] += 1
            if sleep_count["n"] >= 2:
                raise KeyboardInterrupt

        peek_iter = iter(peek_ids)
        argv = [
            "run_clock.py",
            "--output", str(tmp_path / "current.png"),
            "--interval-seconds", "0",
            "--history-path", str(ledger),
            "--quiet-off",
        ]
        with patch("sys.argv", argv), \
             patch("run_clock.render_now"), \
             patch("run_clock.current_bucket", side_effect=buckets), \
             patch("run_clock.peek_quote_id", side_effect=lambda _ts, **_kw: next(peek_iter)), \
             patch("run_clock.pick_quote_module.append_history") as mock_append, \
             patch("run_clock._loop_sleep", side_effect=lambda _s, _sec: stop_after(_sec)):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()
        assert mock_append.call_count == 2
        first_call = mock_append.call_args_list[0][0]
        assert first_call == (str(ledger), "src-1", 1)

    def test_loop_no_append_during_quiet_hours(self, tmp_path):
        """Quiet-hours entry shows the static image; no ledger write."""
        src = tmp_path / "quiet.png"
        src.write_bytes(b"\x89PNG")
        time_strs = iter(["22:00", "22:05"])
        sleep_count = {"n": 0}

        def stop_after(_):
            sleep_count["n"] += 1
            if sleep_count["n"] >= 2:
                raise KeyboardInterrupt

        argv = [
            "run_clock.py",
            "--output", str(tmp_path / "current.png"),
            "--interval-seconds", "0",
            "--quiet-start", "22:00", "--quiet-end", "07:00",
            "--quiet-image", str(src),
            "--history-path", str(tmp_path / "history.jsonl"),
        ]
        with patch("sys.argv", argv), \
             patch("run_clock.render_now"), \
             patch("run_clock._display_quiet_image"), \
             patch("run_clock.current_time_str", side_effect=lambda: next(time_strs)), \
             patch("run_clock.pick_quote_module.append_history") as mock_append, \
             patch("run_clock._loop_sleep", side_effect=lambda _s, _sec: stop_after(_sec)):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()
        mock_append.assert_not_called()

    def test_loop_no_append_on_render_failure(self, tmp_path):
        """If render_now raises, the ledger must not grow."""
        ledger = tmp_path / "history.jsonl"
        buckets = ["h3_exact"]
        peek_ids = iter([("src-1", 1, "q1", "mt1")])
        sleep_count = {"n": 0}

        def stop_after(_):
            sleep_count["n"] += 1
            if sleep_count["n"] >= 1:
                raise KeyboardInterrupt

        argv = [
            "run_clock.py",
            "--output", str(tmp_path / "current.png"),
            "--interval-seconds", "0",
            "--history-path", str(ledger),
            "--quiet-off",
        ]
        with patch("sys.argv", argv), \
             patch("run_clock.render_now", side_effect=RuntimeError("boom")), \
             patch("run_clock.current_bucket", side_effect=buckets), \
             patch("run_clock.peek_quote_id", side_effect=lambda _ts, **_kw: next(peek_ids)), \
             patch("run_clock.pick_quote_module.append_history") as mock_append, \
             patch("run_clock._loop_sleep", side_effect=lambda _s, _sec: stop_after(_sec)):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()
        mock_append.assert_not_called()

    def test_loop_no_append_when_quote_unchanged(self, tmp_path):
        """Dedup skip path must not append — no new render means no new entry."""
        ledger = tmp_path / "history.jsonl"
        buckets = ["h3_exact", "h3_five_past"]
        # Same identity tuple across both ticks — dedup should trigger on tick 2.
        peek_ids = iter([("src-1", 1, "q", "mt"), ("src-1", 1, "q", "mt")])
        sleep_count = {"n": 0}

        def stop_after(_):
            sleep_count["n"] += 1
            if sleep_count["n"] >= 2:
                raise KeyboardInterrupt

        argv = [
            "run_clock.py",
            "--output", str(tmp_path / "current.png"),
            "--interval-seconds", "0",
            "--history-path", str(ledger),
            "--quiet-off",
        ]
        with patch("sys.argv", argv), \
             patch("run_clock.render_now"), \
             patch("run_clock.current_bucket", side_effect=buckets), \
             patch("run_clock.peek_quote_id", side_effect=lambda _ts, **_kw: next(peek_ids)), \
             patch("run_clock.pick_quote_module.append_history") as mock_append, \
             patch("run_clock._loop_sleep", side_effect=lambda _s, _sec: stop_after(_sec)):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()
        # Only the first render appends; second tick sees unchanged quote and skips.
        assert mock_append.call_count == 1

    def test_history_args_passed_to_render_subprocess(self, tmp_path):
        """The --history-path and --history-days from run_clock must reach render_quote.py."""
        argv = [
            "run_clock.py", "--once",
            "--output", str(tmp_path / "current.png"),
            "--history-path", str(tmp_path / "history.jsonl"),
            "--history-days", "14",
        ]
        with patch("sys.argv", argv), \
             patch("subprocess.run") as mock_call, \
             patch("run_clock.current_time_str", return_value="14:30"), \
             patch(
                 "run_clock.peek_quote_id",
                 return_value=("src-1", 1, "q", "mt"),
             ), \
             patch("run_clock.pick_quote_module.append_history"):
            run_clock.main()
        cmd = mock_call.call_args[0][0]
        assert "--history-path" in cmd
        assert str(tmp_path / "history.jsonl") in cmd
        assert "--history-days" in cmd
        assert "14" in cmd


class TestDisplayQuietImage:
    def test_copies_file_to_output(self, tmp_path):
        src = tmp_path / "quiet.png"
        src.write_bytes(b"\x89PNG")
        out = tmp_path / "current.png"
        run_clock._display_quiet_image(str(src), str(out), display_script=None)
        assert out.read_bytes() == b"\x89PNG"

    def test_calls_display_script(self, tmp_path):
        src = tmp_path / "quiet.png"
        src.write_bytes(b"\x89PNG")
        out = tmp_path / "current.png"
        with patch("subprocess.run") as mock_call:
            run_clock._display_quiet_image(str(src), str(out), display_script="display_inky.py")
        assert mock_call.called
        cmd = mock_call.call_args[0][0]
        assert "display_inky.py" in " ".join(str(a) for a in cmd)
        assert str(out) in cmd

    def test_no_display_script_no_subprocess(self, tmp_path):
        src = tmp_path / "quiet.png"
        src.write_bytes(b"\x89PNG")
        out = tmp_path / "current.png"
        with patch("subprocess.run") as mock_call:
            run_clock._display_quiet_image(str(src), str(out), display_script=None)
        mock_call.assert_not_called()

    def test_loop_uses_quiet_image_not_render_now(self, tmp_path):
        """With --quiet-image set, the loop calls _display_quiet_image, not render_now."""
        src = tmp_path / "quiet.png"
        src.write_bytes(b"\x89PNG")

        display_calls = []
        time_strs = iter(["22:00", "22:05"])
        sleep_count = {"n": 0}

        def stop_after(_):
            sleep_count["n"] += 1
            if sleep_count["n"] >= 2:
                raise KeyboardInterrupt

        argv = [
            "run_clock.py", "--output", str(tmp_path / "current.png"),
            "--interval-seconds", "0",
            "--quiet-start", "22:00", "--quiet-end", "07:00",
            "--quiet-image", str(src),
        ]
        with patch("sys.argv", argv), \
             patch("run_clock.render_now") as mock_render, \
             patch("run_clock._display_quiet_image", side_effect=lambda *a, **kw: display_calls.append(a)), \
             patch("run_clock.current_time_str", side_effect=lambda: next(time_strs)), \
             patch("run_clock._loop_sleep", side_effect=lambda _s, _sec: stop_after(_sec)):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()

        mock_render.assert_not_called()
        assert len(display_calls) == 1
        assert display_calls[0][0] == str(src)


class TestAutoTheme:
    def test_auto_theme_morning_is_default(self):
        assert run_clock.auto_theme_for("09:00") == "default"

    def test_auto_theme_afternoon_is_default(self):
        assert run_clock.auto_theme_for("15:30") == "default"

    def test_auto_theme_evening_is_dark(self):
        assert run_clock.auto_theme_for("19:00") == "dark"

    def test_auto_theme_late_night_is_dark(self):
        assert run_clock.auto_theme_for("23:30") == "dark"

    def test_auto_theme_pre_dawn_is_dark(self):
        assert run_clock.auto_theme_for("04:00") == "dark"

    def test_auto_theme_boundary_dusk_is_dark(self):
        assert run_clock.auto_theme_for("18:00") == "dark"

    def test_auto_theme_boundary_dawn_is_default(self):
        assert run_clock.auto_theme_for("06:00") == "default"


class TestResolveEffectiveTheme:
    def test_explicit_default_is_returned(self):
        assert run_clock.resolve_effective_theme("default", "20:00", None) == "default"

    def test_explicit_dark_is_returned(self):
        assert run_clock.resolve_effective_theme("dark", "10:00", None) == "dark"

    def test_auto_resolves_via_clock(self):
        assert run_clock.resolve_effective_theme("auto", "21:00", None) == "dark"
        assert run_clock.resolve_effective_theme("auto", "10:00", None) == "default"

    def test_manual_override_wins_over_auto(self):
        assert run_clock.resolve_effective_theme("auto", "21:00", "default") == "default"
        assert run_clock.resolve_effective_theme("auto", "10:00", "dark") == "dark"

    def test_manual_override_wins_over_explicit(self):
        # If the user pressed B while running with --theme dark, the manual override wins.
        assert run_clock.resolve_effective_theme("dark", "10:00", "default") == "default"

    def test_invalid_manual_override_ignored(self):
        assert run_clock.resolve_effective_theme("auto", "21:00", "garbage") == "dark"


class TestRuntimeStatePersistence:
    def test_load_missing_returns_empty(self, tmp_path):
        assert run_clock.load_runtime_state(str(tmp_path / "missing.json")) == {}

    def test_load_empty_path_returns_empty(self):
        assert run_clock.load_runtime_state("") == {}
        assert run_clock.load_runtime_state(None) == {}

    def test_save_then_load_roundtrip(self, tmp_path):
        path = tmp_path / "state.json"
        run_clock.save_runtime_state(str(path), {"manual_theme": "dark", "manual_quiet": True})
        loaded = run_clock.load_runtime_state(str(path))
        assert loaded == {"manual_theme": "dark", "manual_quiet": True}

    def test_save_creates_parent_directory(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "state.json"
        run_clock.save_runtime_state(str(path), {"manual_theme": "dark"})
        assert path.exists()

    def test_load_corrupt_file_returns_empty(self, tmp_path, capsys):
        path = tmp_path / "state.json"
        path.write_text("not-json", encoding="utf-8")
        assert run_clock.load_runtime_state(str(path)) == {}
        assert "unreadable" in capsys.readouterr().err

    def test_load_non_object_json_returns_empty(self, tmp_path, capsys):
        """Valid JSON that isn't an object (bare string/number/list) must be rejected —
        RuntimeState calls .get() on the result so a non-dict would otherwise crash startup.
        """
        path = tmp_path / "state.json"
        path.write_text('"oops"', encoding="utf-8")
        assert run_clock.load_runtime_state(str(path)) == {}
        assert "not a JSON object" in capsys.readouterr().err

    def test_load_number_json_returns_empty(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("42", encoding="utf-8")
        assert run_clock.load_runtime_state(str(path)) == {}

    def test_load_list_json_returns_empty(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("[]", encoding="utf-8")
        assert run_clock.load_runtime_state(str(path)) == {}

    def test_load_rejects_wrong_type_on_known_key(self, tmp_path, capsys):
        """Issue #53: malformed-but-parseable state.json must log a validation
        error rather than silently flipping the field to ``{}``.

        Scenario: operator hand-edits state.json and leaves ``manual_theme: 42``
        instead of a string. Before validation, ``RuntimeState`` would read
        the 42 and (because 42 is truthy but not one of "default"/"dark")
        drop it to None — silent, no operator signal.
        """
        path = tmp_path / "state.json"
        path.write_text('{"manual_theme": 42, "manual_quiet": true}', encoding="utf-8")
        result = run_clock.load_runtime_state(str(path))
        # Manual_theme is dropped; manual_quiet survives (it was valid).
        assert result == {"manual_quiet": True}
        err = capsys.readouterr().err
        assert "validation" in err
        assert "manual_theme" in err

    def test_load_validation_telemetrises(self, tmp_path):
        """Issue #53: a malformed state.json writes a telemetry entry so the
        drift is visible in ``litclock_health.py`` summaries, not just stderr.
        """
        state_path = tmp_path / "state.json"
        telemetry_path = tmp_path / "telemetry.jsonl"
        state_path.write_text(
            '{"manual_theme": 42, "manual_quiet": "not-a-bool"}',
            encoding="utf-8",
        )
        run_clock.load_runtime_state(str(state_path), telemetry_path=str(telemetry_path))
        daily = run_clock.daily_telemetry_path(telemetry_path)
        entries = [json.loads(line) for line in daily.read_text(encoding="utf-8").splitlines() if line.strip()]
        validation = [e for e in entries if e.get("mode") == "state_validation"]
        assert len(validation) == 1
        issues = validation[0]["issues"]
        assert any("manual_theme" in i for i in issues)
        assert any("manual_quiet" in i for i in issues)

    def test_load_preserves_unknown_keys(self, tmp_path, capsys):
        """Forward-compat: an unknown top-level key is flagged but kept in the
        returned dict, so an older install can round-trip a newer schema field
        without dropping it.
        """
        path = tmp_path / "state.json"
        path.write_text(
            '{"manual_theme": "dark", "manual_quiet": false, "v3_new_thing": "stays"}',
            encoding="utf-8",
        )
        result = run_clock.load_runtime_state(str(path))
        assert result.get("v3_new_thing") == "stays"
        assert "unknown key" in capsys.readouterr().err

    def test_load_parse_error_telemetrises(self, tmp_path):
        """Parse-level corruption (tuncated write) also emits a telemetry entry."""
        state_path = tmp_path / "state.json"
        telemetry_path = tmp_path / "telemetry.jsonl"
        state_path.write_text("{broken json", encoding="utf-8")
        run_clock.load_runtime_state(str(state_path), telemetry_path=str(telemetry_path))
        daily = run_clock.daily_telemetry_path(telemetry_path)
        entries = [json.loads(line) for line in daily.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(e.get("mode") == "state_validation" for e in entries)

    def test_runtime_state_seeds_from_persisted(self):
        s = run_clock.RuntimeState("auto", persisted={"manual_theme": "dark", "manual_quiet": True})
        assert s.manual_theme == "dark"
        assert s.manual_quiet is True

    def test_runtime_state_ignores_invalid_persisted_theme(self):
        s = run_clock.RuntimeState("auto", persisted={"manual_theme": "neon", "manual_quiet": False})
        assert s.manual_theme is None

    def test_snapshot_for_persistence_round_trips(self):
        s = run_clock.RuntimeState("auto", persisted={"manual_theme": "dark", "manual_quiet": True})
        assert s.snapshot_for_persistence() == {
            "manual_theme": "dark",
            "manual_quiet": True,
            "last_bucket": None,
            "last_quote_id": None,
            "last_effective_theme": None,
        }

    def test_snapshot_includes_render_identity_triple(self):
        """Issue #53 phase 2: a restart mid-bucket must be able to skip redraw.

        The render-identity fields (``last_bucket`` / ``last_quote_id`` /
        ``last_effective_theme``) live only in RAM otherwise, so they have to
        land in the snapshot for the main-loop dedup check to be meaningful
        across restarts.
        """
        s = run_clock.RuntimeState("default")
        s.commit_render_result("h2_half_past", "default", ("src-1", 42))
        snap = s.snapshot_for_persistence()
        assert snap["last_bucket"] == "h2_half_past"
        assert snap["last_effective_theme"] == "default"
        # Stored as list for JSON round-tripping; re-load tupleizes it.
        assert snap["last_quote_id"] == ["src-1", 42]

    def test_persisted_render_identity_round_trips(self, tmp_path):
        """A save → load cycle preserves the render-identity triple.

        Guards against the type-drift case where JSON list → tuple mismatch
        would make the post-restart dedup check compare a tuple against a
        list and always miss.
        """
        path = tmp_path / "state.json"
        s = run_clock.RuntimeState("default")
        s.commit_render_result("h2_half_past", "default", ("src-1", 42))
        run_clock.save_runtime_state(str(path), s.snapshot_for_persistence())
        loaded = run_clock.load_runtime_state(str(path))
        restored = run_clock.RuntimeState("default", persisted=loaded)
        assert restored.last_bucket == "h2_half_past"
        assert restored.last_effective_theme == "default"
        # Restored as tuple so equality with peek_quote_id output matches.
        assert restored.last_quote_id == ("src-1", 42)

    def test_save_is_atomic_leaves_old_file_on_replace_failure(self, tmp_path):
        """A crash during os.replace must not corrupt the existing state file.

        Simulate the crash by patching os.replace to raise; assert the original
        contents survive and the tmp file is cleaned up (not left as debris).
        """
        path = tmp_path / "state.json"
        run_clock.save_runtime_state(str(path), {"manual_theme": "default", "manual_quiet": False})
        original = path.read_text(encoding="utf-8")

        with patch("atomic_io.os.replace", side_effect=OSError("simulated crash")):
            with pytest.raises(OSError):
                run_clock.save_runtime_state(str(path), {"manual_theme": "dark", "manual_quiet": True})

        assert path.read_text(encoding="utf-8") == original
        assert not (tmp_path / "state.json.tmp").exists()

    def test_save_writes_via_tmp_file(self, tmp_path):
        """Verify the tmp+rename path is actually used (not a direct write)."""
        path = tmp_path / "state.json"
        with patch("atomic_io.os.replace") as mock_replace:
            run_clock.save_runtime_state(str(path), {"manual_theme": "dark"})
            assert mock_replace.called
            src, dst = mock_replace.call_args[0]
            assert str(src).endswith(".json.tmp")
            assert str(dst).endswith(".json")
        # The tmp file is left behind because we patched replace; clean up.
        tmp_path_file = tmp_path / "state.json.tmp"
        assert tmp_path_file.exists()

    def test_save_fsyncs_parent_directory_after_replace(self, tmp_path):
        """Without a dirent fsync the rename itself isn't durable on ext4.
        Assert the directory fd is opened and fsynced after ``os.replace``.
        """
        path = tmp_path / "state.json"
        with patch("atomic_io.os.fsync") as mock_fsync:
            run_clock.save_runtime_state(str(path), {"manual_theme": "dark"})
        # Two fsyncs: one for the tmp file fd, one for the parent directory fd.
        assert mock_fsync.call_count == 2
        fds = [call.args[0] for call in mock_fsync.call_args_list]
        # Both should be real file descriptors (ints ≥ 3).
        assert all(isinstance(fd, int) and fd >= 3 for fd in fds)

    def test_save_tolerates_directory_fsync_failure(self, tmp_path):
        """On platforms where directory fsync is not meaningful (e.g. Windows),
        opening or fsyncing the parent dir can raise OSError. The file must
        still land in place and no exception must escape.
        """
        path = tmp_path / "state.json"
        import atomic_io as _atomic_io
        real_open = _atomic_io.os.open
        real_fsync = _atomic_io.os.fsync

        def flaky_open(pth, flags):
            # Fail only for the directory handle; let the file-fd path through.
            if str(pth) == str(tmp_path):
                raise OSError("simulated no-op dir fsync")
            return real_open(pth, flags)

        with patch("atomic_io.os.open", side_effect=flaky_open), \
             patch("atomic_io.os.fsync", side_effect=real_fsync):
            # Must not raise.
            run_clock.save_runtime_state(str(path), {"manual_theme": "dark"})
        assert json.loads(path.read_text()) == {"manual_theme": "dark"}


def _today_telemetry_path(base):
    """Return the date-suffixed sibling that append_telemetry would write to today."""
    return run_clock.daily_telemetry_path(base)


class TestAppendTelemetry:
    def test_disabled_path_is_noop(self, tmp_path):
        run_clock.append_telemetry("", {"bucket": "h3_exact"})
        run_clock.append_telemetry(None, {"bucket": "h3_exact"})
        # No file written.
        assert list(tmp_path.iterdir()) == []

    def test_appends_one_line_with_ts(self, tmp_path):
        base = tmp_path / "telemetry.jsonl"
        run_clock.append_telemetry(str(base), {"bucket": "h3_exact", "render_ms": 500})
        daily = _today_telemetry_path(base)
        lines = daily.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["bucket"] == "h3_exact"
        assert entry["render_ms"] == 500
        assert "ts" in entry
        # The base path itself is no longer written — telemetry is rotated.
        assert not base.exists()

    def test_appends_multiple_lines(self, tmp_path):
        base = tmp_path / "telemetry.jsonl"
        run_clock.append_telemetry(str(base), {"bucket": "a"})
        run_clock.append_telemetry(str(base), {"bucket": "b"})
        daily = _today_telemetry_path(base)
        lines = daily.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_creates_parent_directory(self, tmp_path):
        base = tmp_path / "nested" / "telemetry.jsonl"
        run_clock.append_telemetry(str(base), {"bucket": "h1_exact"})
        assert _today_telemetry_path(base).exists()

    def test_rotates_by_date(self, tmp_path):
        """Two runs on different dates produce two separate files."""
        base = tmp_path / "telemetry.jsonl"
        import datetime as _dt
        day1 = _dt.date(2026, 4, 19)
        day2 = _dt.date(2026, 4, 20)
        with patch("runtime_telemetry.dt") as mock_dt:
            mock_dt.date.today.return_value = day1
            mock_dt.datetime = dt.datetime
            mock_dt.timezone = dt.timezone
            run_clock.append_telemetry(str(base), {"bucket": "day1"})
        with patch("runtime_telemetry.dt") as mock_dt:
            mock_dt.date.today.return_value = day2
            mock_dt.datetime = dt.datetime
            mock_dt.timezone = dt.timezone
            run_clock.append_telemetry(str(base), {"bucket": "day2"})
        files = sorted(p.name for p in tmp_path.iterdir())
        assert files == ["telemetry-20260419.jsonl", "telemetry-20260420.jsonl"]

    def test_io_failure_does_not_raise(self, tmp_path, capsys):
        """Telemetry is best-effort — an unwritable path must never crash the caller,
        since append_telemetry runs in the loop's error-recovery branch.
        """
        # Path collides with a directory → opening for append raises IsADirectoryError.
        # We collide with the *daily* path because that's what the function now writes to.
        base = tmp_path / "telemetry.jsonl"
        _today_telemetry_path(base).mkdir()
        # Must not raise.
        run_clock.append_telemetry(str(base), {"bucket": "h3_exact"})
        assert "telemetry write" in capsys.readouterr().err

    def test_unserialisable_payload_does_not_raise(self, tmp_path, capsys):
        """json.dumps blows up on non-serialisable values — swallow and log."""
        base = tmp_path / "telemetry.jsonl"

        class NotSerialisable:
            pass

        run_clock.append_telemetry(str(base), {"bucket": "h3_exact", "blob": NotSerialisable()})
        assert "telemetry write" in capsys.readouterr().err


class TestDailyTelemetryPath:
    def test_standard_suffix(self, tmp_path):
        base = tmp_path / "telemetry.jsonl"
        out = run_clock.daily_telemetry_path(base, dt.date(2026, 4, 20))
        assert out.name == "telemetry-20260420.jsonl"
        assert out.parent == tmp_path

    def test_missing_suffix_defaults_to_jsonl(self, tmp_path):
        base = tmp_path / "telemetry"
        out = run_clock.daily_telemetry_path(base, dt.date(2026, 1, 2))
        assert out.name == "telemetry-20260102.jsonl"


class TestRenderNowTelemetry:
    def test_writes_telemetry_after_successful_render(self, tmp_path):
        telemetry_base = tmp_path / "telemetry.jsonl"
        with patch("subprocess.run"), \
             patch("run_clock.current_time_str", return_value="14:30"):
            run_clock.render_now(
                render_script="render_quote.py",
                output_path=str(tmp_path / "current.png"),
                width=800,
                height=480,
                mode="production",
                theme="dark",
                telemetry_path=str(telemetry_base),
                bucket="h2_half_past",
                quote_id=("141", 482, "q", "mt"),
            )
        daily = _today_telemetry_path(telemetry_base)
        entry = json.loads(daily.read_text(encoding="utf-8").strip())
        assert entry["bucket"] == "h2_half_past"
        assert entry["mode"] == "production"
        assert entry["theme"] == "dark"
        assert entry["source_id"] == "141"
        assert entry["line_number"] == 482
        assert "render_ms" in entry

    def test_no_telemetry_when_disabled(self, tmp_path):
        with patch("subprocess.run"), \
             patch("run_clock.current_time_str", return_value="14:30"):
            run_clock.render_now(
                render_script="render_quote.py",
                output_path=str(tmp_path / "current.png"),
                width=800,
                height=480,
                telemetry_path=None,
            )
        # No telemetry file created (neither legacy nor rotated).
        files = [p.name for p in tmp_path.iterdir()]
        assert not any("telemetry" in f for f in files)

    def test_display_script_passes_theme(self, tmp_path):
        calls = []
        with patch("subprocess.run", side_effect=lambda cmd, **kw: calls.append(cmd)), \
             patch("run_clock.current_time_str", return_value="10:00"):
            run_clock.render_now(
                render_script="render_quote.py",
                output_path=str(tmp_path / "current.png"),
                width=800,
                height=480,
                display_script="display_inky.py",
                theme="dark",
            )
        # Second subprocess call is the display push; --theme dark must be in its argv.
        assert len(calls) == 2
        assert "--theme" in calls[1]
        idx = calls[1].index("--theme")
        assert calls[1][idx + 1] == "dark"


class TestThemePersistenceEndToEnd:
    """Theme persisted to state.json should be restored on the next process start."""

    def test_persisted_dark_theme_overrides_default_arg(self, tmp_path):
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"manual_theme": "dark"}), encoding="utf-8")

        captured_themes: list[str] = []

        def fake_render(*args, **kwargs):
            theme = kwargs.get("theme") if "theme" in kwargs else (args[6] if len(args) > 6 else None)
            captured_themes.append(theme)

        sleep_count = {"n": 0}

        def stop_after(_):
            sleep_count["n"] += 1
            if sleep_count["n"] >= 1:
                raise KeyboardInterrupt

        argv = [
            "run_clock.py",
            "--output", str(tmp_path / "current.png"),
            "--theme", "default",
            "--state-path", str(state_path),
            "--telemetry-path", "",
            "--history-path", "",
            "--quiet-off",
            "--buttons-off",
            "--interval-seconds", "0",
        ]
        with patch("sys.argv", argv), \
             patch("run_clock.render_now", side_effect=fake_render), \
             patch("run_clock.current_time_str", return_value="10:00"), \
             patch("run_clock.current_bucket", return_value="h10_exact"), \
             patch("run_clock.peek_quote_id", return_value=("src", 1, "q", "mt")), \
             patch("run_clock._loop_sleep", side_effect=lambda _s, _sec: stop_after(_sec)):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()

        assert captured_themes == ["dark"], "Persisted manual_theme must override --theme arg"


class TestAutoThemeLoopIntegration:
    """--theme auto must pick the right theme each tick and force a redraw on theme change."""

    def test_auto_theme_evening_renders_dark(self, tmp_path):
        captured_themes: list[str] = []

        def fake_render(*args, **kwargs):
            # render_now(..., display_script, mode, theme, ...) — theme is positional[6].
            theme = kwargs.get("theme") if "theme" in kwargs else (args[6] if len(args) > 6 else None)
            captured_themes.append(theme)

        sleep_count = {"n": 0}

        def stop_after(_):
            sleep_count["n"] += 1
            if sleep_count["n"] >= 1:
                raise KeyboardInterrupt

        argv = [
            "run_clock.py",
            "--output", str(tmp_path / "current.png"),
            "--theme", "auto",
            "--state-path", "",
            "--telemetry-path", "",
            "--history-path", "",
            "--quiet-off",
            "--buttons-off",
            "--interval-seconds", "0",
        ]
        with patch("sys.argv", argv), \
             patch("run_clock.render_now", side_effect=fake_render), \
             patch("run_clock.current_time_str", return_value="20:00"), \
             patch("run_clock.current_bucket", return_value="h8_exact"), \
             patch("run_clock.peek_quote_id", return_value=("src", 1, "q", "mt")), \
             patch("run_clock._loop_sleep", side_effect=lambda _s, _sec: stop_after(_sec)):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()
        assert captured_themes == ["dark"]

    def test_auto_theme_change_forces_redraw(self, tmp_path):
        """Same bucket + same quote across two ticks; only the theme flips → render twice."""
        captured_themes: list[str] = []

        def fake_render(*args, **kwargs):
            # render_now(..., display_script, mode, theme, ...) — theme is positional[6].
            theme = kwargs.get("theme") if "theme" in kwargs else (args[6] if len(args) > 6 else None)
            captured_themes.append(theme)

        # Tick 1: 17:55 → default theme. Tick 2: 18:00 → dark theme. Same bucket & quote.
        time_strs = iter(["17:55", "18:00"])
        sleep_count = {"n": 0}

        def stop_after(_):
            sleep_count["n"] += 1
            if sleep_count["n"] >= 2:
                raise KeyboardInterrupt

        argv = [
            "run_clock.py",
            "--output", str(tmp_path / "current.png"),
            "--theme", "auto",
            "--state-path", "",
            "--telemetry-path", "",
            "--history-path", "",
            "--quiet-off",
            "--buttons-off",
            "--interval-seconds", "0",
        ]
        with patch("sys.argv", argv), \
             patch("run_clock.render_now", side_effect=fake_render), \
             patch("run_clock.current_time_str", side_effect=lambda: next(time_strs)), \
             patch("run_clock.current_bucket", return_value="h6_exact"), \
             patch("run_clock.peek_quote_id", return_value=("src", 1, "q", "mt")), \
             patch("run_clock._loop_sleep", side_effect=lambda _s, _sec: stop_after(_sec)):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()
        assert captured_themes == ["default", "dark"]


class TestMidnightThemeReset:
    def test_clears_manual_theme_at_day_boundary(self, tmp_path):
        state_path = tmp_path / "state.json"
        args = argparse.Namespace(state_path=str(state_path))
        state = run_clock.RuntimeState("auto", persisted={"manual_theme": "dark"})
        # Pretend yesterday already happened.
        state.last_seen_date = dt.date.today() - dt.timedelta(days=1)
        run_clock._maybe_reset_manual_theme_at_midnight(args, state)
        assert state.manual_theme is None
        # Persisted state file should reflect the cleared override.
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        assert persisted["manual_theme"] is None

    def test_no_reset_when_theme_arg_is_explicit(self, tmp_path):
        args = argparse.Namespace(state_path=str(tmp_path / "state.json"))
        state = run_clock.RuntimeState("dark", persisted={"manual_theme": "default"})
        state.last_seen_date = dt.date.today() - dt.timedelta(days=1)
        run_clock._maybe_reset_manual_theme_at_midnight(args, state)
        # theme_arg != "auto" means we don't auto-clear.
        assert state.manual_theme == "default"

    def test_no_reset_within_same_day(self, tmp_path):
        args = argparse.Namespace(state_path=str(tmp_path / "state.json"))
        state = run_clock.RuntimeState("auto", persisted={"manual_theme": "dark"})
        state.last_seen_date = dt.date.today()
        run_clock._maybe_reset_manual_theme_at_midnight(args, state)
        assert state.manual_theme == "dark"

    def test_save_hook_routes_through_run_clock(self, tmp_path, monkeypatch):
        """Patching ``run_clock.save_runtime_state`` must intercept the midnight save.

        The refactor's compatibility contract is that every ``run_clock.X`` patch
        target still works after extraction; without the lazy ``import run_clock``
        in ``runtime_theme``, the midnight reset would bind ``save_runtime_state``
        directly from ``runtime_store`` and silently bypass the patch, writing to
        disk even when a test has replaced the hook.
        """
        state_path = tmp_path / "state.json"
        args = argparse.Namespace(state_path=str(state_path))
        state = run_clock.RuntimeState("auto", persisted={"manual_theme": "dark"})
        state.last_seen_date = dt.date.today() - dt.timedelta(days=1)
        calls = []
        monkeypatch.setattr(
            run_clock, "save_runtime_state",
            lambda path, payload: calls.append((path, payload)),
        )
        run_clock._maybe_reset_manual_theme_at_midnight(args, state)
        assert state.manual_theme is None
        assert calls == [(
            str(state_path),
            {
                "manual_theme": None,
                "manual_quiet": False,
                "last_bucket": None,
                "last_quote_id": None,
                "last_effective_theme": None,
            },
        )]
        # Patch was honored: the real writer never ran, so no file on disk.
        assert not state_path.exists()


class TestButtonHandlers:
    """Synchronous handler dispatch — verifies wiring without spinning the loop."""

    def _args(self, tmp_path, **overrides):
        defaults = dict(
            render_script="render_quote.py",
            output=str(tmp_path / "current.png"),
            width=800,
            height=480,
            display_script=None,
            mode="debug",
            theme="default",
            history_path=str(tmp_path / "history.jsonl"),
            history_days=7,
            telemetry_path="",
            state_path=str(tmp_path / "state.json"),
            quiet_image="",
            shutdown_command="",
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_skip_handler_bans_current_quote_then_renders(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_quote_id = ("src-old", 5, "q-old", "mt-old")
        with patch("run_clock.peek_quote_id", return_value=("src-new", 7, "q-new", "mt-new")), \
             patch("run_clock.render_now") as mock_render, \
             patch("run_clock.current_time_str", return_value="10:00"), \
             patch("run_clock.current_bucket", return_value="h10_exact"), \
             patch("run_clock.pick_quote_module.append_history") as mock_append:
            short_handlers, _hold_handlers = run_clock._build_button_handlers(args, state)
            short_handlers["A"]()
        # First append: ban the previous quote. Second: log the new one.
        assert mock_append.call_count == 2
        assert mock_append.call_args_list[0][0][1:] == ("src-old", 5)
        assert mock_append.call_args_list[1][0][1:] == ("src-new", 7)
        assert mock_render.called

    def test_toggle_theme_handler_flips_and_persists(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_effective_theme = "default"
        with patch("run_clock.render_now") as mock_render, \
             patch("run_clock.current_time_str", return_value="10:00"), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            short_handlers, _hold_handlers = run_clock._build_button_handlers(args, state)
            short_handlers["B"]()
        assert state.manual_theme == "dark"
        persisted = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert persisted["manual_theme"] == "dark"
        # Render must use the new theme.
        assert mock_render.called
        kwargs = mock_render.call_args[1]
        positional = mock_render.call_args[0]
        used_theme = kwargs.get("theme") or (positional[6] if len(positional) > 6 else None)
        assert used_theme == "dark"

    def test_toggle_theme_handler_flips_back_when_dark(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_effective_theme = "dark"
        with patch("run_clock.render_now"), \
             patch("run_clock.current_time_str", return_value="10:00"), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            short_handlers, _hold_handlers = run_clock._build_button_handlers(args, state)
            short_handlers["B"]()
        assert state.manual_theme == "default"

    def test_do_render_bucket_matches_time_str_near_boundary(self, tmp_path):
        """_do_render stamps state.last_bucket from time_str, not a fresh clock read —
        otherwise a handler firing at 03:02:59.900 could derive bucket h3_five_past from
        a clock read at 03:03:00.001, then stamp that into state while the panel still
        shows the h3_exact frame, causing the next loop tick to wrongly skip the redraw.
        """
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        with patch("run_clock.render_now"), \
             patch("run_clock.current_bucket", side_effect=AssertionError("must not call current_bucket")), \
             patch("run_clock.current_time_str", side_effect=AssertionError("must not call current_time_str")):
            run_clock._do_render(args, state, "03:02", history_path=None, quote_id=("src", 1, "q", "mt"))
        assert state.last_bucket == "h3_exact"

    def test_source_card_handler_renders_in_card_mode(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        # Patch threading.Timer so the test doesn't leave a 5s timer running.
        with patch("run_clock.peek_quote_id", return_value=("src", 1, "q", "mt")), \
             patch("run_clock.render_now") as mock_render, \
             patch("run_clock.threading.Timer") as mock_timer, \
             patch("run_clock.current_time_str", return_value="10:00"), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            short_handlers, _hold_handlers = run_clock._build_button_handlers(args, state)
            short_handlers["C"]()
        kwargs = mock_render.call_args[1]
        positional = mock_render.call_args[0]
        used_mode = kwargs.get("mode") or (positional[5] if len(positional) > 5 else None)
        assert used_mode == "card"
        assert mock_timer.called
        # The 5-second restore callback should be scheduled.
        delay, _callback = mock_timer.call_args[0][:2]
        assert delay == 5.0

    def test_source_card_restore_re_renders_normal_frame(self, tmp_path):
        """The restore callback at +5s must actually push a new render — relying on the
        next loop tick would leave the card up for up to --interval-seconds (60s default).
        """
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        with patch("run_clock.peek_quote_id", return_value=("src", 1, "q", "mt")), \
             patch("run_clock.render_now") as mock_render, \
             patch("run_clock.threading.Timer") as mock_timer, \
             patch("run_clock.current_time_str", return_value="10:00"), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            short_handlers, _hold_handlers = run_clock._build_button_handlers(args, state)
            short_handlers["C"]()
            # First render is the card itself.
            assert mock_render.call_count == 1
            # Now invoke the restore callback manually (simulating the 5s timer firing).
            _delay, callback = mock_timer.call_args[0][:2]
            callback()
            assert mock_render.call_count == 2
            # Second call must be in the normal mode, not "card".
            second_call = mock_render.call_args_list[1]
            mode = second_call.kwargs.get("mode") or (second_call.args[5] if len(second_call.args) > 5 else None)
            assert mode == "debug"

    def test_quiet_toggle_handler_enables_and_persists(self, tmp_path):
        quiet = tmp_path / "goodnight.png"
        quiet.write_bytes(b"\x89PNG")
        args = self._args(tmp_path, quiet_image=str(quiet))
        state = run_clock.RuntimeState("default")
        state.manual_quiet = False
        # action_quiet calls runtime_quiet._display_quiet_image directly (not through
        # run_clock), so the patch target is the action module's binding.
        with patch("runtime_actions._display_quiet_image") as mock_display:
            short_handlers, _hold_handlers = run_clock._build_button_handlers(args, state)
            short_handlers["D"]()
        assert state.manual_quiet is True
        persisted = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert persisted["manual_quiet"] is True
        assert mock_display.called

    def test_quiet_toggle_handler_disable_triggers_wake_render(self, tmp_path):
        args = self._args(tmp_path, quiet_image="")
        state = run_clock.RuntimeState("default")
        state.manual_quiet = True
        with patch("run_clock.peek_quote_id", return_value=("src", 1, "q", "mt")), \
             patch("run_clock.render_now") as mock_render, \
             patch("run_clock.current_time_str", return_value="10:00"), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            short_handlers, _hold_handlers = run_clock._build_button_handlers(args, state)
            short_handlers["D"]()
        assert state.manual_quiet is False
        assert mock_render.called

    def test_theme_toggle_rolls_back_when_render_fails(self, tmp_path):
        """Persist-before-display race: if the display push raises, manual_theme
        must NOT land in state.json. Swap/rollback semantics keep state.json in
        sync with what is actually on the panel."""
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_effective_theme = "default"
        # state.json must not pre-exist — a pre-existing file would make "did we persist?"
        # ambiguous. argparse.Namespace doesn't create it; confirm.
        assert not (tmp_path / "state.json").exists()
        with patch("run_clock.render_now", side_effect=RuntimeError("I/O boom")), \
             patch("run_clock.current_time_str", return_value="10:00"):
            short_handlers, _hold_handlers = run_clock._build_button_handlers(args, state)
            short_handlers["B"]()
        # manual_theme reverted to its pre-flip value; state.json must never
        # have been written with a flipped-theme snapshot.
        assert state.manual_theme is None
        assert not (tmp_path / "state.json").exists()

    def test_quiet_toggle_rolls_back_when_display_fails(self, tmp_path):
        """Flip-then-display-then-persist ordering: a display push failure must
        revert manual_quiet so the two signals stay in sync."""
        quiet = tmp_path / "goodnight.png"
        quiet.write_bytes(b"\x89PNG")
        args = self._args(tmp_path, quiet_image=str(quiet))
        state = run_clock.RuntimeState("default")
        state.manual_quiet = False
        assert not (tmp_path / "state.json").exists()
        with patch("runtime_actions._display_quiet_image", side_effect=OSError("disk full")):
            short_handlers, _hold_handlers = run_clock._build_button_handlers(args, state)
            short_handlers["D"]()
        # Rolled back: manual_quiet stays False; nothing persisted.
        assert state.manual_quiet is False
        assert not (tmp_path / "state.json").exists()

    def test_theme_toggle_persists_only_after_render_succeeds(self, tmp_path):
        """Happy path: persistence still happens — just AFTER the render succeeds,
        not before. The persisted file must exist and must match the flipped theme."""
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_effective_theme = "default"
        with patch("run_clock.render_now"), \
             patch("run_clock.current_time_str", return_value="10:00"):
            short_handlers, _hold_handlers = run_clock._build_button_handlers(args, state)
            short_handlers["B"]()
        assert state.manual_theme == "dark"
        persisted = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert persisted["manual_theme"] == "dark"


class TestMaybeStartButtons:
    def test_buttons_off_returns_none(self, tmp_path):
        args = argparse.Namespace(buttons_off=True)
        assert run_clock._maybe_start_buttons(args, run_clock.RuntimeState("default")) is None

    def test_import_failure_logs_and_returns_none(self, tmp_path, capsys, monkeypatch):
        # Force import of inky_buttons.start_listener to raise.
        import inky_buttons as ib
        monkeypatch.setattr(ib, "start_listener", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no gpio")))
        args = argparse.Namespace(
            buttons_off=False,
            render_script="r", output="o", width=800, height=480,
            display_script=None, mode="debug", theme="default",
            history_path="", history_days=7, telemetry_path="",
            state_path="", quiet_image="", shutdown_command="",
        )
        result = run_clock._maybe_start_buttons(args, run_clock.RuntimeState("default"))
        assert result is None
        assert "button listener disabled" in capsys.readouterr().err

    def test_passes_both_short_and_hold_handlers(self, tmp_path, monkeypatch):
        captured = {}

        def fake_start(handlers, *, hold_handlers=None, **kw):
            captured["short"] = handlers
            captured["hold"] = hold_handlers
            return ["stub"]

        import inky_buttons as ib
        monkeypatch.setattr(ib, "start_listener", fake_start)
        args = argparse.Namespace(
            buttons_off=False,
            render_script="r", output=str(tmp_path / "out.png"),
            width=800, height=480, display_script=None, mode="debug",
            theme="default", history_path="", history_days=7, telemetry_path="",
            state_path="", quiet_image="", shutdown_command="",
        )
        result = run_clock._maybe_start_buttons(args, run_clock.RuntimeState("default"))
        assert result == ["stub"]
        assert set(captured["short"]) == {"A", "B", "C", "D"}
        # Long-press is only wired on A (un-skip) and D (shutdown).
        assert set(captured["hold"]) == {"A", "D"}

    def test_successful_start_attaches_handles_to_state(self, tmp_path, monkeypatch):
        """The liveness check relies on state.button_handles; make sure start wires it up."""
        import inky_buttons as ib
        monkeypatch.setattr(ib, "start_listener", lambda *a, **kw: ["h1", "h2"])
        args = argparse.Namespace(
            buttons_off=False,
            render_script="r", output=str(tmp_path / "out.png"),
            width=800, height=480, display_script=None, mode="debug",
            theme="default", history_path="", history_days=7, telemetry_path="",
            state_path="", quiet_image="", shutdown_command="",
        )
        state = run_clock.RuntimeState("default")
        run_clock._maybe_start_buttons(args, state)
        assert state.button_handles == ["h1", "h2"]


class TestCheckButtonLiveness:
    """The main loop polls button liveness each tick. A dead listener must log
    once and emit telemetry, never spam, and auto-restart is deliberately not
    attempted (would thrash GPIO claims on a persistent failure)."""

    def test_alive_is_noop(self, tmp_path, capsys):
        state = run_clock.RuntimeState("default")
        state.button_handles = []  # empty means "alive" per buttons_alive contract
        run_clock._check_button_liveness(state, str(tmp_path / "telemetry.jsonl"))
        assert state.buttons_dead_logged is False
        assert capsys.readouterr().err == ""

    def test_none_handles_is_noop(self, tmp_path, capsys):
        """--buttons-off or a failed start leaves button_handles=None; no warning."""
        state = run_clock.RuntimeState("default")
        run_clock._check_button_liveness(state, str(tmp_path / "telemetry.jsonl"))
        assert state.buttons_dead_logged is False
        assert capsys.readouterr().err == ""

    def test_dead_logs_once_and_latches(self, tmp_path, capsys, monkeypatch):
        state = run_clock.RuntimeState("default")
        state.button_handles = ["anything"]
        monkeypatch.setattr("inky_buttons.buttons_alive", lambda _handles: False)
        telemetry_base = tmp_path / "telemetry.jsonl"
        with patch("run_clock.current_bucket", return_value="h3_exact"):
            run_clock._check_button_liveness(state, str(telemetry_base))
            # Second call: already latched, must not log again.
            run_clock._check_button_liveness(state, str(telemetry_base))
        err = capsys.readouterr().err
        assert err.count("button listener died") == 1
        assert state.buttons_dead_logged is True
        # One telemetry entry was written to today's rotated file.
        daily = run_clock.daily_telemetry_path(telemetry_base)
        entries = [json.loads(line) for line in daily.read_text().strip().splitlines()]
        assert len(entries) == 1
        assert entries[0]["mode"] == "buttons_dead"
        assert entries[0]["error"] == "button listener died"


class TestUnskipHandler:
    """Button A held 2s: remove the last-skipped ban from the ledger and re-render."""

    def _args(self, tmp_path, **overrides):
        defaults = dict(
            render_script="render_quote.py",
            output=str(tmp_path / "current.png"),
            width=800, height=480, display_script=None,
            mode="debug", theme="default",
            history_path=str(tmp_path / "history.jsonl"),
            history_days=7, telemetry_path="",
            state_path=str(tmp_path / "state.json"),
            quiet_image="", shutdown_command="",
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_skip_records_last_skipped_in_state(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_quote_id = ("src-old", 5, "q-old", "mt-old")
        with patch("run_clock.peek_quote_id", return_value=("src-new", 7, "q-new", "mt-new")), \
             patch("run_clock.render_now"), \
             patch("run_clock.current_time_str", return_value="10:00"), \
             patch("run_clock.current_bucket", return_value="h10_exact"), \
             patch("run_clock.pick_quote_module.append_history"):
            short, _hold = run_clock._build_button_handlers(args, state)
            short["A"]()
        assert state.last_skipped == ("src-old", 5, "q-old", "mt-old")

    def test_unskip_removes_ledger_entry_and_rerenders(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_skipped = ("src-old", 5, "q-old", "mt-old")
        with patch("run_clock.peek_quote_id", return_value=("src-new", 7, "q-new", "mt-new")), \
             patch("run_clock.render_now") as mock_render, \
             patch("run_clock.current_time_str", return_value="10:00"), \
             patch("run_clock.current_bucket", return_value="h10_exact"), \
             patch("run_clock.pick_quote_module.remove_last_history_entry", return_value=True) as mock_rm, \
             patch("run_clock.pick_quote_module.append_history") as mock_append:
            _short, hold = run_clock._build_button_handlers(args, state)
            hold["A"]()
        # Removed the ban.
        assert mock_rm.called
        assert mock_rm.call_args[0][1:] == ("src-old", 5)
        # State cleared so double-press doesn't double-remove.
        assert state.last_skipped is None
        # Re-rendered the current time.
        assert mock_render.called
        # Logged the new pick in history.
        assert mock_append.called

    def test_unskip_noop_when_no_last_skipped(self, tmp_path, capsys):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_skipped = None
        with patch("run_clock.render_now") as mock_render, \
             patch("run_clock.pick_quote_module.remove_last_history_entry") as mock_rm:
            _short, hold = run_clock._build_button_handlers(args, state)
            hold["A"]()
        assert not mock_rm.called
        assert not mock_render.called
        assert "no recently-skipped" in capsys.readouterr().out


class TestShutdownHandler:
    """Button D held 2s: goodnight frame, then invoke shutdown command."""

    def _args(self, tmp_path, **overrides):
        defaults = dict(
            render_script="render_quote.py",
            output=str(tmp_path / "current.png"),
            width=800, height=480, display_script=None,
            mode="debug", theme="default",
            history_path="", history_days=7, telemetry_path="",
            state_path="", quiet_image="",
            shutdown_command="sudo -n shutdown -h now",
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_shutdown_invokes_configured_command(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        with patch("run_clock.subprocess.run") as mock_check, \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            _short, hold = run_clock._build_button_handlers(args, state)
            hold["D"]()
        assert mock_check.called
        cmd = mock_check.call_args[0][0]
        assert cmd == ["sudo", "-n", "shutdown", "-h", "now"]

    def test_empty_shutdown_command_skips_invocation(self, tmp_path, capsys):
        args = self._args(tmp_path, shutdown_command="")
        state = run_clock.RuntimeState("default")
        with patch("run_clock.subprocess.run") as mock_check, \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            _short, hold = run_clock._build_button_handlers(args, state)
            hold["D"]()
        assert not mock_check.called
        assert "skipping system shutdown" in capsys.readouterr().out

    def test_empty_shutdown_command_does_not_flip_quiet(self, tmp_path):
        """When shutdown is disabled, an accidental long-press must not leave
        the clock stuck in manual quiet mode (which would persist across restarts)."""
        args = self._args(tmp_path, shutdown_command="")
        state = run_clock.RuntimeState("default")
        assert state.manual_quiet is False
        with patch("run_clock._display_quiet_image") as mock_display, \
             patch("run_clock.subprocess.run"), \
             patch("run_clock.save_runtime_state") as mock_save, \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            _short, hold = run_clock._build_button_handlers(args, state)
            hold["D"]()
        assert state.manual_quiet is False
        assert not mock_display.called
        assert not mock_save.called

    def test_shutdown_displays_goodnight_first(self, tmp_path):
        quiet = tmp_path / "goodnight.png"
        quiet.write_bytes(b"\x89PNG")
        args = self._args(tmp_path, quiet_image=str(quiet))
        state = run_clock.RuntimeState("default")
        with patch("run_clock._display_quiet_image") as mock_display, \
             patch("run_clock.subprocess.run"), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            _short, hold = run_clock._build_button_handlers(args, state)
            hold["D"]()
        assert mock_display.called

    def test_shutdown_command_failure_is_logged_not_raised(self, tmp_path, capsys):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        with patch("run_clock.subprocess.run", side_effect=RuntimeError("nope")), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            _short, hold = run_clock._build_button_handlers(args, state)
            # Must not raise.
            hold["D"]()
        assert "shutdown command" in capsys.readouterr().err

    def test_shutdown_flips_manual_quiet_before_goodnight_push(self, tmp_path):
        """P1 regression: manual_quiet must be set before the goodnight push
        so a concurrent main-loop tick takes the quiet branch and cannot slip a
        normal render between the goodnight frame and the shutdown invocation.
        """
        quiet = tmp_path / "goodnight.png"
        quiet.write_bytes(b"\x89PNG")
        args = self._args(tmp_path, quiet_image=str(quiet))
        state = run_clock.RuntimeState("default")
        seen_flag_at_display = []

        def record_display(*a, **kw):
            seen_flag_at_display.append(state.manual_quiet)

        with patch("run_clock._display_quiet_image", side_effect=record_display), \
             patch("run_clock.subprocess.run"), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            _short, hold = run_clock._build_button_handlers(args, state)
            hold["D"]()
        assert seen_flag_at_display == [True]

    def test_shutdown_passes_reason_to_quiet_display(self, tmp_path):
        """Log label for the goodnight push must distinguish shutdown from quiet hours."""
        quiet = tmp_path / "goodnight.png"
        quiet.write_bytes(b"\x89PNG")
        args = self._args(tmp_path, quiet_image=str(quiet))
        state = run_clock.RuntimeState("default")
        with patch("run_clock._display_quiet_image") as mock_display, \
             patch("run_clock.subprocess.run"), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            _short, hold = run_clock._build_button_handlers(args, state)
            hold["D"]()
        kwargs = mock_display.call_args.kwargs
        assert kwargs.get("reason") == "shutdown"


class TestStartupImage:
    """--startup-image: push a static PNG before the first real render on boot."""

    def test_startup_image_pushed_when_set(self, tmp_path):
        startup = tmp_path / "starting.png"
        startup.write_bytes(b"\x89PNG")
        argv = [
            "run_clock.py",
            "--once",
            "--startup-image", str(startup),
            "--output", str(tmp_path / "out.png"),
            "--history-path", "",
            "--telemetry-path", "",
            "--state-path", "",
        ]
        # --once skips the startup image (it's for the loop). Verify parse accepts.
        with patch("sys.argv", argv):
            args = run_clock.parse_args()
        assert args.startup_image == str(startup)

    def test_startup_image_used_in_main_loop_path(self, tmp_path, monkeypatch):
        """When --startup-image is set and --once is not, main() calls _display_quiet_image
        once before entering the loop, then the loop body can be aborted via a stub.
        """
        startup = tmp_path / "starting.png"
        startup.write_bytes(b"\x89PNG")
        argv = [
            "run_clock.py",
            "--startup-image", str(startup),
            "--output", str(tmp_path / "out.png"),
            "--buttons-off",
            "--history-path", "", "--telemetry-path", "",
            "--state-path", "",
            "--quiet-off",
            "--interval-seconds", "1",
        ]
        calls = []

        def fake_display(quiet_image, output, display_script, **kwargs):
            calls.append(("display", quiet_image, kwargs.get("reason")))

        def fake_sleep(_):
            raise KeyboardInterrupt

        monkeypatch.setattr(run_clock, "_display_quiet_image", fake_display)
        monkeypatch.setattr(run_clock, "_loop_sleep", lambda _s, _sec: fake_sleep(_sec))
        with patch("sys.argv", argv), \
             patch("run_clock.render_now") as mock_render, \
             patch("run_clock.peek_quote_id", return_value=("src", 1, "q", "mt")):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()
        # Startup image was pushed before any render.
        assert any(c[0] == "display" for c in calls)
        # And normal render still ran for the first tick.
        assert mock_render.called

    def test_startup_image_pushed_before_buttons_start(self, tmp_path, monkeypatch):
        """P1 regression: startup-frame push must happen BEFORE the button
        listener starts, so a press during the (slow) Inky push cannot race
        against the unlocked display call.
        """
        startup = tmp_path / "starting.png"
        startup.write_bytes(b"\x89PNG")
        argv = [
            "run_clock.py",
            "--startup-image", str(startup),
            "--output", str(tmp_path / "out.png"),
            "--history-path", "", "--telemetry-path", "",
            "--state-path", "", "--quiet-off",
            "--interval-seconds", "1",
        ]
        order = []

        def fake_display(*a, **kw):
            order.append(("display", kw.get("reason")))

        def fake_start_buttons(*a, **kw):
            order.append(("buttons",))
            return []

        monkeypatch.setattr(run_clock, "_display_quiet_image", fake_display)
        monkeypatch.setattr(run_clock, "_maybe_start_buttons", fake_start_buttons)
        monkeypatch.setattr(run_clock, "_loop_sleep", lambda _s, _sec: (_ for _ in ()).throw(KeyboardInterrupt))
        with patch("sys.argv", argv), \
             patch("run_clock.render_now"), \
             patch("run_clock.peek_quote_id", return_value=("s", 1, "q", "m")):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()
        # Startup display must precede button listener.
        assert order[0] == ("display", "startup")
        assert ("buttons",) in order
        assert order.index(("display", "startup")) < order.index(("buttons",))

    def test_no_startup_image_when_flag_omitted(self, tmp_path, monkeypatch):
        argv = [
            "run_clock.py",
            "--output", str(tmp_path / "out.png"),
            "--buttons-off",
            "--history-path", "", "--telemetry-path", "",
            "--state-path", "", "--quiet-off",
            "--interval-seconds", "1",
        ]
        displayed = []
        monkeypatch.setattr(
            run_clock, "_display_quiet_image",
            lambda q, o, d, **kw: displayed.append(q),
        )
        monkeypatch.setattr(run_clock, "_loop_sleep", lambda _s, _sec: (_ for _ in ()).throw(KeyboardInterrupt))
        with patch("sys.argv", argv), \
             patch("run_clock.render_now"), \
             patch("run_clock.peek_quote_id", return_value=None):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()
        assert displayed == []


class TestButtonRenderGate:
    """Rapid presses must not queue behind an in-flight render.

    The Spectra 6 refresh is 10–20 s per frame, so gpiozero's default
    behavior (queue each press until the prior callback returns) makes the
    clock feel unresponsive for up to a minute after a burst of taps. The
    gate uses a non-blocking ``acquire`` so the first press wins and the
    rest are logged and dropped.
    """

    def _args(self, tmp_path, **overrides):
        defaults = dict(
            render_script="render_quote.py",
            output=str(tmp_path / "current.png"),
            width=800, height=480, display_script=None,
            mode="debug", theme="default",
            history_path="", history_days=7, telemetry_path="",
            state_path="", quiet_image="", shutdown_command="",
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_skip_dropped_when_render_lock_busy(self, tmp_path, capsys):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.render_lock.acquire()  # Simulate an in-flight render.
        try:
            with patch("run_clock.render_now") as mock_render, \
                 patch("run_clock.peek_quote_id", return_value=("src", 1, "q", "mt")), \
                 patch("run_clock.current_time_str", return_value="10:00"), \
                 patch("run_clock.current_bucket", return_value="h10_exact"):
                short, _hold = run_clock._build_button_handlers(args, state)
                short["A"]()
        finally:
            state.render_lock.release()
        assert not mock_render.called
        assert "busy" in capsys.readouterr().out

    def test_theme_dropped_when_render_lock_busy_leaves_state_untouched(self, tmp_path):
        """A dropped press must not mutate persisted state — otherwise tapping
        B during a render would silently flip manual_theme while the user sees
        no change, and the next tick would re-render with a surprise theme."""
        args = self._args(tmp_path, state_path=str(tmp_path / "state.json"))
        state = run_clock.RuntimeState("default")
        state.render_lock.acquire()
        try:
            with patch("run_clock.render_now"), \
                 patch("run_clock.save_runtime_state") as mock_save, \
                 patch("run_clock.current_time_str", return_value="10:00"):
                short, _hold = run_clock._build_button_handlers(args, state)
                short["B"]()
        finally:
            state.render_lock.release()
        assert state.manual_theme is None
        assert not mock_save.called

    def test_release_is_released_even_if_handler_raises(self, tmp_path):
        """Gate must release the lock on handler exception so subsequent presses work."""
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        with patch("run_clock.peek_quote_id", side_effect=RuntimeError("boom")), \
             patch("run_clock.current_time_str", return_value="10:00"), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            short, _hold = run_clock._build_button_handlers(args, state)
            short["A"]()  # Exception is caught by handler's try/except; gate must still release.
        # Lock should be free now; acquiring non-blocking must succeed.
        assert state.render_lock.acquire(blocking=False)
        state.render_lock.release()


class TestPruneTelemetry:
    """``prune_telemetry`` unlinks only date-suffixed siblings older than the window."""

    def _touch(self, base, date_str):
        path = base.parent / f"{base.stem}-{date_str}{base.suffix}"
        path.write_text("")
        return path

    def test_drops_siblings_older_than_retain_days(self, tmp_path):
        base = tmp_path / "telemetry.jsonl"
        today = dt.date(2026, 4, 20)
        old = self._touch(base, "20260101")
        recent = self._touch(base, "20260418")
        current = self._touch(base, "20260420")
        removed = run_clock.prune_telemetry(str(base), retain_days=30, today=today)
        assert removed == 1
        assert not old.exists()
        assert recent.exists()
        assert current.exists()

    def test_retain_zero_disables_pruning(self, tmp_path):
        base = tmp_path / "telemetry.jsonl"
        today = dt.date(2026, 4, 20)
        old = self._touch(base, "20200101")
        removed = run_clock.prune_telemetry(str(base), retain_days=0, today=today)
        assert removed == 0
        assert old.exists()

    def test_missing_directory_is_safe(self, tmp_path):
        base = tmp_path / "does" / "not" / "exist" / "telemetry.jsonl"
        removed = run_clock.prune_telemetry(str(base), retain_days=30, today=dt.date(2026, 4, 20))
        assert removed == 0

    def test_empty_path_disables_pruning(self, tmp_path):
        assert run_clock.prune_telemetry("", retain_days=30) == 0
        assert run_clock.prune_telemetry(None, retain_days=30) == 0

    def test_non_matching_siblings_ignored(self, tmp_path):
        """Files that match the glob pattern but have a bad date suffix stay put."""
        base = tmp_path / "telemetry.jsonl"
        today = dt.date(2026, 4, 20)
        bogus = base.parent / "telemetry-BADSUFFIX.jsonl"
        bogus.write_text("")
        removed = run_clock.prune_telemetry(str(base), retain_days=1, today=today)
        assert removed == 0
        assert bogus.exists()

    def test_other_stems_ignored(self, tmp_path):
        """A different base stem's date siblings must not be pruned."""
        base = tmp_path / "telemetry.jsonl"
        other = tmp_path / "unrelated-20200101.jsonl"
        other.write_text("")
        removed = run_clock.prune_telemetry(str(base), retain_days=1, today=dt.date(2026, 4, 20))
        assert removed == 0
        assert other.exists()


class TestInstallSignalHandlers:
    """Signal handlers must flip ``state.stop_requested`` without tearing down the process."""

    def test_sigterm_sets_stop_event(self):
        import os
        import signal
        import time

        state = run_clock.RuntimeState("default")
        run_clock._install_signal_handlers(state)
        try:
            assert not state.stop_requested.is_set()
            os.kill(os.getpid(), signal.SIGTERM)
            # Give the signal dispatcher a moment.
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline and not state.stop_requested.is_set():
                time.sleep(0.01)
            assert state.stop_requested.is_set()
        finally:
            # Reset default handler so subsequent tests in this process aren't affected.
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            signal.signal(signal.SIGINT, signal.SIG_DFL)


class TestShutdown:
    """``_shutdown`` must tear resources down best-effort even when something raises."""

    def _args(self, tmp_path):
        return argparse.Namespace(state_path=str(tmp_path / "state.json"))

    def test_releases_buttons_and_saves_state(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.manual_theme = "dark"

        closed = []

        class FakeButton:
            def close(self):
                closed.append(True)

        state.button_handles = [FakeButton(), FakeButton()]

        run_clock._shutdown(args, state, web_handle=None)
        assert closed == [True, True]
        # State persisted.
        assert json.loads((tmp_path / "state.json").read_text())["manual_theme"] == "dark"

    def test_tolerates_render_lock_already_held(self, tmp_path, capsys):
        """If render lock can't be acquired within the drain window, shutdown still proceeds.

        Swap in a stub lock whose ``acquire`` returns False immediately (simulating
        a 30s drain timeout) so the test doesn't wait.
        """
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")

        class _StubLock:
            def acquire(self, *a, **kw):
                return False

            def release(self):
                pass

        state.render_lock = _StubLock()
        # Must not raise; should log the "still in flight" warning.
        run_clock._shutdown(args, state, web_handle=None)
        err = capsys.readouterr().err
        assert "render still in flight" in err

    def test_missing_button_handles_is_fine(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        # No button handles set; shutdown should not blow up.
        run_clock._shutdown(args, state, web_handle=None)

    def test_holds_render_lock_across_ingress_teardown(self, tmp_path):
        """Regression: the render lock must stay held while the web server is
        stopped and GPIO buttons are closed, so a late POST / button press
        can't grab it via ``_button_render_gate`` and start a fresh render
        during shutdown.
        """
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")

        observations = []

        def observe_stop(handle):
            observations.append(("web_stop", state.render_lock.locked()))

        class FakeButton:
            def close(self):
                observations.append(("button_close", state.render_lock.locked()))

        state.button_handles = [FakeButton()]
        with patch("run_clock.stop_web_server", side_effect=observe_stop):
            run_clock._shutdown(args, state, web_handle=object())

        # The web server and button close both observed the lock as HELD.
        assert ("web_stop", True) in observations
        assert ("button_close", True) in observations
        # And it was released afterwards so the process can exit cleanly.
        assert not state.render_lock.locked()

    def test_persist_failure_does_not_raise(self, tmp_path, monkeypatch):
        """A save-state failure during shutdown must be swallowed (best-effort)."""
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        monkeypatch.setattr(
            run_clock, "save_runtime_state",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        # Must not raise.
        run_clock._shutdown(args, state, web_handle=None)


class TestMaybePruneTelemetry:
    """The main-loop wrapper must prune at most once per local-date rollover."""

    def _args(self, tmp_path, retain_days=30):
        return argparse.Namespace(telemetry_retain_days=retain_days)

    def test_skips_when_telemetry_disabled(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(run_clock, "prune_telemetry", lambda *a, **kw: calls.append(a) or 0)
        state = run_clock.RuntimeState("default")
        run_clock._maybe_prune_telemetry(self._args(tmp_path), state, telemetry_path=None)
        run_clock._maybe_prune_telemetry(self._args(tmp_path), state, telemetry_path="")
        assert calls == []

    def test_runs_once_per_day(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(run_clock, "prune_telemetry", lambda *a, **kw: calls.append(a) or 0)
        state = run_clock.RuntimeState("default")
        args = self._args(tmp_path)
        run_clock._maybe_prune_telemetry(args, state, telemetry_path=str(tmp_path / "t.jsonl"))
        run_clock._maybe_prune_telemetry(args, state, telemetry_path=str(tmp_path / "t.jsonl"))
        assert len(calls) == 1

    def test_runs_again_next_day(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(run_clock, "prune_telemetry", lambda *a, **kw: calls.append(a) or 0)
        state = run_clock.RuntimeState("default")
        args = self._args(tmp_path)
        run_clock._maybe_prune_telemetry(args, state, telemetry_path=str(tmp_path / "t.jsonl"))
        state.last_pruned_date = dt.date.today() - dt.timedelta(days=1)
        run_clock._maybe_prune_telemetry(args, state, telemetry_path=str(tmp_path / "t.jsonl"))
        assert len(calls) == 2

    def test_skips_when_retain_days_zero(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(run_clock, "prune_telemetry", lambda *a, **kw: calls.append(a) or 0)
        state = run_clock.RuntimeState("default")
        args = self._args(tmp_path, retain_days=0)
        run_clock._maybe_prune_telemetry(args, state, telemetry_path=str(tmp_path / "t.jsonl"))
        assert calls == []


class TestMaybeCompactHistory:
    """The main-loop wrapper must compact the ledger at most once per local-date rollover."""

    def _args(self, tmp_path, history_days=7, history_path=None):
        return argparse.Namespace(
            history_days=history_days,
            history_path=history_path if history_path is not None else str(tmp_path / "history.jsonl"),
        )

    def test_runs_once_per_day(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(
            run_clock.pick_quote_module, "compact_history", lambda *a, **kw: calls.append(a) or 0,
        )
        state = run_clock.RuntimeState("default")
        args = self._args(tmp_path)
        run_clock._maybe_compact_history(args, state)
        run_clock._maybe_compact_history(args, state)
        assert len(calls) == 1

    def test_runs_again_next_day(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(
            run_clock.pick_quote_module, "compact_history", lambda *a, **kw: calls.append(a) or 0,
        )
        state = run_clock.RuntimeState("default")
        args = self._args(tmp_path)
        run_clock._maybe_compact_history(args, state)
        state.last_compacted_date = dt.date.today() - dt.timedelta(days=1)
        run_clock._maybe_compact_history(args, state)
        assert len(calls) == 2

    def test_skips_when_history_disabled(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(
            run_clock.pick_quote_module, "compact_history", lambda *a, **kw: calls.append(a) or 0,
        )
        state = run_clock.RuntimeState("default")
        run_clock._maybe_compact_history(self._args(tmp_path, history_path=""), state)
        run_clock._maybe_compact_history(self._args(tmp_path, history_days=0), state)
        assert calls == []

    def test_disk_error_does_not_bubble(self, tmp_path, monkeypatch):
        """A compact failure is logged, not raised — the ledger compact must not
        trip the outer-loop render backoff."""
        def boom(*a, **kw):
            raise OSError("disk full")

        monkeypatch.setattr(run_clock.pick_quote_module, "compact_history", boom)
        state = run_clock.RuntimeState("default")
        run_clock._maybe_compact_history(self._args(tmp_path), state)


class TestActionExceptionBranches:
    """Every ``action_*`` wraps its body in ``except Exception`` so a failure
    can't kill the GPIO listener thread or the HTTP worker. These tests inject
    failures into the inner render path and verify (a) the error is logged to
    telemetry, (b) the returned dict shape is ``{"ok": False, "error": <repr>}``,
    and (c) no exception escapes to the caller.
    """

    def _args(self, tmp_path, **overrides):
        defaults = dict(
            render_script="render_quote.py",
            output=str(tmp_path / "current.png"),
            width=800,
            height=480,
            display_script=None,
            mode="debug",
            theme="default",
            history_path=str(tmp_path / "history.jsonl"),
            history_days=7,
            telemetry_path=str(tmp_path / "telemetry.jsonl"),
            state_path=str(tmp_path / "state.json"),
            quiet_image="",
            shutdown_command="",
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def _read_telemetry(self, tmp_path) -> list[dict]:
        """Read every rotated telemetry sibling (date-suffixed). Tests may see
        zero or one file depending on whether ``append_telemetry`` ran."""
        entries = []
        for path in tmp_path.glob("telemetry-*.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entries.append(json.loads(line))
        return entries

    def test_skip_renders_failure_returns_error_dict(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_quote_id = ("src-old", 5, "q-old", "mt-old")
        with patch("run_clock.peek_quote_id", return_value=("src-new", 7, "q-new", "mt-new")), \
             patch("run_clock._render_unlocked", side_effect=RuntimeError("panel disconnected")), \
             patch("run_clock.current_time_str", return_value="10:00"), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            result = run_clock.action_skip(args, state, label="web")
        assert result["ok"] is False
        assert "panel disconnected" in result["error"]
        entries = self._read_telemetry(tmp_path)
        assert any(
            e.get("mode") == "action"
            and e.get("action") == "skip"
            and e.get("ok") is False
            and "panel disconnected" in e.get("error", "")
            for e in entries
        )

    def test_unskip_remove_entry_failure_returns_error_dict(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_skipped = ("src-banned", 42)
        with patch("run_clock.pick_quote_module.remove_last_history_entry",
                   side_effect=OSError("disk full")), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            result = run_clock.action_unskip(args, state, label="web")
        assert result["ok"] is False
        assert "disk full" in result["error"]
        entries = self._read_telemetry(tmp_path)
        assert any(
            e.get("mode") == "action" and e.get("action") == "unskip" and e.get("ok") is False
            for e in entries
        )

    def test_theme_render_failure_returns_error_dict(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_effective_theme = "default"
        with patch("run_clock._render_unlocked", side_effect=RuntimeError("pillow boom")), \
             patch("run_clock.current_time_str", return_value="10:00"), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            result = run_clock.action_theme(args, state, label="web")
        assert result["ok"] is False
        assert "pillow boom" in result["error"]
        # Persist-before-display race fix: a display push failure must roll
        # the flip back so ``state.json`` stays in sync with what's on the
        # panel. Pre-fix this asserted ``state.manual_theme == "dark"``, which
        # is exactly the bug that issue #56 describes.
        assert state.manual_theme is None
        assert result.get("rolled_back") is True

    def test_quiet_render_failure_returns_error_dict(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.manual_quiet = True  # toggling will flip to False and try to wake-render
        with patch("run_clock._render_unlocked", side_effect=RuntimeError("no corpus")), \
             patch("run_clock.peek_quote_id", return_value=("src", 1, "q", "mt")), \
             patch("run_clock.current_time_str", return_value="10:00"), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            result = run_clock.action_quiet(args, state, label="web")
        assert result["ok"] is False
        assert "no corpus" in result["error"]

    def test_rerender_failure_returns_error_dict(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        with patch("run_clock.peek_quote_id", return_value=("src", 1, "q", "mt")), \
             patch("run_clock._render_unlocked", side_effect=RuntimeError("pick failed")), \
             patch("run_clock.current_time_str", return_value="10:00"), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            result = run_clock.action_rerender(args, state, label="web")
        assert result["ok"] is False
        assert "pick failed" in result["error"]
        entries = self._read_telemetry(tmp_path)
        assert any(
            e.get("mode") == "action" and e.get("action") == "rerender" and e.get("ok") is False
            for e in entries
        )

    def test_all_actions_return_busy_when_render_lock_held(self, tmp_path):
        """Non-blocking acquire must return {'ok': False, 'error': 'busy'}
        for every action when another thread holds render_lock."""
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        # Simulate an in-flight render by holding render_lock in this test.
        state.render_lock.acquire()
        try:
            for action in (
                run_clock.action_skip, run_clock.action_unskip,
                run_clock.action_theme, run_clock.action_quiet,
                run_clock.action_rerender,
            ):
                result = action(args, state, label="web")
                assert result == {"ok": False, "error": "busy"}, f"{action.__name__} did not drop on busy"
        finally:
            state.render_lock.release()

    def test_unskip_noop_when_no_last_skipped_returns_ok(self, tmp_path):
        """Un-skip with an empty ``state.last_skipped`` is a no-op, not an error."""
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_skipped = None
        result = run_clock.action_unskip(args, state, label="web")
        assert result == {"ok": True, "restored": None}


class TestActionSuccessTelemetry:
    """Each ``action_*`` emits a structured ``mode="action"`` entry on
    success. Failures emit the same shape with ``ok=False`` (covered in
    ``TestActionExceptionBranches``); busy-drops emit ``mode="press_dropped"``
    from ``_button_render_gate`` (covered in ``TestPressDroppedTelemetry``)
    so there is exactly one operator-visible marker per press.
    """

    def _args(self, tmp_path, **overrides):
        defaults = dict(
            render_script="render_quote.py",
            output=str(tmp_path / "current.png"),
            width=800,
            height=480,
            display_script=None,
            mode="debug",
            theme="default",
            history_path=str(tmp_path / "history.jsonl"),
            history_days=7,
            telemetry_path=str(tmp_path / "telemetry.jsonl"),
            state_path=str(tmp_path / "state.json"),
            quiet_image="",
            shutdown_command="",
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def _read_telemetry(self, tmp_path) -> list[dict]:
        entries = []
        for path in tmp_path.glob("telemetry-*.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entries.append(json.loads(line))
        return entries

    def test_skip_success_emits_action_entry(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        with patch("run_clock.peek_quote_id", return_value=("src", 1, "q", "mt")), \
             patch("run_clock._render_unlocked"), \
             patch("run_clock.current_time_str", return_value="10:00"):
            result = run_clock.action_skip(args, state, label="button A")
        assert result["ok"] is True
        entries = self._read_telemetry(tmp_path)
        matching = [e for e in entries if e.get("mode") == "action" and e.get("action") == "skip"]
        assert matching, entries
        assert matching[0]["label"] == "button A"
        assert matching[0]["ok"] is True
        assert "error" not in matching[0]

    def test_theme_success_emits_action_entry(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_effective_theme = "default"
        with patch("run_clock._render_unlocked"), \
             patch("run_clock.current_time_str", return_value="10:00"):
            result = run_clock.action_theme(args, state, label="web")
        assert result["ok"] is True
        entries = self._read_telemetry(tmp_path)
        matching = [e for e in entries if e.get("mode") == "action" and e.get("action") == "theme"]
        assert matching
        assert matching[0]["label"] == "web"
        assert matching[0]["ok"] is True

    def test_quiet_success_emits_action_entry(self, tmp_path):
        args = self._args(tmp_path, quiet_image="")
        state = run_clock.RuntimeState("default")
        state.manual_quiet = True
        with patch("run_clock._render_unlocked"), \
             patch("run_clock.peek_quote_id", return_value=("src", 1, "q", "mt")), \
             patch("run_clock.current_time_str", return_value="10:00"):
            result = run_clock.action_quiet(args, state, label="button D")
        assert result["ok"] is True
        entries = self._read_telemetry(tmp_path)
        matching = [e for e in entries if e.get("mode") == "action" and e.get("action") == "quiet"]
        assert matching
        assert matching[0]["label"] == "button D"

    def test_rerender_success_emits_action_entry(self, tmp_path):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        with patch("run_clock._render_unlocked"), \
             patch("run_clock.peek_quote_id", return_value=("src", 1, "q", "mt")), \
             patch("run_clock.current_time_str", return_value="10:00"):
            result = run_clock.action_rerender(args, state, label="web")
        assert result["ok"] is True
        entries = self._read_telemetry(tmp_path)
        matching = [e for e in entries if e.get("mode") == "action" and e.get("action") == "rerender"]
        assert matching

    def test_unskip_noop_still_emits_action_entry(self, tmp_path):
        """An un-skip with nothing to restore is a successful no-op — still
        emits ``mode="action"`` so the summary counts the operator press."""
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_skipped = None
        run_clock.action_unskip(args, state, label="button A")
        entries = self._read_telemetry(tmp_path)
        matching = [e for e in entries if e.get("mode") == "action" and e.get("action") == "unskip"]
        assert matching
        assert matching[0]["ok"] is True


class TestPressDroppedTelemetry:
    """``_button_render_gate`` emits a ``mode="press_dropped"`` entry when
    the non-blocking ``render_lock.acquire`` fails. One entry per dropped
    press, never paired with an action entry.
    """

    def _args(self, tmp_path, **overrides):
        defaults = dict(
            render_script="render_quote.py",
            output=str(tmp_path / "current.png"),
            width=800,
            height=480,
            display_script=None,
            mode="debug",
            theme="default",
            history_path=str(tmp_path / "history.jsonl"),
            history_days=7,
            telemetry_path=str(tmp_path / "telemetry.jsonl"),
            state_path=str(tmp_path / "state.json"),
            quiet_image="",
            shutdown_command="",
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def _read_telemetry(self, tmp_path) -> list[dict]:
        entries = []
        for path in tmp_path.glob("telemetry-*.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entries.append(json.loads(line))
        return entries

    def test_busy_skip_emits_press_dropped_not_action(self, tmp_path):
        """Acceptance criterion from issue #55: a press during an in-flight
        render shows up as ``press_dropped``, and NOT as an ``action`` entry."""
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.render_lock.acquire()
        try:
            result = run_clock.action_skip(args, state, label="button A")
        finally:
            state.render_lock.release()
        assert result == {"ok": False, "error": "busy"}
        entries = self._read_telemetry(tmp_path)
        dropped = [e for e in entries if e.get("mode") == "press_dropped"]
        actions = [e for e in entries if e.get("mode") == "action"]
        assert len(dropped) == 1
        assert actions == []  # busy path must not double-count
        assert dropped[0]["label"] == "button A"
        assert dropped[0]["action"] == "skip"
        assert dropped[0]["reason"] == "render_in_flight"

    def test_spam_ten_presses_yields_one_success_and_nine_dropped(self, tmp_path):
        """Acceptance criterion from issue #55: 10 presses during a slow
        render ⇒ 1 success + 9 dropped. We simulate this by holding the
        render lock for 9 of the 10 presses, then releasing for the 10th."""
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        with patch("run_clock._render_unlocked"), \
             patch("run_clock.peek_quote_id", return_value=("src", 1, "q", "mt")), \
             patch("run_clock.current_time_str", return_value="10:00"):
            state.render_lock.acquire()
            try:
                for _ in range(9):
                    run_clock.action_theme(args, state, label="button B")
            finally:
                state.render_lock.release()
            # The 10th press succeeds.
            run_clock.action_theme(args, state, label="button B")
        entries = self._read_telemetry(tmp_path)
        dropped = [e for e in entries if e.get("mode") == "press_dropped"]
        actions = [e for e in entries if e.get("mode") == "action" and e.get("ok") is True]
        assert len(dropped) == 9
        assert len(actions) == 1


class TestQuietHoursTelemetry:
    """``enter_quiet`` emits ``mode="quiet_enter"`` (scheduled or manual);
    the main loop's scheduled-exit branch emits ``mode="quiet_exit"`` after
    calling ``exit_quiet``. Manual-quiet toggles are tracked via the
    ``action`` telemetry instead, so they don't double-count here.
    """

    def test_enter_quiet_emits_telemetry(self, tmp_path):
        import runtime_quiet
        args = argparse.Namespace(
            history_path="",
            telemetry_path=str(tmp_path / "telemetry.jsonl"),
            quiet_start="22:00",
            quiet_end="06:00",
            quiet_image="",
            output=str(tmp_path / "out.png"),
            display_script=None,
            render_script="render_quote.py",
            width=800,
            height=480,
            mode="debug",
            history_days=7,
        )
        state = run_clock.RuntimeState("default")
        with patch("run_clock.render_now"), \
             patch("run_clock._display_quiet_image"):
            runtime_quiet.enter_quiet(args, state, "22:30", manual_only=False)
        entries = []
        for path in tmp_path.glob("telemetry-*.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entries.append(json.loads(line))
        matching = [e for e in entries if e.get("mode") == "quiet_enter"]
        assert matching, entries
        assert matching[0]["manual"] is False

    def test_manual_quiet_enter_records_manual_true(self, tmp_path):
        import runtime_quiet
        args = argparse.Namespace(
            history_path="",
            telemetry_path=str(tmp_path / "telemetry.jsonl"),
            quiet_start="22:00",
            quiet_end="06:00",
            quiet_image="",
            output=str(tmp_path / "out.png"),
            display_script=None,
            render_script="render_quote.py",
            width=800,
            height=480,
            mode="debug",
            history_days=7,
        )
        state = run_clock.RuntimeState("default")
        with patch("run_clock.render_now"), \
             patch("run_clock._display_quiet_image"):
            runtime_quiet.enter_quiet(args, state, "12:00", manual_only=True)
        entries = []
        for path in tmp_path.glob("telemetry-*.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entries.append(json.loads(line))
        matching = [e for e in entries if e.get("mode") == "quiet_enter"]
        assert matching
        assert matching[0]["manual"] is True


class TestParseArgsBasic:
    """Smoke coverage for parse_args — the loop entry point."""

    def test_defaults(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["run_clock.py"])
        args = run_clock.parse_args()
        assert args.quiet_start == "22:00"
        assert args.quiet_end == "06:00"
        assert args.mode == "debug"
        assert args.theme == "default"

    def test_overrides(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            [
                "run_clock.py",
                "--quiet-start", "23:30",
                "--quiet-end", "07:00",
                "--mode", "production",
                "--theme", "dark",
            ],
        )
        args = run_clock.parse_args()
        assert args.quiet_start == "23:30"
        assert args.quiet_end == "07:00"
        assert args.mode == "production"
        assert args.theme == "dark"

    def test_invalid_hhmm_is_rejected(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["run_clock.py", "--quiet-start", "25:99"])
        with pytest.raises(SystemExit):
            run_clock.parse_args()


class TestMaybeStartWebServer:
    """The web server is optional; startup failures must not abort the loop."""

    def _args(self, web_bind=None):
        return argparse.Namespace(
            web_bind=web_bind,
            web_token="",
            web_token_file=None,
            output="out.png",
            history_path="",
            telemetry_path="",
            overrides="assets/selection_overrides.json",
            mode="debug",
        )

    def test_disabled_when_bind_empty(self):
        state = run_clock.RuntimeState("default")
        assert run_clock._maybe_start_web_server(self._args(None), state) is None
        assert run_clock._maybe_start_web_server(self._args(""), state) is None

    def test_start_failure_logs_and_returns_none(self, monkeypatch, capsys):
        """If web_server.start_web_server raises, we log and return None —
        never propagate the exception and never kill the loop."""
        state = run_clock.RuntimeState("default")
        import web_server
        monkeypatch.setattr(web_server, "start_web_server",
                            lambda *a, **kw: (_ for _ in ()).throw(ValueError("bad bind")))
        result = run_clock._maybe_start_web_server(self._args("0.0.0.0:8080"), state)
        assert result is None
        err = capsys.readouterr().err
        assert "web UI failed to start" in err and "bad bind" in err


class TestResolveWebToken:
    def _args(self, **kw):
        return argparse.Namespace(web_token=kw.get("web_token", ""), web_token_file=kw.get("web_token_file"))

    def test_empty_when_unset(self):
        assert run_clock._resolve_web_token(self._args()) == ""

    def test_reads_from_token_file(self, tmp_path):
        token_file = tmp_path / "token"
        token_file.write_text("s3cret\n", encoding="utf-8")
        assert run_clock._resolve_web_token(self._args(web_token_file=str(token_file))) == "s3cret"

    def test_token_file_wins_over_inline(self, tmp_path):
        token_file = tmp_path / "token"
        token_file.write_text("from-file\n", encoding="utf-8")
        args = self._args(web_token="from-flag", web_token_file=str(token_file))
        assert run_clock._resolve_web_token(args) == "from-file"

    def test_missing_token_file_falls_back_to_inline(self, tmp_path, capsys):
        args = self._args(web_token="fallback", web_token_file=str(tmp_path / "nonexistent"))
        assert run_clock._resolve_web_token(args) == "fallback"
        assert "unreadable" in capsys.readouterr().err

    def test_missing_file_and_no_inline_returns_empty(self, tmp_path):
        args = self._args(web_token_file=str(tmp_path / "nope"))
        assert run_clock._resolve_web_token(args) == ""


class TestStopWebServer:
    def test_none_handle_is_noop(self):
        run_clock.stop_web_server(None)  # must not raise

    def test_server_close_failure_is_swallowed(self):
        class BadServer:
            def shutdown(self):
                pass

            def server_close(self):
                raise OSError("already closed")
        thread = type("T", (), {"join": lambda self, timeout=None: None})()
        # Must not raise despite server_close failing.
        run_clock.stop_web_server((BadServer(), thread))


class TestRenderSubprocessTimeout:
    """The render subprocess must not be able to wedge the loop indefinitely.

    subprocess.run(timeout=...) kills the child before re-raising TimeoutExpired;
    we verify that our wrapper catches it, writes a telemetry entry tagged
    ``mode="render_timeout"``, and re-raises so the main-loop error branch
    keeps ``last_bucket`` stale for retry next tick.
    """

    def _boom(self, *a, **kw):
        raise subprocess.TimeoutExpired(cmd=["render_quote.py"], timeout=run_clock.RENDER_TIMEOUT_SECONDS)

    def test_render_timeout_writes_telemetry_and_reraises(self, tmp_path, capsys):
        telemetry_base = tmp_path / "telemetry.jsonl"
        with patch("subprocess.run", side_effect=self._boom), \
             patch("run_clock.current_time_str", return_value="14:30"):
            with pytest.raises(subprocess.TimeoutExpired):
                run_clock.render_now(
                    render_script="render_quote.py",
                    output_path=str(tmp_path / "current.png"),
                    width=800,
                    height=480,
                    telemetry_path=str(telemetry_base),
                    bucket="h2_half_past",
                )
        err = capsys.readouterr().err
        assert "render subprocess timed out" in err
        # Telemetry entry tagged as render_timeout.
        daily = run_clock.daily_telemetry_path(telemetry_base)
        entries = [json.loads(line) for line in daily.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(e.get("mode") == "render_timeout" for e in entries)

    def test_display_timeout_writes_telemetry_and_reraises(self, tmp_path, capsys):
        # First subprocess.run call (render) succeeds; second (display) times out.
        telemetry_base = tmp_path / "telemetry.jsonl"
        call_count = {"n": 0}

        def side(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return None
            raise subprocess.TimeoutExpired(cmd=["display_inky.py"], timeout=run_clock.DISPLAY_TIMEOUT_SECONDS)

        with patch("subprocess.run", side_effect=side), \
             patch("run_clock.current_time_str", return_value="14:30"):
            with pytest.raises(subprocess.TimeoutExpired):
                run_clock.render_now(
                    render_script="render_quote.py",
                    output_path=str(tmp_path / "current.png"),
                    width=800,
                    height=480,
                    display_script="display_inky.py",
                    telemetry_path=str(telemetry_base),
                    bucket="h2_half_past",
                )
        assert "display subprocess timed out" in capsys.readouterr().err
        daily = run_clock.daily_telemetry_path(telemetry_base)
        entries = [json.loads(line) for line in daily.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(e.get("mode") == "display_timeout" for e in entries)

    def test_timeout_kwarg_is_passed(self, tmp_path):
        """Regression: subprocess.run must actually receive the timeout kwarg."""
        captured = {}

        def record(cmd, **kw):
            captured.update(kw)

        with patch("subprocess.run", side_effect=record), \
             patch("run_clock.current_time_str", return_value="14:30"):
            run_clock.render_now(
                render_script="render_quote.py",
                output_path=str(tmp_path / "current.png"),
                width=800,
                height=480,
            )
        assert captured.get("timeout") == run_clock.RENDER_TIMEOUT_SECONDS
        assert captured.get("check") is True


class TestRenderFailureBackoff:
    """Repeated render failures must trigger exponential backoff and skip ticks.

    Without this, a pulled ribbon cable or wedged display library would have
    the main loop retry every --interval-seconds forever, flooding the log
    and starving the GPIO thread.
    """

    def test_counter_increments_on_failure(self):
        state = run_clock.RuntimeState("default")
        # Two failures in a row is below the BACKOFF_EVERY_N_FAILURES
        # threshold of 3, so no skip window is set yet.
        run_clock._record_render_failure(state, telemetry_path=None, bucket="h1_exact")
        run_clock._record_render_failure(state, telemetry_path=None, bucket="h1_exact")
        assert state.consecutive_render_failures == 2
        assert state.backoff_skip_until == 0.0

    def test_threshold_triggers_skip_window(self, tmp_path):
        telemetry_base = tmp_path / "telemetry.jsonl"
        state = run_clock.RuntimeState("default")
        for _ in range(run_clock.BACKOFF_EVERY_N_FAILURES):
            run_clock._record_render_failure(state, telemetry_path=str(telemetry_base), bucket="h1_exact")
        assert state.consecutive_render_failures == run_clock.BACKOFF_EVERY_N_FAILURES
        assert state.backoff_skip_until > 0.0
        # Telemetry entry records the backoff event.
        daily = run_clock.daily_telemetry_path(telemetry_base)
        entries = [json.loads(line) for line in daily.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(e.get("mode") == "backoff" for e in entries)

    def test_backoff_is_capped(self):
        """Very high failure counts must not produce an unbounded skip window."""
        state = run_clock.RuntimeState("default")
        # Simulate enough failures that 2**level would vastly exceed the cap.
        for _ in range(run_clock.BACKOFF_EVERY_N_FAILURES * 30):
            run_clock._record_render_failure(state, telemetry_path=None, bucket="h1_exact")
        # backoff_skip_until is a monotonic deadline, so compare via remaining
        # skip seconds bounded by BACKOFF_MAX_SECONDS + a small slack.
        import time as _time
        remaining = state.backoff_skip_until - _time.monotonic()
        assert remaining <= run_clock.BACKOFF_MAX_SECONDS + 1

    def test_in_backoff_skip_reports_true_during_window(self):
        state = run_clock.RuntimeState("default")
        import time as _time
        state.backoff_skip_until = _time.monotonic() + 30
        assert run_clock._in_backoff_skip(state) is True

    def test_in_backoff_skip_reports_false_after_window(self):
        state = run_clock.RuntimeState("default")
        state.backoff_skip_until = 0.0
        assert run_clock._in_backoff_skip(state) is False

    def test_successful_render_resets_counter(self):
        """commit_render_result is the single success seam; it must clear backoff."""
        state = run_clock.RuntimeState("default")
        state.consecutive_render_failures = 5
        import time as _time
        state.backoff_skip_until = _time.monotonic() + 60
        state.commit_render_result("h2_half_past", "default", ("src", 1))
        assert state.consecutive_render_failures == 0
        assert state.backoff_skip_until == 0.0


class TestHeartbeat:
    """The loop emits a positive liveness signal so health checks can tell
    'idle but alive' apart from 'wedged'."""

    def test_heartbeat_written_first_call(self, tmp_path):
        state = run_clock.RuntimeState("default")
        telemetry_base = tmp_path / "telemetry.jsonl"
        run_clock._maybe_emit_heartbeat(state, str(telemetry_base))
        daily = run_clock.daily_telemetry_path(telemetry_base)
        entries = [json.loads(line) for line in daily.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(e.get("type") == "heartbeat" for e in entries)

    def test_heartbeat_throttled_within_interval(self, tmp_path):
        """Three back-to-back calls must produce at most one heartbeat entry."""
        state = run_clock.RuntimeState("default")
        telemetry_base = tmp_path / "telemetry.jsonl"
        for _ in range(3):
            run_clock._maybe_emit_heartbeat(state, str(telemetry_base))
        daily = run_clock.daily_telemetry_path(telemetry_base)
        entries = [json.loads(line) for line in daily.read_text(encoding="utf-8").splitlines() if line.strip()]
        hb = [e for e in entries if e.get("type") == "heartbeat"]
        assert len(hb) == 1

    def test_heartbeat_disabled_when_no_telemetry(self, tmp_path):
        state = run_clock.RuntimeState("default")
        # No telemetry path → no-op, no file created.
        run_clock._maybe_emit_heartbeat(state, None)
        assert list(tmp_path.iterdir()) == []


class TestSourceCardTimerCancellation:
    """The 5s source-card restore Timer must not fire after _shutdown."""

    def _args(self, tmp_path):
        return argparse.Namespace(
            state_path=str(tmp_path / "state.json"),
        )

    def test_shutdown_cancels_registered_timers(self, tmp_path):
        import threading
        state = run_clock.RuntimeState("default")
        fired = []
        timer = threading.Timer(30.0, lambda: fired.append("late"))
        timer.daemon = True
        state.pending_timers.append(timer)
        timer.start()

        run_clock._shutdown(self._args(tmp_path), state, web_handle=None)
        # Timer was cancelled before it could fire.
        assert fired == []
        # Shutdown drained pending_timers so a repeat teardown doesn't double-cancel.
        assert state.pending_timers == []

    def test_shutdown_tolerates_already_fired_timer(self, tmp_path):
        """Timer.cancel is idempotent on a fired timer; shutdown must not raise."""
        import threading
        state = run_clock.RuntimeState("default")
        # A timer that never actually scheduled — cancel is still safe.
        timer = threading.Timer(0.0, lambda: None)
        state.pending_timers.append(timer)
        # No raise; pending_timers drained.
        run_clock._shutdown(self._args(tmp_path), state, web_handle=None)
        assert state.pending_timers == []


class TestBackoffSkipsSubprocess:
    """Integration assertion: when _in_backoff_skip is True, the main-loop
    body must not invoke render_now / subprocess.run at all. The unit tests
    above prove the counter / deadline arithmetic; this pins the downstream
    behaviour that actually saves the GPIO thread / log from spam.
    """

    def test_backoff_window_prevents_render_call(self, tmp_path):
        import time as _time
        # Build args for run_clock.main with a 0s interval so the loop ticks fast.
        argv = ["run_clock.py", "--output", str(tmp_path / "current.png"), "--interval-seconds", "0"]
        render_calls = []

        def fake_render(*a, **kw):
            render_calls.append(1)

        tick_count = {"n": 0}

        def stop_after_ticks(_state, _sec):
            tick_count["n"] += 1
            if tick_count["n"] >= 3:
                raise KeyboardInterrupt
            return False

        # Prime RuntimeState.backoff_skip_until BEFORE the loop starts so every
        # tick takes the backoff-skip continue. We do it via a patched
        # RuntimeState.__init__ that sets the deadline 60s in the future.
        real_init = run_clock.RuntimeState.__init__

        def init_with_backoff(self, theme_arg, persisted=None):
            real_init(self, theme_arg, persisted=persisted)
            self.backoff_skip_until = _time.monotonic() + 60.0

        with patch("sys.argv", argv), \
             patch("run_clock.render_now", side_effect=fake_render), \
             patch("run_clock.RuntimeState.__init__", init_with_backoff), \
             patch("run_clock.current_time_str", return_value="12:00"), \
             patch("run_clock._loop_sleep", side_effect=stop_after_ticks):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()
        assert render_calls == [], "render_now must not run while backoff_skip_until is in the future"

    def test_commit_resets_backoff_so_next_tick_renders(self, tmp_path):
        """Regression guard: once a success happens, the skip window clears."""
        state = run_clock.RuntimeState("default")
        import time as _time
        # Start in backoff.
        state.consecutive_render_failures = 5
        state.backoff_skip_until = _time.monotonic() + 60.0
        # Simulating a successful render call.
        state.commit_render_result("h2_half_past", "default", ("src", 1))
        assert run_clock._in_backoff_skip(state) is False


class TestDedupResetsBackoff:
    """The 'quote unchanged' dedup branch is a successful peek — it must
    also clear render-failure counters, otherwise a streak of below-threshold
    failures across ticks that happen to dedup could compound into a skip."""

    def test_dedup_branch_clears_counter_and_deadline(self, tmp_path):
        # Drive one loop tick where peek_quote_id returns the same id the state
        # already has; the dedup branch should run and reset backoff.
        argv = ["run_clock.py", "--output", str(tmp_path / "current.png"), "--interval-seconds", "0"]

        tick_count = {"n": 0}

        def stop_after(_state, _sec):
            tick_count["n"] += 1
            if tick_count["n"] >= 1:
                raise KeyboardInterrupt
            return False

        # Prime state with a pending backoff count (but below the threshold
        # that would set backoff_skip_until).
        captured = {"state": None}
        real_init = run_clock.RuntimeState.__init__

        def init_with_pending_failures(self, theme_arg, persisted=None):
            real_init(self, theme_arg, persisted=persisted)
            self.consecutive_render_failures = 2
            # Force the bucket-changed branch by pre-seeding a different last_bucket.
            self.last_bucket = "h99_exact"
            # And prime last_quote_id so the dedup branch fires when peek returns the same.
            # Shape matches peek_quote_id's (source_id, line_number, display_quote, matched_text).
            self.last_quote_id = ("src-1", 1, "q", "mt")
            # last_effective_theme non-None so theme_changed evaluates False when the
            # effective theme matches.
            self.last_effective_theme = "default"
            captured["state"] = self

        with patch("sys.argv", argv), \
             patch("run_clock.render_now") as render_mock, \
             patch("run_clock.RuntimeState.__init__", init_with_pending_failures), \
             patch("run_clock.current_time_str", return_value="12:00"), \
             patch("run_clock.current_bucket", return_value="h12_exact"), \
             patch("run_clock.peek_quote_id", return_value=("src-1", 1, "q", "mt")), \
             patch("run_clock._loop_sleep", side_effect=stop_after):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()
        # Dedup branch fired (render_now not called), and the counter was reset.
        assert not render_mock.called
        assert captured["state"].consecutive_render_failures == 0
        assert captured["state"].backoff_skip_until == 0.0


class TestQuietImageTimeoutTelemetry:
    """_display_quiet_image must emit telemetry on display timeout,
    matching the contract the render/display paths follow.
    """

    def test_quiet_image_display_timeout_writes_telemetry(self, tmp_path, capsys):
        import runtime_quiet
        src = tmp_path / "goodnight.png"
        src.write_bytes(b"\x89PNG")
        out = tmp_path / "current.png"
        telemetry_base = tmp_path / "telemetry.jsonl"

        def timeout_on_display(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=runtime_quiet.DISPLAY_TIMEOUT_SECONDS)

        with patch("subprocess.run", side_effect=timeout_on_display):
            # Does not raise — _display_quiet_image swallows timeouts.
            runtime_quiet._display_quiet_image(
                str(src), str(out), display_script="display_inky.py",
                reason="quiet hours", telemetry_path=str(telemetry_base),
            )
        assert "timed out" in capsys.readouterr().err
        daily = run_clock.daily_telemetry_path(telemetry_base)
        entries = [json.loads(line) for line in daily.read_text(encoding="utf-8").splitlines() if line.strip()]
        display_timeouts = [e for e in entries if e.get("mode") == "display_timeout"]
        assert len(display_timeouts) == 1
        assert display_timeouts[0].get("reason") == "quiet hours"


class TestPreflightPaths:
    """Issue #53: startup must abort loudly when configured paths don't exist,
    so a typoed --display-script / --quiet-image in the systemd unit fails
    fast in the journal instead of silently on first use."""

    def _args(self, **kw):
        """Build a Namespace with only the preflight-relevant fields."""
        defaults = dict(
            render_script="render_quote.py",
            display_script=None,
            quiet_image=None,
            startup_image=None,
            skip_preflight=False,
        )
        defaults.update(kw)
        return argparse.Namespace(**defaults)

    def test_missing_display_script_surfaces(self, tmp_path):
        errors = run_clock._preflight_paths(
            self._args(display_script="/does/not/exist/display.py"),
        )
        assert any("display-script" in e for e in errors)

    def test_existing_display_script_passes(self, tmp_path):
        real = tmp_path / "display.py"
        real.write_text("")
        errors = run_clock._preflight_paths(self._args(display_script=str(real)))
        assert errors == []

    def test_missing_render_script_fatal(self):
        # render_script is REQUIRED; the default resolves against BASE_DIR.
        errors = run_clock._preflight_paths(
            self._args(render_script="no_such_render_script.py"),
        )
        assert any("render-script" in e for e in errors)

    def test_repo_default_render_script_exists(self):
        """The default render_quote.py in the repo resolves against BASE_DIR."""
        errors = run_clock._preflight_paths(self._args(render_script="render_quote.py"))
        assert errors == []

    def test_skip_preflight_flag_bypasses(self, capsys):
        """With --skip-preflight, _run_preflight must be a no-op even when
        paths are bogus (escape hatch for unusual setups)."""
        args = self._args(display_script="/bogus", skip_preflight=True)
        # Must not raise.
        run_clock._run_preflight(args)

    def test_run_preflight_raises_on_error(self):
        args = self._args(display_script="/does/not/exist/display.py")
        with pytest.raises(SystemExit) as excinfo:
            run_clock._run_preflight(args)
        assert excinfo.value.code == 1

    def test_unset_optional_paths_are_fine(self):
        """Leaving --display-script / --quiet-image / --startup-image empty is
        not a preflight failure — those fields are off by default."""
        args = self._args(
            display_script=None,
            quiet_image="",
            startup_image=None,
        )
        assert run_clock._preflight_paths(args) == []


class TestOnceSignalHandlers:
    """Issue #53: ``--once`` must install signal handlers so a mid-render
    SIGTERM unwinds cleanly instead of truncating the PNG mid-write."""

    def test_once_installs_signal_handlers(self, tmp_path):
        """Patch _install_signal_handlers and verify --once calls it."""
        argv = [
            "run_clock.py", "--once",
            "--output", str(tmp_path / "out.png"),
            "--history-path", "", "--telemetry-path", "",
            "--state-path", "",
            "--skip-preflight",
        ]
        installed = []

        def record(state):
            installed.append(state)

        with patch("sys.argv", argv), \
             patch("run_clock._install_signal_handlers", side_effect=record), \
             patch("run_clock.render_now"), \
             patch("run_clock.peek_quote_id", return_value=None):
            rc = run_clock.main()
        assert rc == 0
        assert len(installed) == 1
        assert isinstance(installed[0], run_clock.RuntimeState)

    def test_once_returns_143_when_signal_received(self, tmp_path):
        """If a signal arrives during the --once render (sets stop_requested),
        return 143 (SIGTERM's canonical exit code) so cron / systemd one-shots
        can distinguish 'rendered cleanly' from 'rendered under duress'.
        """
        argv = [
            "run_clock.py", "--once",
            "--output", str(tmp_path / "out.png"),
            "--history-path", "", "--telemetry-path", "",
            "--state-path", "",
            "--skip-preflight",
        ]

        def install_and_fire(state):
            # Simulate a signal arriving by setting stop_requested before render_now returns.
            state.stop_requested.set()

        with patch("sys.argv", argv), \
             patch("run_clock._install_signal_handlers", side_effect=install_and_fire), \
             patch("run_clock.render_now"), \
             patch("run_clock.peek_quote_id", return_value=None):
            rc = run_clock.main()
        assert rc == 143


class TestStateRoundtripPersistsRenderIdentity:
    """Issue #53: a mid-bucket restart must not redraw the same frame.

    Verifies the end-to-end flow: (1) the loop persists the render-identity
    triple after a render, (2) a subsequent load-rehydrate of a fresh
    RuntimeState sees the same ``(last_bucket, last_quote_id)``, and (3) the
    main-loop dedup check short-circuits so render_now is not called.
    """

    def test_commit_then_load_restores_last_quote_id(self, tmp_path):
        state_path = tmp_path / "state.json"
        s = run_clock.RuntimeState("default")
        s.commit_render_result("h3_half_past", "default", ("src-123", 99, "q", "mt"))
        # Persist like the main loop would after a successful render.
        run_clock.save_runtime_state(str(state_path), s.snapshot_for_persistence())
        # Simulate a restart: load + seed a fresh RuntimeState.
        persisted = run_clock.load_runtime_state(str(state_path))
        restored = run_clock.RuntimeState("default", persisted=persisted)
        assert restored.last_bucket == "h3_half_past"
        assert restored.last_effective_theme == "default"
        assert restored.last_quote_id == ("src-123", 99, "q", "mt")

    def test_persist_after_render_writes_identity_fields(self, tmp_path):
        """_persist_state_after_render must write the identity triple to disk.

        Without this hook, the snapshot only hits the disk on shutdown — a
        ``kill -9`` mid-bucket would lose the last-render state and force a
        redraw on restart.
        """
        state_path = tmp_path / "state.json"
        args = argparse.Namespace(state_path=str(state_path))
        state = run_clock.RuntimeState("default")
        state.commit_render_result("h4_five_past", "dark", ("s", 1, "q", "mt"))
        run_clock._persist_state_after_render(args, state)
        loaded = run_clock.load_runtime_state(str(state_path))
        assert loaded["last_bucket"] == "h4_five_past"
        assert loaded["last_effective_theme"] == "dark"
        assert loaded["last_quote_id"] == ["s", 1, "q", "mt"]

    def test_persist_after_render_is_noop_without_state_path(self, tmp_path):
        args = argparse.Namespace(state_path="")
        state = run_clock.RuntimeState("default")
        # Must not raise.
        run_clock._persist_state_after_render(args, state)
        assert list(tmp_path.iterdir()) == []

    def test_persist_swallows_disk_errors(self, tmp_path, monkeypatch, capsys):
        """A disk error during post-render persist must NOT bubble into the
        render path — that would incorrectly trigger outer-loop backoff.
        """
        args = argparse.Namespace(state_path=str(tmp_path / "state.json"))
        state = run_clock.RuntimeState("default")
        monkeypatch.setattr(
            run_clock, "save_runtime_state",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        # Must not raise.
        run_clock._persist_state_after_render(args, state)
        assert "persist after render failed" in capsys.readouterr().err


class TestTransientRenderDoesNotUpdateIdentity:
    """Issue #53 review follow-up: the source-card overlay (``mode="card"``)
    is a transient render that the 5s restore timer replaces. If its
    ``(bucket, quote_id, theme)`` landed in the persisted identity triple,
    a process death inside the 5s window would leave the card pinned on the
    panel forever — the next-boot dedup check would see the current tick's
    bucket match ``last_bucket`` and skip the redraw.
    """

    def _args(self, tmp_path):
        return argparse.Namespace(
            render_script="render_quote.py",
            output=str(tmp_path / "current.png"),
            width=800,
            height=480,
            display_script=None,
            mode="debug",
            theme="default",
            history_path="",
            history_days=7,
            telemetry_path="",
            state_path=str(tmp_path / "state.json"),
        )

    def test_card_mode_does_not_commit_render_identity(self, tmp_path):
        """After a ``mode="card"`` render, ``state.last_bucket`` /
        ``last_quote_id`` / ``last_effective_theme`` must remain whatever
        they were before the card (i.e. the underlying frame's identity)."""
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        # Seed pre-card identity (the frame the restore timer will rebuild).
        state.commit_render_result("h3_half_past", "default", ("src", 10, "q", "mt"))
        with patch("run_clock.render_now"):
            state.render_lock.acquire()
            try:
                run_clock._render_unlocked(
                    args, state, time_str="14:30", history_path=None,
                    mode="card", quote_id=("card-src", 99, "card-q", "card-mt"),
                )
            finally:
                state.render_lock.release()
        # Identity triple still reflects the PRE-card frame, not the card.
        assert state.last_bucket == "h3_half_past"
        assert state.last_quote_id == ("src", 10, "q", "mt")
        assert state.last_effective_theme == "default"

    def test_card_mode_does_not_persist_state(self, tmp_path):
        """The post-render persist hook must also be skipped in card mode, or
        an SSD flush + power cut in the 5s window would leave the card's
        identity on disk (with the underlying frame still on the panel)."""
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        persisted_payloads = []
        with patch("run_clock.render_now"), \
             patch("run_clock.save_runtime_state",
                   side_effect=lambda path, payload: persisted_payloads.append(payload)):
            state.render_lock.acquire()
            try:
                run_clock._render_unlocked(
                    args, state, time_str="14:30", history_path=None,
                    mode="card", quote_id=("card-src", 99, "card-q", "card-mt"),
                )
            finally:
                state.render_lock.release()
        assert persisted_payloads == [], "card mode must not persist state"

    def test_card_mode_still_resets_backoff(self, tmp_path):
        """A successful card render is still a positive 'render path is healthy'
        signal — the outer-loop failure counter must drop to zero so a prior
        streak of transient failures doesn't trigger a skip window after we've
        just demonstrably talked to the panel."""
        import time as _time
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        # Prime with a pending backoff; a transient render must clear it.
        state.consecutive_render_failures = 2
        state.backoff_skip_until = _time.monotonic() + 30
        with patch("run_clock.render_now"):
            state.render_lock.acquire()
            try:
                run_clock._render_unlocked(
                    args, state, time_str="14:30", history_path=None,
                    mode="card", quote_id=("card-src", 99, "card-q", "card-mt"),
                )
            finally:
                state.render_lock.release()
        assert state.consecutive_render_failures == 0
        assert state.backoff_skip_until == 0.0

    def test_normal_mode_still_commits_and_persists(self, tmp_path):
        """Baseline: a normal ``mode="debug"`` render (the default) still
        updates identity AND persists."""
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        persisted_payloads = []
        with patch("run_clock.render_now"), \
             patch("run_clock.save_runtime_state",
                   side_effect=lambda path, payload: persisted_payloads.append(payload)):
            state.render_lock.acquire()
            try:
                run_clock._render_unlocked(
                    args, state, time_str="14:30", history_path=None,
                    quote_id=("src", 42, "q", "mt"),
                )
            finally:
                state.render_lock.release()
        # Identity triple reflects the new render.
        assert state.last_quote_id == ("src", 42, "q", "mt")
        # And state was persisted exactly once.
        assert len(persisted_payloads) == 1
        assert persisted_payloads[0]["last_quote_id"] == ["src", 42, "q", "mt"]


class TestPidfileIntegration:
    """Issue #53: a second run_clock must detect the held pidfile and exit 1."""

    def test_main_exits_one_when_pidfile_held(self, tmp_path, capsys):
        import pidfile
        pid_path = tmp_path / "run_clock.pid"
        held = pidfile.acquire_pidfile(str(pid_path))
        try:
            argv = [
                "run_clock.py",
                "--output", str(tmp_path / "out.png"),
                "--buttons-off",
                "--history-path", "", "--telemetry-path", "",
                "--state-path", "",
                "--quiet-off", "--interval-seconds", "1",
                "--pidfile", str(pid_path),
                "--skip-preflight",
            ]
            with patch("sys.argv", argv):
                rc = run_clock.main()
            assert rc == 1
            assert "already locked" in capsys.readouterr().err
        finally:
            held.release()

    def test_main_releases_pidfile_on_shutdown(self, tmp_path):
        """After main() exits cleanly, the pidfile must be released so a
        replacement instance can start without operator intervention.
        ``--once`` is single-shot and skips the pidfile, so we use the loop
        path with a KeyboardInterrupt-on-first-sleep to drive one iteration.
        """
        pid_path = tmp_path / "run_clock.pid"
        argv_loop = [
            "run_clock.py",
            "--output", str(tmp_path / "out.png"),
            "--buttons-off",
            "--history-path", "", "--telemetry-path", "",
            "--state-path", "",
            "--quiet-off", "--interval-seconds", "1",
            "--pidfile", str(pid_path),
            "--skip-preflight",
        ]
        with patch("sys.argv", argv_loop), \
             patch("run_clock._loop_sleep", side_effect=KeyboardInterrupt), \
             patch("run_clock.render_now"), \
             patch("run_clock.peek_quote_id", return_value=None), \
             patch("run_clock.current_bucket", return_value="h12_exact"), \
             patch("run_clock.current_time_str", return_value="12:00"):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()
        # Pidfile should be gone.
        assert not pid_path.exists()
