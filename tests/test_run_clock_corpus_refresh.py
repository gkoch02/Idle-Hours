"""Tests for run_clock's upgrade-time refresh of a relocated corpus.

An appliance relocates the raw corpus and baked DB into its state dir, where
``_seed_writable_corpus_paths`` creates them once. ``_refresh_relocated_corpus``
rebuilds that pair when the installed package ships a different corpus, with
the operator's content overrides re-applied, and never writes either sidecar.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from idle_hours import apply_content_overrides, bake_quote_database, run_clock
from idle_hours.buckets import rederive_buckets
from idle_hours.jsonl_io import iter_jsonl
from tests.conftest import make_args

REAL_RAW = Path(run_clock.pick_quote_module.DEFAULT_INPUT_PATH)
REAL_BAKED = Path(run_clock.pick_quote_module.DEFAULT_DATABASE_PATH)
REAL_CONTENT = apply_content_overrides.DEFAULT_OVERRIDES_PATH


def _jsonl(rows: list[dict]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")


def _bake(rows: list[dict], sidecar: dict) -> tuple[list[dict], list[dict]]:
    patched, _ = apply_content_overrides.apply_overrides(rows, sidecar)
    rederive_buckets(patched)
    baked, _ = bake_quote_database.bake_rows(patched, min_quality=60)
    return patched, baked


def _bakeable_rows(count: int) -> list[dict]:
    """Rows from the shipped corpus the baker keeps and no override has touched."""
    kept_keys = {(r["source_id"], r["line_number"], r["matched_text"]) for r in iter_jsonl(REAL_BAKED)}
    rows = []
    for row in iter_jsonl(REAL_RAW):
        if apply_content_overrides.ORIGINALS_FIELD in row:
            continue
        if (row.get("source_id"), row.get("line_number"), row.get("matched_text")) not in kept_keys:
            continue
        rows.append(row)
        if len(rows) == count:
            break
    return rows


class FakeBundle:
    """A small self-consistent bundle standing in for the package's assets."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.dir = root / "bundle"
        self.dir.mkdir()
        self.raw = self.dir / "candidates-attributed.jsonl"
        self.baked = self.dir / "quote_database.jsonl"
        self.content = self.dir / "content_overrides.json"
        self.selection = self.dir / "selection_overrides.json"
        self.pool = _bakeable_rows(40)
        self.publish(self.pool[:30], {})
        self.selection.write_text('{"ban_source_ids": []}\n', encoding="utf-8")
        monkeypatch.setattr(run_clock.pick_quote_module, "DEFAULT_INPUT_PATH", str(self.raw))
        monkeypatch.setattr(run_clock.pick_quote_module, "DEFAULT_DATABASE_PATH", str(self.baked))
        monkeypatch.setattr(apply_content_overrides, "DEFAULT_OVERRIDES_PATH", self.content)
        monkeypatch.setattr(run_clock, "_SEEDED_CORPUS_PATHS", (
            ("overrides", self.selection),
            ("content_overrides", self.content),
            ("raw_corpus", self.raw),
            ("baked_db", self.baked),
        ))

    def publish(self, rows: list[dict], sidecar: dict) -> None:
        """Write a release the way the pipeline does: overrides applied, then baked."""
        patched, baked = _bake(rows, sidecar)
        self.raw.write_bytes(_jsonl(patched))
        self.baked.write_bytes(_jsonl(baked))
        self.content.write_text(json.dumps(sidecar) + "\n", encoding="utf-8")


@pytest.fixture
def bundle(tmp_path, monkeypatch) -> FakeBundle:
    return FakeBundle(tmp_path, monkeypatch)


def _state_args(tmp_path: Path, **overrides):
    state = tmp_path / "state"
    return make_args(
        tmp_path,
        overrides=str(state / "selection_overrides.json"),
        content_overrides=str(state / "content_overrides.json"),
        raw_corpus=str(state / "candidates-attributed.jsonl"),
        baked_db=str(state / "quote_database.jsonl"),
        **overrides,
    )


def _boot(args) -> None:
    """What pre-flight does: seed what's missing, then refresh."""
    assert run_clock._seed_writable_corpus_paths(args) == []
    run_clock._refresh_relocated_corpus(args)


def _key(row: dict) -> str:
    return f"{row['source_id']}:{row['line_number']}"


class TestFirstBoot:
    def test_seeds_byte_identical_and_stamps(self, tmp_path, bundle):
        args = _state_args(tmp_path)
        _boot(args)
        assert Path(args.raw_corpus).read_bytes() == bundle.raw.read_bytes()
        assert Path(args.baked_db).read_bytes() == bundle.baked.read_bytes()
        stamp = json.loads((tmp_path / "state" / run_clock.CORPUS_STAMP_NAME).read_text())
        assert stamp["bundle_digest"] == run_clock._bundle_digest(bundle.raw, bundle.baked)

    def test_first_boot_keeps_no_backup(self, tmp_path, bundle):
        """The refresh after a seed finds the files already right and leaves them."""
        _boot(_state_args(tmp_path))
        assert not list((tmp_path / "state").glob("*" + run_clock.CORPUS_BACKUP_SUFFIX))

    def test_preflight_seeds_but_does_not_refresh(self, tmp_path, bundle):
        """The refresh waits for the pidfile; pre-flight runs before it is taken."""
        args = _state_args(tmp_path, skip_preflight=False)
        with patch.object(run_clock, "_refresh_relocated_corpus") as refresh:
            run_clock._run_preflight(args)
        refresh.assert_not_called()
        assert Path(args.baked_db).exists()


class TestUpgrade:
    def test_new_bundle_reaches_the_state_dir(self, tmp_path, bundle, capsys):
        args = _state_args(tmp_path)
        _boot(args)
        old_raw = Path(args.raw_corpus).read_bytes()
        bundle.publish(bundle.pool, {})  # an expansion: ten more rows
        run_clock._refresh_relocated_corpus(args)
        assert Path(args.raw_corpus).read_bytes() == bundle.raw.read_bytes()
        assert Path(args.baked_db).read_bytes() == bundle.baked.read_bytes()
        prev = Path(args.raw_corpus + run_clock.CORPUS_BACKUP_SUFFIX)
        assert prev.read_bytes() == old_raw
        assert "corpus refreshed" in capsys.readouterr().out

    def test_operator_content_overrides_are_reapplied(self, tmp_path, bundle):
        """A curator edit lives in content_overrides.json; the rebuild keeps it."""
        args = _state_args(tmp_path)
        _boot(args)
        target = bundle.pool[3]
        edited = target["display_quote"] + " (curated)"
        content = Path(args.content_overrides)
        content.write_text(json.dumps({_key(target): {"display_quote": edited}}), encoding="utf-8")
        sidecar_bytes = content.read_bytes()

        bundle.publish(bundle.pool, {})
        run_clock._refresh_relocated_corpus(args)

        raw = {_key(r): r for r in iter_jsonl(Path(args.raw_corpus))}
        assert raw[_key(target)]["display_quote"] == edited
        assert len(raw) == len(bundle.pool), "the new rows arrived too"
        baked = [r for r in iter_jsonl(Path(args.baked_db)) if _key(r) == _key(target)]
        assert baked and baked[0]["display_quote"] == edited
        assert content.read_bytes() == sidecar_bytes, "the sidecar is never written"

    def test_rebuild_matches_a_curator_bake(self, tmp_path, bundle):
        """The refreshed pair is what POST /api/bake would produce from it."""
        args = _state_args(tmp_path)
        _boot(args)
        target = bundle.pool[5]
        sidecar = {_key(target): {"display_quote": target["display_quote"] + " (curated)"}}
        Path(args.content_overrides).write_text(json.dumps(sidecar), encoding="utf-8")
        bundle.publish(bundle.pool, {})
        run_clock._refresh_relocated_corpus(args)
        expected_raw, expected_baked = _bake(list(iter_jsonl(bundle.raw)), sidecar)
        assert list(iter_jsonl(Path(args.raw_corpus))) == expected_raw
        assert list(iter_jsonl(Path(args.baked_db))) == expected_baked

    def test_selection_overrides_are_never_written(self, tmp_path, bundle):
        args = _state_args(tmp_path)
        _boot(args)
        selection = Path(args.overrides)
        selection.write_text('{"ban_source_ids": ["operator-edit"]}', encoding="utf-8")
        bundle.selection.write_text('{"ban_source_ids": ["shipped"]}', encoding="utf-8")
        bundle.publish(bundle.pool, {})
        _boot(args)
        assert "operator-edit" in selection.read_text(encoding="utf-8")

    def test_install_without_a_stamp_is_refreshed(self, tmp_path, bundle):
        """An appliance seeded before the stamp existed gets the current corpus."""
        args = _state_args(tmp_path)
        state = tmp_path / "state"
        state.mkdir()
        Path(args.raw_corpus).write_bytes(_jsonl(bundle.pool[:5]))
        Path(args.baked_db).write_bytes(_jsonl(bundle.pool[:5]))
        _boot(args)
        assert Path(args.baked_db).read_bytes() == bundle.baked.read_bytes()
        assert (state / run_clock.CORPUS_STAMP_NAME).exists()


class TestShippedOverridesAcrossUpgrades:
    """The operator's sidecar is the previous release's copy plus their edits;
    content fixes shipped since must not be read as deletions."""

    def _curator_bake(self, args) -> list[dict]:
        """What POST /api/bake does to the refreshed raw corpus."""
        sidecar = json.loads(Path(args.content_overrides).read_text(encoding="utf-8"))
        rows, _ = apply_content_overrides.apply_overrides(list(iter_jsonl(Path(args.raw_corpus))), sidecar)
        return rows

    def _upgrade_adding_a_fix(self, tmp_path, bundle, *, operator_edit: bool = True):
        args = _state_args(tmp_path)
        _boot(args)
        if operator_edit:
            mine = bundle.pool[3]
            Path(args.content_overrides).write_text(
                json.dumps({_key(mine): {"display_quote": mine["display_quote"] + " (curated)"}}), encoding="utf-8")
        shipped = bundle.pool[7]
        fixed = shipped["display_quote"] + " (shipped fix)"
        bundle.publish(bundle.pool, {_key(shipped): {"display_quote": fixed}})
        run_clock._refresh_relocated_corpus(args)
        return args, shipped, fixed

    def test_new_shipped_fix_reaches_the_refreshed_corpus(self, tmp_path, bundle):
        args, shipped, fixed = self._upgrade_adding_a_fix(tmp_path, bundle)
        raw = {_key(r): r for r in iter_jsonl(Path(args.raw_corpus))}
        assert raw[_key(shipped)]["display_quote"] == fixed
        baked = [r for r in iter_jsonl(Path(args.baked_db)) if _key(r) == _key(shipped)]
        assert baked and baked[0]["display_quote"] == fixed

    def test_new_shipped_fix_survives_a_later_curator_bake(self, tmp_path, bundle):
        args, shipped, fixed = self._upgrade_adding_a_fix(tmp_path, bundle)
        rows = {_key(r): r for r in self._curator_bake(args)}
        assert rows[_key(shipped)]["display_quote"] == fixed
        assert rows[_key(bundle.pool[3])]["display_quote"].endswith(" (curated)")

    def test_a_shipped_fix_the_operator_deleted_stays_deleted(self, tmp_path, bundle):
        args = _state_args(tmp_path)
        target = bundle.pool[7]
        original = target["display_quote"]
        bundle.publish(bundle.pool[:30], {_key(target): {"display_quote": original + " (shipped fix)"}})
        _boot(args)
        Path(args.content_overrides).write_text("{}", encoding="utf-8")  # the operator drops it
        bundle.publish(bundle.pool, {_key(target): {"display_quote": original + " (shipped fix)"}})
        run_clock._refresh_relocated_corpus(args)
        raw = {_key(r): r for r in iter_jsonl(Path(args.raw_corpus))}
        assert raw[_key(target)]["display_quote"] == original

    def test_install_without_a_stamp_keeps_a_deletion_and_takes_a_new_fix(self, tmp_path, bundle):
        """With no recorded bundle, the ledgers in the operator's old corpus say
        which shipped keys they had, so a deleted one is not read as new."""
        args = _state_args(tmp_path)
        deleted, added = bundle.pool[7], bundle.pool[8]
        bundle.publish(bundle.pool[:30], {_key(deleted): {"display_quote": deleted["display_quote"] + " (shipped fix)"}})
        _boot(args)
        (tmp_path / "state" / run_clock.CORPUS_STAMP_NAME).unlink()  # seeded before stamps existed
        Path(args.content_overrides).write_text("{}", encoding="utf-8")  # the operator drops it, no bake yet
        bundle.publish(bundle.pool, {
            _key(deleted): {"display_quote": deleted["display_quote"] + " (shipped fix)"},
            _key(added): {"display_quote": added["display_quote"] + " (new fix)"},
        })
        run_clock._refresh_relocated_corpus(args)
        raw = {_key(r): r for r in iter_jsonl(Path(args.raw_corpus))}
        assert raw[_key(deleted)]["display_quote"] == deleted["display_quote"]
        assert raw[_key(added)]["display_quote"] == added["display_quote"] + " (new fix)"

    def test_stamp_records_the_shipped_overrides(self, tmp_path, bundle):
        args, shipped, fixed = self._upgrade_adding_a_fix(tmp_path, bundle)
        stamp = json.loads((tmp_path / "state" / run_clock.CORPUS_STAMP_NAME).read_text())
        assert stamp["content_overrides"] == {_key(shipped): {"display_quote": fixed}}

    def test_restamp_keeps_the_shipped_overrides(self, tmp_path, bundle):
        args, shipped, fixed = self._upgrade_adding_a_fix(tmp_path, bundle)
        stat = bundle.raw.stat()
        os.utime(bundle.raw, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
        run_clock._refresh_relocated_corpus(args)
        stamp = json.loads((tmp_path / "state" / run_clock.CORPUS_STAMP_NAME).read_text())
        assert stamp["content_overrides"] == {_key(shipped): {"display_quote": fixed}}


class TestRefreshRunsUnderThePidfile:
    def _main(self, tmp_path, *, acquire):
        events: list[str] = []
        argv = [
            "run_clock", "--buttons-off", "--quiet-off", "--shutdown-command", "",
            "--output", str(tmp_path / "current.png"), "--state-path", str(tmp_path / "state.json"),
            "--history-path", "", "--telemetry-path", "", "--pidfile", str(tmp_path / "run_clock.pid"),
        ]
        with patch("sys.argv", argv), \
             patch.object(run_clock, "_run_preflight"), \
             patch.object(run_clock.pidfile, "acquire_pidfile", side_effect=acquire(events)), \
             patch.object(run_clock, "_refresh_relocated_corpus", side_effect=lambda a: events.append("refresh")), \
             patch.object(run_clock, "_maybe_start_buttons"), \
             patch.object(run_clock, "_maybe_start_web_server"), \
             patch.object(run_clock, "_install_signal_handlers"), \
             patch.object(run_clock.sd_notify, "notify_ready"), \
             patch("idle_hours.runtime_render.current_time_str", return_value="12:00"), \
             patch("idle_hours.runtime_render.current_bucket", return_value="h12_exact"), \
             patch("idle_hours.runtime_render.peek_quote_id", return_value=("1", 2, "q", "m")), \
             patch("idle_hours.runtime_render.render_now"), \
             patch.object(run_clock, "_loop_sleep", side_effect=KeyboardInterrupt):
            try:
                result = run_clock.main()
            except KeyboardInterrupt:
                result = None
        return events, result

    def test_loop_refreshes_only_after_taking_the_lock(self, tmp_path):
        def acquire(events):
            return lambda path: events.append("lock")
        events, _ = self._main(tmp_path, acquire=acquire)
        assert events[:2] == ["lock", "refresh"]

    def test_a_locked_out_second_instance_never_refreshes(self, tmp_path):
        def acquire(events):
            def locked(path):
                raise run_clock.pidfile.PidfileLockedError(Path(path), 4242)
            return locked
        events, result = self._main(tmp_path, acquire=acquire)
        assert result == 1
        assert "refresh" not in events

    def test_once_beside_a_running_loop_skips_the_refresh(self, tmp_path, capsys):
        args = make_args(tmp_path, skip_preflight=False)
        held = run_clock.pidfile.acquire_pidfile(args.pidfile)
        try:
            with patch.object(run_clock, "_refresh_relocated_corpus") as refresh:
                run_clock._refresh_corpus_once_locked(args)
        finally:
            held.release()
        refresh.assert_not_called()
        assert "another instance holds the pidfile" in capsys.readouterr().out

    def test_once_alone_refreshes_and_releases_the_lock(self, tmp_path):
        args = make_args(tmp_path, skip_preflight=False)
        with patch.object(run_clock, "_refresh_relocated_corpus") as refresh:
            run_clock._refresh_corpus_once_locked(args)
        refresh.assert_called_once()
        run_clock.pidfile.acquire_pidfile(args.pidfile).release()


class TestNoRefresh:
    def test_matching_stamp_leaves_curated_files_alone(self, tmp_path, bundle):
        args = _state_args(tmp_path)
        _boot(args)
        Path(args.baked_db).write_text("curated bake\n", encoding="utf-8")
        _boot(args)
        assert Path(args.baked_db).read_text(encoding="utf-8") == "curated bake\n"

    def test_matching_stamp_skips_hashing(self, tmp_path, bundle):
        """An unchanged install costs a stat, not a 25 MB hash, at each start."""
        args = _state_args(tmp_path)
        _boot(args)
        with patch.object(run_clock, "_bundle_digest", side_effect=AssertionError("hashed")):
            run_clock._refresh_relocated_corpus(args)

    def test_reinstalled_identical_bundle_only_restamps(self, tmp_path, bundle):
        args = _state_args(tmp_path)
        _boot(args)
        Path(args.baked_db).write_text("curated bake\n", encoding="utf-8")
        stat = bundle.raw.stat()
        os.utime(bundle.raw, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
        run_clock._refresh_relocated_corpus(args)
        assert Path(args.baked_db).read_text(encoding="utf-8") == "curated bake\n"
        stamp = json.loads((tmp_path / "state" / run_clock.CORPUS_STAMP_NAME).read_text())
        assert stamp["bundle_files"]["raw_corpus"] == run_clock._file_signature(bundle.raw)

    def test_freeze_corpus(self, tmp_path, bundle):
        args = _state_args(tmp_path, freeze_corpus=True)
        _boot(args)
        Path(args.baked_db).write_text("my own corpus\n", encoding="utf-8")
        bundle.publish(bundle.pool, {})
        _boot(args)
        assert Path(args.baked_db).read_text(encoding="utf-8") == "my own corpus\n"

    def test_unrelocated_paths_are_left_alone(self, tmp_path, bundle):
        """A dev checkout reads the bundle directly; there is nothing to refresh."""
        before = bundle.raw.read_bytes()
        run_clock._refresh_relocated_corpus(make_args(tmp_path))
        assert bundle.raw.read_bytes() == before
        assert not (bundle.dir / run_clock.CORPUS_STAMP_NAME).exists()

    @pytest.mark.parametrize("content", ['{"141:482": {"display_quote": "x"', "[]"])
    def test_untrustworthy_content_overrides_skip_the_refresh(self, tmp_path, bundle, capsys, content):
        """Re-applying a broken sidecar as empty would undo every content fix."""
        args = _state_args(tmp_path)
        _boot(args)
        Path(args.content_overrides).write_text(content, encoding="utf-8")
        old_raw = Path(args.raw_corpus).read_bytes()
        bundle.publish(bundle.pool, {})
        run_clock._refresh_relocated_corpus(args)
        assert Path(args.raw_corpus).read_bytes() == old_raw
        assert "corpus refresh skipped" in capsys.readouterr().err

    def test_failed_write_keeps_the_stamp_stale_and_retries(self, tmp_path, bundle, capsys):
        args = _state_args(tmp_path)
        _boot(args)
        bundle.publish(bundle.pool, {})
        real_write = run_clock.atomic_io.atomic_write_bytes

        def fail_on_baked(path, payload):
            if Path(path) == Path(args.baked_db):
                raise OSError("No space left on device")
            real_write(path, payload)

        with patch.object(run_clock.atomic_io, "atomic_write_bytes", side_effect=fail_on_baked):
            run_clock._refresh_relocated_corpus(args)
        assert "corpus refresh failed" in capsys.readouterr().err
        assert Path(args.baked_db).read_bytes() != bundle.baked.read_bytes()

        run_clock._refresh_relocated_corpus(args)
        assert Path(args.baked_db).read_bytes() == bundle.baked.read_bytes()


class TestOnlyBakedDbRelocated:
    def test_rebuilds_baked_db_without_writing_the_package(self, tmp_path, bundle):
        args = make_args(tmp_path, baked_db=str(tmp_path / "state" / "quote_database.jsonl"))
        _boot(args)
        bundle.publish(bundle.pool, {})
        raw_before = bundle.raw.read_bytes()
        run_clock._refresh_relocated_corpus(args)
        assert Path(args.baked_db).read_bytes() == bundle.baked.read_bytes()
        assert bundle.raw.read_bytes() == raw_before


class TestShippedBundleIsSelfConsistent:
    def test_copy_shortcut_equals_a_rebuild(self):
        """The refresh copies the bundle when the operator's content overrides
        equal the shipped ones; that is only right if the shipped raw corpus
        already carries those overrides and the shipped DB is its bake."""
        rows = list(iter_jsonl(REAL_RAW))
        sidecar = apply_content_overrides.load_overrides(REAL_CONTENT)
        patched, baked = _bake(rows, sidecar)
        assert patched == rows, "re-run apply_content_overrides on the shipped corpus"
        assert baked == list(iter_jsonl(REAL_BAKED)), "re-bake quote_database.jsonl"
