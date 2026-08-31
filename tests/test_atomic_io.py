"""Durability tests for the shared atomic_io module."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from idle_hours import atomic_io


class TestAtomicWriteText:
    def test_round_trip(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        atomic_io.atomic_write_text(target, "{\"k\": 1}")
        assert target.read_text(encoding="utf-8") == "{\"k\": 1}"

    def test_overwrite_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        target.write_text("old", encoding="utf-8")
        atomic_io.atomic_write_text(target, "new")
        assert target.read_text(encoding="utf-8") == "new"

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "deeper" / "file.json"
        atomic_io.atomic_write_text(target, "payload")
        assert target.read_text(encoding="utf-8") == "payload"

    def test_replace_failure_cleans_up_tmp_and_preserves_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When os.replace fails, the tmp file is removed and the target is untouched."""
        target = tmp_path / "state.json"
        target.write_text("original", encoding="utf-8")

        boom = OSError("simulated replace failure")

        def exploding_replace(src, dst):
            raise boom

        monkeypatch.setattr(os, "replace", exploding_replace)

        with pytest.raises(OSError):
            atomic_io.atomic_write_text(target, "new")

        # Target must still hold the original content.
        assert target.read_text(encoding="utf-8") == "original"
        # tmp sibling must have been cleaned up on the exception path.
        tmp_siblings = list(tmp_path.glob("*.tmp"))
        assert tmp_siblings == []

    def test_target_absent_still_writes(self, tmp_path: Path) -> None:
        target = tmp_path / "fresh.json"
        assert not target.exists()
        atomic_io.atomic_write_text(target, "hello")
        assert target.read_text(encoding="utf-8") == "hello"


class TestAtomicWriteBytes:
    def test_round_trip(self, tmp_path: Path) -> None:
        target = tmp_path / "render.png"
        payload = b"\x89PNG\r\n\x1a\npayload"
        atomic_io.atomic_write_bytes(target, payload)
        assert target.read_bytes() == payload

    def test_replace_failure_preserves_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "render.png"
        target.write_bytes(b"old-bytes")

        monkeypatch.setattr(os, "replace", lambda s, d: (_ for _ in ()).throw(OSError("replace boom")))
        with pytest.raises(OSError):
            atomic_io.atomic_write_bytes(target, b"new-bytes")

        assert target.read_bytes() == b"old-bytes"
        assert list(tmp_path.glob("*.tmp")) == []


class TestAtomicWriteLines:
    def test_lines_are_newline_terminated(self, tmp_path: Path) -> None:
        target = tmp_path / "out.jsonl"
        atomic_io.atomic_write_lines(target, ["a", "b\n", "c"])
        assert target.read_text(encoding="utf-8") == "a\nb\nc\n"

    def test_streaming_generator(self, tmp_path: Path) -> None:
        target = tmp_path / "out.jsonl"

        def gen():
            for i in range(5):
                yield f"row-{i}"

        atomic_io.atomic_write_lines(target, gen())
        assert target.read_text(encoding="utf-8").splitlines() == [f"row-{i}" for i in range(5)]

    def test_empty_iterable_produces_empty_file(self, tmp_path: Path) -> None:
        target = tmp_path / "out.jsonl"
        atomic_io.atomic_write_lines(target, [])
        assert target.exists()
        assert target.read_text(encoding="utf-8") == ""

    def test_replace_failure_preserves_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "out.jsonl"
        target.write_text("original\n", encoding="utf-8")

        monkeypatch.setattr(os, "replace", lambda s, d: (_ for _ in ()).throw(OSError("replace boom")))
        with pytest.raises(OSError):
            atomic_io.atomic_write_lines(target, ["new"])

        assert target.read_text(encoding="utf-8") == "original\n"
        assert list(tmp_path.glob("*.tmp")) == []


class TestDirFsyncBestEffort:
    def test_missing_directory_is_ignored(self, tmp_path: Path) -> None:
        # The internal helper should not raise when the directory vanishes.
        atomic_io._fsync_dir(tmp_path / "does-not-exist")

    def test_fsync_failure_is_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An OSError from os.fsync (e.g. on a filesystem that doesn't
        # support it) must not propagate — dir-fsync is best-effort.
        def exploding_fsync(fd):
            raise OSError("simulated fsync failure")

        monkeypatch.setattr(os, "fsync", exploding_fsync)
        atomic_io._fsync_dir(tmp_path)


class TestUniqueStagingFile:
    """#235: the staging sibling must be unique per write, not derived from the target.

    A deterministic ``<target>.tmp`` meant every writer of a given target
    shared one staging file, so two concurrent writers interleaved their
    payloads into it and each ``os.replace``d the blend into place — a corrupt
    file, published atomically. These tests fence the properties that make
    that impossible while keeping the rename atomic.
    """

    def test_staging_names_are_unique(self, tmp_path: Path) -> None:
        target = tmp_path / "quote_database.jsonl"
        names = {atomic_io._tmp_path_for(target).name for _ in range(200)}
        assert len(names) == 200

    def test_staging_file_is_a_sibling_of_the_target(self, tmp_path: Path) -> None:
        # os.replace is only atomic within one filesystem, so the staging file
        # must live in the target's own directory.
        target = tmp_path / "nested" / "quote_database.jsonl"
        tmp = atomic_io._tmp_path_for(target)
        assert tmp.parent == target.parent
        assert tmp.name.startswith("quote_database.jsonl.")
        assert tmp.suffix == ".tmp"

    def test_interleaved_writers_each_publish_a_whole_payload(self, tmp_path: Path) -> None:
        """Drive two writes whose staging phases overlap; the result is one intact payload.

        ``atomic_write_lines`` streams from the caller's iterable, so a
        generator that re-enters the module part-way through reproduces the
        interleaving a second process would cause — without needing real
        concurrency.
        """
        target = tmp_path / "corpus.jsonl"
        outer = [f"outer-{i}" for i in range(20)]
        inner = [f"inner-{i}" for i in range(20)]

        def interleaving():
            for i, line in enumerate(outer):
                if i == 10:
                    # A second writer runs to completion mid-stream.
                    atomic_io.atomic_write_lines(target, inner)
                yield line

        atomic_io.atomic_write_lines(target, interleaving())

        # Last writer wins — but it wins with *its own* payload, not a blend.
        assert target.read_text(encoding="utf-8").splitlines() == outer
        assert list(tmp_path.glob("*.tmp")) == []

    def test_failed_write_does_not_unlink_another_writers_staging_file(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "corpus.jsonl"
        target.write_text("original\n", encoding="utf-8")
        # Stand in for a concurrent writer's in-progress staging file.
        other = atomic_io._tmp_path_for(target)
        other.write_text("someone else's half-written payload\n", encoding="utf-8")

        def exploding():
            yield "line"
            raise RuntimeError("writer blew up mid-stream")

        with pytest.raises(RuntimeError):
            atomic_io.atomic_write_lines(target, exploding())

        assert target.read_text(encoding="utf-8") == "original\n"
        assert other.exists(), "cleanup must only remove this writer's own staging file"

    def test_name_collision_retries_then_gives_up(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """O_EXCL is what makes a token collision safe: it fails the create
        instead of clobbering whatever is already there. Astronomically
        unlikely in practice, but the branch must not silently truncate a
        stranger's file, and exhausting the retries must raise rather than
        return a bogus fd."""
        attempts = {"n": 0}
        real_open = os.open

        def always_taken(path, flags, *args):
            if str(path).endswith(".tmp"):
                attempts["n"] += 1
                raise FileExistsError(17, "File exists", str(path))
            return real_open(path, flags, *args)

        monkeypatch.setattr(atomic_io.os, "open", always_taken)
        with pytest.raises(FileExistsError):
            atomic_io.atomic_write_text(tmp_path / "state.json", "payload")
        assert attempts["n"] == atomic_io._TMP_CREATE_ATTEMPTS

    def test_mode_follows_umask_like_a_plain_open(self, tmp_path: Path) -> None:
        """tempfile.mkstemp would force 0600; we must match ``open(path, "w")``.

        Files written through here include the rendered PNG and the baked
        corpus, which other tooling reads — silently tightening their mode
        would be a behaviour change, not a fix.
        """
        reference = tmp_path / "reference"
        with reference.open("w", encoding="utf-8") as handle:
            handle.write("x")
        target = tmp_path / "written"
        atomic_io.atomic_write_text(target, "x")
        assert (target.stat().st_mode & 0o777) == (reference.stat().st_mode & 0o777)


class TestStaleStagingSweep:
    """Unique names cost the old scheme's accidental self-limiting property: a
    deterministic name meant a process killed mid-write left one orphan and the
    next write reused it. Nothing reclaims a unique one, and no ``except`` runs
    when a process is killed outright — a SIGKILL, a power cut, or
    ``subprocess.run(timeout=...)`` killing the render child mid-PNG-write.
    """

    def _abandon(self, target: Path, age_seconds: float) -> Path:
        """Create an orphan the way a hard-killed writer would leave one."""
        fd, tmp = atomic_io._open_tmp(target)
        os.close(fd)
        stamp = time.time() - age_seconds
        os.utime(tmp, (stamp, stamp))
        return tmp

    def test_old_orphans_are_reaped_after_a_successful_write(self, tmp_path: Path) -> None:
        target = tmp_path / "current.png"
        orphans = [self._abandon(target, atomic_io._TMP_SWEEP_AGE_SECONDS + 60)
                   for _ in range(5)]
        atomic_io.atomic_write_bytes(target, b"payload")
        assert not any(o.exists() for o in orphans)
        assert list(tmp_path.glob("*.tmp")) == []

    def test_recent_orphans_are_left_alone(self, tmp_path: Path) -> None:
        """The age margin is what makes the sweep safe against a concurrent
        writer — its staging file is seconds old, not an hour."""
        target = tmp_path / "current.png"
        fresh = self._abandon(target, 5)
        atomic_io.atomic_write_bytes(target, b"payload")
        assert fresh.exists()

    def test_other_targets_are_untouched(self, tmp_path: Path) -> None:
        target = tmp_path / "current.png"
        other = tmp_path / "quote_database.jsonl"
        other_orphan = self._abandon(other, atomic_io._TMP_SWEEP_AGE_SECONDS + 60)
        atomic_io.atomic_write_bytes(target, b"payload")
        assert other_orphan.exists(), "the sweep must be scoped to its own target"

    def test_sweep_failure_never_fails_the_write(self, tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
        """Hygiene, not correctness — it must not turn a good write into an error."""
        target = tmp_path / "current.png"
        monkeypatch.setattr(
            atomic_io.Path, "glob",
            lambda self, pattern: (_ for _ in ()).throw(OSError("no dir")),
        )
        atomic_io.atomic_write_bytes(target, b"payload")
        assert target.read_bytes() == b"payload"

    def test_an_operators_own_sibling_is_not_swept(self, tmp_path: Path) -> None:
        """The sweep deletes files, so it must recognise its own output exactly
        rather than approximately. A ``<target>.*.tmp`` glob reaped
        ``current.png.notes.tmp`` an hour after the next render."""
        target = tmp_path / "current.png"
        for name in ("current.png.notes.tmp", "current.png.backup.tmp",
                     "current.png.tmp", "current.png.12345.tmp",
                     "current.png.abc.3920cc9be95f.tmp",      # non-numeric pid
                     "current.png.123.nothexadecimal.tmp",    # not a hex token
                     "current.png.123.3920cc9be95.tmp"):      # token one char short
            victim = tmp_path / name
            victim.write_text("not ours")
            stamp = time.time() - (atomic_io._TMP_SWEEP_AGE_SECONDS + 60)
            os.utime(victim, (stamp, stamp))
        atomic_io.atomic_write_bytes(target, b"payload")
        survivors = sorted(p.name for p in tmp_path.glob("*.tmp"))
        assert len(survivors) == 7, f"swept a file it did not create: {survivors}"

    def test_glob_metacharacters_in_the_target_name(self, tmp_path: Path) -> None:
        """A target literally named ``foo[1].png`` produced the glob class
        ``[1]``, whose pattern matches ``foo1.png.…`` — a *different* target's
        staging files. Structural parsing needs no escaping rules."""
        weird = tmp_path / "foo[1].png"
        other = tmp_path / "foo1.png"
        stranger = self._abandon(other, atomic_io._TMP_SWEEP_AGE_SECONDS + 60)
        mine = self._abandon(weird, atomic_io._TMP_SWEEP_AGE_SECONDS + 60)
        atomic_io.atomic_write_bytes(weird, b"payload")
        assert stranger.exists(), "swept another target's staging file"
        assert not mine.exists(), "failed to sweep its own staging file"

    def test_is_staging_name_accepts_what_the_module_generates(self, tmp_path: Path) -> None:
        """Fence the two halves against drift — if the name format changes and
        the recogniser doesn't, the sweep silently stops reaping anything."""
        for name in ("current.png", "quote_database.jsonl", "state.json", "no-suffix"):
            target = tmp_path / name
            generated = atomic_io._tmp_path_for(target)
            assert atomic_io._is_staging_name(target.name, generated.name), generated.name

    def test_a_future_mtime_is_not_swept(self, tmp_path: Path) -> None:
        """A clock stepped backwards makes mtime look like the future; that
        must read as 'too young', which is the safe direction."""
        target = tmp_path / "current.png"
        future = self._abandon(target, -3600)
        atomic_io.atomic_write_bytes(target, b"payload")
        assert future.exists()
