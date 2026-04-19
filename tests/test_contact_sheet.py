"""Tests for contact_sheet.py."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from PIL import Image

import contact_sheet


class TestBucketToTime:
    def test_hour12_maps_to_midnight(self):
        assert contact_sheet.bucket_to_time("h12_exact") == "00:00"

    def test_hour12_half_past_is_midnight_thirty(self):
        assert contact_sheet.bucket_to_time("h12_half_past") == "00:30"

    def test_hour1(self):
        assert contact_sheet.bucket_to_time("h1_exact") == "01:00"

    def test_all_minute_states(self):
        expected = {
            "exact": "03:00",
            "five_past": "03:05",
            "ten_past": "03:10",
            "quarter_past": "03:15",
            "twenty_past": "03:20",
            "twenty_five_past": "03:25",
            "half_past": "03:30",
            "twenty_five_to": "03:35",
            "twenty_to": "03:40",
            "quarter_to": "03:45",
            "ten_to": "03:50",
            "five_to": "03:55",
        }
        for state, time_str in expected.items():
            assert contact_sheet.bucket_to_time(f"h3_{state}") == time_str

    def test_hour11_five_to(self):
        assert contact_sheet.bucket_to_time("h11_five_to") == "11:55"


def _fake_render(time_str, quote_row, width, height, mode="debug", theme="default"):
    """Stand-in for render_quote.render that returns a single-color PIL image."""
    return Image.new("RGB", (width, height), color=(128, 128, 128))


def _fake_select_quote(time_str, **kwargs):
    return {
        "display_quote": f"A quote for {time_str}",
        "matched_text": time_str,
        "source_id": "1",
        "line_number": 1,
    }


class TestRenderTile:
    def test_returns_correct_tile_size(self):
        with patch("contact_sheet.render_quote_module.render", side_effect=_fake_render), \
             patch("contact_sheet.pick_quote_module.select_quote", side_effect=_fake_select_quote):
            tile = contact_sheet.render_tile("03:00", 200, 120, "default", "production")
        assert tile.size == (200, 120)

    def test_placeholder_used_on_systemexit(self):
        with patch(
            "contact_sheet.pick_quote_module.select_quote",
            side_effect=SystemExit("no candidates"),
        ), patch("contact_sheet.render_quote_module.render", side_effect=_fake_render) as mock_render:
            tile = contact_sheet.render_tile("02:20", 200, 120, "default", "production")
        assert tile.size == (200, 120)
        mock_render.assert_not_called()

    def test_history_disabled_when_selecting(self):
        captured = {}

        def capture(**kwargs):
            captured.update(kwargs)
            return _fake_select_quote(**kwargs)

        with patch("contact_sheet.pick_quote_module.select_quote", side_effect=capture), \
             patch("contact_sheet.render_quote_module.render", side_effect=_fake_render):
            contact_sheet.render_tile("03:00", 200, 120, "default", "production")
        assert captured.get("history_path") is None
        assert captured.get("history_days") == 0


class TestBuildCell:
    def test_cell_includes_caption_height(self):
        with patch("contact_sheet.render_quote_module.render", side_effect=_fake_render), \
             patch("contact_sheet.pick_quote_module.select_quote", side_effect=_fake_select_quote):
            cell = contact_sheet.build_cell("03:00", "h3_exact", 200, 120, 18, "default", "production")
        assert cell.size == (200, 138)

    def test_cell_without_caption(self):
        with patch("contact_sheet.render_quote_module.render", side_effect=_fake_render), \
             patch("contact_sheet.pick_quote_module.select_quote", side_effect=_fake_select_quote):
            cell = contact_sheet.build_cell("03:00", "h3_exact", 200, 120, 0, "default", "production")
        assert cell.size == (200, 120)


class TestBuildSheet:
    def test_renders_all_144_cells(self):
        called_times: list[str] = []

        def capture_render(time_str, *_a, **_kw):
            called_times.append(time_str)
            return Image.new("RGB", (800, 480), color=(255, 255, 255))

        with patch("contact_sheet.render_quote_module.render", side_effect=capture_render), \
             patch("contact_sheet.pick_quote_module.select_quote", side_effect=_fake_select_quote):
            sheet = contact_sheet.build_sheet(
                tile_w=100, tile_h=60, caption_h=16, margin=4,
                theme="default", mode="production",
                log=lambda _msg: None,
            )
        assert len(called_times) == 144
        # First row first col is h1_exact → "01:00"
        assert called_times[0] == "01:00"
        # Sheet dimensions: 12 cols × 100 + 13 × 4 = 1252; 12 rows × 76 + 13 × 4 = 964
        assert sheet.size == (12 * 100 + 13 * 4, 12 * 76 + 13 * 4)

    def test_sheet_dimensions_scale_with_margin(self):
        with patch("contact_sheet.render_quote_module.render", side_effect=_fake_render), \
             patch("contact_sheet.pick_quote_module.select_quote", side_effect=_fake_select_quote):
            sheet = contact_sheet.build_sheet(
                tile_w=50, tile_h=30, caption_h=10, margin=0,
                theme="default", mode="production",
                log=lambda _msg: None,
            )
        # No margin → sheet is exactly rows×cell_h by cols×cell_w
        assert sheet.size == (12 * 50, 12 * 40)


class TestMainCLI:
    def test_writes_output_file(self, tmp_path):
        output = tmp_path / "sheet.png"
        argv = [
            "contact_sheet.py",
            "--output", str(output),
            "--tile-width", "50",
            "--tile-height", "30",
            "--caption-height", "10",
            "--margin", "2",
        ]
        with patch("sys.argv", argv), \
             patch("contact_sheet.render_quote_module.render", side_effect=_fake_render), \
             patch("contact_sheet.pick_quote_module.select_quote", side_effect=_fake_select_quote):
            rc = contact_sheet.main()
        assert rc == 0
        assert output.exists()
        # Verify it's a valid PNG
        img = Image.open(output)
        img.load()

    def test_missing_parent_dir_is_created(self, tmp_path):
        output = tmp_path / "nested" / "deep" / "sheet.png"
        argv = [
            "contact_sheet.py",
            "--output", str(output),
            "--tile-width", "40",
            "--tile-height", "24",
        ]
        with patch("sys.argv", argv), \
             patch("contact_sheet.render_quote_module.render", side_effect=_fake_render), \
             patch("contact_sheet.pick_quote_module.select_quote", side_effect=_fake_select_quote):
            contact_sheet.main()
        assert output.exists()


class TestBucketIteration:
    """The sheet must cover every (hour, state) in BUCKET_ORDER × 1..12."""

    def test_sheet_covers_all_hours_and_states(self):
        seen: list[str] = []

        def capture(time_str, *_a, **_kw):
            seen.append(time_str)
            return Image.new("RGB", (800, 480))

        with patch("contact_sheet.render_quote_module.render", side_effect=capture), \
             patch("contact_sheet.pick_quote_module.select_quote", side_effect=_fake_select_quote):
            contact_sheet.build_sheet(
                tile_w=50, tile_h=30, caption_h=0, margin=0,
                theme="default", mode="production",
                log=lambda _msg: None,
            )
        # Unique HH:MM strings — one per bucket (144).
        assert len(seen) == 144
        assert len(set(seen)) == 144

    def test_corpus_is_loaded_only_once(self):
        """Regression: 144 tiles must not each re-parse the JSONL + overrides."""
        with patch("contact_sheet.pick_quote_module.load_rows", return_value=[]) as mock_rows, \
             patch("contact_sheet.pick_quote_module.load_overrides", return_value={}) as mock_overrides, \
             patch("contact_sheet.render_quote_module.render", side_effect=_fake_render), \
             patch("contact_sheet.pick_quote_module.select_quote", side_effect=_fake_select_quote):
            contact_sheet.build_sheet(
                tile_w=50, tile_h=30, caption_h=0, margin=0,
                theme="default", mode="production",
                log=lambda _msg: None,
            )
        assert mock_rows.call_count == 1
        assert mock_overrides.call_count == 1

    def test_preloaded_rows_are_passed_to_select_quote(self):
        """build_sheet must thread pre-loaded rows/overrides into select_quote."""
        preloaded_rows = [{"sentinel": "rows"}]
        preloaded_overrides = {"sentinel": "overrides"}
        captured: list[dict] = []

        def capture(**kwargs):
            captured.append(kwargs)
            return _fake_select_quote(**kwargs)

        with patch("contact_sheet.pick_quote_module.load_rows", return_value=preloaded_rows), \
             patch("contact_sheet.pick_quote_module.load_overrides", return_value=preloaded_overrides), \
             patch("contact_sheet.render_quote_module.render", side_effect=_fake_render), \
             patch("contact_sheet.pick_quote_module.select_quote", side_effect=capture):
            contact_sheet.build_sheet(
                tile_w=50, tile_h=30, caption_h=0, margin=0,
                theme="default", mode="production",
                log=lambda _msg: None,
            )
        assert len(captured) == 144
        assert all(call.get("rows") is preloaded_rows for call in captured)
        assert all(call.get("overrides") is preloaded_overrides for call in captured)

    @pytest.mark.parametrize("theme", ["default", "dark"])
    def test_theme_propagates(self, theme):
        seen_themes: list[str] = []

        def capture(_t, _q, _w, _h, mode="debug", theme="default"):
            seen_themes.append(theme)
            return Image.new("RGB", (800, 480))

        with patch("contact_sheet.render_quote_module.render", side_effect=capture), \
             patch("contact_sheet.pick_quote_module.select_quote", side_effect=_fake_select_quote):
            contact_sheet.build_sheet(
                tile_w=50, tile_h=30, caption_h=0, margin=0,
                theme=theme, mode="production",
                log=lambda _msg: None,
            )
        assert all(t == theme for t in seen_themes)
