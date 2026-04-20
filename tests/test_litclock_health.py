"""Tests for the litclock_health telemetry summariser."""
from __future__ import annotations

import datetime as dt
import json
from unittest.mock import patch

import litclock_health


def _ledger(tmp_path, lines: list[dict]):
    path = tmp_path / "telemetry.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for entry in lines:
            handle.write(json.dumps(entry) + "\n")
    return path


def _ts(minutes_ago: int) -> str:
    moment = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)
    return moment.isoformat(timespec="seconds")


class TestPercentile:
    def test_empty_returns_none(self):
        assert litclock_health._percentile([], 50) is None

    def test_single_value(self):
        assert litclock_health._percentile([42], 50) == 42

    def test_p50_of_three(self):
        assert litclock_health._percentile([10, 20, 30], 50) == 20

    def test_p95_clamps_to_max_index(self):
        # With 11 values 0..100, p95 lands between values[9]=90 and values[10]=100.
        values = list(range(0, 110, 10))
        assert litclock_health._percentile(values, 95) == 95


class TestLoadEntries:
    def test_missing_path_returns_empty(self, tmp_path):
        assert litclock_health.load_entries(tmp_path / "missing.jsonl", dt.datetime.now(dt.timezone.utc)) == []

    def test_skips_malformed_lines(self, tmp_path):
        path = tmp_path / "log.jsonl"
        path.write_text(
            "not-json\n"
            f'{{"ts": "{_ts(5)}", "render_ms": 100}}\n'
            '{"ts": "garbage"}\n'
            f'{{"ts": "{_ts(10)}", "render_ms": 50}}\n',
            encoding="utf-8",
        )
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
        assert len(litclock_health.load_entries(path, since)) == 2

    def test_filters_by_timestamp(self, tmp_path):
        path = _ledger(tmp_path, [
            {"ts": _ts(120), "render_ms": 100},   # 2h ago, before window
            {"ts": _ts(30), "render_ms": 200},    # within window
        ])
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
        rows = litclock_health.load_entries(path, since)
        assert len(rows) == 1
        assert rows[0]["render_ms"] == 200


class TestSummarise:
    def test_counts_renders_and_errors(self):
        entries = [
            {"render_ms": 100, "display_ms": 50},
            {"render_ms": 200, "display_ms": 100},
            {"error": "boom"},
        ]
        summary = litclock_health.summarise(entries)
        assert summary["render_count"] == 2
        assert summary["error_count"] == 1
        assert summary["last_error"] == "boom"

    def test_latencies_computed(self):
        entries = [{"render_ms": v, "display_ms": v // 2} for v in (10, 20, 30, 40, 50)]
        summary = litclock_health.summarise(entries)
        assert summary["render_p50_ms"] == 30
        assert summary["render_p95_ms"] is not None
        assert summary["display_p50_ms"] == 15

    def test_empty_returns_none_latencies(self):
        summary = litclock_health.summarise([])
        assert summary["render_count"] == 0
        assert summary["render_p50_ms"] is None


class TestMain:
    def test_missing_log_exits_nonzero(self, tmp_path, capsys):
        argv = ["litclock_health.py", "--telemetry-path", str(tmp_path / "missing.jsonl")]
        with patch("sys.argv", argv):
            rc = litclock_health.main()
        assert rc == 1
        assert "No telemetry log" in capsys.readouterr().err

    def test_summary_printed(self, tmp_path, capsys):
        path = _ledger(tmp_path, [
            {"ts": _ts(5), "render_ms": 100, "display_ms": 50, "bucket": "h2_exact"},
            {"ts": _ts(10), "render_ms": 150, "display_ms": 70, "bucket": "h2_five_past"},
            {"ts": _ts(15), "error": "RuntimeError(...)", "bucket": "h2_ten_past"},
        ])
        argv = ["litclock_health.py", "--telemetry-path", str(path), "--hours", "1"]
        with patch("sys.argv", argv):
            rc = litclock_health.main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "2 renders" in out
        assert "1 errors" in out
        assert "render latency" in out
        assert "last error" in out
