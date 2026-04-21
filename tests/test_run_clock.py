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
        with patch("subprocess.check_call") as mock_call, \
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
        with patch("subprocess.check_call") as mock_call, \
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
        with patch("subprocess.check_call") as mock_call, \
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
        with patch("subprocess.check_call", side_effect=lambda cmd: calls.append(cmd)), \
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
        with patch("subprocess.check_call") as mock_call, \
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
        assert "pick_quote failed" in capsys.readouterr().err


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
             patch("subprocess.check_call") as mock_call, \
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
        with patch("subprocess.check_call") as mock_call:
            run_clock._display_quiet_image(str(src), str(out), display_script="display_inky.py")
        assert mock_call.called
        cmd = mock_call.call_args[0][0]
        assert "display_inky.py" in " ".join(str(a) for a in cmd)
        assert str(out) in cmd

    def test_no_display_script_no_subprocess(self, tmp_path):
        src = tmp_path / "quiet.png"
        src.write_bytes(b"\x89PNG")
        out = tmp_path / "current.png"
        with patch("subprocess.check_call") as mock_call:
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

    def test_runtime_state_seeds_from_persisted(self):
        s = run_clock.RuntimeState("auto", persisted={"manual_theme": "dark", "manual_quiet": True})
        assert s.manual_theme == "dark"
        assert s.manual_quiet is True

    def test_runtime_state_ignores_invalid_persisted_theme(self):
        s = run_clock.RuntimeState("auto", persisted={"manual_theme": "neon", "manual_quiet": False})
        assert s.manual_theme is None

    def test_snapshot_for_persistence_round_trips(self):
        s = run_clock.RuntimeState("auto", persisted={"manual_theme": "dark", "manual_quiet": True})
        assert s.snapshot_for_persistence() == {"manual_theme": "dark", "manual_quiet": True}

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
        with patch("run_clock.dt") as mock_dt:
            mock_dt.date.today.return_value = day1
            mock_dt.datetime = dt.datetime
            mock_dt.timezone = dt.timezone
            run_clock.append_telemetry(str(base), {"bucket": "day1"})
        with patch("run_clock.dt") as mock_dt:
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
        with patch("subprocess.check_call"), \
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
        with patch("subprocess.check_call"), \
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
        with patch("subprocess.check_call", side_effect=lambda cmd: calls.append(cmd)), \
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
        with patch("run_clock._display_quiet_image") as mock_display:
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
        with patch("run_clock.subprocess.check_call") as mock_check, \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            _short, hold = run_clock._build_button_handlers(args, state)
            hold["D"]()
        assert mock_check.called
        cmd = mock_check.call_args[0][0]
        assert cmd == ["sudo", "-n", "shutdown", "-h", "now"]

    def test_empty_shutdown_command_skips_invocation(self, tmp_path, capsys):
        args = self._args(tmp_path, shutdown_command="")
        state = run_clock.RuntimeState("default")
        with patch("run_clock.subprocess.check_call") as mock_check, \
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
             patch("run_clock.subprocess.check_call"), \
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
             patch("run_clock.subprocess.check_call"), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            _short, hold = run_clock._build_button_handlers(args, state)
            hold["D"]()
        assert mock_display.called

    def test_shutdown_command_failure_is_logged_not_raised(self, tmp_path, capsys):
        args = self._args(tmp_path)
        state = run_clock.RuntimeState("default")
        with patch("run_clock.subprocess.check_call", side_effect=RuntimeError("nope")), \
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
             patch("run_clock.subprocess.check_call"), \
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
             patch("run_clock.subprocess.check_call"), \
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
