"""Durability tests for the shared atomic_io module."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import atomic_io


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
