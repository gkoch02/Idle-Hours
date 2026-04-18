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
