"""Tests for ``scripts/ingest_tarot_plates.py``, the tarot plate separator.

The committed plates are generated, never hand-edited (CLAUDE.md), so these
pin each one to a fresh run of the script on the committed scans: a change to
the separation shows up as a failing test rather than a plate that silently no
longer matches its generator.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from PIL import Image

from tests.pixel_helpers import pixel_bytes

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "ingest_tarot_plates.py"
ASSETS = REPO_ROOT / "idle_hours" / "assets"
SCANS = ASSETS / "tarot" / "dodal"


def _load_script():
    """Import the ingest script by path — ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location("ingest_tarot_plates", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ingest():
    return _load_script()


def _same_pixels(a: Path, b: Path) -> bool:
    with Image.open(a) as x, Image.open(b) as y:
        return x.size == y.size and pixel_bytes(x.convert("RGB")) == pixel_bytes(y.convert("RGB"))


class TestCommittedPlatesMatchTheirGenerator:
    def test_the_hour_sheet(self, ingest, tmp_path):
        out = tmp_path / "plates.png"
        assert ingest.main(["--input", str(SCANS), "--output", str(out)]) == 0
        assert _same_pixels(out, ASSETS / "tarot_plates.png")

    def test_the_moon_plate(self, ingest, tmp_path):
        out = tmp_path / "moon.png"
        assert ingest.main(["--single", "--input", str(SCANS / "trump_18.jpg"), "--output", str(out)]) == 0
        assert _same_pixels(out, ASSETS / "tarot_moon.png")
        with Image.open(out) as tile:
            assert tile.size == (ingest.TILE_W, ingest.TILE_H)


class TestSingleMode:
    def test_refuses_a_directory(self, ingest, tmp_path):
        out = tmp_path / "x.png"
        assert ingest.main(["--single", "--input", str(SCANS), "--output", str(out)]) == 1
        assert not out.exists()

    def test_the_sheet_never_picks_up_the_moon(self, ingest):
        """trump_18 sits beside trump_01..12, and hour 8's glob must not match it."""
        hits = [q for q in SCANS.glob("*08.jpg")]
        assert [q.name for q in hits] == ["trump_08.jpg"]
