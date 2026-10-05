"""The theme registry built from each module's ``SPEC`` (issue #335).

``registry`` replaced four tables kept by hand (``_BORDER_PAINTERS``,
``_FRAME_RENDERERS``, ``_DEBUG_LABEL_RIGHT_INSET`` and ``render``'s local
``_CLEAR_RECT_PADS``) plus the by-name ``if``/``elif`` ladder in ``render``.
These tests pin the registry's own rules. (A snapshot of the old tables proved
the migration in #360 and was retired with the facade's forwarding.)
"""

from __future__ import annotations

import types

import pytest

from idle_hours import render_quote as rq
from idle_hours.render_quote import registry
from idle_hours.render_quote.spec import BorderSpec, FrameSpec


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
