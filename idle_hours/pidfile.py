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

from idle_hours.runtime_log import _log

DEFAULT_PIDFILE_PATH = "~/.idle-hours/run_clock.pid"


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
        """Unlock + remove the pidfile. Idempotent; safe to call from ``finally``.

        Order matters: we unlink the path FIRST (while still holding the flock)
        and only then release the lock + close the fd. If we unlinked after the
        unlock, a replacement process could slip in between our ``LOCK_UN`` and
        our ``unlink``: it would open the still-live path, acquire the flock on
        the same inode, and then our ``unlink`` would remove its pathname out
        from under it — opening the door for a third process to create a new
        inode at the same path and win a second flock on the new inode, breaking
        the single-instance guarantee. Unlinking while we hold the lock means a
        racer either blocks on the flock (and sees us as holder in the error
        message) or opens a fresh inode (post-unlink) and proceeds cleanly.
        """
        if self._released:
            return
        self._released = True
        if self._fh is None:
            return
        try:
            # Unlink before unlocking: inode stays referenced via our fd until
            # close, but the dentry is gone so a racer's ``os.open(path, O_CREAT)``
            # lands on a brand-new inode.
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                _log(f"pidfile cleanup failed for {self.path}: {exc!r}", err=True)
            if _HAS_FCNTL:
                try:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            try:
                self._fh.close()
            except OSError:
                pass
        finally:
            self._fh = None


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
            # Someone else holds the flock — they are, by definition, the
            # live holder. Read the pid they wrote so we can surface it to
            # the operator, then bail.
            existing = _read_existing_pid(fh)
            fh.close()
            raise PidfileLockedError(path, existing) from None
        # We hold the exclusive flock, so we own the pidfile. Any pid bytes
        # already in the file are stale — either a dead predecessor, or
        # (more commonly on a Pi that reboots) a PID that has been recycled
        # by an unrelated process. ``flock`` is the single source of truth;
        # second-guessing it with ``_pid_alive`` would trap startup on every
        # SIGKILL / power-loss / reboot where the PID happens to be reused.
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
