"""Single-instance pidfile lock for the long-running clock loop.

A second ``run_clock.py`` starting while the first is still running would race
the first on every appliance file — ``state.json``, ``history.jsonl``, and the
date-rotated telemetry sibling. :mod:`atomic_io`'s tmp-rename pattern is
crash-safe but NOT concurrent-writer-safe: two processes interleaving
read-modify-write can each think they won and clobber the other. An advisory
``fcntl.flock`` on a pidfile is the standard Unix answer.

Semantics:

* ``acquire_pidfile(path)`` opens ``path`` (creating the parent dir as needed),
  takes a non-blocking exclusive ``flock``, writes the current pid, and returns
  a handle whose ``release()`` method unlocks + removes the file.
* If the lock is already held by a live process, raises
  :class:`PidfileLockedError` with the existing pid. The caller is expected to
  log loudly and exit 1.
* A **stale** pidfile (locked by nothing, or containing a dead pid) is
  reclaimed: the pid contents are rewritten and the lock is acquired. This
  handles the ``SIGKILL`` / power-loss cases where the OS released the
  ``flock`` but the pidfile bytes stayed on disk.
* Best-effort cleanup on ``release()``: a failure to unlink the file is logged
  but not raised, because by the time we're tearing down there is nothing the
  caller can usefully do with the error.

Platform note: ``fcntl.flock`` is a Unix-only API. On Windows this module
gracefully no-ops (``acquire_pidfile`` returns a handle whose ``release()`` is
idle) — the appliance only runs on Linux (Raspberry Pi), but the module stays
importable on a dev host so the test suite doesn't fork on OS.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]
    _HAS_FCNTL = False

from runtime_log import _log

DEFAULT_PIDFILE_PATH = "~/.litclock/run_clock.pid"


class PidfileLockedError(RuntimeError):
    """Raised when another process already holds the pidfile lock."""

    def __init__(self, path: Path, existing_pid: int | None):
        self.path = path
        self.existing_pid = existing_pid
        if existing_pid is not None:
            msg = f"pidfile {path} is already locked by pid {existing_pid}"
        else:
            msg = f"pidfile {path} is already locked"
        super().__init__(msg)


class PidfileHandle:
    """Returned by :func:`acquire_pidfile`; release with :meth:`release`."""

    def __init__(self, path: Path, fh):
        self.path = path
        self._fh = fh
        self._released = False

    def release(self) -> None:
        """Unlock + remove the pidfile. Idempotent; safe to call from ``finally``."""
        if self._released:
            return
        self._released = True
        if self._fh is None:
            return
        try:
            if _HAS_FCNTL:
                try:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            try:
                self._fh.close()
            except OSError:
                pass
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                _log(f"pidfile cleanup failed for {self.path}: {exc!r}", err=True)
        finally:
            self._fh = None


def _pid_alive(pid: int) -> bool:
    """Return True if ``pid`` names a live process on this host."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it (different uid) — still alive.
        return True
    except OSError:
        return False
    return True


def _read_existing_pid(fh) -> int | None:
    try:
        fh.seek(0)
        contents = fh.read()
    except OSError:
        return None
    try:
        return int(contents.strip())
    except (ValueError, AttributeError):
        return None


def acquire_pidfile(pidfile_path: str | None = DEFAULT_PIDFILE_PATH) -> PidfileHandle | None:
    """Try to acquire an exclusive lock on ``pidfile_path``.

    Returns a :class:`PidfileHandle` on success, or ``None`` when pidfiles are
    disabled (empty path). Raises :class:`PidfileLockedError` when another
    process already holds the lock.

    Idempotency: a stale pidfile (file exists, lock not held, or pid dead) is
    reclaimed transparently. A live-holder is not — that's the whole point.
    """
    if not pidfile_path:
        return None
    if not _HAS_FCNTL:  # pragma: no cover - Windows
        _log("pidfile lock unavailable on this platform; skipping single-instance check", err=True)
        return None
    path = Path(pidfile_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Open with O_RDWR|O_CREAT so flock can adjudicate; we never truncate up
    # front because that would wipe the existing-pid contents before we've
    # confirmed the lock is ours to take.
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    fh = os.fdopen(fd, "r+", encoding="utf-8")
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            existing = _read_existing_pid(fh)
            # The holder is live (or we can't tell); surface a loud error.
            fh.close()
            raise PidfileLockedError(path, existing) from None
        # We hold the lock. Check for a stale pid written by a dead
        # predecessor and overwrite it with ours.
        existing = _read_existing_pid(fh)
        if existing is not None and existing != os.getpid() and _pid_alive(existing):
            # Extremely unlikely: we got the lock but the bytes say someone
            # else is alive. Treat as a conflict to be safe.
            fh.close()
            raise PidfileLockedError(path, existing)
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    except Exception:
        try:
            fh.close()
        except OSError:
            pass
        raise
    return PidfileHandle(path, fh)
