"""Tests for sd_notify.py — the stdlib ``sd_notify`` client."""
from __future__ import annotations

import os
import socket
import threading
from unittest.mock import patch

import pytest

import sd_notify


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Every test starts with a clean ``NOTIFY_SOCKET`` + no warning latch.

    Autouse so a test forgetting to set / unset the env var can't poison a
    sibling that asserts on the off-socket branch. We reset the one-shot
    warning latch too, so each test independently exercises it.
    """
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    sd_notify.reset_warning_state_for_tests()


class TestNotifyOffSocket:
    """Dev-host behaviour: no env var, notify returns False, no exception."""

    def test_notify_returns_false_when_env_missing(self):
        assert sd_notify.notify("READY=1") is False

    def test_notify_ready_no_op_off_socket(self):
        assert sd_notify.notify_ready() is False

    def test_notify_watchdog_no_op_off_socket(self):
        assert sd_notify.notify_watchdog() is False

    def test_empty_state_is_rejected(self, monkeypatch):
        """notify("") short-circuits so a misuse can't spam systemd with empty datagrams."""
        monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")
        assert sd_notify.notify("") is False


class TestNotifyFilesystemSocket:
    """With a real AF_UNIX path socket we should receive the exact payload."""

    def _receive_one(self, sock: socket.socket, received: list) -> None:
        data, _ = sock.recvfrom(4096)
        received.append(data)

    def test_ready_payload_delivered(self, monkeypatch, tmp_path):
        socket_path = tmp_path / "notify.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        server.bind(str(socket_path))
        try:
            server.settimeout(2.0)
            received: list = []
            thread = threading.Thread(target=self._receive_one, args=(server, received))
            thread.start()
            monkeypatch.setenv("NOTIFY_SOCKET", str(socket_path))
            assert sd_notify.notify_ready() is True
            thread.join(timeout=2.0)
            assert received == [b"READY=1"]
        finally:
            server.close()

    def test_watchdog_payload_delivered(self, monkeypatch, tmp_path):
        socket_path = tmp_path / "notify.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        server.bind(str(socket_path))
        try:
            server.settimeout(2.0)
            received: list = []
            thread = threading.Thread(target=self._receive_one, args=(server, received))
            thread.start()
            monkeypatch.setenv("NOTIFY_SOCKET", str(socket_path))
            assert sd_notify.notify_watchdog() is True
            thread.join(timeout=2.0)
            assert received == [b"WATCHDOG=1"]
        finally:
            server.close()


class TestNotifyAbstractSocket:
    """Linux abstract-namespace sockets — systemd uses ``@`` prefix in env."""

    def test_abstract_namespace_prefix_translated_to_nul(self, monkeypatch):
        if not hasattr(socket, "AF_UNIX"):
            pytest.skip("AF_UNIX not available")
        # Pick a unique abstract name so parallel test runs don't collide.
        abstract_name = f"idle-hours-test-{os.getpid()}"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            server.bind("\0" + abstract_name)
        except OSError:
            pytest.skip("Abstract-namespace AF_UNIX sockets not supported on this platform")
        try:
            server.settimeout(2.0)
            received: list = []

            def _recv():
                data, _ = server.recvfrom(4096)
                received.append(data)

            thread = threading.Thread(target=_recv)
            thread.start()
            monkeypatch.setenv("NOTIFY_SOCKET", "@" + abstract_name)
            assert sd_notify.notify("READY=1") is True
            thread.join(timeout=2.0)
            assert received == [b"READY=1"]
        finally:
            server.close()


class TestNotifyFailureSwallowing:
    """A dead/missing socket must never raise into the caller."""

    def test_missing_socket_file_swallowed(self, monkeypatch, tmp_path, capsys):
        # Pointed at a socket path that doesn't exist — sendto() raises
        # FileNotFoundError/ENOENT. sd_notify must swallow and return False.
        monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "nonexistent.sock"))
        assert sd_notify.notify_ready() is False
        captured = capsys.readouterr()
        assert "sd_notify" in captured.err  # one-shot warning emitted

    def test_second_failure_does_not_re_warn(self, monkeypatch, tmp_path, capsys):
        """The ``_warned_once`` latch suppresses repeated warnings during a run."""
        monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "nonexistent.sock"))
        sd_notify.notify_ready()
        capsys.readouterr()  # drain first warning
        sd_notify.notify_watchdog()
        captured = capsys.readouterr()
        assert "sd_notify" not in captured.err

    def test_reset_warning_state_for_tests_clears_latch(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "nonexistent.sock"))
        sd_notify.notify_ready()
        capsys.readouterr()
        sd_notify.reset_warning_state_for_tests()
        sd_notify.notify_ready()
        captured = capsys.readouterr()
        assert "sd_notify" in captured.err

    def test_os_error_during_send_returns_false(self, monkeypatch):
        """Even a valid env var path can raise on sendto; we must not propagate."""
        monkeypatch.setenv("NOTIFY_SOCKET", "/definitely/not/a/socket/path")
        with patch("socket.socket") as mock_socket:
            mock_sock = mock_socket.return_value.__enter__.return_value
            mock_sock.sendto.side_effect = OSError("ECONNREFUSED")
            assert sd_notify.notify_ready() is False


class TestMainLoopReadyNotification:
    """``run_clock.main`` must call ``sd_notify.notify_ready`` after buttons +
    web server + signal handlers are armed, so a systemd ``Type=notify`` unit
    only gets ``READY=1`` once the appliance is actually able to respond."""

    def test_notify_ready_called_before_first_tick(self, tmp_path):
        import run_clock
        argv = [
            "run_clock.py",
            "--output", str(tmp_path / "current.png"),
            "--state-path", "",
            "--telemetry-path", "",
            "--history-path", "",
            "--pidfile", "",
            "--buttons-off",
            "--interval-seconds", "0",
        ]

        # Fire KeyboardInterrupt on the first _loop_sleep so main() returns
        # after exactly one iteration (enough to confirm READY fired during
        # startup, which happens BEFORE the while-loop starts).
        sleep_called = {"n": 0}

        def stop_immediately(_state, _sec):
            sleep_called["n"] += 1
            raise KeyboardInterrupt

        with patch("sys.argv", argv), \
             patch("run_clock.render_now"), \
             patch("run_clock.peek_quote_id", return_value=("src", 1, "q", "m")), \
             patch("run_clock.current_bucket", return_value="h3_exact"), \
             patch("run_clock.current_time_str", return_value="12:00"), \
             patch("run_clock._loop_sleep", side_effect=stop_immediately), \
             patch("sd_notify.notify_ready") as mock_ready:
            with pytest.raises(KeyboardInterrupt):
                run_clock.main()
        assert mock_ready.called, "main() must send READY=1 so Type=notify units come up"


class TestHeartbeatPingsWatchdog:
    """The run_clock heartbeat must pet the systemd watchdog.

    Phase 3's whole point: every heartbeat also sends WATCHDOG=1 so a wedged
    loop stops pinging and systemd restarts us within WatchdogSec.
    """

    def test_heartbeat_emits_watchdog(self, tmp_path):
        import run_clock
        state = run_clock.RuntimeState("default")
        telemetry_base = tmp_path / "telemetry.jsonl"
        with patch("sd_notify.notify_watchdog") as mock_watchdog:
            run_clock._maybe_emit_heartbeat(state, str(telemetry_base))
        assert mock_watchdog.called

    def test_throttled_heartbeat_does_not_emit_watchdog(self, tmp_path):
        """Throttle applies to BOTH the telemetry write AND the watchdog ping."""
        import run_clock
        state = run_clock.RuntimeState("default")
        telemetry_base = tmp_path / "telemetry.jsonl"
        with patch("sd_notify.notify_watchdog") as mock_watchdog:
            for _ in range(3):
                run_clock._maybe_emit_heartbeat(state, str(telemetry_base))
        assert mock_watchdog.call_count == 1

    def test_watchdog_fires_even_when_telemetry_disabled(self):
        """An operator who passed --telemetry-path="" still gets supervised."""
        import run_clock
        state = run_clock.RuntimeState("default")
        with patch("sd_notify.notify_watchdog") as mock_watchdog:
            run_clock._maybe_emit_heartbeat(state, None)
        assert mock_watchdog.called
