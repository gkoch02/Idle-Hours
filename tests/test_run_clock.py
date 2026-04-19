"""Tests for run_clock.py"""
from __future__ import annotations

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
        with patch("sys.argv", argv), \
             patch("run_clock.render_now", side_effect=fake_render), \
             patch("run_clock.current_bucket", side_effect=buckets), \
             patch("run_clock.peek_quote_id", side_effect=lambda _ts: next(peek_ids)), \
             patch("time.sleep", side_effect=stop_after_ticks):
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
        with patch("sys.argv", argv), \
             patch("run_clock.render_now", side_effect=fake_render), \
             patch("run_clock.current_bucket", side_effect=buckets), \
             patch("run_clock.peek_quote_id", side_effect=lambda _ts: next(peek_iter)), \
             patch("time.sleep", side_effect=stop_after_ticks):
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
             patch("time.sleep", side_effect=stop_after):
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
             patch("run_clock.peek_quote_id", side_effect=lambda _: next(peek_seq)), \
             patch("time.sleep", side_effect=stop_after):
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
             patch("run_clock.peek_quote_id", side_effect=lambda _: next(peek_seq)), \
             patch("time.sleep", side_effect=stop_after):
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
             patch("time.sleep", side_effect=stop_after):
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()

        mock_render.assert_not_called()
        assert len(display_calls) == 1
        assert display_calls[0][0] == str(src)
