"""Durable atomic-write helpers shared across the codebase.

Every helper here implements the same crash-safe contract:

    parent dir exists → write payload to sibling ``*.tmp`` →
    ``fsync`` data → ``os.replace`` tmp → target → ``fsync`` parent dir.

The final directory fsync is what distinguishes a merely "atomic" rename from
a *durable* one: without it ``os.replace`` can return with the new dirent still
in the kernel's cache, and a crash in that window leaves the old or missing
file despite the rename having "succeeded". Parent-directory fsync failures
are swallowed on platforms where the operation isn't meaningful (notably
Windows).

Kept dependency-free (stdlib only) so every caller — ``run_clock`` on the
appliance loop, ``pick_quote``/``apply_content_overrides`` on the stdlib-only
pipeline side, ``render_quote`` on the Pillow side, ``web_server`` on the
curator UI — can import it without pulling in new runtime deps.
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Iterable


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
    return path.with_suffix(path.suffix + ".tmp")


def atomic_write_text(path: Path, payload: str, *, encoding: str = "utf-8") -> None:
    """Durably write a text payload to ``path`` (tmp → fsync → replace → dir fsync)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _tmp_path_for(path)
    try:
        with tmp_path.open("w", encoding=encoding) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise
    _fsync_dir(path.parent)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Durably write a binary payload to ``path`` (PNG renders, etc.)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _tmp_path_for(path)
    try:
        with tmp_path.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise
    _fsync_dir(path.parent)


def atomic_write_lines(path: Path, lines: Iterable[str], *, encoding: str = "utf-8") -> None:
    """Durably write an iterable of lines to ``path``.

    Each line has a trailing ``\\n`` appended if one is not already present so
    callers can pass either ``"foo"`` or ``"foo\\n"``. Streams line-by-line so
    large JSONL outputs (the attributed corpus, say) do not have to be buffered
    whole in memory before writing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _tmp_path_for(path)
    try:
        with tmp_path.open("w", encoding=encoding) as handle:
            for line in lines:
                if not line.endswith("\n"):
                    line = line + "\n"
                handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise
    _fsync_dir(path.parent)
