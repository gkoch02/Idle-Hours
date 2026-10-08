"""Durable atomic-write helpers shared across the codebase.

Every helper implements the same crash-safe contract:

    parent dir exists → write payload to a *uniquely named* sibling ``*.tmp`` →
    ``fsync`` data → ``os.replace`` tmp → target → ``fsync`` parent dir.

The final directory fsync is what makes the rename durable rather than merely
atomic: without it ``os.replace`` can return with the new dirent still in the
kernel's cache, and a crash in that window leaves the old or missing file.
It is skipped where the operation isn't meaningful (notably Windows).

Why the staging name is unique, how ``_sweep_stale_tmp`` reaps orphans, and
why it opens with ``0o666`` rather than ``mkstemp``: docs/runtime.md ("Atomic
writes"). Stdlib only, so every caller (the loop, the pipeline, the renderer,
the curator UI) can import it.
"""
from __future__ import annotations

import contextlib
import os
import secrets
import time
from pathlib import Path
from typing import IO, Callable, Iterable

# O_EXCL makes the create fail rather than clobber if the random token ever
# collides; the retry loop then picks a fresh one.
_TMP_OPEN_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL
_TMP_CREATE_ATTEMPTS = 8
# Random component of a staging name, in bytes; ``secrets.token_hex`` renders
# it as twice as many hex characters. The sweep validates against this, so the
# two cannot drift.
_TMP_TOKEN_BYTES = 6
# Age past which an abandoned staging file is swept. Unique names cost us the
# self-limiting property the old deterministic name had for free: there, a
# process killed mid-write left one orphan and the *next* write reused that
# exact name. Now nothing ever reclaims it, and the cleanup handler cannot
# help — a SIGKILL, a power cut, or ``subprocess.run(timeout=...)`` killing
# the render child unwinds no ``except`` block at all. ``render_quote`` writes
# ``output/current.png`` through here on every render and ``run_clock`` kills
# that child at RENDER_TIMEOUT_SECONDS, so an appliance stuck in the
# render-timeout backoff loop would accrete a PNG-sized orphan per failure.
# An hour is far beyond any plausible write duration, so the sweep cannot
# race a live writer's staging file.
_TMP_SWEEP_AGE_SECONDS = 3600


def _fsync_dir(path: Path) -> None:
    try:
        dir_fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def _tmp_path_for(path: Path) -> Path:
    """Return a collision-free staging sibling next to ``path``.

    Same directory as the target so the later ``os.replace`` stays within one
    filesystem (and therefore atomic). The ``.tmp`` suffix is preserved from
    the original scheme so operator glob-based cleanup still finds debris.
    """
    return path.parent / f"{path.name}.{os.getpid()}.{secrets.token_hex(_TMP_TOKEN_BYTES)}.tmp"


def _open_tmp(path: Path) -> tuple[int, Path]:
    """Create and open a fresh staging file for ``path``; return ``(fd, tmp_path)``."""
    last_exc: OSError | None = None
    for _ in range(_TMP_CREATE_ATTEMPTS):
        tmp_path = _tmp_path_for(path)
        try:
            return os.open(tmp_path, _TMP_OPEN_FLAGS, 0o666), tmp_path
        except FileExistsError as exc:
            last_exc = exc
            continue
    raise last_exc or OSError(f"could not create a staging file for {path}")


def _is_staging_name(target_name: str, candidate_name: str) -> bool:
    """True only for a name this module could itself have generated for ``target_name``.

    The sweep deletes files, so it must recognise its own output exactly rather
    than approximately. A ``<target>.*.tmp`` glob is too loose in two ways: it
    matches an operator's own sibling (``current.png.notes.tmp`` would be
    reaped an hour after the next render), and glob metacharacters in the
    target name reinterpret the pattern — a target literally named
    ``foo[1].png`` produces the class ``[1]``, whose pattern matches
    ``foo1.png.…``, i.e. a *different* target's staging files. Structural
    parsing sidesteps both, and needs no escaping rules to be got right.
    """
    prefix = f"{target_name}."
    suffix = ".tmp"
    if not candidate_name.startswith(prefix) or not candidate_name.endswith(suffix):
        return False
    middle = candidate_name[len(prefix):-len(suffix)]
    pid, sep, token = middle.partition(".")
    if not sep or not pid.isdigit():
        return False
    return len(token) == _TMP_TOKEN_BYTES * 2 and all(c in "0123456789abcdef" for c in token)


def _sweep_stale_tmp(path: Path, keep: Path) -> None:
    """Best-effort removal of long-abandoned staging siblings of ``path``.

    Only files older than :data:`_TMP_SWEEP_AGE_SECONDS` are touched, so a
    concurrent writer's in-flight staging file is never at risk — that margin
    is three orders of magnitude beyond a normal write. ``keep`` is our own
    file, excluded defensively even though it is always younger than the
    threshold. Every failure is swallowed: this is hygiene, not correctness,
    and it must never turn a successful write into an exception.

    Candidates come from a plain directory scan filtered by
    :func:`_is_staging_name` rather than from a glob, so a target name
    containing glob metacharacters cannot widen the match.
    """
    cutoff = time.time() - _TMP_SWEEP_AGE_SECONDS
    try:
        entries = list(os.scandir(path.parent))
    except OSError:
        return
    for entry in entries:
        if entry.name == keep.name or not _is_staging_name(path.name, entry.name):
            continue
        with contextlib.suppress(OSError):
            # A clock stepped backwards makes mtime look like the future,
            # which reads as "too young to sweep" — the safe direction.
            if entry.stat().st_mtime < cutoff:
                os.unlink(entry.path)


def _atomic_write(path: Path, mode: str, writer: Callable[[IO], object], **open_kwargs) -> None:
    """Shared tmp → fsync → replace → dir-fsync body for the three public helpers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = _open_tmp(path)
    try:
        with os.fdopen(fd, mode, **open_kwargs) as handle:
            writer(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # Any failure — OSError from the write/replace, or an exception raised
        # by the caller's ``lines`` generator part-way through — must not leave
        # a half-written staging file behind. Ours is uniquely named, so no
        # other writer's file can be caught by this.
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise
    _fsync_dir(path.parent)
    _sweep_stale_tmp(path, tmp_path)


def atomic_write_text(path: Path, payload: str, *, encoding: str = "utf-8") -> None:
    """Durably write a text payload to ``path`` (tmp → fsync → replace → dir fsync)."""
    _atomic_write(path, "w", lambda handle: handle.write(payload), encoding=encoding)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Durably write a binary payload to ``path`` (PNG renders, etc.)."""
    _atomic_write(path, "wb", lambda handle: handle.write(payload))


def atomic_write_lines(path: Path, lines: Iterable[str], *, encoding: str = "utf-8") -> None:
    """Durably write an iterable of lines to ``path``.

    Each line has a trailing ``\\n`` appended if one is not already present so
    callers can pass either ``"foo"`` or ``"foo\\n"``. Streams line-by-line so
    large JSONL outputs (the attributed corpus, say) do not have to be buffered
    whole in memory before writing.
    """

    def _write(handle: IO) -> None:
        for line in lines:
            if not line.endswith("\n"):
                line = line + "\n"
            handle.write(line)

    _atomic_write(path, "w", _write, encoding=encoding)
