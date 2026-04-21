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

import apply_content_overrides
import clean_display_quotes
import enrich_metadata
import gutenberg_time_miner as miner
import merge_candidates
import pick_quote
import quality_filter
import render_quote


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