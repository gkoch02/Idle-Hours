"""The theme registry built from each module's ``SPEC`` (issue #335).

``registry`` replaced four tables kept by hand (``_BORDER_PAINTERS``,
``_FRAME_RENDERERS``, ``_DEBUG_LABEL_RIGHT_INSET`` and ``render``'s local
``_CLEAR_RECT_PADS``) plus the by-name ``if``/``elif`` ladder in ``render``.
``TestMatchesThePreRegistryTables`` pins the derived tables to those literals
as they stood on ``main`` before the change; it is a migration check, to be
retired with the facade in the split's final PR. The other classes pin the
registry's own rules.
"""

from __future__ import annotations

import types

import pytest

from idle_hours import render_quote as rq
from idle_hours.render_quote import registry
from idle_hours.render_quote.spec import BorderSpec, FrameSpec

# The pre-registry tables, as they stood on main at b142d14.
OLD_BORDER_PAINTERS = {
    "alchemy": "draw_alchemy_border", "anna_atkins": "draw_anna_atkins_border", "atomic": "draw_atomic_border",
    "bauhaus": "draw_bauhaus_border", "betweenus": "draw_betweenus_border", "betweenus_dark": "draw_betweenus_border",
    "blueprint": "draw_blueprint_border", "carcosa": "draw_carcosa_border", "cartograph": "draw_cartograph_border",
    "chalkboard": "draw_chalkboard_border", "chanbara": "draw_chanbara_border", "circuit": "draw_circuit_border",
    "comic": "draw_comic_corner_stripes", "deco": "draw_deco_border", "dispatch": "draw_dispatch_border",
    "fillmore": "draw_fillmore_border", "firmament": "draw_firmament_border", "glacier": "draw_glacier_border",
    "gothic": "draw_gothic_border", "grimdark": "draw_grimdark_border", "grimoire": "draw_grimoire_border",
    "herbarium": "draw_herbarium_border", "illuminated": "draw_illuminated_border", "kanagawa": "draw_kanagawa_border",
    "lcars": "draw_lcars_border", "letter": "draw_letter_border", "marker": "draw_marker_border",
    "mucha": "draw_mucha_border", "newsprint": "draw_newsprint_border", "nightvision": "draw_nightvision_border",
    "placard": "draw_placard_border", "risograph": "draw_risograph_border", "roman": "draw_roman_border",
    "saloon": "draw_saloon_border", "scholar": "draw_scholar_border", "swiss": "draw_swiss_border",
    "synoptic": "draw_synoptic_border",
}
OLD_FRAME_THEMES = {
    "abyssal", "astrarium", "atropos", "autochrome", "bakelite", "beksinski", "biomech", "bosch", "cardcatalog",
    "chrono", "codex", "control", "culture", "daguerreotype", "diags", "dsky", "escritoire", "expanse",
    "expedition", "furies", "goya", "hades", "hal", "hitchhiker", "intaglio", "izakaya", "lieder", "lumon",
    "marquee", "metro", "nocturne", "oblivion", "observation", "orbital", "outrun", "photo", "plaque", "pride",
    "pulp", "questline", "sampler", "saros", "semiotic", "tarot", "trisolaris", "vhs", "vinyl", "vitrail",
    "witcher", "yorha",
}
OLD_CLEAR_RECT_PADS = {
    "betweenus": (28, 18, 24), "betweenus_dark": (28, 18, 24), "blueprint": (2, 2, 2), "cartograph": (22, 12, 12),
    "circuit": (16, 10, 10), "kanagawa": (14, 6, 6), "letter": (26, 18, 18), "risograph": (20, 14, 14),
    "synoptic": (20, 14, 14),
}
# The ladder passed ``time_str`` to these.
OLD_TIME_THEMES = {"synoptic", "betweenus", "betweenus_dark"}
OLD_DEBUG_LABEL_RIGHT_INSET = {
    "alchemy": 76, "bauhaus": 38, "betweenus": 144, "betweenus_dark": 144, "blueprint": 34, "carcosa": 46,
    "circuit": 46, "glacier": 37, "gothic": 30, "grimoire": 50, "herbarium": 24, "illuminated": 28, "marker": 44,
    "risograph": 44, "roman": 38, "saloon": 44,
}


class TestMatchesThePreRegistryTables:
    def test_border_painters(self):
        assert {t: fn.__name__ for t, fn in rq._BORDER_PAINTERS.items()} == OLD_BORDER_PAINTERS

    def test_frame_renderers(self):
        assert set(rq._FRAME_RENDERERS) == OLD_FRAME_THEMES
        for theme, fn in rq._FRAME_RENDERERS.items():
            assert fn.__name__ == f"render_{theme}_frame"

    def test_clear_rect_pads(self):
        pads = {t: s.clear_rect_pad for t, s in rq.BORDER_SPECS.items() if s.clear_rect_pad is not None}
        assert pads == OLD_CLEAR_RECT_PADS

    def test_time_is_passed_to_the_same_themes(self):
        assert {t for t, s in rq.BORDER_SPECS.items() if s.wants_time} == OLD_TIME_THEMES

    def test_debug_label_insets(self):
        assert dict(rq._DEBUG_LABEL_RIGHT_INSET) == OLD_DEBUG_LABEL_RIGHT_INSET

    def test_only_blueprint_has_its_own_knockout(self):
        assert {t for t, s in rq.BORDER_SPECS.items() if s.knockout is not None} == {"blueprint"}


class TestBuildRegistry:
    def _module(self, name, spec=None):
        module = types.ModuleType(f"themes.{name}")
        if spec is not None:
            module.SPEC = spec
        return module

    def test_every_theme_is_claimed_once(self):
        claimed = set(rq.BORDER_SPECS) | set(rq.FRAME_SPECS)
        assert not set(rq.BORDER_SPECS) & set(rq.FRAME_SPECS)
        assert claimed | registry.PLAIN_THEMES == set(rq.THEMES)
        assert not claimed & registry.PLAIN_THEMES

    def test_a_valid_set_builds(self):
        built = registry.build_registry(
            [self._module("a", BorderSpec(themes=("a",), paint=print)), self._module("b", FrameSpec(themes=("b",), render=print))],
            {"a", "b", "default", "dark"},
        )
        assert set(built.borders) == {"a"} and set(built.frames) == {"b"}

    @pytest.mark.parametrize(("modules", "names", "message"), [
        (lambda m: [m("a")], {"default", "dark"}, "has no BorderSpec or FrameSpec SPEC"),
        (lambda m: [m("a", BorderSpec(themes=("x",), paint=print)), m("b", FrameSpec(themes=("x",), render=print))],
         {"x", "default", "dark"}, "x is claimed by both"),
        (lambda m: [m("a", BorderSpec(themes=("typo",), paint=print))], {"default", "dark"}, "typo, which is not in THEMES"),
        (lambda m: [m("a", BorderSpec(themes=("dark",), paint=print))], {"default", "dark"}, "dark, which is a plain theme"),
        (lambda m: [], {"orphan", "default", "dark"}, "themes with no SPEC and not plain: orphan"),
    ])
    def test_an_inconsistent_set_fails_naming_the_problem(self, modules, names, message):
        with pytest.raises(RuntimeError, match=message):
            registry.build_registry(modules(self._module), names)

    def test_the_old_table_names_are_read_only(self):
        """A patch on a view would land where ``render`` never looks, so it must raise."""
        with pytest.raises(TypeError):
            rq._BORDER_PAINTERS["kanagawa"] = print
        with pytest.raises(TypeError):
            rq._FRAME_RENDERERS["vinyl"] = print


class TestBorderSpec:
    def test_knockout_options_need_a_pad(self):
        with pytest.raises(ValueError, match="need a clear_rect_pad|needs a clear_rect_pad"):
            BorderSpec(themes=("a",), paint=print, wants_time=True)
        with pytest.raises(ValueError):
            BorderSpec(themes=("a",), paint=print, knockout=print)

    def test_a_spec_must_name_a_theme(self):
        with pytest.raises(ValueError):
            BorderSpec(themes=(), paint=print)
        with pytest.raises(ValueError):
            FrameSpec(themes=(), render=print)

    @pytest.mark.parametrize(("spec_kwargs", "expected"), [
        ({}, ("paint", {})),
        ({"clear_rect_pad": (1, 1, 1)}, ("paint", {"clear_rect": "RECT"})),
        ({"clear_rect_pad": (1, 1, 1), "wants_time": True}, ("paint", {"clear_rect": "RECT", "time_str": "08:55"})),
        ({"clear_rect_pad": (1, 1, 1), "knockout": "KNOCKOUT"}, ("knockout", {"clear_rect": "RECT"})),
    ])
    def test_the_knockout_pass_forwards_what_the_spec_asks_for(self, spec_kwargs, expected):
        calls = []

        def recorder(label):
            return lambda image, colors, **kwargs: calls.append((label, kwargs))

        if spec_kwargs.get("knockout") == "KNOCKOUT":
            spec_kwargs = {**spec_kwargs, "knockout": recorder("knockout")}
        spec = BorderSpec(themes=("a",), paint=recorder("paint"), **spec_kwargs)
        spec.paint_knockout("IMAGE", {}, "RECT", "08:55")
        assert calls == [expected]
