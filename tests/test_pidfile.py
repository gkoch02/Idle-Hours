"""Tests for pidfile.py — single-instance lock on ~/.litclock/run_clock.pid."""
from __future__ import annotations

import multiprocessing
import os

import pidfile


class TestAcquirePidfile:
    def test_disabled_when_path_empty(self):
        """Empty path disables the single-instance check entirely."""
        assert pidfile.acquire_pidfile("") is None
        assert pidfile.acquire_pidfile(None) is None

    def test_first_acquirer_writes_pid_and_returns_handle(self, tmp_path):
        path = tmp_path / "run_clock.pid"
        handle = pidfile.acquire_pidfile(str(path))
        try:
            assert handle is not None
            assert path.exists()
            assert path.read_text().strip() == str(os.getpid())
        finally:
            handle.release()

    def test_second_acquirer_raises_locked_error(self, tmp_path):
        """A second in-process acquire of the same pidfile must surface the lock error.

        We run the second acquire in a subprocess because ``fcntl.flock`` is
        per-file-description and a second ``open`` in the SAME process would
        not actually contend on Linux — realistic contention only happens
        between distinct processes.
        """
        path = tmp_path / "run_clock.pid"
        handle = pidfile.acquire_pidfile(str(path))
        try:
            parent_conn, child_conn = multiprocessing.Pipe()

            def try_acquire(conn, pidfile_str):
                try:
                    h = pidfile.acquire_pidfile(pidfile_str)
                    conn.send(("ok", h.path.read_text() if h else None))
                except pidfile.PidfileLockedError as exc:
                    conn.send(("locked", exc.existing_pid))
                except Exception as exc:
                    conn.send(("err", repr(exc)))
                finally:
                    conn.close()

            p = multiprocessing.Process(target=try_acquire, args=(child_conn, str(path)))
            p.start()
            p.join(timeout=5)
            status, detail = parent_conn.recv()
            assert status == "locked", f"expected locked, got ({status!r}, {detail!r})"
            assert detail == os.getpid()
        finally:
            handle.release()

    def test_stale_pidfile_with_dead_pid_is_reclaimed(self, tmp_path):
        """A pidfile containing a dead pid (SIGKILL / power-loss aftermath) must
        be reclaimed transparently — otherwise the appliance would refuse to
        start after an unclean shutdown until an operator manually cleaned up.
        """
        path = tmp_path / "run_clock.pid"
        # Seed a dead pid. 999999 is very unlikely to exist.
        path.write_text("999999\n")
        handle = pidfile.acquire_pidfile(str(path))
        try:
            assert handle is not None
            # Our pid is now in the file.
            assert path.read_text().strip() == str(os.getpid())
        finally:
            handle.release()

    def test_stale_pidfile_with_recycled_live_pid_is_reclaimed(self, tmp_path):
        """A SIGKILL / reboot can leave a pidfile whose stored pid has since
        been reassigned by the kernel to a totally unrelated live process.
        ``flock`` is the single source of truth: if we successfully took the
        exclusive lock, the bytes in the file are stale by definition. We
        must NOT second-guess flock by checking whether the stored pid is
        alive — that would wedge startup on every reboot that recycles the
        pid, which is common on Pi-class appliances where the init system
        starts processes in a near-deterministic order.
        """
        path = tmp_path / "run_clock.pid"
        # Seed the CURRENT process's pid (guaranteed live) — a worst-case
        # "recycled pid" scenario. A correct implementation still reclaims.
        path.write_text(f"{os.getpid()}\n")
        handle = pidfile.acquire_pidfile(str(path))
        try:
            assert handle is not None
            # Our pid still in the file (we wrote it); what matters is the
            # flock was successfully taken and no error was raised.
            assert path.read_text().strip() == str(os.getpid())
        finally:
            handle.release()

    def test_stale_pidfile_with_arbitrary_live_pid_is_reclaimed(self, tmp_path):
        """Same as above but with the parent process's pid — an arbitrary
        live pid that definitely isn't us — to guard against a naive
        'if existing != self and existing is alive, bail' check.
        """
        path = tmp_path / "run_clock.pid"
        # PPID is almost certainly alive and definitely not us.
        path.write_text(f"{os.getppid()}\n")
        handle = pidfile.acquire_pidfile(str(path))
        try:
            assert handle is not None
        finally:
            handle.release()

    def test_release_removes_pidfile(self, tmp_path):
        path = tmp_path / "run_clock.pid"
        handle = pidfile.acquire_pidfile(str(path))
        assert path.exists()
        handle.release()
        assert not path.exists()

    def test_release_is_idempotent(self, tmp_path):
        path = tmp_path / "run_clock.pid"
        handle = pidfile.acquire_pidfile(str(path))
        handle.release()
        # Second release is a no-op.
        handle.release()

    def test_creates_parent_directory(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "run_clock.pid"
        handle = pidfile.acquire_pidfile(str(path))
        try:
            assert path.exists()
        finally:
            handle.release()

class TestPidfileLockedError:
    def test_message_includes_pid(self, tmp_path):
        err = pidfile.PidfileLockedError(tmp_path / "run_clock.pid", 12345)
        assert "12345" in str(err)
        assert err.existing_pid == 12345

    def test_message_without_pid(self, tmp_path):
        err = pidfile.PidfileLockedError(tmp_path / "run_clock.pid", None)
        assert "locked" in str(err)


class TestRunClockMainRejectsSecondInstance:
    """Integration: ``run_clock.main`` must exit 1 when another instance holds the pidfile."""

    def test_second_main_exits_one_with_log(self, tmp_path, capsys):
        """Hold the pidfile, then invoke main() and verify it returns 1 quickly."""
        import run_clock
        pid_path = tmp_path / "run_clock.pid"
        state_path = tmp_path / "state.json"
        held = pidfile.acquire_pidfile(str(pid_path))
        try:
            argv = [
                "run_clock.py",
                "--output", str(tmp_path / "out.png"),
                "--buttons-off",
                "--history-path", "",
                "--telemetry-path", "",
                "--state-path", str(state_path),
                "--quiet-off",
                "--interval-seconds", "1",
                "--pidfile", str(pid_path),
                "--skip-preflight",
            ]
            from unittest.mock import patch
            with patch("sys.argv", argv):
                rc = run_clock.main()
            assert rc == 1
            err = capsys.readouterr().err
            assert "already locked" in err
        finally:
            held.release()
