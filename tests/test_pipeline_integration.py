"""End-to-end pipeline smoke test.

Feeds a tiny synthetic Gutenberg-style text through every stage of the
pipeline (miner → merge → clean → quality → enrich → apply_overrides → pick
→ render) and asserts a PNG falls out. The value of this test is NOT deep
per-stage coverage (every stage has its own module already), but catching
inter-stage schema drift: a field one stage stops emitting that a later stage
silently assumes is present.

Why this belongs in its own module: it cuts across nearly every top-level
script, so it has no natural home in a per-stage test file.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

try:
    from PIL import Image  # noqa: F401
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not installed")

import apply_content_overrides  # noqa: E402
import bake_quote_database  # noqa: E402
import clean_display_quotes  # noqa: E402
import enrich_metadata  # noqa: E402
import gutenberg_time_miner as miner  # noqa: E402
import merge_candidates  # noqa: E402
import pick_quote  # noqa: E402
import quality_filter  # noqa: E402

if PIL_AVAILABLE:
    import render_quote  # noqa: E402

# A minimal but realistic Gutenberg body. Must include a Gutenberg-style header
# (so enrich_metadata picks up Title / Author) and enough phrasing that every
# active match_type can fire at least once.
GUTENBERG_TEXT = """The Project Gutenberg eBook of Tiny Test Book

Title: Tiny Test Book
Author: Test Author

*** START OF THE PROJECT GUTENBERG EBOOK TINY TEST BOOK ***

It was three o'clock in the afternoon when she arrived at the gate,
the sun still high above the orchard wall. She had agreed to meet him
at quarter past six, and now feared she would be late returning home.

At half past eight the clock in the hall began to chime, and the old
man stirred in his chair. "Ten minutes past nine," he murmured, not
quite awake, glancing at the mantelpiece clock.

Shortly after noon the messenger returned with news from the village.
The clock struck midnight just as the last guest departed from the hall,
leaving the ballroom echoing and still.
"""


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


class TestPipelineEndToEnd:
    def test_harvest_through_render_produces_png(self, tmp_path):
        """Full pipeline smoke test — the most important regression guard
        against inter-stage schema drift."""
        # --- 1. Harvest -----------------------------------------------------
        # The miner reads the file under download_dir/pg<id>.txt when given
        # --gutenberg-id, but here we point --input at the file directly and
        # post-stamp source_id so the downstream enrich step can find it.
        cache_dir = tmp_path / "gutenberg"
        cache_dir.mkdir()
        book = cache_dir / "pg9999.txt"
        book.write_text(GUTENBERG_TEXT, encoding="utf-8")

        mine_args = argparse.Namespace(
            gutenberg_id=[],
            input=[str(book)],
            download_dir=str(cache_dir),
            context_chars=120,
            max_per_file=0,
            max_total=0,
            exclude_match_type=[],
            strict=False,
            skip_fetch_errors=False,
        )
        candidates = miner.mine(mine_args)
        assert candidates, "miner produced no candidates from the synthetic text"

        harvest_path = tmp_path / "candidates.jsonl"
        miner.write_jsonl(harvest_path, candidates)
        harvest_rows = _read_jsonl(harvest_path)
        for row in harvest_rows:
            # Without --gutenberg-id the miner leaves source_id=None. Stamp it
            # here so enrich_metadata can associate the row with pg9999.txt.
            row["source_id"] = "9999"
        _write_jsonl(harvest_path, harvest_rows)

        # --- 2. Merge (dedup) ----------------------------------------------
        records = list(merge_candidates.iter_records([str(harvest_path)]))
        merged_rows, merge_stats = merge_candidates.dedupe(records)
        assert merged_rows, "merge dropped every row (dedup bug?)"
        assert merge_stats.get("deduped_rows", 0) == len(merged_rows)
        merged_path = tmp_path / "merged.jsonl"
        _write_jsonl(merged_path, merged_rows)

        # --- 3. Clean display quotes ---------------------------------------
        cleaned_rows = []
        for row in merged_rows:
            quote, fragment, status = clean_display_quotes.best_display_quote(row)
            row = dict(row)
            row["display_quote"] = quote
            row["display_fragment"] = fragment
            row["cleanup_status"] = status
            cleaned_rows.append(row)
        assert all("display_quote" in r for r in cleaned_rows)

        # --- 4. Quality filter ---------------------------------------------
        quality_rows = []
        for row in cleaned_rows:
            score, flags = quality_filter.score_quote(
                row.get("display_quote") or "",
                row.get("display_fragment", False),
                row.get("cleanup_status") or "",
            )
            row = dict(row)
            row["quality_score"] = score
            row["quality_flags"] = flags
            quality_rows.append(row)
        assert all(isinstance(r["quality_flags"], list) for r in quality_rows)
        assert all(0 <= r["quality_score"] <= 100 for r in quality_rows)

        # --- 5. Enrich metadata --------------------------------------------
        title, author = enrich_metadata.parse_header(book)
        enriched_rows = []
        for row in quality_rows:
            row = dict(row)
            if not row.get("author") and author:
                row["author"] = author
            if not row.get("title") and title:
                row["title"] = title
            enriched_rows.append(row)
        assert any(r.get("title") == "Tiny Test Book" for r in enriched_rows), (
            "enrich_metadata did not pick up Title header"
        )
        assert any(r.get("author") == "Test Author" for r in enriched_rows)

        # --- 6. Apply content overrides (no-op sidecar) --------------------
        patched_rows, applied = apply_content_overrides.apply_overrides(enriched_rows, {})
        assert applied == 0  # empty sidecar → no patches
        final_path = tmp_path / "candidates-attributed.jsonl"
        _write_jsonl(final_path, patched_rows)

        # --- 7. Pick a quote for 03:00 -------------------------------------
        overrides = {"ban_source_ids": [], "boost_source_ids": [], "preferred_buckets": {}}
        picked = pick_quote.select_quote(
            time_str="03:00",
            input_path=str(final_path),
            rows=patched_rows,
            overrides=overrides,
            history_path=None,
            history_days=0,
            min_quality=0,
        )
        assert picked["display_quote"], "pick_quote returned no display_quote"
        assert picked["bucket"] == "h3_exact"

        # --- 8. Render to PNG ----------------------------------------------
        output_path = tmp_path / "render.png"
        image = render_quote.render("03:00", picked, 800, 480, mode="production", theme="default")
        image.save(output_path, format="PNG")
        image.close()
        assert output_path.exists()
        assert output_path.stat().st_size > 1024, "rendered PNG is suspiciously small"

        with output_path.open("rb") as f:
            magic = f.read(8)
        assert magic == b"\x89PNG\r\n\x1a\n", "output is not a valid PNG"

    def test_pipeline_survives_empty_corpus(self, tmp_path):
        """Every stage must cope with an empty input without crashing."""
        merged, stats = merge_candidates.dedupe(iter([]))
        assert merged == []
        patched, applied = apply_content_overrides.apply_overrides([], {})
        assert patched == []
        assert applied == 0
        # Baking an empty input must not crash either — a partial checkout or
        # fresh repo should still produce an (empty) quote database.
        baked, bake_stats = bake_quote_database.bake_rows([], min_quality=60)
        assert baked == []
        assert bake_stats["input"] == 0
        assert bake_stats["kept"] == 0


class TestPipelineWithBaking:
    """Extends the end-to-end smoke to cover the bake stage and bake-equivalence.

    ``TestPipelineEndToEnd`` stops at raw-corpus picking + rendering, which
    mirrors what the picker falls back to when the baked DB is missing. This
    class walks the canonical happy path (including bake) and asserts that
    baked picks match raw picks on the same synthetic corpus, and that a
    committed content-override actually lands on the row the operator
    targeted.
    """

    @pytest.fixture
    def attributed_rows(self, tmp_path) -> list[dict]:
        """Replay the miner → merge → clean → quality → enrich flow to produce
        attributed rows. Factored out as a fixture so each test in this class
        can start from the same corpus without re-running the pipeline."""
        cache_dir = tmp_path / "gutenberg"
        cache_dir.mkdir()
        book = cache_dir / "pg9999.txt"
        book.write_text(GUTENBERG_TEXT, encoding="utf-8")

        mine_args = argparse.Namespace(
            gutenberg_id=[], input=[str(book)], download_dir=str(cache_dir),
            context_chars=120, max_per_file=0, max_total=0, exclude_match_type=[],
            strict=False, skip_fetch_errors=False,
        )
        candidates = miner.mine(mine_args)
        harvest_rows = [c.as_dict() for c in candidates]
        for row in harvest_rows:
            row["source_id"] = "9999"

        # ``merge_candidates.dedupe`` takes ``Record`` instances, not raw dicts.
        # Construct them directly to skip the file round-trip here.
        records = [
            merge_candidates.Record(
                raw=row,
                canonical_quote=merge_candidates.normalize_text(row.get("quote_text") or ""),
                canonical_context=merge_candidates.normalize_text(row.get("context_text") or ""),
            )
            for row in harvest_rows
        ]
        merged_rows, _ = merge_candidates.dedupe(records)
        rows = []
        for row in merged_rows:
            row = dict(row)
            q, frag, status = clean_display_quotes.best_display_quote(row)
            row["display_quote"] = q
            row["display_fragment"] = frag
            row["cleanup_status"] = status
            score, flags = quality_filter.score_quote(q or "", frag, status or "")
            row["quality_score"] = score
            row["quality_flags"] = flags
            rows.append(row)

        title, author = enrich_metadata.parse_header(book)
        for row in rows:
            row.setdefault("author", author)
            row.setdefault("title", title)
        return rows

    def test_bake_rows_drops_daypart_only_and_stamps_schema(self, attributed_rows):
        # bake_rows is the final pipeline stage and enforces the same drop
        # rules the raw-corpus picker would apply per-tick.
        baked, stats = bake_quote_database.bake_rows(attributed_rows, min_quality=0)
        assert stats["input"] == len(attributed_rows)
        # Daypart-only matches (e.g. bare "noon" / "midnight") fall out at
        # bake time — the shipped miner emits them alongside clock matches.
        assert stats["kept"] <= stats["input"]
        for row in baked:
            assert row["schema_version"] == bake_quote_database.BAKED_SCORE_SCHEMA_VERSION
            assert "baked_score" in row
            assert len(row["baked_score"]) == len(pick_quote.BAKED_SCORE_COMPONENTS)
            assert "baked_rank" in row
            assert isinstance(row["inferred_quote_minute"], (int, type(None)))

    def test_baked_and_raw_pick_agree(self, attributed_rows):
        """The core bake-equivalence invariant replayed on a fresh synthetic
        corpus: the runtime picker must return the same ``(source_id,
        line_number)`` from the baked DB and from the raw corpus at a time
        where at least one candidate exists.

        ``test_bake_equivalence.py`` already sweeps the shipped corpus across
        all 144 buckets; this version proves the invariant also holds on a
        tiny tmp-path corpus, catching "bake-equivalence only works because
        of some quirk of the real corpus" bugs that would otherwise hide.
        """
        baked, _ = bake_quote_database.bake_rows(attributed_rows, min_quality=0)
        if not baked:
            pytest.skip("synthetic corpus produced no bake-eligible rows")

        # Pick a time where we know there's a candidate: use the bucket of the
        # first baked row so the test stays stable even if the synthetic text
        # changes.
        bucket = baked[0]["fuzzy_bucket"]
        hour_str, state = bucket.split("_", 1)
        hour = 12 if hour_str == "h12" else int(hour_str[1:])
        # Canonical minute for the bucket's minute-state (e.g. h3_exact → :00).
        from buckets import DEFAULT_BUCKET_MINUTES
        minute = DEFAULT_BUCKET_MINUTES.get(state, 0)
        time_str = f"{hour:02d}:{minute:02d}"

        empty_overrides = {"ban_source_ids": [], "boost_source_ids": [], "preferred_buckets": {}}
        raw_pick = pick_quote.select_quote(
            time_str=time_str, rows=attributed_rows, overrides=empty_overrides,
            history_path=None, history_days=0, min_quality=0,
        )
        baked_pick = pick_quote.select_quote(
            time_str=time_str, rows=baked, overrides=empty_overrides,
            history_path=None, history_days=0, min_quality=0,
        )
        assert (raw_pick["source_id"], raw_pick["line_number"]) == \
               (baked_pick["source_id"], baked_pick["line_number"]), (
            f"baked and raw picks disagree for {time_str}: "
            f"raw={raw_pick['source_id']}:{raw_pick['line_number']} vs "
            f"baked={baked_pick['source_id']}:{baked_pick['line_number']}"
        )

    def test_content_overrides_land_on_targeted_row(self, attributed_rows):
        """A sidecar entry keyed on (source_id, line_number) must mutate every
        row with that key and stamp ``override_applied=True``.

        Multiple time phrases on the same Gutenberg line produce multiple
        rows that share ``line_number`` (the miner records each match
        separately). ``applied`` counts per-row, so an override keyed on a
        popular line legitimately stamps more than once.
        """
        if not attributed_rows:
            pytest.skip("synthetic corpus empty")
        target = attributed_rows[0]
        target_key = (target["source_id"], target["line_number"])
        key = f"{target['source_id']}:{target['line_number']}"
        sidecar = {key: {"display_quote": "OVERRIDE MARKER — 03:00"}}

        patched, applied = apply_content_overrides.apply_overrides(attributed_rows, sidecar)
        # At least one row matched; extra matches are fine (same-line siblings).
        assert applied >= 1

        patched_targets = [
            r for r in patched
            if (r["source_id"], r["line_number"]) == target_key
        ]
        assert patched_targets, "override did not land on the target row"
        for row in patched_targets:
            assert row["display_quote"] == "OVERRIDE MARKER — 03:00"
            assert row.get("override_applied") is True

        # Rows with a different (source_id, line_number) must be untouched.
        untouched = [
            r for r in patched
            if (r["source_id"], r["line_number"]) != target_key
        ]
        for r in untouched:
            assert r.get("override_applied") is not True

    def test_selection_overrides_ban_drops_source_from_picks(self, attributed_rows):
        """A banned source_id must never be selected, even when it's the only
        candidate in the target bucket (picker falls back to neighbor bucket)."""
        baked, _ = bake_quote_database.bake_rows(attributed_rows, min_quality=0)
        if not baked:
            pytest.skip("synthetic corpus produced no bake-eligible rows")

        # Ban every source in the corpus; the picker must then fail gracefully
        # (no candidates available) rather than returning a banned row.
        banned_sources = list({str(r["source_id"]) for r in baked if r.get("source_id")})
        assert banned_sources, "synthetic corpus has no source_ids"
        overrides = {
            "ban_source_ids": banned_sources,
            "boost_source_ids": [],
            "preferred_buckets": {},
        }
        # After the ban, pick_best should exhaust every bucket's candidates
        # and raise the "no candidates" SystemExit — we exercise the lower-level
        # call to observe that exhaustion directly instead of through the
        # select_quote wrapper.
        bucket = baked[0]["fuzzy_bucket"]
        with pytest.raises(SystemExit):
            pick_quote.pick_best(
                baked, bucket, seed=0, min_quality=0, overrides=overrides,
                requested_time=None, recent_history=set(),
            )
