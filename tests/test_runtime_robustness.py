"""Regression tests for runtime robustness fixes (issues #279-#283)."""
from __future__ import annotations

import argparse
import datetime as dt
from unittest.mock import patch

from idle_hours import run_clock, runtime_config, runtime_telemetry, runtime_webhook


class TestMidnightResetPersistFailure:
    """#279 (1): a persist error at the midnight rollover must not escape."""

    def test_persist_error_is_logged_not_raised(self, tmp_path, capsys, monkeypatch):
        args = argparse.Namespace(state_path=str(tmp_path / "state.json"))
        state = run_clock.RuntimeState("auto", persisted={"manual_theme": "dark"})
        state.last_seen_date = dt.date.today() - dt.timedelta(days=1)

        def boom(_path, _payload):
            raise OSError("disk full")

        monkeypatch.setattr(run_clock, "save_runtime_state", boom)
        run_clock._maybe_reset_manual_theme_at_midnight(args, state)
        assert state.manual_theme is None
        assert state.last_seen_date == dt.date.today()
        assert "persist failed" in capsys.readouterr().err


class TestShutdownPersistFailure:
    """#279 (2): a persist error in the button-D hold handler must not skip the
    shutdown command, and a failed command still rolls back manual_quiet."""

    def _args(self, tmp_path):
        return argparse.Namespace(
            render_script="render_quote.py", output=str(tmp_path / "current.png"),
            width=800, height=480, display_script=None, mode="debug", theme="default",
            history_path="", history_days=7, telemetry_path="",
            state_path=str(tmp_path / "state.json"), quiet_image="",
            shutdown_command="sudo -n shutdown -h now",
        )

    def test_command_still_runs_when_persist_fails(self, tmp_path, capsys):
        state = run_clock.RuntimeState("default")
        with patch("idle_hours.run_clock.save_runtime_state", side_effect=OSError("ro fs")), \
             patch("idle_hours.run_clock.subprocess.run") as mock_run, \
             patch("idle_hours.run_clock.current_bucket", return_value="h10_exact"):
            _short, hold = run_clock._build_button_handlers(self._args(tmp_path), state)
            hold["D"]()
        assert mock_run.called
        assert state.manual_quiet is True
        assert "persist failed" in capsys.readouterr().err

    def test_failed_command_rolls_back_even_when_persist_fails(self, tmp_path):
        state = run_clock.RuntimeState("default")
        with patch("idle_hours.run_clock.save_runtime_state", side_effect=OSError("ro fs")), \
             patch("idle_hours.run_clock.subprocess.run", side_effect=OSError("no sudo")), \
             patch("idle_hours.run_clock.current_bucket", return_value="h10_exact"):
            _short, hold = run_clock._build_button_handlers(self._args(tmp_path), state)
            hold["D"]()
        assert state.manual_quiet is False


class TestLoopSleepPetsWatchdog:
    """#280: a long inter-tick sleep must keep pinging the systemd watchdog."""

    def test_long_sleep_is_sliced_and_pings(self, monkeypatch):
        state = run_clock.RuntimeState("default")
        waits: list[float] = []
        monkeypatch.setattr(state.stop_requested, "wait", lambda timeout: waits.append(timeout) or False)
        with patch("idle_hours.run_clock.sd_notify.notify_watchdog") as ping:
            stopped = run_clock._loop_sleep(state, 3 * run_clock.WATCHDOG_SLICE_SECONDS + 5)
        assert stopped is False
        assert all(w <= run_clock.WATCHDOG_SLICE_SECONDS for w in waits)
        assert sum(waits) == 3 * run_clock.WATCHDOG_SLICE_SECONDS + 5
        assert ping.call_count == len(waits) == 4

    def test_stop_returns_promptly(self, monkeypatch):
        state = run_clock.RuntimeState("default")
        calls = []

        def wait(timeout):
            calls.append(timeout)
            return len(calls) == 2

        monkeypatch.setattr(state.stop_requested, "wait", wait)
        with patch("idle_hours.run_clock.sd_notify.notify_watchdog"):
            assert run_clock._loop_sleep(state, 10_000) is True
        assert len(calls) == 2

    def test_real_event_interrupts(self):
        state = run_clock.RuntimeState("default")
        state.stop_requested.set()
        assert run_clock._loop_sleep(state, 10_000) is True

    def test_slice_fits_shipped_watchdog(self):
        # ops/idle-hours.service.example ships WatchdogSec=180s.
        assert run_clock.WATCHDOG_SLICE_SECONDS < 180


class TestWebhookPayloadCarriesTs:
    """#281: the webhook payload must carry the same ts as the file line."""

    def test_ts_stamped_once_for_file_and_webhook(self, tmp_path, monkeypatch):
        posted = []
        monkeypatch.setattr(runtime_webhook, "get_config", lambda: ("https://x.test/h", False))
        monkeypatch.setattr(runtime_webhook, "post_event", lambda url, entry, send_all=False: posted.append(entry))
        base = tmp_path / "telemetry.jsonl"
        entry = {"error": "boom", "mode": "debug"}
        runtime_telemetry.append_telemetry(str(base), entry)
        assert len(posted) == 1
        assert "ts" in posted[0]
        assert "ts" not in entry  # caller's dict is not mutated
        import json
        line = json.loads(runtime_telemetry.daily_telemetry_path(base).read_text().strip())
        assert line["ts"] == posted[0]["ts"]

    def test_webhook_gets_ts_even_without_telemetry_path(self, monkeypatch):
        posted = []
        monkeypatch.setattr(runtime_webhook, "get_config", lambda: ("https://x.test/h", False))
        monkeypatch.setattr(runtime_webhook, "post_event", lambda url, entry, send_all=False: posted.append(entry))
        runtime_telemetry.append_telemetry(None, {"error": "boom"})
        assert posted and "ts" in posted[0]


class TestOncePinsQuote:
    """#282: --once must forward the pin key like the main loop does."""

    def test_once_passes_pin_quote(self, tmp_path):
        argv = [
            "run_clock.py", "--once", "--output", str(tmp_path / "current.png"),
            "--history-path", "", "--telemetry-path", "", "--state-path", "",
            "--skip-preflight",
        ]
        qid = ("141", 482, "a quote", "half past two")
        with patch("sys.argv", argv), \
             patch("idle_hours.run_clock.render_now") as mock_render, \
             patch("idle_hours.run_clock.current_time_str", return_value="14:30"), \
             patch("idle_hours.run_clock.peek_quote_id", return_value=qid), \
             patch("idle_hours.run_clock.pick_quote_module.append_history"):
            assert run_clock.main() == 0
        assert mock_render.call_args.kwargs["pin_quote"] == ("141", 482, "half past two")


class TestPidfileOSError:
    """#283: a non-contention pidfile OSError exits 42, not 1."""

    def test_permission_error_returns_config_error(self, tmp_path, capsys):
        pid = str(tmp_path / "run_clock.pid")
        argv = [
            "run_clock.py", "--output", str(tmp_path / "current.png"),
            "--buttons-off", "--history-path", "", "--telemetry-path", "",
            "--state-path", "", "--quiet-off", "--skip-preflight", "--pidfile", pid,
        ]
        with patch("sys.argv", argv), \
             patch("idle_hours.run_clock.pidfile.acquire_pidfile", side_effect=PermissionError(13, "denied")), \
             patch("idle_hours.run_clock.render_now") as mock_render:
            rc = run_clock.main()
        assert rc == runtime_config.EXIT_CONFIG_ERROR
        assert not mock_render.called
        err = capsys.readouterr().err
        assert pid in err and "denied" in err

    def test_real_unopenable_pidfile_path(self, tmp_path):
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x")
        argv = [
            "run_clock.py", "--output", str(tmp_path / "current.png"),
            "--buttons-off", "--history-path", "", "--telemetry-path", "",
            "--state-path", "", "--quiet-off", "--skip-preflight",
            "--pidfile", str(blocker / "run_clock.pid"),
        ]
        with patch("sys.argv", argv), patch("idle_hours.run_clock.render_now"):
            assert run_clock.main() == runtime_config.EXIT_CONFIG_ERROR
