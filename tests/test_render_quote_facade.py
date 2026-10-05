"""The ``render_quote`` package facade (issue #335).

``render_quote`` is a package whose code lives in submodules, while tests and
scripts still read and patch ``render_quote.X``. ``_facade`` makes reads resolve
in the submodule that binds a name and sends writes there too, or refuses them.
These tests pin both halves. A patch that quietly lands on the package
namespace, where no code reads it, is the failure the facade exists to prevent.
"""

from __future__ import annotations

import subprocess
import sys
import types
from unittest import mock

import pytest

from idle_hours import render_quote as rq
from idle_hours.render_quote import _facade, _monolith, fonts


class TestReads:
    def test_names_resolve_in_the_submodule(self):
        assert rq.render is _monolith.render
        assert rq.THEMES is _monolith.THEMES

    def test_reads_are_live_after_the_code_rebinds_a_global(self, monkeypatch):
        """The renderer rebinds some globals itself (latches, caches); a copy
        taken at import would go stale."""
        monkeypatch.setattr(fonts, "_FONT_FALLBACK_WARNED", "rebound-in-submodule")
        assert rq._FONT_FALLBACK_WARNED == "rebound-in-submodule"

    def test_dir_lists_submodule_names(self):
        """The decoration fence finds painters by scanning ``dir(rq)``."""
        names = dir(rq)
        assert "render" in names
        assert any(name.startswith("_tarot_paint_") for name in names)

    def test_unknown_name_is_an_attribute_error(self):
        with pytest.raises(AttributeError):
            rq.no_such_name_anywhere  # noqa: B018

    def test_base_dir_still_names_the_idle_hours_package(self):
        assert (rq.BASE_DIR / "fonts").is_dir()
        assert (rq.BASE_DIR / "assets").is_dir()


class TestWrites:
    def test_monkeypatch_reaches_the_code_and_is_undone(self, monkeypatch):
        original = _monolith._diags_system_info
        monkeypatch.setattr(rq, "_diags_system_info", lambda: "patched")
        assert _monolith._diags_system_info() == "patched"
        monkeypatch.undo()
        assert _monolith._diags_system_info is original
        assert "_diags_system_info" not in vars(rq), "the patch must not leave a shadow on the package"

    def test_mock_patch_object_round_trips(self):
        """``patch.object`` restores a non-local attribute by delete then set."""
        original = _monolith._diags_system_info
        with mock.patch.object(rq, "_diags_system_info", return_value={}):
            assert _monolith._diags_system_info() == {}
        assert _monolith._diags_system_info is original

    def test_mock_patch_by_dotted_path(self):
        original = _monolith.render
        with mock.patch("idle_hours.render_quote.render") as fake:
            assert _monolith.render is fake
        assert _monolith.render is original

    def test_plain_assignment_is_forwarded(self):
        original = _monolith._diags_system_info
        try:
            rq._diags_system_info = lambda: "assigned"
            assert _monolith._diags_system_info() == "assigned"
        finally:
            rq._diags_system_info = original
        assert _monolith._diags_system_info is original

    def test_writing_a_name_no_submodule_binds_raises(self):
        with pytest.raises(AttributeError, match="no submodule binds"):
            rq.no_such_name_anywhere = 1


class TestAmbiguousNames:
    """Once code is split, a name bound in two submodules can't be patched via the package."""

    @pytest.fixture
    def package(self, monkeypatch):
        pkg = types.ModuleType("fakepkg")
        first = types.ModuleType("fakepkg.first")
        second = types.ModuleType("fakepkg.second")
        first.shared = second.shared = "same object"
        first.only_here = 1
        monkeypatch.setitem(sys.modules, "fakepkg", pkg)
        _facade.install("fakepkg", (first, second))
        return pkg, first, second

    def test_ambiguous_write_names_every_owner(self, package):
        pkg, _first, _second = package
        with pytest.raises(AttributeError, match="fakepkg.first, fakepkg.second"):
            pkg.shared = "patched"

    def test_ambiguous_read_comes_from_the_first_owner(self, package):
        pkg, first, _second = package
        assert pkg.shared is first.shared

    def test_single_owner_write_is_forwarded(self, package):
        pkg, first, _second = package
        pkg.only_here = 2
        assert first.only_here == 2

    def test_import_system_can_attach_submodules(self, package):
        pkg, *_ = package
        child = types.ModuleType("fakepkg.child")
        pkg.child = child
        assert vars(pkg)["child"] is child


def test_python_dash_m_runs_the_renderer():
    """``run_clock`` launches ``python -m idle_hours.render_quote``."""
    result = subprocess.run(
        [sys.executable, "-m", "idle_hours.render_quote", "--help"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--time" in result.stdout
