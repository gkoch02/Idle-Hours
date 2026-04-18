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
        with patch("sys.argv", argv), \
             patch("run_clock.render_now", side_effect=fake_render), \
             patch("run_clock.current_bucket", side_effect=buckets), \
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
