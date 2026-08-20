"""Tests for the idle_hours_health telemetry summariser."""
from __future__ import annotations

import datetime as dt
import json
from unittest.mock import patch

from idle_hours import idle_hours_health


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
        assert idle_hours_health._percentile([], 50) is None

    def test_single_value(self):
        assert idle_hours_health._percentile([42], 50) == 42

    def test_p50_of_three(self):
        assert idle_hours_health._percentile([10, 20, 30], 50) == 20

    def test_p95_clamps_to_max_index(self):
        # With 11 values 0..100, p95 lands between values[9]=90 and values[10]=100.
        values = list(range(0, 110, 10))
        assert idle_hours_health._percentile(values, 95) == 95


class TestLoadEntries:
    def test_missing_path_returns_empty(self, tmp_path):
        # The base path and its parent both exist (tmp_path itself), but no telemetry files.
        assert idle_hours_health.load_entries(tmp_path / "missing.jsonl", dt.datetime.now(dt.timezone.utc)) == []

    def test_missing_parent_returns_empty(self, tmp_path):
        # Parent dir itself is absent → should quietly return [] without blowing up on glob.
        assert idle_hours_health.load_entries(tmp_path / "nope" / "telemetry.jsonl", dt.datetime.now(dt.timezone.utc)) == []

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
        assert len(idle_hours_health.load_entries(path, since)) == 2

    def test_filters_by_timestamp(self, tmp_path):
        path = _ledger(tmp_path, [
            {"ts": _ts(120), "render_ms": 100},   # 2h ago, before window
            {"ts": _ts(30), "render_ms": 200},    # within window
        ])
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
        rows = idle_hours_health.load_entries(path, since)
        assert len(rows) == 1
        assert rows[0]["render_ms"] == 200


class TestSummarise:
    def test_counts_renders_and_errors(self):
        entries = [
            {"render_ms": 100, "display_ms": 50},
            {"render_ms": 200, "display_ms": 100},
            {"error": "boom"},
        ]
        summary = idle_hours_health.summarise(entries)
        assert summary["render_count"] == 2
        assert summary["error_count"] == 1
        assert summary["last_error"] == "boom"

    def test_latencies_computed(self):
        entries = [{"render_ms": v, "display_ms": v // 2} for v in (10, 20, 30, 40, 50)]
        summary = idle_hours_health.summarise(entries)
        assert summary["render_p50_ms"] == 30
        assert summary["render_p95_ms"] is not None
        assert summary["display_p50_ms"] == 15

    def test_empty_returns_none_latencies(self):
        summary = idle_hours_health.summarise([])
        assert summary["render_count"] == 0
        assert summary["render_p50_ms"] is None

    def test_bool_render_ms_not_counted_as_render(self):
        # bool is an int subclass; a corrupt {"render_ms": true} entry must not
        # be counted as a render-with-latency-1, which would skew both the count
        # and the percentiles.
        entries = [
            {"render_ms": 100, "display_ms": 50},
            {"render_ms": True},   # corrupt — must be ignored
            {"display_ms": False},  # corrupt — must be ignored
        ]
        summary = idle_hours_health.summarise(entries)
        assert summary["render_count"] == 1
        assert summary["render_p50_ms"] == 100


class TestMain:
    def test_missing_log_exits_nonzero(self, tmp_path, capsys):
        argv = ["idle_hours_health.py", "--telemetry-path", str(tmp_path / "missing.jsonl")]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
        assert rc == 1
        assert "No telemetry log" in capsys.readouterr().err

    def test_summary_printed(self, tmp_path, capsys):
        path = _ledger(tmp_path, [
            {"ts": _ts(5), "render_ms": 100, "display_ms": 50, "bucket": "h2_exact"},
            {"ts": _ts(10), "render_ms": 150, "display_ms": 70, "bucket": "h2_five_past"},
            {"ts": _ts(15), "error": "RuntimeError(...)", "bucket": "h2_ten_past"},
        ])
        argv = ["idle_hours_health.py", "--telemetry-path", str(path), "--hours", "1"]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
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
        argv = ["idle_hours_health.py", "--telemetry-path", str(path), "--hours", "1", "--json"]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
        assert rc == 0
        out = capsys.readouterr().out.strip()
        parsed = json.loads(out)
        assert parsed["render_count"] == 1
        assert parsed["error_count"] == 0
        assert parsed["hours"] == 1

    def test_json_flag_on_missing_log_still_emits_json(self, tmp_path, capsys):
        argv = [
            "idle_hours_health.py", "--telemetry-path", str(tmp_path / "missing.jsonl"),
            "--json",
        ]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
        assert rc == 1
        out = capsys.readouterr().out.strip()
        parsed = json.loads(out)
        assert "error" in parsed


class TestRotatedTelemetry:
    """Verify that idle_hours_health reads across date-rotated telemetry files
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
        rows = idle_hours_health.load_entries(base, since)
        render_ms_values = sorted(r["render_ms"] for r in rows)
        assert render_ms_values == [100, 200]

    def test_legacy_unsuffixed_file_still_read(self, tmp_path):
        """Telemetry written by pre-rotation builds lives at the base path; include it."""
        base = tmp_path / "telemetry.jsonl"
        with base.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": _ts(5), "render_ms": 77}) + "\n")
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
        rows = idle_hours_health.load_entries(base, since)
        assert [r["render_ms"] for r in rows] == [77]

    def test_main_reports_no_log_when_no_files_at_all(self, tmp_path, capsys):
        """If neither the base nor any rotated sibling exists, main() returns 1."""
        argv = ["idle_hours_health.py", "--telemetry-path", str(tmp_path / "telemetry.jsonl")]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
        assert rc == 1

    def test_main_succeeds_when_only_rotated_file_exists(self, tmp_path, capsys):
        """Rotation means the base path may be absent even on a healthy appliance."""
        today = dt.datetime.now(dt.timezone.utc)
        self._write_daily(tmp_path, today.strftime("%Y%m%d"), [
            {"ts": today.isoformat(), "render_ms": 100, "bucket": "h2_exact"},
        ])
        argv = [
            "idle_hours_health.py", "--telemetry-path", str(tmp_path / "telemetry.jsonl"),
            "--hours", "1",
        ]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
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
        rows = idle_hours_health.load_entries(base, since)
        assert rows == []
        # Confirmed at the file-listing level too.
        assert backup not in idle_hours_health.find_telemetry_files(base)

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
        rows = idle_hours_health.load_entries(base, since)
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
        rows = idle_hours_health.load_entries(base, since)
        assert [r["render_ms"] for r in rows] == [42]


class TestEvaluateHealth:
    def test_healthy_returns_zero(self):
        summary = {"render_count": 10, "error_count": 0}
        assert idle_hours_health.evaluate_health(summary, fail_if_no_renders=False) == 0

    def test_errors_but_some_renders_still_healthy(self):
        summary = {"render_count": 10, "error_count": 2}
        assert idle_hours_health.evaluate_health(summary, fail_if_no_renders=False) == 0

    def test_errors_and_zero_renders_is_unhealthy(self):
        summary = {"render_count": 0, "error_count": 3}
        assert idle_hours_health.evaluate_health(summary, fail_if_no_renders=False) == 2

    def test_fail_if_no_renders_triggers_exit_two(self):
        summary = {"render_count": 0, "error_count": 0}
        assert idle_hours_health.evaluate_health(summary, fail_if_no_renders=True) == 2
        assert idle_hours_health.evaluate_health(summary, fail_if_no_renders=False) == 0


class TestMainExitCodes:
    def test_errors_with_no_renders_exits_two(self, tmp_path):
        path = _ledger(tmp_path, [
            {"ts": _ts(5), "error": "boom", "bucket": "h2_exact"},
        ])
        argv = ["idle_hours_health.py", "--telemetry-path", str(path), "--hours", "1"]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
        assert rc == 2

    def test_fail_if_no_renders_with_empty_window(self, tmp_path):
        # An entry outside the --hours window leaves the window empty but the file exists.
        path = _ledger(tmp_path, [
            {"ts": _ts(24 * 60), "render_ms": 100, "bucket": "h2_exact"},
        ])
        argv = [
            "idle_hours_health.py", "--telemetry-path", str(path),
            "--hours", "1", "--fail-if-no-renders",
        ]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
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
        entries = idle_hours_health.load_entries(path, dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1))
        summary = idle_hours_health.summarise(entries)
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
        entries = idle_hours_health.load_entries(path, dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1))
        summary = idle_hours_health.summarise(entries)
        assert summary["last_heartbeat_ts"] == new_ts


class TestFormatSummary:
    """Direct unit tests for format_summary() — the human-readable output path."""

    def _base_summary(self, **overrides):
        """Minimal summary dict that format_summary won't crash on."""
        base = {
            "render_count": 0,
            "error_count": 0,
            "heartbeat_count": 0,
            "last_heartbeat_ts": None,
            "render_p50_ms": None,
            "render_p95_ms": None,
            "display_p50_ms": None,
            "display_p95_ms": None,
            "action_count": 0,
            "actions_by_type": {},
            "last_action_ts": None,
            "press_dropped_count": 0,
            "web_auth_fail_count": 0,
            "web_error_count": 0,
            "quiet_enter_count": 0,
            "quiet_exit_count": 0,
            "last_error": None,
            "stale_heartbeat": False,
        }
        base.update(overrides)
        return base

    def test_basic_counts_in_output(self):
        out = idle_hours_health.format_summary(self._base_summary(render_count=5, error_count=2), hours=24)
        assert "5 renders" in out
        assert "2 errors" in out
        assert "24h" in out

    def test_latency_shown_when_renders_exist(self):
        out = idle_hours_health.format_summary(
            self._base_summary(render_count=2, render_p50_ms=120, render_p95_ms=300,
                               display_p50_ms=14000, display_p95_ms=17000),
            hours=1,
        )
        assert "120ms" in out
        assert "14000ms" in out

    def test_latency_hidden_when_no_renders(self):
        out = idle_hours_health.format_summary(self._base_summary(), hours=1)
        assert "latency" not in out

    def test_last_error_shown_when_present(self):
        out = idle_hours_health.format_summary(self._base_summary(last_error="boom"), hours=1)
        assert "last error" in out
        assert "boom" in out

    def test_stale_heartbeat_warning_shown(self):
        out = idle_hours_health.format_summary(self._base_summary(stale_heartbeat=True), hours=1)
        assert "stale" in out.lower() or "wedged" in out.lower()

    def test_actions_breakdown_shown_when_nonzero(self):
        out = idle_hours_health.format_summary(
            self._base_summary(
                action_count=3,
                actions_by_type={"skip": 2, "theme": 1},
                last_action_ts=_ts(5),
            ),
            hours=1,
        )
        assert "3 actions" in out
        assert "skip 2" in out
        assert "theme 1" in out

    def test_press_dropped_shown_when_nonzero(self):
        out = idle_hours_health.format_summary(self._base_summary(press_dropped_count=4), hours=1)
        assert "4 presses dropped" in out

    def test_web_auth_fail_shown_when_nonzero(self):
        out = idle_hours_health.format_summary(self._base_summary(web_auth_fail_count=2), hours=1)
        assert "2 web auth failures" in out

    def test_web_error_shown_when_nonzero(self):
        out = idle_hours_health.format_summary(self._base_summary(web_error_count=1), hours=1)
        assert "1 web POST errors" in out

    def test_quiet_hours_shown_when_nonzero(self):
        out = idle_hours_health.format_summary(
            self._base_summary(quiet_enter_count=2, quiet_exit_count=1), hours=1,
        )
        assert "quiet hours" in out
        assert "2 enters" in out
        assert "1 exits" in out

    def test_heartbeat_line_shown_when_present(self):
        ts = _ts(1)
        out = idle_hours_health.format_summary(
            self._base_summary(heartbeat_count=10, last_heartbeat_ts=ts), hours=1,
        )
        assert "10 heartbeats" in out


class TestHeartbeatStaleness:
    def test_fresh_heartbeat_is_not_stale(self):
        summary = {"last_heartbeat_ts": _ts(2)}
        assert idle_hours_health.is_heartbeat_stale(summary, max_age_minutes=5) is False

    def test_old_heartbeat_is_stale(self):
        summary = {"last_heartbeat_ts": _ts(10)}
        assert idle_hours_health.is_heartbeat_stale(summary, max_age_minutes=5) is True

    def test_missing_heartbeat_is_stale(self):
        """An appliance running on pre-heartbeat code, OR wedged before the
        first emit, has no last_heartbeat_ts. Either interpretation should
        trip the staleness flag."""
        assert idle_hours_health.is_heartbeat_stale({"last_heartbeat_ts": None}, max_age_minutes=5) is True
        assert idle_hours_health.is_heartbeat_stale({}, max_age_minutes=5) is True

    def test_malformed_timestamp_is_treated_as_stale(self):
        """A corrupted last_heartbeat_ts that can't be parsed must return stale=True
        rather than crashing — the ValueError branch at idle_hours_health.py:312-313."""
        assert idle_hours_health.is_heartbeat_stale(
            {"last_heartbeat_ts": "not-a-date"}, max_age_minutes=5,
        ) is True
        assert idle_hours_health.is_heartbeat_stale(
            {"last_heartbeat_ts": "2026-99-99T00:00:00"}, max_age_minutes=5,
        ) is True

    def test_cli_exits_2_when_heartbeat_stale(self, tmp_path, capsys):
        # Window has a render so --fail-if-no-renders wouldn't fire; only the
        # heartbeat-age flag should cause a non-zero exit.
        path = _ledger(tmp_path, [
            {"ts": _ts(1), "render_ms": 100, "bucket": "h2_exact"},
            {"ts": _ts(20), "type": "heartbeat"},
        ])
        argv = [
            "idle_hours_health.py",
            "--telemetry-path", str(path),
            "--hours", "1",
            "--max-heartbeat-age-minutes", "5",
            "--json",
        ]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
        assert rc == 2
        out = json.loads(capsys.readouterr().out.strip())
        assert out.get("stale_heartbeat") is True

    def test_cli_exits_0_when_heartbeat_fresh(self, tmp_path):
        path = _ledger(tmp_path, [
            {"ts": _ts(1), "render_ms": 100, "bucket": "h2_exact"},
            {"ts": _ts(1), "type": "heartbeat"},
        ])
        argv = [
            "idle_hours_health.py",
            "--telemetry-path", str(path),
            "--hours", "1",
            "--max-heartbeat-age-minutes", "5",
        ]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
        assert rc == 0


class TestBackoffNotCountedAsRender:
    """Regression for the P1 surfaced in code review:

    ``run_clock._record_render_failure`` writes ``mode="backoff"`` telemetry
    entries that have neither an ``error`` field nor a ``type="heartbeat"``
    marker. Defining renders as "non-heartbeat without error" miscounted
    them as successful renders, which could make ``evaluate_health`` return
    healthy (exit 0) for an appliance that was in a backoff loop with zero
    actual renders.
    """

    def test_backoff_entry_is_not_a_render(self, tmp_path):
        path = _ledger(tmp_path, [
            {"ts": _ts(5), "mode": "backoff", "failures": 3, "skip_seconds": 8, "bucket": "h2_exact"},
        ])
        entries = idle_hours_health.load_entries(path, dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1))
        summary = idle_hours_health.summarise(entries)
        assert summary["render_count"] == 0
        assert summary["error_count"] == 0

    def test_error_plus_backoff_without_render_is_unhealthy(self, tmp_path):
        """The motivating pathological case from review: one render exception
        and one backoff record would previously yield render_count=1,
        error_count=1, exit 0 — looking healthy despite zero real renders."""
        path = _ledger(tmp_path, [
            {"ts": _ts(5), "error": "boom", "bucket": "h2_exact", "mode": "debug"},
            {"ts": _ts(5), "mode": "backoff", "failures": 3, "skip_seconds": 8, "bucket": "h2_exact"},
        ])
        argv = ["idle_hours_health.py", "--telemetry-path", str(path), "--hours", "1"]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
        assert rc == 2

    def test_timeout_entries_counted_as_errors_not_renders(self, tmp_path):
        """render_timeout / display_timeout / shutdown_timeout entries
        all carry an ``error`` field but no ``render_ms`` — they must be
        errors, not renders."""
        path = _ledger(tmp_path, [
            {"ts": _ts(5), "error": "TimeoutExpired", "mode": "render_timeout", "timeout_seconds": 45},
            {"ts": _ts(5), "error": "TimeoutExpired", "mode": "display_timeout", "timeout_seconds": 60},
        ])
        entries = idle_hours_health.load_entries(path, dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1))
        summary = idle_hours_health.summarise(entries)
        assert summary["render_count"] == 0
        assert summary["error_count"] == 2


class TestActionSummarisation:
    """Phase 4 observability — operator actions, press-drops, web auth
    failures, and quiet-window transitions surface as counters in the
    summary. See github.com/gkoch02/idle-hours issue #55.
    """

    def test_actions_broken_down_by_type(self):
        entries = [
            {"ts": _ts(5), "mode": "action", "action": "skip", "label": "button A", "ok": True},
            {"ts": _ts(4), "mode": "action", "action": "skip", "label": "web", "ok": True},
            {"ts": _ts(3), "mode": "action", "action": "theme", "label": "button B", "ok": True},
            {"ts": _ts(2), "mode": "action", "action": "theme", "label": "web", "ok": False, "error": "X"},
        ]
        summary = idle_hours_health.summarise(entries)
        assert summary["action_count"] == 4
        assert summary["actions_by_type"] == {"skip": 2, "theme": 2}
        # last action is the most recent one in the list order
        assert summary["last_action_ts"] == entries[-1]["ts"]

    def test_action_errors_do_not_inflate_error_count(self):
        """A failed skip action has ``ok=False, error=...`` but the render
        pipeline itself is unaffected — it belongs in action_count, not
        error_count, so a spurious web call doesn't light up health
        monitoring."""
        entries = [
            {"ts": _ts(5), "mode": "action", "action": "skip", "ok": False, "error": "boom"},
            {"ts": _ts(4), "render_ms": 100},
        ]
        summary = idle_hours_health.summarise(entries)
        assert summary["render_count"] == 1
        assert summary["error_count"] == 0
        assert summary["action_count"] == 1

    def test_press_dropped_counted(self):
        entries = [
            {"ts": _ts(5), "mode": "press_dropped", "label": "button A", "action": "skip", "reason": "render_in_flight"},
            {"ts": _ts(4), "mode": "press_dropped", "label": "web", "action": "theme", "reason": "render_in_flight"},
        ]
        summary = idle_hours_health.summarise(entries)
        assert summary["press_dropped_count"] == 2

    def test_web_auth_fail_counted(self):
        entries = [
            {"ts": _ts(5), "mode": "web_auth_fail", "remote": "10.0.0.2", "path": "/api/action/theme"},
        ]
        summary = idle_hours_health.summarise(entries)
        assert summary["web_auth_fail_count"] == 1
        # web_auth_fail has no error field, so it shouldn't influence error_count either way.
        assert summary["error_count"] == 0

    def test_web_error_counted_not_as_generic_error(self):
        """``web_error`` entries carry an ``error`` field but represent HTTP
        4xx/5xx responses, not render-pipeline failures. They get their own
        counter, not the generic error_count."""
        entries = [
            {"ts": _ts(5), "mode": "web_error", "status": 400, "path": "/api/overrides", "error": "invalid bucket"},
            {"ts": _ts(4), "mode": "web_error", "status": 500, "path": "/api/action/theme", "error": "RuntimeError()"},
        ]
        summary = idle_hours_health.summarise(entries)
        assert summary["web_error_count"] == 2
        assert summary["error_count"] == 0

    def test_quiet_enter_and_exit_counted(self):
        entries = [
            {"ts": _ts(30), "mode": "quiet_enter", "manual": False},
            {"ts": _ts(20), "mode": "quiet_exit"},
            {"ts": _ts(10), "mode": "quiet_enter", "manual": True},
        ]
        summary = idle_hours_health.summarise(entries)
        assert summary["quiet_enter_count"] == 2
        assert summary["quiet_exit_count"] == 1

    def test_summary_fields_all_present_on_empty(self):
        """Zero entries still produce every counter so downstream consumers
        don't need ``summary.get(..., 0)`` guards."""
        summary = idle_hours_health.summarise([])
        for key in (
            "action_count", "press_dropped_count", "web_auth_fail_count",
            "web_error_count", "quiet_enter_count", "quiet_exit_count",
        ):
            assert summary[key] == 0, key
        assert summary["actions_by_type"] == {}
        assert summary["last_action_ts"] is None


class TestActionsOnlyView:
    def test_actions_only_text_output(self, tmp_path, capsys):
        path = _ledger(tmp_path, [
            {"ts": _ts(5), "mode": "action", "action": "skip", "label": "button A", "ok": True},
            {"ts": _ts(4), "mode": "action", "action": "theme", "label": "web", "ok": True},
            {"ts": _ts(3), "mode": "press_dropped", "label": "button A", "action": "skip", "reason": "render_in_flight"},
            {"ts": _ts(2), "mode": "web_auth_fail", "remote": "1.2.3.4", "path": "/api/action/theme"},
            {"ts": _ts(1), "mode": "quiet_enter", "manual": False},
        ])
        argv = [
            "idle_hours_health.py",
            "--telemetry-path", str(path),
            "--hours", "1",
            "--actions-only",
        ]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "operator activity" in out
        assert "actions: 2" in out
        assert "skip 1" in out
        assert "theme 1" in out
        assert "presses dropped: 1" in out
        assert "web auth failures: 1" in out
        assert "1 enters" in out

    def test_actions_only_stable_shape_on_empty_window(self, tmp_path, capsys):
        """Every counter prints even when zero so grep-based cron workflows
        don't silently break when the window is quiet."""
        path = _ledger(tmp_path, [
            {"ts": _ts(5), "render_ms": 100},  # no action traffic, but a render exists so we don't exit 1
        ])
        argv = [
            "idle_hours_health.py",
            "--telemetry-path", str(path),
            "--hours", "1",
            "--actions-only",
        ]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "actions: 0" in out
        assert "presses dropped: 0" in out
        assert "web auth failures: 0" in out
        assert "last action: never" in out

    def test_actions_only_stable_shape_on_empty_ledger(self, tmp_path, capsys):
        """Output is non-empty even when the telemetry file has no entries."""
        path = _ledger(tmp_path, [])
        argv = [
            "idle_hours_health.py",
            "--telemetry-path", str(path),
            "--hours", "1",
            "--actions-only",
        ]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
        assert rc in (0, 1)
        out = capsys.readouterr().out
        assert out.strip() != ""

    def test_actions_only_ignored_by_json_flag(self, tmp_path, capsys):
        """--json keeps its machine-readable shape regardless of --actions-only."""
        path = _ledger(tmp_path, [
            {"ts": _ts(5), "mode": "action", "action": "skip", "label": "web", "ok": True},
            {"ts": _ts(4), "mode": "press_dropped", "label": "web", "action": "skip", "reason": "render_in_flight"},
        ])
        argv = [
            "idle_hours_health.py",
            "--telemetry-path", str(path),
            "--hours", "1",
            "--actions-only", "--json",
        ]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
        assert rc == 0
        data = json.loads(capsys.readouterr().out.strip())
        assert data["action_count"] == 1
        assert data["press_dropped_count"] == 1
        assert data["actions_by_type"] == {"skip": 1}


class TestConfigFileTelemetryPath:
    """#195: the documented appliance preset relocates telemetry under
    /var/lib/idle-hours, but the health CLI defaulted to ~/.idle-hours — so
    the exact command the README and CLAUDE.md document exited 1 'No
    telemetry log' on the shipped deployment."""

    def _config(self, tmp_path, telemetry_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            f'telemetry_path = "{telemetry_path}"\n'
            'mode = "production"\n'
            'quiet_start = "22:00"\n',
            encoding="utf-8",
        )
        return cfg

    def test_config_supplies_telemetry_path(self, tmp_path, capsys):
        path = _ledger(tmp_path, [{"ts": _ts(5), "render_ms": 100, "display_ms": 50}])
        cfg = self._config(tmp_path, path)
        argv = ["idle_hours_health.py", "--config", str(cfg), "--hours", "1"]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
        assert rc == 0
        assert "1 renders" in capsys.readouterr().out

    def test_explicit_flag_beats_config(self, tmp_path, capsys):
        real = _ledger(tmp_path, [{"ts": _ts(5), "render_ms": 100, "display_ms": 50}])
        cfg = self._config(tmp_path, tmp_path / "decoy.jsonl")
        argv = [
            "idle_hours_health.py", "--config", str(cfg),
            "--telemetry-path", str(real), "--hours", "1",
        ]
        with patch("sys.argv", argv):
            rc = idle_hours_health.main()
        assert rc == 0
        assert "1 renders" in capsys.readouterr().out

    def test_config_without_telemetry_key_keeps_default(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text('mode = "production"\n', encoding="utf-8")
        argv = ["idle_hours_health.py", "--config", str(cfg)]
        with patch("sys.argv", argv):
            args = idle_hours_health.parse_args()
        assert args.telemetry_path == idle_hours_health.DEFAULT_TELEMETRY_PATH

    def test_missing_config_file_exits_config_error(self, tmp_path):
        """Same hard-fail run_clock gives a typoed --config path."""
        from idle_hours import runtime_config
        argv = ["idle_hours_health.py", "--config", str(tmp_path / "nope.toml")]
        with patch("sys.argv", argv):
            try:
                idle_hours_health.parse_args()
            except SystemExit as exc:
                assert exc.code == runtime_config.EXIT_CONFIG_ERROR
            else:  # pragma: no cover
                raise AssertionError("expected SystemExit")


class TestLastRenderAge:
    """#196: 'when did the panel last render' is the most operator-relevant
    timestamp and the summary didn't carry it. A loop wedged in dedup-skip or
    render backoff keeps heartbeating, so the heartbeat gate reads healthy
    while the panel goes stale."""

    def test_summarise_reports_last_render_ts(self):
        entries = [
            {"ts": _ts(30), "render_ms": 100},
            {"ts": _ts(10), "render_ms": 120},
            {"ts": _ts(2), "type": "heartbeat"},
        ]
        summary = idle_hours_health.summarise(entries)
        assert summary["last_render_ts"] == entries[1]["ts"]

    def test_last_render_ts_none_when_no_renders(self):
        summary = idle_hours_health.summarise([{"ts": _ts(2), "type": "heartbeat"}])
        assert summary["last_render_ts"] is None

    def test_backoff_entry_is_not_a_render(self):
        """Guards the same misclassification render_count already avoids."""
        summary = idle_hours_health.summarise(
            [{"ts": _ts(3), "mode": "backoff", "failures": 3, "skip_seconds": 8}]
        )
        assert summary["last_render_ts"] is None

    def test_human_summary_shows_last_render(self, tmp_path, capsys):
        path = _ledger(tmp_path, [{"ts": _ts(5), "render_ms": 100, "display_ms": 50}])
        argv = ["idle_hours_health.py", "--telemetry-path", str(path), "--hours", "1"]
        with patch("sys.argv", argv):
            idle_hours_health.main()
        assert "last render:" in capsys.readouterr().out

    def test_json_carries_last_render_ts(self, tmp_path, capsys):
        path = _ledger(tmp_path, [{"ts": _ts(5), "render_ms": 100, "display_ms": 50}])
        argv = ["idle_hours_health.py", "--telemetry-path", str(path), "--hours", "1", "--json"]
        with patch("sys.argv", argv):
            idle_hours_health.main()
        assert json.loads(capsys.readouterr().out)["last_render_ts"] is not None

    def test_is_render_stale_missing_counts_as_stale(self):
        assert idle_hours_health.is_render_stale({}, 30) is True
        assert idle_hours_health.is_render_stale({"last_render_ts": "not-a-date"}, 30) is True

    def test_is_render_stale_respects_cap(self):
        assert idle_hours_health.is_render_stale({"last_render_ts": _ts(5)}, 30) is False
        assert idle_hours_health.is_render_stale({"last_render_ts": _ts(60)}, 30) is True

    def test_naive_timestamp_treated_as_utc(self):
        naive = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).replace(
            tzinfo=None
        ).isoformat(timespec="seconds")
        assert idle_hours_health.is_render_stale({"last_render_ts": naive}, 30) is False

    def test_gate_exits_two_when_render_stale(self, tmp_path):
        """Heartbeating but not rendering: the condition heartbeat age misses."""
        path = _ledger(tmp_path, [
            {"ts": _ts(200), "render_ms": 100, "display_ms": 50},
            {"ts": _ts(1), "type": "heartbeat"},
        ])
        argv = [
            "idle_hours_health.py", "--telemetry-path", str(path), "--hours", "24",
            "--max-render-age-minutes", "30", "--max-heartbeat-age-minutes", "10",
        ]
        with patch("sys.argv", argv):
            assert idle_hours_health.main() == 2

    def test_gate_exits_zero_when_render_fresh(self, tmp_path):
        path = _ledger(tmp_path, [
            {"ts": _ts(5), "render_ms": 100, "display_ms": 50},
            {"ts": _ts(1), "type": "heartbeat"},
        ])
        argv = [
            "idle_hours_health.py", "--telemetry-path", str(path), "--hours", "24",
            "--max-render-age-minutes", "30",
        ]
        with patch("sys.argv", argv):
            assert idle_hours_health.main() == 0

    def test_gate_disabled_by_default(self, tmp_path):
        path = _ledger(tmp_path, [
            {"ts": _ts(600), "render_ms": 100, "display_ms": 50},
            {"ts": _ts(1), "type": "heartbeat"},
        ])
        argv = ["idle_hours_health.py", "--telemetry-path", str(path), "--hours", "24"]
        with patch("sys.argv", argv):
            assert idle_hours_health.main() == 0

    def test_stale_render_warning_in_human_output(self, tmp_path, capsys):
        path = _ledger(tmp_path, [
            {"ts": _ts(200), "render_ms": 100, "display_ms": 50},
            {"ts": _ts(1), "type": "heartbeat"},
        ])
        argv = [
            "idle_hours_health.py", "--telemetry-path", str(path), "--hours", "24",
            "--max-render-age-minutes", "30",
        ]
        with patch("sys.argv", argv):
            idle_hours_health.main()
        assert "last render is stale" in capsys.readouterr().out
