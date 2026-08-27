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

import contextlib
import datetime
import os
import types
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from idle_hours import render_quote as rq

GOLDEN_DIR = Path(__file__).parent / "golden" / "renderer"

# Ratio of pixels allowed to differ from the golden. 0.001 = 0.1% (384 pixels
# out of 384,000 for an 800x480 image). Calibrated tight enough that a layout
# regression (which flips thousands of pixels) fails, loose enough that a
# one-pixel antialiasing boundary doesn't. If this starts flaking on CI across
# Pillow upgrades, widen to 0.005 before lowering the signal of the test.
MAX_DIFF_RATIO = 0.001
# The diagnostics frame uses the host's installed DejaVu metadata faces for
# very small system-info labels. Pillow/FreeType point releases can move those
# glyph edges by roughly 0.14% of the canvas while leaving every panel-scale
# shape and swatch unchanged. Keep the literary themes on the stricter global
# budget; allow only this environment-facing calibration screen a slightly
# wider cross-runner allowance.
SCENARIO_MAX_DIFF_RATIOS = {"standard_diags_production": 0.0015}

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
    # Blueprint paints a drafting-sheet border — thin blue outer rectangle
    # plus red crosshair registration marks at each corner. Parallel
    # reasoning to the bauhaus golden: catch a silent drop of
    # ``draw_blueprint_border`` or a regression in crosshair placement.
    {
        "name": "standard_blueprint_production",
        "time": "08:55",
        "row": _row(
            "Do you think I should be standing here at five minutes to nine "
            "looking for it if I had it in my pocket all the while?",
            "five minutes to nine",
        ),
        "mode": "production",
        "theme": "blueprint",
    },
    # Illuminated paints a manuscript-style border — double red rubricated
    # rule with a blue jewel at each outer corner. Pin the painted pixels
    # so a regression that dropped ``draw_illuminated_border`` would flip
    # thousands of margin pixels against the empty-margin baseline.
    {
        "name": "standard_illuminated_production",
        "time": "08:55",
        "row": _row(
            "Do you think I should be standing here at five minutes to nine "
            "looking for it if I had it in my pocket all the while?",
            "five minutes to nine",
        ),
        "mode": "production",
        "theme": "illuminated",
    },
    # Bauhaus in *debug* mode pins the ``_DEBUG_LABEL_RIGHT_INSET``
    # contract — the TR blue square sits at x=width-28 to width-6, which
    # would clip the default "DEBUG MODE" banner at x=width-SIDE_MARGIN.
    # The inset entry shifts the label left by 18px; a regression that
    # removed the inset would land the label back on top of the square
    # and flip thousands of pixels here. Bauhaus is chosen because it
    # has the most aggressive inset (38px); blueprint / illuminated
    # insets are less load-bearing and their production goldens already
    # catch graphic-placement regressions.
    {
        "name": "standard_bauhaus_debug",
        "time": "08:55",
        "row": _row(
            "Do you think I should be standing here at five minutes to nine "
            "looking for it if I had it in my pocket all the while?",
            "five minutes to nine",
        ),
        "mode": "debug",
        "theme": "bauhaus",
    },
    # Goodnight mode (--quiet-image=auto / --startup-image=auto) renders a
    # centred static message in the active theme via render_static_message.
    # Pin one light-theme + one dark-theme + one operator-theme golden so a
    # regression in the headline font, fit-loop, or theme-border interaction
    # for the goodnight code path lands here loudly.
    # Deco's art-deco border paints a doubled hairline frame, four
    # concentric stepped-corner L-shapes, and a centred top-edge rising-sun
    # fan in red. A regression that dropped ``draw_deco_border`` (or any
    # of those three motifs) would flip thousands of margin pixels.
    {
        "name": "standard_deco_production",
        "time": "08:55",
        "row": _row(
            "Do you think I should be standing here at five minutes to nine "
            "looking for it if I had it in my pocket all the while?",
            "five minutes to nine",
        ),
        "mode": "production",
        "theme": "deco",
    },
    # Glacier paints a thin blue outer rule, four corner frost-crystal
    # clusters (two blue shards + one green-tipped diagonal shard each),
    # and four mid-edge snowflake-tick stars. Pins both the painted pixels
    # and Iceland's font load.
    {
        "name": "standard_glacier_production",
        "time": "08:55",
        "row": _row(
            "Do you think I should be standing here at five minutes to nine "
            "looking for it if I had it in my pocket all the while?",
            "five minutes to nine",
        ),
        "mode": "production",
        "theme": "glacier",
    },
    # Chalkboard pins the doubled white wooden frame and the BL chalk-dust
    # scatter. Also locks the Playwrite GB J Guides handwriting font load —
    # the cursive silhouette is the entire point, so a regression that
    # dropped to the fallback DejaVu Oblique would flip thousands of glyph
    # pixels here.
    {
        "name": "standard_chalkboard_production",
        "time": "08:55",
        "row": _row(
            "Do you think I should be standing here at five minutes to nine "
            "looking for it if I had it in my pocket all the while?",
            "five minutes to nine",
        ),
        "mode": "production",
        "theme": "chalkboard",
    },
    # Placard pins the doubled sign-painter's frame, the four red
    # thumbtack accents, and the Patrick Hand SC small-caps font load.
    # A regression that dropped to the fallback DejaVu Bold would flip
    # thousands of glyph pixels (small caps silhouette → mixed-case sans).
    {
        "name": "standard_placard_production",
        "time": "08:55",
        "row": _row(
            "Do you think I should be standing here at five minutes to nine "
            "looking for it if I had it in my pocket all the while?",
            "five minutes to nine",
        ),
        "mode": "production",
        "theme": "placard",
    },
    # Chanbara pins both the large off-canvas rising-sun disc in the BR
    # corner (a regression that mis-positioned the centre or shrank the
    # radius would flip the entire bottom-right quadrant) and the small
    # red artist's-chop seal in the TL. Also locks the Shojumaru
    # brush-painted font load — the dramatic display silhouette is the
    # whole point.
    {
        "name": "standard_chanbara_production",
        "time": "08:55",
        "row": _row(
            "Do you think I should be standing here at five minutes to nine "
            "looking for it if I had it in my pocket all the while?",
            "five minutes to nine",
        ),
        "mode": "production",
        "theme": "chanbara",
    },
    # Kanagawa is the most heavily composited theme in the rotation —
    # seven distinct layers (sky gradient + birds + horizon line +
    # seigaiha tile band + navy deepest-row post-pass + cream-tinted
    # rounded panel knockout + hanko seal) on top of the Yuji Boku
    # brush face for body + matched-phrase. A regression in any of
    # those layers flips hundreds-to-thousands of pixels here: the
    # seigaiha lattice geometry alone (each scale is a half-disk with
    # three concentric white arcs) accounts for ~30k painted pixels in
    # the bottom band, and a font drop to the Cormorant fallback would
    # flip every body-text glyph silhouette. The clear_rect knockout
    # also pins the rounded-corner panel geometry (radius 12, 2 px
    # shadow ledge, 1 px black frame, ~6% off-grid yellow cream
    # stipple) — a regression that mis-sized any of those would land
    # here loudly.
    {
        "name": "standard_kanagawa_production",
        "time": "04:30",
        "row": _row(
            "It was almost half past four when the bell finally rang and "
            "the waves crashed against the harbour wall.",
            "half past four",
            author="Jane Austen",
            title="Pride and Prejudice",
            bucket="h4_half_past",
            resolved_bucket="h4_half_past",
            quality_score=88,
            source_id="1342",
        ),
        "mode": "production",
        "theme": "kanagawa",
    },
    # sampler — a custom-render frame (counted cross-stitch). Pins the
    # deterministic stitch-mapping: a regression in the fit loop, the stitch
    # primitive, the matched-phrase floss reroute, or the Aida ground flips
    # thousands of pixels here.
    {
        "name": "standard_sampler_production",
        "time": "04:30",
        "row": _row(
            "It was almost half past four when the bell finally rang and "
            "the waves crashed against the harbour wall.",
            "half past four",
            author="Jane Austen",
            title="Pride and Prejudice",
            bucket="h4_half_past",
            resolved_bucket="h4_half_past",
            quality_score=88,
            source_id="1342",
        ),
        "mode": "production",
        "theme": "sampler",
    },
    # lieder — a custom-render frame (engraved art song). The generated sweep
    # entry below covers it at 08:55; this second scenario pins a *small* hour
    # on purpose, because lieder is the one theme whose composition changes
    # shape with the hour: the time signature is hour/4 and the barlines fall
    # every ``hour`` notes, so 3 o'clock engraves a densely barred staff where
    # 12 o'clock engraves an open one. It also fences the minimum-bar-spacing
    # guard, which only engages at the small hours.
    {
        "name": "lieder_meter_h3_production",
        "time": "03:15",
        "row": _row(
            "It was a quarter past three, and the house had not yet begun "
            "to stir, though the light was already on the stairs.",
            "quarter past three",
            author="Henry James",
            title="The Portrait of a Lady",
            bucket="h3_quarter_past",
            resolved_bucket="h3_quarter_past",
            quality_score=91,
            source_id="2833",
        ),
        "mode": "production",
        "theme": "lieder",
    },
    # izakaya — a custom-render frame (neon alley). The generated sweep entry
    # below covers it at 08:55; this second scenario pins an hour whose lantern
    # numeral is TWO kanji (十一), which is the only case where the lantern
    # stacks its characters, and uses a long quote so the neon fit loop and the
    # cool/hot dual-mask bloom are exercised across five wrapped lines.
    {
        "name": "izakaya_hour11_production",
        "time": "11:50",
        "row": _row(
            "It was ten minutes to twelve, and the long corridor lay empty in "
            "the winter light; somewhere below a door closed, and then another.",
            "ten minutes to twelve",
            author="Henry James",
            title="The Portrait of a Lady",
            bucket="h11_ten_to",
            resolved_bucket="h11_ten_to",
            quality_score=89,
            source_id="2833",
        ),
        "mode": "production",
        "theme": "izakaya",
    },
    # abyssal — a custom-render frame (deep sea). The generated sweep entry
    # below covers it at 08:55; this second scenario pins the hour at its
    # extreme, because the hour IS the depth here: at twelve the sounding gauge
    # marker sits on the last graduation, which is the case where the marker
    # label and the graduation numeral collide unless one is suppressed.
    {
        "name": "abyssal_depth_h12_production",
        "time": "12:45",
        "row": _row(
            "It was a quarter to twelve, and the long corridor lay empty in "
            "the winter light; somewhere below a door closed, and then another.",
            "quarter to twelve",
            author="Henry James",
            title="The Portrait of a Lady",
            bucket="h12_quarter_to",
            resolved_bucket="h12_quarter_to",
            quality_score=89,
            source_id="2833",
        ),
        "mode": "production",
        "theme": "abyssal",
    },
    # pride — a custom-render frame (the six-stripe flag, flying). The generated
    # sweep entry below covers it at the standard length; this second scenario
    # pins a ONE-LINE quote, because the card is sized to its contents and the
    # short case is the one that exercises the _PRIDE_CARD_MIN floor and the
    # centring of a card much smaller than its maximum. It also fences the two
    # synthesised stripes: an orange or violet band that stopped mixing would
    # move far more than 0.1% of the canvas.
    {
        "name": "pride_short_production",
        "time": "09:00",
        "row": _row(
            "Nine o'clock, and not a soul stirring.",
            "Nine o'clock",
            author="Elizabeth Gaskell",
            title="Cranford",
            bucket="h9_exact",
            resolved_bucket="h9_exact",
            quality_score=84,
            source_id="394",
        ),
        "mode": "production",
        "theme": "pride",
    },
    # pulp — a custom-render frame (1940s paperback). The generated sweep entry
    # covers it at the standard length; this pins a LONG title, because the
    # cover title is the dominant element and the two-line wrap path is the one
    # the sweep's short title never reaches. It also fences the misregistration:
    # a lost red plate would move thousands of pixels around every glyph.
    {
        "name": "pulp_long_title_production",
        "time": "02:30",
        "row": _row(
            "It was half past two when the shot rang out, and nobody in that "
            "house ever told the truth again.",
            "half past two",
            author="Wilkie Collins",
            title="The Woman in White and Other Stories of Suspense",
            bucket="h2_half_past",
            resolved_bucket="h2_half_past",
            quality_score=86,
            source_id="583",
        ),
        "mode": "production",
        "theme": "pulp",
    },
    # synoptic — a literary-layout theme whose painter owns the ground. Pinned
    # at a time whose stamp digits differ in every position from the sweep's, so
    # a broken validity stamp cannot hide behind a coincidence.
    {
        "name": "synoptic_stamp_production",
        "time": "16:30",
        "row": _row(
            "It was about half past two when the wind shifted and the glass "
            "began to fall.",
            "half past two",
            author="Joseph Conrad",
            title="Typhoon",
            bucket="h2_half_past",
            resolved_bucket="h2_half_past",
            quality_score=88,
            source_id="1142",
        ),
        "mode": "production",
        "theme": "synoptic",
    },
    {
        "name": "goodnight_default",
        "message": "Good night.",
        "mode": "goodnight",
        "theme": "default",
    },
    {
        "name": "goodnight_dark",
        "message": "Good night.",
        "mode": "goodnight",
        "theme": "dark",
    },
    {
        "name": "goodnight_scholar",
        "message": "Good night.",
        "mode": "goodnight",
        "theme": "scholar",
    },
]


# ---------------------------------------------------------------------------
# Full-rotation theme coverage
# ---------------------------------------------------------------------------
#
# The hand-written scenarios above pin layouts, modes, and the themes whose
# decoration warranted a bespoke note. That left most of the rotation with no
# pixel-level fence at all: before this block, 14 of 45 registered themes had
# a golden, and the only all-theme sweep in the suite renders at the
# ``/api/preview`` thumbnail sizes (80x60, 240x144) asserting nothing but size
# and palette-subset.
#
# Rather than hand-listing the remainder — which guarantees the list rots the
# next time someone adds a theme — the standard-layout scenario for every
# registered theme is generated here. A newly registered theme therefore
# arrives with a failing golden test ("golden was missing; wrote a new
# fixture") instead of silently shipping unpinned.
#
# Themes that already have a hand-written ``standard_<theme>_production``
# entry keep it; this only fills gaps.

THEME_SWEEP_TIME = "08:55"
THEME_SWEEP_QUOTE = (
    "Do you think I should be standing here at five minutes to nine "
    "looking for it if I had it in my pocket all the while?"
)
THEME_SWEEP_MATCH = "five minutes to nine"

_hand_written = {s["name"] for s in SCENARIOS}
for _theme in sorted(rq.THEMES):
    _name = f"standard_{_theme}_production"
    if _name in _hand_written:
        continue
    SCENARIOS.append(
        {
            "name": _name,
            "time": THEME_SWEEP_TIME,
            "row": _row(THEME_SWEEP_QUOTE, THEME_SWEEP_MATCH),
            "mode": "production",
            "theme": _theme,
        }
    )


# A fixed instant for the two themes that read the wall clock. ``astrarium``
# prints the date in its header strip and derives its solar-elevation and
# lunar-phase datums from the day of year; ``vinyl`` stamps a copyright year on
# the label and seeds its sleeve wear-speckle from ``YYYYMMDD`` so the pattern
# drifts day to day (by design — see the theme's note in CLAUDE.md).
#
# Both are legitimate behaviours and both make an un-frozen golden expire
# overnight, which is why neither theme had a fixture before. Freezing the
# clock for the comparison keeps the rest of each frame — the dial, the
# tonearm geometry, the liner-notes typography — under the same regression
# fence as every other theme. The set is verified against the renderer rather
# than trusted: ``test_clock_dependent_theme_list_is_accurate`` re-renders
# every theme at two instants and fails if this list is wrong in either
# direction.
GOLDEN_NOW = datetime.datetime(2026, 4, 19, 14, 30, 0)
CLOCK_DEPENDENT_THEMES = frozenset({"astrarium", "vinyl"})


def _frozen_datetime_module() -> types.SimpleNamespace:
    """A stand-in for the stdlib ``datetime`` module pinned to ``GOLDEN_NOW``.

    The frozen classes subclass the real ones so ``isinstance`` checks and
    ordinary construction keep working; only ``now()`` / ``today()`` are
    overridden. ``render_quote`` does ``import datetime`` and touches just
    ``datetime.datetime`` and ``datetime.date``, so swapping the module
    reference on the module object is enough.
    """

    class _FrozenDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return GOLDEN_NOW if tz is None else GOLDEN_NOW.replace(tzinfo=tz)

    class _FrozenDate(datetime.date):
        @classmethod
        def today(cls):
            return GOLDEN_NOW.date()

    return types.SimpleNamespace(
        datetime=_FrozenDatetime,
        date=_FrozenDate,
        timedelta=datetime.timedelta,
        timezone=datetime.timezone,
    )


@contextlib.contextmanager
def _frozen_clock():
    original = rq.datetime
    rq.datetime = _frozen_datetime_module()
    try:
        yield
    finally:
        rq.datetime = original


def _render_scenario(scenario: dict) -> Image.Image:
    if scenario["theme"] in CLOCK_DEPENDENT_THEMES:
        with _frozen_clock():
            return _render_scenario_now(scenario)
    return _render_scenario_now(scenario)


def _render_scenario_now(scenario: dict) -> Image.Image:
    if scenario["mode"] == "goodnight":
        return rq.render_static_message(
            scenario["message"],
            800,
            480,
            theme=scenario["theme"],
        )
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
    # ``histogram()`` buckets an 'L' image by value, so everything from index 1
    # upward is a differing pixel — the same count the per-pixel walk produced,
    # without ``getdata()`` (deprecated, removed in Pillow 14).
    return sum(diff.crop(bbox).convert("L").histogram()[1:])


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
        max_diff_ratio = SCENARIO_MAX_DIFF_RATIOS.get(scenario["name"], MAX_DIFF_RATIO)
        assert ratio <= max_diff_ratio, (
            f"scenario {scenario['name']}: {diff} of {total} pixels differ "
            f"({ratio:.4%} > {max_diff_ratio:.4%}). "
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

    def test_every_registered_theme_has_a_golden(self):
        """Every theme in the rotation must be pinned by at least one scenario.

        The generated block above makes this true by construction today; the
        assertion exists so that a future refactor which replaces generation
        with a hand-maintained list (or filters it) can't quietly drop themes
        back to being unpinned — the exact state 31 of them were in before.
        """
        pinned = {s["theme"] for s in SCENARIOS}
        missing = set(rq.THEMES) - pinned
        assert not missing, f"themes with no golden scenario: {sorted(missing)}"

    def test_clock_dependent_theme_list_is_accurate(self, monkeypatch):
        """``CLOCK_DEPENDENT_THEMES`` must match what the renderer actually does.

        Wrong in one direction (a theme reads the clock but isn't listed) and
        its golden expires overnight, turning CI red for reasons unrelated to
        any commit. Wrong in the other (a listed theme stopped reading the
        clock) and the freeze silently hides a real dependency change. Both are
        cheap to detect: render every theme at two well-separated instants and
        see which frames move.

        The sysinfo strip is pinned because it is the one live input the
        datetime freeze does not cover: ``diags`` renders ``/proc/uptime`` at
        minute granularity, and when the machine's uptime minute ticks between
        a theme's two back-to-back renders the strip moves a few pixels and
        this fence flags ``diags`` as clock-dependent — a real CI flake
        (PR #229's first run), reproduced by feeding two uptime strings into
        consecutive renders. Uptime is machine state, not the wall-clock
        dependency this test measures, so pinning it here narrows nothing.
        """
        monkeypatch.setattr(
            rq, "_diags_system_info",
            lambda: {"host": "golden", "ip": "0.0.0.0", "uptime": "1h 0m"},
        )
        far_future = datetime.datetime(2031, 11, 3, 9, 5, 0)
        row = _row(THEME_SWEEP_QUOTE, THEME_SWEEP_MATCH)
        drifted = set()
        original = rq.datetime
        try:
            for theme in sorted(rq.THEMES):
                frames = []
                for instant in (GOLDEN_NOW, far_future):
                    module = _frozen_datetime_module()
                    module.datetime.now = classmethod(lambda cls, tz=None, _i=instant: _i)
                    module.date.today = classmethod(lambda cls, _i=instant: _i.date())
                    rq.datetime = module
                    frames.append(
                        rq.render(THEME_SWEEP_TIME, dict(row), 800, 480,
                                  mode="production", theme=theme).convert("RGB")
                    )
                if ImageChops.difference(*frames).getbbox() is not None:
                    drifted.add(theme)
        finally:
            rq.datetime = original
        assert drifted == CLOCK_DEPENDENT_THEMES, (
            "CLOCK_DEPENDENT_THEMES is stale: themes that read the wall clock "
            f"but aren't frozen={sorted(drifted - CLOCK_DEPENDENT_THEMES)}, "
            f"themes frozen unnecessarily={sorted(CLOCK_DEPENDENT_THEMES - drifted)}"
        )

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
