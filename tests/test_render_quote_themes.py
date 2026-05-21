"""Smoke tests for the custom-render themes that bypass the standard literary layout.

These themes (``astrarium``, ``diags``, ``departures``, ``tarot``, ``vinyl``)
each dispatch out of ``render()`` into their own frame function and own their
composition top to bottom. The contracts every custom-render frame must keep:

* the returned image is the requested ``(width, height)``;
* every output pixel sits on the SPECTRA6 palette (verified after
  ``snap_image_to_palette``);
* the frame doesn't raise on representative inputs (full quote_row, missing
  metadata, edge-of-bucket minutes, every hour in the rotation).

The literary-layout themes have their own assertions in ``test_render_quote.py``;
this module focuses on the dispatch + on-palette + don't-crash invariants the
custom paths add.
"""
from __future__ import annotations

import pytest
from PIL import Image

from idle_hours import render_quote as rq

from .conftest import make_row

CUSTOM_THEMES = ("departures", "tarot", "vinyl")


def _on_palette(image: Image.Image) -> bool:
    palette = set(rq.SPECTRA6.values())
    return set(image.getdata()).issubset(palette)


@pytest.mark.parametrize("theme", CUSTOM_THEMES)
class TestCustomRenderContract:
    """Every custom-render theme must satisfy the four-clause contract above."""

    def test_returns_requested_size(self, theme):
        img = rq.render("14:30", make_row(), 800, 480, theme=theme)
        assert img.size == (800, 480)

    def test_output_is_on_palette(self, theme):
        img = rq.render("14:30", make_row(), 800, 480, theme=theme)
        assert _on_palette(img), f"{theme} produced off-palette pixels"

    def test_renders_with_empty_metadata(self, theme):
        """A row missing author / title / matched_text must still render."""
        row = make_row(author="", title="", matched_text="")
        img = rq.render("14:30", row, 800, 480, theme=theme)
        assert img.size == (800, 480)
        assert _on_palette(img)

    def test_renders_without_fuzzy_bucket(self, theme):
        """Bucket is re-derived from time_str when missing on the row."""
        row = make_row()
        row.pop("fuzzy_bucket", None)
        img = rq.render("14:30", row, 800, 480, theme=theme)
        assert img.size == (800, 480)


class TestDeparturesFrame:
    """Solari split-flap board — history-ledger sourcing + bucket math."""

    def test_upcoming_buckets_walk_forward_three(self):
        rows = rq._departures_upcoming_buckets("14:30", count=3)
        # Walking forward from h2_half_past (the canonical bucket for 14:30):
        # twenty_five_to / twenty_to / quarter_to → 14:35 / 14:40 / 14:45.
        assert [r["time"] for r in rows] == ["14:35", "14:40", "14:45"]

    def test_upcoming_buckets_roll_over_to_next_hour(self):
        rows = rq._departures_upcoming_buckets("14:55", count=3)
        # 14:55 → h3_exact (15:00) → h3_five_past → h3_ten_past.
        assert [r["time"] for r in rows] == ["15:00", "15:05", "15:10"]

    def test_upcoming_buckets_handles_malformed_time(self):
        assert rq._departures_upcoming_buckets("garbage") == []

    def test_recent_history_returns_empty_when_ledger_missing(self, tmp_path, monkeypatch):
        """The isolate_home conftest fixture redirects $HOME; with no ledger
        on disk the helper returns ``[]`` so the frame renders placeholder
        rows rather than crashing."""
        rq._departures_load_corpus_index.cache_clear()
        # No history.jsonl in the freshly-monkeypatched $HOME.
        assert rq._departures_recent_history(limit=3) == []

    def test_frame_emits_announcement_panel(self):
        """The dominant central announcement panel exists: top stripe is
        solid red (the NOW BOARDING banner), and the body underneath is
        the solid-yellow panel ground. Sampling near the panel corners
        avoids the quote-text region in the centre."""
        rq._departures_load_corpus_index.cache_clear()
        row = make_row(title="A Tale of Two Cities", author="Charles Dickens")
        img = rq.render("14:30", row, 800, 480, theme="departures")
        # Panel runs x∈[10, 790]; banner y∈[150, 180]; yellow body y∈[180, 378].
        # Banner: sample at the left edge (clear of centred text).
        assert img.getpixel((20, 160)) == rq.SPECTRA6["red"], \
            "banner band must be solid red"
        # Yellow panel ground: sample near the panel's bottom-left corner.
        assert img.getpixel((20, 360)) == rq.SPECTRA6["yellow"], \
            "announcement panel must be solid yellow"


class TestTarotFrame:
    """Major-arcana card — renders for every hour without raising."""

    @pytest.mark.parametrize("hour", range(0, 24))
    def test_renders_for_every_hour(self, hour):
        img = rq.render(f"{hour:02d}:00", make_row(), 800, 480, theme="tarot")
        assert img.size == (800, 480)
        assert _on_palette(img)

    def test_unmapped_hour_falls_back_to_pentagram(self):
        """The emblem registry only ships 3 of 12 templates; unmapped hours
        must reach the generic-pentagram fallback (no KeyError)."""
        # h=2 (II) is unmapped at v1; should hit _tarot_emblem_default.
        img = rq.render("02:00", make_row(), 800, 480, theme="tarot")
        assert img.size == (800, 480)

    def test_card_name_is_dithered_tyrian_purple(self):
        """The matched-phrase card name paints via draw_text_dithered with
        dark=red+light=blue at 0.5 density. Both inks must appear in the
        name band — failing means the dither call regressed to a single
        solid colour."""
        row = make_row(matched_text="half past two")
        img = rq.render("14:30", row, 800, 480, theme="tarot")
        # Card name band sits at y≈88..120 (y0=20, +68 offset, font ~22pt).
        # Sample a stripe across the card centre.
        counts = {}
        for y in range(95, 115):
            for x in range(280, 520):
                c = img.getpixel((x, y))
                counts[c] = counts.get(c, 0) + 1
        # Both red and blue pixels must be present (the 50/50 dither).
        assert counts.get(rq.SPECTRA6["red"], 0) > 100, "card name missing red pixels"
        assert counts.get(rq.SPECTRA6["blue"], 0) > 100, "card name missing blue pixels"

    def test_roman_numeral_table_is_complete(self):
        """Every hour 1..12 maps to a Roman numeral string."""
        assert set(rq._TAROT_ROMAN_NUMERALS.keys()) == set(range(1, 13))
        for hour, numeral in rq._TAROT_ROMAN_NUMERALS.items():
            assert numeral and isinstance(numeral, str)


class TestVinylFrame:
    """Turntable + record label — stylus angle math + catalog number."""

    @pytest.mark.parametrize("minute,expected_axis", [
        (0,  "up"),     # 0° = pointing up (12-o'-clock)
        (15, "right"),  # 90° = pointing right
        (30, "down"),   # 180° = pointing down
        (45, "left"),   # 270° = pointing left
    ])
    def test_stylus_angle_renders_at_expected_axis(self, minute, expected_axis):
        """The stylus arm sweeps clockwise from 12-o'-clock. Verify the red
        cartridge tip lands on the expected rim octant. The cartridge is a
        small red ellipse near the rim; we sample the 8 cardinal points
        and assert the right one carries red ink."""
        img = rq.render(f"11:{minute:02d}", make_row(), 800, 480, theme="vinyl")
        cx, cy, r = rq._VINYL_DISK_CX, rq._VINYL_DISK_CY, rq._VINYL_DISK_R
        # Cardinal probe points just inside the rim.
        probes = {
            "up":    (cx, cy - r + 5),
            "right": (cx + r - 5, cy),
            "down":  (cx, cy + r - 5),
            "left":  (cx - r + 5, cy),
        }
        x, y = probes[expected_axis]
        # The expected axis should have a red pixel within a small window
        # around the cartridge tip.
        red_seen = False
        for dy in range(-8, 9):
            for dx in range(-8, 9):
                if img.getpixel((x + dx, y + dy)) == rq.SPECTRA6["red"]:
                    red_seen = True
                    break
            if red_seen:
                break
        assert red_seen, f"stylus did not paint red at expected {expected_axis} axis"

    def test_catalog_number_format(self):
        assert rq._vinyl_catalog_number("h2_half_past") == "IH-H2-30"
        assert rq._vinyl_catalog_number("h12_exact") == "IH-H12-00"
        assert rq._vinyl_catalog_number("h7_quarter_to") == "IH-H7-45"

    def test_catalog_number_handles_garbage(self):
        assert rq._vinyl_catalog_number("") == "IH-?"
        assert rq._vinyl_catalog_number(None) == "IH-?"
        assert rq._vinyl_catalog_number("h2_unknown_state") == "IH-H2-?"

    def test_wear_speckle_is_deterministic_per_seed(self):
        """Same seed must produce the same wear-mark pattern so the
        per-day daily-seeded variation is stable across re-renders within
        the same day."""
        img_a = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        img_b = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        rq._astrarium_paint_cream_wash(img_a)
        rq._astrarium_paint_cream_wash(img_b)
        rq._vinyl_paint_wear_speckle(img_a, seed=20260521)
        rq._vinyl_paint_wear_speckle(img_b, seed=20260521)
        assert list(img_a.getdata()) == list(img_b.getdata())

    def test_wear_speckle_varies_with_seed(self):
        """Different seeds must produce different wear-mark patterns
        (i.e., the speckle isn't a no-op)."""
        img_a = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        img_b = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        rq._astrarium_paint_cream_wash(img_a)
        rq._astrarium_paint_cream_wash(img_b)
        rq._vinyl_paint_wear_speckle(img_a, seed=20260101)
        rq._vinyl_paint_wear_speckle(img_b, seed=20261231)
        assert list(img_a.getdata()) != list(img_b.getdata())
