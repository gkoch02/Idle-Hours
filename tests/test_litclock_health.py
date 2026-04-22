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
        # The base path and its parent both exist (tmp_path itself), but no telemetry files.
        assert litclock_health.load_entries(tmp_path / "missing.jsonl", dt.datetime.now(dt.timezone.utc)) == []

    def test_missing_parent_returns_empty(self, tmp_path):
        # Parent dir itself is absent → should quietly return [] without blowing up on glob.
        assert litclock_health.load_entries(tmp_path / "nope" / "telemetry.jsonl", dt.datetime.now(dt.timezone.utc)) == []

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


class TestJsonOutput:
    def test_json_flag_emits_valid_json(self, tmp_path, capsys):
        path = _ledger(tmp_path, [
            {"ts": _ts(5), "render_ms": 100, "display_ms": 50, "bucket": "h2_exact"},
        ])
        argv = ["litclock_health.py", "--telemetry-path", str(path), "--hours", "1", "--json"]
        with patch("sys.argv", argv):
            rc = litclock_health.main()
        assert rc == 0
        out = capsys.readouterr().out.strip()
        parsed = json.loads(out)
        assert parsed["render_count"] == 1
        assert parsed["error_count"] == 0
        assert parsed["hours"] == 1

    def test_json_flag_on_missing_log_still_emits_json(self, tmp_path, capsys):
        argv = [
            "litclock_health.py", "--telemetry-path", str(tmp_path / "missing.jsonl"),
            "--json",
        ]
        with patch("sys.argv", argv):
            rc = litclock_health.main()
        assert rc == 1
        out = capsys.readouterr().out.strip()
        parsed = json.loads(out)
        assert "error" in parsed


class TestRotatedTelemetry:
    """Verify that litclock_health reads across date-rotated telemetry files
    written by run_clock.append_telemetry, and falls back to the legacy
    unsuffixed file when older installations wrote directly to it.
    """

    def _write_daily(self, parent, date_str, entries):
        path = parent / f"telemetry-{date_str}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry) + "\n")
        return path

    def test_reads_across_rotated_files(self, tmp_path):
        base = tmp_path / "telemetry.jsonl"
        today = dt.datetime.now(dt.timezone.utc)
        yesterday = today - dt.timedelta(days=1)
        self._write_daily(tmp_path, yesterday.strftime("%Y%m%d"), [
            {"ts": (today - dt.timedelta(hours=20)).isoformat(), "render_ms": 100},
        ])
        self._write_daily(tmp_path, today.strftime("%Y%m%d"), [
            {"ts": today.isoformat(), "render_ms": 200},
        ])
        since = today - dt.timedelta(hours=48)
        rows = litclock_health.load_entries(base, since)
        render_ms_values = sorted(r["render_ms"] for r in rows)
        assert render_ms_values == [100, 200]

    def test_legacy_unsuffixed_file_still_read(self, tmp_path):
        """Telemetry written by pre-rotation builds lives at the base path; include it."""
        base = tmp_path / "telemetry.jsonl"
        with base.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": _ts(5), "render_ms": 77}) + "\n")
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
        rows = litclock_health.load_entries(base, since)
        assert [r["render_ms"] for r in rows] == [77]

    def test_main_reports_no_log_when_no_files_at_all(self, tmp_path, capsys):
        """If neither the base nor any rotated sibling exists, main() returns 1."""
        argv = ["litclock_health.py", "--telemetry-path", str(tmp_path / "telemetry.jsonl")]
        with patch("sys.argv", argv):
            rc = litclock_health.main()
        assert rc == 1

    def test_main_succeeds_when_only_rotated_file_exists(self, tmp_path, capsys):
        """Rotation means the base path may be absent even on a healthy appliance."""
        today = dt.datetime.now(dt.timezone.utc)
        self._write_daily(tmp_path, today.strftime("%Y%m%d"), [
            {"ts": today.isoformat(), "render_ms": 100, "bucket": "h2_exact"},
        ])
        argv = [
            "litclock_health.py", "--telemetry-path", str(tmp_path / "telemetry.jsonl"),
            "--hours", "1",
        ]
        with patch("sys.argv", argv):
            rc = litclock_health.main()
        assert rc == 0
        assert "1 renders" in capsys.readouterr().out

    def test_non_date_siblings_are_ignored(self, tmp_path):
        """A non-rotated sibling like telemetry-backup.jsonl must not be
        read forever just because it matches the glob — otherwise any stray
        file in the telemetry dir becomes unbounded read overhead.
        """
        base = tmp_path / "telemetry.jsonl"
        backup = tmp_path / "telemetry-backup.jsonl"
        with backup.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": _ts(5), "render_ms": 9999}) + "\n")
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
        rows = litclock_health.load_entries(base, since)
        assert rows == []
        # Confirmed at the file-listing level too.
        assert backup not in litclock_health.find_telemetry_files(base)

    def test_prunes_old_dated_files_by_filename(self, tmp_path):
        """Files dated well before the window are not opened — we prune by filename."""
        base = tmp_path / "telemetry.jsonl"
        today = dt.datetime.now(dt.timezone.utc)
        old_date = (today - dt.timedelta(days=30)).strftime("%Y%m%d")
        # Deliberately put a line that WOULD match the timestamp filter inside an old file —
        # if the pruner opens the file it would be counted. (The timestamp is forged but the
        # filename is old, so pruning relies on the filename.)
        self._write_daily(tmp_path, old_date, [
            {"ts": today.isoformat(), "render_ms": 999},
        ])
        since = today - dt.timedelta(hours=1)
        rows = litclock_health.load_entries(base, since)
        assert rows == []

    def test_prune_includes_prior_day_to_tolerate_local_utc_skew(self, tmp_path):
        """Filenames use local date; `since` is UTC. A west-of-UTC appliance
        near UTC midnight can have today's active file dated "yesterday-UTC"
        — pruning must keep a day of slack so the currently-active file is
        still read. Without slack, `--hours 1` on a host in UTC-7 at 20:30
        local (UTC=next day 03:30) produces a false "0 renders".
        """
        base = tmp_path / "telemetry.jsonl"
        now_utc = dt.datetime.now(dt.timezone.utc)
        # Simulate the west-of-UTC boundary: the active file is dated one day
        # before the UTC date embedded in `since`, but its entries' timestamps
        # fall inside the requested window.
        prior_day = (now_utc - dt.timedelta(days=1)).strftime("%Y%m%d")
        self._write_daily(tmp_path, prior_day, [
            {"ts": (now_utc - dt.timedelta(minutes=5)).isoformat(), "render_ms": 42},
        ])
        since = now_utc - dt.timedelta(hours=1)
        rows = litclock_health.load_entries(base, since)
        assert [r["render_ms"] for r in rows] == [42]


class TestEvaluateHealth:
    def test_healthy_returns_zero(self):
        summary = {"render_count": 10, "error_count": 0}
        assert litclock_health.evaluate_health(summary, fail_if_no_renders=False) == 0

    def test_errors_but_some_renders_still_healthy(self):
        summary = {"render_count": 10, "error_count": 2}
        assert litclock_health.evaluate_health(summary, fail_if_no_renders=False) == 0

    def test_errors_and_zero_renders_is_unhealthy(self):
        summary = {"render_count": 0, "error_count": 3}
        assert litclock_health.evaluate_health(summary, fail_if_no_renders=False) == 2

    def test_fail_if_no_renders_triggers_exit_two(self):
        summary = {"render_count": 0, "error_count": 0}
        assert litclock_health.evaluate_health(summary, fail_if_no_renders=True) == 2
        assert litclock_health.evaluate_health(summary, fail_if_no_renders=False) == 0


class TestMainExitCodes:
    def test_errors_with_no_renders_exits_two(self, tmp_path):
        path = _ledger(tmp_path, [
            {"ts": _ts(5), "error": "boom", "bucket": "h2_exact"},
        ])
        argv = ["litclock_health.py", "--telemetry-path", str(path), "--hours", "1"]
        with patch("sys.argv", argv):
            rc = litclock_health.main()
        assert rc == 2

    def test_fail_if_no_renders_with_empty_window(self, tmp_path):
        # An entry outside the --hours window leaves the window empty but the file exists.
        path = _ledger(tmp_path, [
            {"ts": _ts(24 * 60), "render_ms": 100, "bucket": "h2_exact"},
        ])
        argv = [
            "litclock_health.py", "--telemetry-path", str(path),
            "--hours", "1", "--fail-if-no-renders",
        ]
        with patch("sys.argv", argv):
            rc = litclock_health.main()
        assert rc == 2


class TestHeartbeatSummarisation:
    """Heartbeat entries are counted separately so a silent-but-alive
    appliance is not mistaken for one that has zero renders AND zero errors
    (which should read as 'no data' rather than 'broken')."""

    def test_heartbeat_does_not_inflate_render_or_error_counts(self, tmp_path):
        path = _ledger(tmp_path, [
            {"ts": _ts(5), "type": "heartbeat"},
            {"ts": _ts(5), "type": "heartbeat"},
            {"ts": _ts(5), "render_ms": 100, "bucket": "h2_exact"},
            {"ts": _ts(5), "error": "boom", "bucket": "h2_exact"},
        ])
        entries = litclock_health.load_entries(path, dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1))
        summary = litclock_health.summarise(entries)
        assert summary["heartbeat_count"] == 2
        assert summary["render_count"] == 1
        assert summary["error_count"] == 1

    def test_last_heartbeat_ts_is_most_recent(self, tmp_path):
        old_ts = _ts(30)
        new_ts = _ts(1)
        path = _ledger(tmp_path, [
            {"ts": old_ts, "type": "heartbeat"},
            {"ts": new_ts, "type": "heartbeat"},
        ])
        entries = litclock_health.load_entries(path, dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1))
        summary = litclock_health.summarise(entries)
        assert summary["last_heartbeat_ts"] == new_ts


class TestHeartbeatStaleness:
    def test_fresh_heartbeat_is_not_stale(self):
        summary = {"last_heartbeat_ts": _ts(2)}
        assert litclock_health.is_heartbeat_stale(summary, max_age_minutes=5) is False

    def test_old_heartbeat_is_stale(self):
        summary = {"last_heartbeat_ts": _ts(10)}
        assert litclock_health.is_heartbeat_stale(summary, max_age_minutes=5) is True

    def test_missing_heartbeat_is_stale(self):
        """An appliance running on pre-heartbeat code, OR wedged before the
        first emit, has no last_heartbeat_ts. Either interpretation should
        trip the staleness flag."""
        assert litclock_health.is_heartbeat_stale({"last_heartbeat_ts": None}, max_age_minutes=5) is True
        assert litclock_health.is_heartbeat_stale({}, max_age_minutes=5) is True

    def test_cli_exits_2_when_heartbeat_stale(self, tmp_path, capsys):
        # Window has a render so --fail-if-no-renders wouldn't fire; only the
        # heartbeat-age flag should cause a non-zero exit.
        path = _ledger(tmp_path, [
            {"ts": _ts(1), "render_ms": 100, "bucket": "h2_exact"},
            {"ts": _ts(20), "type": "heartbeat"},
        ])
        argv = [
            "litclock_health.py",
            "--telemetry-path", str(path),
            "--hours", "1",
            "--max-heartbeat-age-minutes", "5",
            "--json",
        ]
        with patch("sys.argv", argv):
            rc = litclock_health.main()
        assert rc == 2
        out = json.loads(capsys.readouterr().out.strip())
        assert out.get("stale_heartbeat") is True

    def test_cli_exits_0_when_heartbeat_fresh(self, tmp_path):
        path = _ledger(tmp_path, [
            {"ts": _ts(1), "render_ms": 100, "bucket": "h2_exact"},
            {"ts": _ts(1), "type": "heartbeat"},
        ])
        argv = [
            "litclock_health.py",
            "--telemetry-path", str(path),
            "--hours", "1",
            "--max-heartbeat-age-minutes", "5",
        ]
        with patch("sys.argv", argv):
            rc = litclock_health.main()
        assert rc == 0
