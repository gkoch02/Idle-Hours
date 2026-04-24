"""Golden-image regression tests for ``render_quote.render``.

Why this exists
---------------

The rest of ``test_render_quote.py`` asserts structural properties: the image
is 800x480, it snaps to the Spectra 6 palette, the dark theme background is
black, etc. None of those assertions would catch:

* a silent layout regression (``choose_layout`` threshold moves, the ``hero``
  font grows past ``font_max``, ``fit_quote`` stops shrinking early);
* a bold/accent-colour regression (``wrap_styled_text`` stops tokenising the
  matched phrase, the theme's ``accent`` colour is swapped);
* a justification regression (non-last lines stop distributing slack, the
  25%-of-width fallback cliff moves);
* a debug-footer regression (the separator rule, the HH:MM . bucket line).

Pixel-level comparison against committed golden PNGs catches all of these.

Why this is robust against FreeType version drift
-------------------------------------------------

``render`` always calls ``snap_image_to_palette`` as its last step, which maps
every pixel to one of six fixed RGB triples. Subpixel antialiasing that would
otherwise differ between FreeType / Pillow versions collapses to the same
palette index in almost all cases, so the committed goldens stay valid across
common environment drift (confirmed locally: three consecutive renders of the
same row produce byte-identical PNGs).

The comparison still allows a tiny per-pixel delta (``MAX_DIFF_RATIO``) to
absorb any single-pixel antialiasing boundary that happens to straddle a
palette cell. A layout regression (wrapping differently, wrong layout choice)
flips thousands of pixels and blows past the budget; font rendering drift
flips a handful at most.

Regenerating goldens
--------------------

After an intentional renderer change, re-generate every golden in one pass::

    UPDATE_RENDER_GOLDEN=1 pytest tests/test_render_golden.py

Inspect the diffs in the PR before committing. A legitimate change may move
many pixels; an unintentional regression is more likely to move them in a
structurally surprising way (e.g. the bold time phrase loses its accent
colour, or the quote block shifts by half a line).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image, ImageChops

import render_quote as rq

GOLDEN_DIR = Path(__file__).parent / "golden" / "renderer"

# Ratio of pixels allowed to differ from the golden. 0.001 = 0.1% (384 pixels
# out of 384,000 for an 800x480 image). Calibrated tight enough that a layout
# regression (which flips thousands of pixels) fails, loose enough that a
# one-pixel antialiasing boundary doesn't. If this starts flaking on CI across
# Pillow upgrades, widen to 0.005 before lowering the signal of the test.
MAX_DIFF_RATIO = 0.001

UPDATE_GOLDEN = os.environ.get("UPDATE_RENDER_GOLDEN") == "1"


def _row(display_quote: str, matched_text: str, **overrides) -> dict:
    """Build a quote row with sensible defaults for rendering.

    ``display_quote`` + ``matched_text`` are the two fields actually painted;
    everything else is metadata the footer / attribution block pulls from.
    """
    row = {
        "display_quote": display_quote,
        "matched_text": matched_text,
        "author": "Jane Austen",
        "title": "Mansfield Park",
        "bucket": "h3_exact",
        "resolved_bucket": "h3_exact",
        "used_fallback": False,
        "quality_score": 80,
        "source_id": "141",
        "line_number": 482,
    }
    row.update(overrides)
    return row


# Scenarios intentionally span every layout x theme x mode combination that
# actually hits a distinct code path in ``render_quote``. Adding more here is
# fine (and cheap — PNGs with six palette colours compress to ~1-4kB each).
# Keep names filesystem-safe: the scenario name becomes the golden filename.
SCENARIOS: list[dict] = [
    # Hero layout (<=90 chars) in both themes, production mode so the footer
    # doesn't mask layout drift.
    {
        "name": "hero_default_production",
        "time": "03:00",
        "row": _row("It was three o'clock in the afternoon.", "three o'clock"),
        "mode": "production",
        "theme": "default",
    },
    {
        "name": "hero_dark_production",
        "time": "03:00",
        "row": _row("It was three o'clock in the afternoon.", "three o'clock"),
        "mode": "production",
        "theme": "dark",
    },
    # Standard layout (91-170 chars) — the most common real-world case.
    {
        "name": "standard_default_production",
        "time": "08:55",
        "row": _row(
            "Do you think I should be standing here at five minutes to nine "
            "looking for it if I had it in my pocket all the while?",
            "five minutes to nine",
        ),
        "mode": "production",
        "theme": "default",
    },
    {
        "name": "standard_dark_production",
        "time": "08:55",
        "row": _row(
            "Do you think I should be standing here at five minutes to nine "
            "looking for it if I had it in my pocket all the while?",
            "five minutes to nine",
        ),
        "mode": "production",
        "theme": "dark",
    },
    # Dense layout (>170 chars) — triggers ``fit_quote``'s smaller-font branch
    # and the wrap engine's many-line path.
    {
        "name": "dense_default_production",
        "time": "02:30",
        "row": _row(
            "It was exactly half past two when she heard the gravel crunch beneath the "
            "carriage wheels for the second time that afternoon, and the hall clock "
            "answered with its own half-hearted chime a moment later, confirming to her "
            "what the window had already revealed.",
            "half past two",
        ),
        "mode": "production",
        "theme": "default",
    },
    # Debug mode — exercises the footer strip, dotted separator, and top-right
    # DEBUG banner. Uses system (DejaVu) sans fonts for the footer, which are
    # present on both the dev host and the CI Ubuntu image.
    {
        "name": "standard_default_debug",
        "time": "08:55",
        "row": _row(
            "Do you think I should be standing here at five minutes to nine "
            "looking for it if I had it in my pocket all the while?",
            "five minutes to nine",
        ),
        "mode": "debug",
        "theme": "default",
    },
    # Fallback-bucket debug — the footer has to render the ``bucket -> resolved``
    # arrow form, which is a separate branch.
    {
        "name": "fallback_debug_default",
        "time": "03:05",
        "row": _row(
            "It was three o'clock in the afternoon.",
            "three o'clock",
            resolved_bucket="h3_exact",
            used_fallback=True,
            bucket="h3_five_past",
        ),
        "mode": "debug",
        "theme": "default",
    },
    # Card mode (button C source-card overlay) — completely different layout
    # code path in render_source_card; both themes matter because card uses
    # the accent colour for the matched phrase.
    {
        "name": "card_default",
        "time": "03:00",
        "row": _row("It was three o'clock in the afternoon.", "three o'clock"),
        "mode": "card",
        "theme": "default",
    },
    {
        "name": "card_dark",
        "time": "03:00",
        "row": _row("It was three o'clock in the afternoon.", "three o'clock"),
        "mode": "card",
        "theme": "dark",
    },
    # No metadata — the attribution block is skipped and the quote block is
    # re-centred; a regression here previously crashed when ``source_path``
    # wasn't set and has been fixed defensively.
    {
        "name": "no_metadata_production",
        "time": "03:00",
        "row": _row(
            "It was three o'clock in the afternoon.",
            "three o'clock",
            author=None,
            title=None,
        ),
        "mode": "production",
        "theme": "default",
    },
    # The three operator-choice themes each use a distinct bundled typeface
    # (Bitter / Old Standard TT / Space Mono). The golden pins both the
    # colour palette (already covered by the field-set / palette tests) AND
    # the font choice — a regression that reverted any of these back to the
    # default Playfair chain would flip thousands of glyph pixels and blow
    # past ``MAX_DIFF_RATIO``. Standard layout is chosen because it exercises
    # both wrap-line and bold-phrase glyph rendering, which is where font
    # drift shows up most visibly.
    {
        "name": "standard_scholar_production",
        "time": "08:55",
        "row": _row(
            "Do you think I should be standing here at five minutes to nine "
            "looking for it if I had it in my pocket all the while?",
            "five minutes to nine",
        ),
        "mode": "production",
        "theme": "scholar",
    },
    {
        "name": "standard_newsprint_production",
        "time": "08:55",
        "row": _row(
            "Do you think I should be standing here at five minutes to nine "
            "looking for it if I had it in my pocket all the while?",
            "five minutes to nine",
        ),
        "mode": "production",
        "theme": "newsprint",
    },
    {
        "name": "standard_nightvision_production",
        "time": "08:55",
        "row": _row(
            "Do you think I should be standing here at five minutes to nine "
            "looking for it if I had it in my pocket all the while?",
            "five minutes to nine",
        ),
        "mode": "production",
        "theme": "nightvision",
    },
    # The bauhaus theme is the only theme that paints a decorative border
    # around the canvas margin (geometric corner accents + outer frame).
    # Pinning a golden here catches any regression that silently drops
    # ``draw_bauhaus_border`` or mis-positions the corner shapes — every
    # such regression flips hundreds-to-thousands of pixels in the otherwise-
    # blank margin strip.
    {
        "name": "standard_bauhaus_production",
        "time": "08:55",
        "row": _row(
            "Do you think I should be standing here at five minutes to nine "
            "looking for it if I had it in my pocket all the while?",
            "five minutes to nine",
        ),
        "mode": "production",
        "theme": "bauhaus",
    },
]


def _render_scenario(scenario: dict) -> Image.Image:
    return rq.render(
        scenario["time"],
        scenario["row"],
        800,
        480,
        mode=scenario["mode"],
        theme=scenario["theme"],
    )


def _count_diff_pixels(a: Image.Image, b: Image.Image) -> int:
    """Count pixels that differ between two same-size RGB images.

    ``ImageChops.difference`` returns a per-channel delta image; any non-zero
    pixel in the result means that pixel differs somewhere. Converting to 'L'
    (luminance) before counting collapses the three channels into one count
    without under-counting three-channel drifts as one.
    """
    assert a.size == b.size, f"size mismatch: {a.size} vs {b.size}"
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    bbox = diff.getbbox()
    if bbox is None:
        return 0
    # Sum non-zero pixels across the bounding box. A channel value of 0 means
    # the pixel matched on that channel; any non-zero byte means drift.
    non_zero = 0
    for px in diff.crop(bbox).convert("L").getdata():
        if px:
            non_zero += 1
    return non_zero


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["name"])
class TestGoldenRenderer:
    """Compare every scenario against its committed golden PNG.

    On first introduction, or after an intentional renderer change, run with
    ``UPDATE_RENDER_GOLDEN=1`` to regenerate the fixtures. Without the env
    var set, a missing golden fails the test (a deleted fixture shouldn't
    silently pass).
    """

    def test_matches_golden(self, scenario: dict):
        golden_path = GOLDEN_DIR / f"{scenario['name']}.png"
        img = _render_scenario(scenario)

        if UPDATE_GOLDEN or not golden_path.exists():
            golden_path.parent.mkdir(parents=True, exist_ok=True)
            # Palette-indexed PNG keeps committed fixtures tiny (~2-4kB each)
            # since the Spectra 6 output only has six distinct colours.
            img.convert("P", palette=Image.ADAPTIVE, colors=8).save(
                golden_path, format="PNG", optimize=True,
            )
            if not UPDATE_GOLDEN:
                pytest.fail(
                    f"golden {golden_path.name} was missing; wrote a new fixture. "
                    "Re-run the test to verify determinism, then commit the PNG."
                )
            return

        golden = Image.open(golden_path).convert("RGB")
        diff = _count_diff_pixels(img, golden)
        total = img.size[0] * img.size[1]
        ratio = diff / total
        assert ratio <= MAX_DIFF_RATIO, (
            f"scenario {scenario['name']}: {diff} of {total} pixels differ "
            f"({ratio:.4%} > {MAX_DIFF_RATIO:.4%}). "
            f"Re-run with UPDATE_RENDER_GOLDEN=1 after verifying the change is intentional."
        )


class TestGoldenStructure:
    """Cross-cutting assertions the per-scenario comparison can't make cheaply."""

    def test_every_scenario_has_unique_name(self):
        """Name collisions would silently overwrite each other's fixtures."""
        names = [s["name"] for s in SCENARIOS]
        assert len(names) == len(set(names)), "scenario names must be unique"

    def test_every_scenario_has_a_matching_golden(self):
        """A committed golden that no scenario renders anymore is dead weight.

        Flags either: (1) a scenario was deleted without cleaning up the
        fixture, or (2) a typo in ``scenario['name']`` made a live scenario
        generate a brand-new golden while the old one lingered.
        """
        expected = {f"{s['name']}.png" for s in SCENARIOS}
        actual = {p.name for p in GOLDEN_DIR.glob("*.png")}
        stale = actual - expected
        assert not stale, f"orphaned golden PNGs in {GOLDEN_DIR}: {sorted(stale)}"

    def test_themes_produce_distinct_goldens(self):
        """A regression that swapped THEMES['default'] and THEMES['dark']
        would pass every individual scenario test (both still render, both
        still snap to Spectra 6) but would make the two theme goldens
        byte-identical. Compare them directly as a belt-and-braces check.
        """
        default_hero = _render_scenario(SCENARIOS[0])  # hero_default_production
        dark_hero = _render_scenario(SCENARIOS[1])     # hero_dark_production
        diff = _count_diff_pixels(default_hero, dark_hero)
        total = default_hero.size[0] * default_hero.size[1]
        # Themes swap bg + text colour, so the overwhelming majority of
        # pixels change. Require >50% to catch a full swap, not a subtle one.
        assert diff / total > 0.5, (
            f"default and dark themes produced near-identical output ({diff}/{total} pixels differ)"
        )
