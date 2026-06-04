"""Tests for the render-time image-dithering capability and the Anna Atkins
cyanotype plate it feeds."""
from __future__ import annotations

import pytest
from PIL import Image

from idle_hours import render_quote as rq


def _all_pixels(img: Image.Image) -> set:
    return set(img.convert("RGB").getdata())


class TestDitherImageToPalette:
    def test_floyd_steinberg_output_is_on_palette(self):
        # A smooth grey gradient that contains no palette colour exactly.
        src = Image.new("RGB", (32, 32))
        px = src.load()
        for y in range(32):
            for x in range(32):
                v = (x + y) * 4 % 256
                px[x, y] = (v, v, v)
        out = rq.dither_image_to_palette(src, rq.SPECTRA6_PALETTE, method="floyd-steinberg")
        assert out.size == src.size
        assert _all_pixels(out) <= set(rq.SPECTRA6_PALETTE)

    def test_ordered_output_is_on_palette(self):
        src = Image.new("RGB", (24, 24), (90, 120, 200))
        out = rq.dither_image_to_palette(src, rq.SPECTRA6_PALETTE, method="ordered")
        assert out.size == src.size
        assert _all_pixels(out) <= set(rq.SPECTRA6_PALETTE)

    def test_ordered_is_deterministic(self):
        src = Image.new("RGB", (40, 16))
        px = src.load()
        for y in range(16):
            for x in range(40):
                px[x, y] = (x * 6, 64, 200 - y * 4)
        a = rq.dither_image_to_palette(src, rq.SPECTRA6_PALETTE, method="ordered")
        b = rq.dither_image_to_palette(src, rq.SPECTRA6_PALETTE, method="ordered")
        assert list(a.getdata()) == list(b.getdata())

    def test_midtone_dithers_to_a_mix_not_a_flat_fill(self):
        # A mid blue+white tone should break into >1 ink (the whole point of
        # dithering) rather than snapping flat to one nearest colour.
        src = Image.new("RGB", (40, 40), (128, 128, 255))
        out = rq.dither_image_to_palette(src, rq.SPECTRA6_PALETTE, method="floyd-steinberg")
        inks = _all_pixels(out)
        assert len(inks) >= 2
        assert inks <= set(rq.SPECTRA6_PALETTE)

    def test_restricted_palette_only_emits_those_inks(self):
        src = Image.new("RGB", (24, 24), (40, 60, 120))
        out = rq.dither_image_to_palette(src, rq._CYANOTYPE_PALETTE, method="floyd-steinberg")
        assert _all_pixels(out) <= set(rq._CYANOTYPE_PALETTE)

    def test_unknown_method_raises(self):
        src = Image.new("RGB", (4, 4), (0, 0, 0))
        with pytest.raises(ValueError):
            rq.dither_image_to_palette(src, rq.SPECTRA6_PALETTE, method="nope")

    def test_empty_palette_raises(self):
        src = Image.new("RGB", (4, 4), (0, 0, 0))
        with pytest.raises(ValueError):
            rq.dither_image_to_palette(src, [], method="floyd-steinberg")


class TestCyanotypePlate:
    def test_plate_asset_is_committed(self):
        assert rq.ANNA_ATKINS_PLATE.exists(), "anna_atkins cyanotype plate asset is missing"

    def test_load_dithered_plate_is_on_palette_and_sized(self):
        plate = rq._load_dithered_plate(rq.ANNA_ATKINS_PLATE, 200, 120, palette=rq._CYANOTYPE_PALETTE)
        assert plate is not None
        assert plate.size == (200, 120)
        assert _all_pixels(plate) <= set(rq._CYANOTYPE_PALETTE)

    def test_load_dithered_plate_is_cached(self):
        a = rq._load_dithered_plate(rq.ANNA_ATKINS_PLATE, 160, 96, palette=rq._CYANOTYPE_PALETTE)
        b = rq._load_dithered_plate(rq.ANNA_ATKINS_PLATE, 160, 96, palette=rq._CYANOTYPE_PALETTE)
        assert a is b  # memoised, same object

    def test_missing_asset_returns_none(self, tmp_path):
        assert rq._load_dithered_plate(tmp_path / "nope.png", 80, 60) is None


class TestGrimdarkPlate:
    def test_plate_asset_is_committed(self):
        assert rq.GRIMDARK_PLATE.exists(), "grimdark gunmetal plate asset is missing"

    def test_load_dithered_plate_is_on_palette_and_sized(self):
        plate = rq._load_dithered_plate(rq.GRIMDARK_PLATE, 200, 120, palette=rq._GUNMETAL_PALETTE)
        assert plate is not None
        assert plate.size == (200, 120)
        assert _all_pixels(plate) <= set(rq._GUNMETAL_PALETTE)

    def test_load_dithered_plate_is_cached(self):
        a = rq._load_dithered_plate(rq.GRIMDARK_PLATE, 160, 96, palette=rq._GUNMETAL_PALETTE)
        b = rq._load_dithered_plate(rq.GRIMDARK_PLATE, 160, 96, palette=rq._GUNMETAL_PALETTE)
        assert a is b  # memoised, same object


class TestLetterPlate:
    def test_plate_asset_is_committed(self):
        assert rq.LETTER_PLATE.exists(), "letter aged-paper plate asset is missing"

    def test_load_dithered_plate_is_on_palette_and_sized(self):
        plate = rq._load_dithered_plate(rq.LETTER_PLATE, 200, 120, palette=rq._AGED_PAPER_PALETTE)
        assert plate is not None
        assert plate.size == (200, 120)
        assert _all_pixels(plate) <= set(rq._AGED_PAPER_PALETTE)

    def test_load_dithered_plate_is_cached(self):
        a = rq._load_dithered_plate(rq.LETTER_PLATE, 160, 96, palette=rq._AGED_PAPER_PALETTE)
        b = rq._load_dithered_plate(rq.LETTER_PLATE, 160, 96, palette=rq._AGED_PAPER_PALETTE)
        assert a is b  # memoised, same object


def _plate_row():
    return {
        "display_quote": "It was half past two when the clock struck and the house fell still.",
        "matched_text": "half past two",
        "author": "Test Author",
        "title": "A Test Title",
        "bucket": "h2_half_past",
        "quality_score": 88,
        "source_id": "1",
        "line_number": 2,
    }


class TestPlateThemeRender:
    @pytest.mark.parametrize("theme", ["grimdark", "letter"])
    @pytest.mark.parametrize("mode", ["production", "debug"])
    def test_renders_on_palette(self, theme, mode):
        img = rq.render("02:30", _plate_row(), 800, 480, mode=mode, theme=theme)
        assert img.size == (800, 480)
        assert _all_pixels(img) <= set(rq.SPECTRA6_PALETTE)

    @pytest.mark.parametrize("theme", ["grimdark", "letter"])
    def test_small_preview_size_does_not_crash(self, theme):
        img = rq.render("02:30", _plate_row(), 400, 240, mode="production", theme=theme)
        assert img.size == (400, 240)

    @pytest.mark.parametrize("theme,const", [("grimdark", "GRIMDARK_PLATE"), ("letter", "LETTER_PLATE")])
    def test_missing_plate_falls_back_to_primitive_painter(self, theme, const, tmp_path, monkeypatch):
        # Point the plate constant at a missing path: _load_dithered_plate
        # returns None and the theme must still render on-palette via its
        # synthesised Layer-0 fallback rather than crashing.
        monkeypatch.setattr(rq, const, tmp_path / "missing.png")
        img = rq.render("02:30", _plate_row(), 800, 480, mode="production", theme=theme)
        assert img.size == (800, 480)
        assert _all_pixels(img) <= set(rq.SPECTRA6_PALETTE)


class TestAnnaAtkinsRender:
    def _row(self):
        return {
            "display_quote": "It was half past two when the clock struck and the house fell still.",
            "matched_text": "half past two",
            "author": "Anna Atkins",
            "title": "Photographs of British Algae",
            "bucket": "h2_half_past",
            "quality_score": 88,
            "source_id": "1843",
            "line_number": 7,
        }

    @pytest.mark.parametrize("mode", ["production", "debug"])
    def test_renders_on_palette(self, mode):
        img = rq.render("02:30", self._row(), 800, 480, mode=mode, theme="anna_atkins")
        assert img.size == (800, 480)
        assert _all_pixels(img) <= set(rq.SPECTRA6_PALETTE)

    def test_small_preview_size_does_not_crash(self):
        # /api/preview can request reduced sizes; the cyanotype frame must clip
        # rather than index past the canvas.
        img = rq.render("02:30", self._row(), 400, 240, mode="production", theme="anna_atkins")
        assert img.size == (400, 240)

    def test_matched_phrase_emits_sky_blue_stipple(self):
        # The matched phrase reroutes to a blue+white stipple, so both blue and
        # white must appear in the panel region (the deep panel is blue/black, so
        # white pixels there come from the body + matched-phrase text).
        img = rq.render("02:30", self._row(), 800, 480, mode="production", theme="anna_atkins")
        inks = _all_pixels(img)
        assert rq.SPECTRA6["white"] in inks
        assert rq.SPECTRA6["blue"] in inks
