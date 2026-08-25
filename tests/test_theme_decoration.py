"""Structural fences for the per-theme decorative renderer.

``render_quote.py``'s per-theme decoration — the 33 ``draw_*_border``
painters plus the ten ``render_*_frame`` custom compositions — is roughly
59% of the module and 37% of all Python in the repo, yet for most themes it
was previously only *executed*, never *asserted*.

The reason is subtle: ``TestPreviewSizeRendering`` renders every registered
theme at 80x60 and 240x144 and asserts only ``img.size`` plus
palette-subset. That walks every painter (so line coverage reads ~95%) while
saying nothing about what the painter drew. A mutation probe confirmed the
gap: replacing all 33 border painters with ``lambda *a, **k: None`` left 17
of them with a fully green suite, and the same treatment applied to the
custom-frame sub-painters left six frame themes (astrarium, chrono,
grimdark, lcars, letter, questline) entirely undefended.

These tests close that class of regression structurally rather than by
hand-writing a bespoke assertion class per theme:

* ``TestBorderPainterActuallyPaints`` renders each theme twice — once
  normally, once with its painter neutered — and requires a meaningful
  pixel delta, concentrated in the outer margin band where decoration
  belongs.
* ``TestCustomFrameCompositionPaints`` does the same for the custom-frame
  themes by neutering their ``_<theme>_paint_*`` helpers.
* ``TestThemeDecorationRegistry`` fences the registry itself so a newly
  added theme can't quietly ship with no decoration and no test.

The thresholds are deliberately loose floors, not golden values: this suite
answers "did the painter paint at all", and ``tests/test_render_golden.py``
answers "did it paint the same thing as before". Keeping the two concerns
separate means a legitimate visual tweak re-baselines one committed PNG
instead of re-tuning a pixel count here.
"""
from __future__ import annotations

import inspect
import re

import pytest
from PIL import ImageChops

from idle_hours import render_quote as rq

from .pixel_helpers import distinct_inks

# Native panel geometry. The sweep deliberately runs at full size rather than
# at the ``/api/preview`` thumbnail sizes the pre-existing smoke sweep uses —
# most frames pin decoration to fixed 800x480 coordinates, so a thumbnail
# clips away the very graphics under test.
WIDTH, HEIGHT = 800, 480

# The outer band decoration lives in. ``render`` never starts the quote block
# before y=72 and keeps text inside a centred column, so a painter that draws
# anything decorative necessarily touches this ring.
MARGIN_X, MARGIN_Y = 40, 60

# Floors, chosen from the measured spread with an order of magnitude of head
# room. The quietest border in the rotation is ``swiss``, whose entire
# decoration is one 1 px hairline plus a 6x6 px square by design (austerity by
# subtraction is its visual identity): it moves 783 px total, 90 of them in the
# margin band. Every other border moves >4,000. A neutered painter moves 0.
MIN_BORDER_PIXELS = 250
MIN_MARGIN_PIXELS = 60

# Custom frames compose the whole canvas, so their floor is far higher; the
# quietest measured (marquee) moves ~25,000 px.
MIN_FRAME_PIXELS = 10_000

# Themes dispatched by ``render`` into a bespoke ``render_*_frame`` instead of
# the shared literary layout. Kept as a literal so a new custom frame has to be
# added here consciously; ``TestThemeDecorationRegistry`` proves the list still
# matches what ``render`` actually dispatches.
CUSTOM_FRAME_THEMES = (
    "diags",
    "astrarium",
    "marquee",
    "tarot",
    "vinyl",
    "vitrail",
    "questline",
    "chrono",
    "outrun",
    "sampler",
    "lieder",
    "izakaya",
    "abyssal",
    "pride",
    "pulp",
    "vhs",
    "cardcatalog",
    "metro",
)

# ``diags`` is the developer swatch panel, not a literary theme: it paints its
# reference bands inline in ``render_diags_frame`` with no ``_diags_paint_*``
# helpers to neuter, and it is already excluded from the random rotation via
# ``RANDOM_EXCLUDED_THEMES``. It is still swept by the registry test below.
FRAME_THEMES_WITH_HELPERS = tuple(t for t in CUSTOM_FRAME_THEMES if t != "diags")

# Themes that intentionally ship no decoration at all — the two originals,
# whose identity is plain type on a plain ground.
UNDECORATED_THEMES = frozenset({"default", "dark"})

ROW = {
    "display_quote": (
        "It was about half past two when the clock struck and the afternoon "
        "slipped quietly away from them."
    ),
    "matched_text": "half past two",
    "author": "Edith Wharton",
    "title": "The House of Mirth",
    "quality_score": 90,
    "fuzzy_bucket": "h2_half_past",
    "resolved_bucket": "h2_half_past",
    "source_id": "141",
    "line_number": 482,
}


def _noop(*args, **kwargs):
    return None


def _changed_pixel_counts(before, after):
    """Return ``(total_changed, margin_changed)`` between two renders.

    Counting goes through a max-of-channels reduction rather than
    ``convert("L")``: luminance rounding can collapse a small single-channel
    delta to zero, and a fence that silently under-counts is worse than no
    fence. ``ImageChops.lighter`` over the three split bands is exact — any
    channel differing leaves a non-zero pixel.
    """
    diff = ImageChops.difference(before.convert("RGB"), after.convert("RGB"))
    red, green, blue = diff.split()
    mask = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    total = sum(mask.histogram()[1:])
    inner = mask.crop((MARGIN_X, MARGIN_Y, WIDTH - MARGIN_X, HEIGHT - MARGIN_Y))
    return total, total - sum(inner.histogram()[1:])


def _render(theme, mode="production"):
    return rq.render("14:30", dict(ROW), WIDTH, HEIGHT, mode=mode, theme=theme)


class TestBorderPainterActuallyPaints:
    """Every registered border painter must leave visible marks on the page.

    Neutering the painter and diffing is the only assertion shape that scales
    to 33 themes without encoding each one's private geometry, and it is
    exactly the mutation that previously went undetected for 17 of them.
    """

    @pytest.mark.parametrize("theme", sorted(rq._BORDER_PAINTERS))
    def test_border_changes_the_canvas(self, theme, monkeypatch):
        painter = rq._BORDER_PAINTERS[theme]
        with_border = _render(theme)

        # Both dispatch paths must be neutered. Most themes reach their
        # painter through ``_paint_theme_border``'s registry lookup, but the
        # six ``_CLEAR_RECT_PADS`` themes (blueprint, kanagawa, cartograph,
        # circuit, synoptic, letter) are called by name from ``render`` so the body-text
        # knockout rect can be threaded through. Patching only the registry
        # made kanagawa and letter register a 0-pixel delta while their
        # painters were in fact still running.
        monkeypatch.setattr(rq, painter.__name__, _noop)
        monkeypatch.setitem(rq._BORDER_PAINTERS, theme, _noop)
        without_border = _render(theme)

        total, margin = _changed_pixel_counts(with_border, without_border)
        assert total >= MIN_BORDER_PIXELS, (
            f"{theme}: neutering {painter.__name__} changed only {total} px "
            f"(expected >= {MIN_BORDER_PIXELS}). The painter is a no-op or a stub."
        )
        assert margin >= MIN_MARGIN_PIXELS, (
            f"{theme}: {painter.__name__} paints {total} px but only {margin} of "
            f"them in the outer margin band (expected >= {MIN_MARGIN_PIXELS}). "
            "Decoration belongs in the margins, clear of the quote block."
        )

    @pytest.mark.parametrize("theme", sorted(rq._BORDER_PAINTERS))
    def test_border_output_stays_on_palette(self, theme):
        """Decoration must not introduce off-palette intermediates.

        The synthesised-colour recipes paint sentinel inks and post-pass them;
        a recipe that forgets its post-pass leaves an off-palette sentinel on
        the page, which looks fine in a PNG viewer and bleeds unpredictably on
        the panel. ``snap_image_to_palette`` normally catches this, so this
        assertion is defence in depth at native resolution.
        """
        image = _render(theme).convert("RGB")
        # ``getcolors`` rather than ``getdata`` / ``get_flattened_data``: the
        # former is deprecated (removed in Pillow 14), the latter only exists
        # from Pillow 11.1, and pyproject.toml floors Pillow well below that
        # (9.3) — so either would tie this test to a version window.
        # ``getcolors`` has been stable across every Pillow release and is the
        # better fit anyway: the assertion is about the set of distinct inks,
        # not about walking 384,000 pixels. ``tests/pixel_helpers.py`` wraps
        # this same call for the rest of the image suite.
        pixels = distinct_inks(image)
        assert pixels.issubset(set(rq.SPECTRA6.values())), (
            f"{theme}: off-palette colours {pixels - set(rq.SPECTRA6.values())}"
        )


class TestCustomFrameCompositionPaints:
    """Custom frames must compose something beyond a bare quote on a ground."""

    @staticmethod
    def _helpers(theme):
        return [
            name
            for name in dir(rq)
            if re.fullmatch(rf"_{theme}_paint_[a-z_0-9]+", name)
            and callable(getattr(rq, name))
        ]

    @pytest.mark.parametrize("theme", FRAME_THEMES_WITH_HELPERS)
    def test_frame_declares_paint_helpers(self, theme):
        """Fence the naming convention the neutering test depends on.

        Without this, renaming ``_questline_paint_sky`` to
        ``_questline_sky`` would empty the neuter set and turn the test below
        into a vacuous pass — the failure mode where a regression test quietly
        stops testing anything.
        """
        assert self._helpers(theme), (
            f"{theme}: no _{theme}_paint_* helpers found. Either the frame was "
            "refactored away from the convention (update _helpers and this "
            "list together) or the theme no longer has a custom frame."
        )

    @pytest.mark.parametrize("theme", FRAME_THEMES_WITH_HELPERS)
    def test_frame_composition_changes_the_canvas(self, theme, monkeypatch):
        with_frame = _render(theme)
        for name in self._helpers(theme):
            monkeypatch.setattr(rq, name, _noop)
        bare = _render(theme)

        total, _ = _changed_pixel_counts(with_frame, bare)
        assert total >= MIN_FRAME_PIXELS, (
            f"{theme}: neutering every _{theme}_paint_* helper changed only "
            f"{total} px (expected >= {MIN_FRAME_PIXELS}). The frame's "
            "composition is not actually being painted."
        )


class TestThemeDecorationRegistry:
    """Keep the decoration registries honest as themes are added."""

    def test_every_theme_is_border_framed_or_deliberately_plain(self):
        """A new theme must land in exactly one of three buckets.

        The registration checklist (THEMES / THEME_ORDER / THEME_FONTS /
        THEME_SATURATION / run_clock argparse choices) is already fenced
        elsewhere, but none of those fences notice a theme that registers a
        palette and then ships no decoration — which is how a half-finished
        theme reaches the rotation looking like ``default`` in a different
        colour.
        """
        for theme in sorted(rq.THEMES):
            buckets = [
                theme in rq._BORDER_PAINTERS,
                theme in CUSTOM_FRAME_THEMES,
                theme in UNDECORATED_THEMES,
            ]
            assert sum(buckets) == 1, (
                f"{theme}: expected exactly one of border painter / custom "
                f"frame / deliberately-plain, got {buckets}. Register the "
                "painter in _BORDER_PAINTERS, add the theme to "
                "CUSTOM_FRAME_THEMES, or add it to UNDECORATED_THEMES with a "
                "note on why it ships bare."
            )

    def test_custom_frame_list_matches_render_dispatch(self):
        """``CUSTOM_FRAME_THEMES`` must mirror ``render``'s dispatch ladder.

        The list is hand-maintained so adding a frame is a conscious act; this
        reads the dispatch branches straight out of the source so the two
        cannot drift apart silently.
        """
        source = inspect.getsource(rq.render)
        dispatched = set(re.findall(r'if theme == "([a-z_0-9]+)":\s*\n\s*return render_', source))
        assert dispatched == set(CUSTOM_FRAME_THEMES), (
            "render's custom-frame dispatch and CUSTOM_FRAME_THEMES disagree: "
            f"only in render={dispatched - set(CUSTOM_FRAME_THEMES)}, "
            f"only in list={set(CUSTOM_FRAME_THEMES) - dispatched}"
        )

    def test_border_painters_are_registered_under_their_theme_name(self):
        """``_BORDER_PAINTERS`` keys must be real themes.

        A typoed key is invisible at runtime — ``_paint_theme_border`` does a
        ``.get()`` and silently paints nothing.
        """
        unknown = set(rq._BORDER_PAINTERS) - set(rq.THEMES)
        assert not unknown, f"_BORDER_PAINTERS keys are not registered themes: {unknown}"
