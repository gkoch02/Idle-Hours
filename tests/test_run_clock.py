"""Tests for run_clock.py"""
from __future__ import annotations

from unittest.mock import patch

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

    def test_just_after(self):
        assert self._bucket_for("03:01") == "h3_just_after"
        assert self._bucket_for("03:05") == "h3_just_after"

    def test_early_past(self):
        assert self._bucket_for("03:06") == "h3_early_past"
        assert self._bucket_for("03:14") == "h3_early_past"

    def test_quarter_pastish(self):
        assert self._bucket_for("03:15") == "h3_quarter_pastish"
        assert self._bucket_for("03:19") == "h3_quarter_pastish"

    def test_half_pastish(self):
        assert self._bucket_for("03:20") == "h3_half_pastish"
        assert self._bucket_for("03:34") == "h3_half_pastish"

    def test_late_past(self):
        assert self._bucket_for("03:35") == "h3_late_past"
        assert self._bucket_for("03:39") == "h3_late_past"

    def test_quarter_toish(self):
        assert self._bucket_for("03:40") == "h3_quarter_toish"
        assert self._bucket_for("03:49") == "h3_quarter_toish"

    def test_just_before(self):
        assert self._bucket_for("03:50") == "h3_just_before"
        assert self._bucket_for("03:59") == "h3_just_before"

    def test_hour12_maps_correctly(self):
        assert self._bucket_for("12:30") == "h12_half_pastish"

    def test_hour_wraps_at_24(self):
        # 23:00 → hour24=23 → hour12=23%12=11
        assert self._bucket_for("23:00") == "h11_exact"

    def test_midnight_hour12(self):
        # 00:30 → hour24=0 → hour12=0%12=0 → corrected to 12
        assert self._bucket_for("00:30") == "h12_half_pastish"


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
