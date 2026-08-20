"""Direct tests for ``path_resolution.resolve_input_path``.

The function had no unit test: its own docstring pointed at two *caller*
regression tests instead
(``test_run_clock.py::TestParseArgsBasic::test_main_persists_resolved_output_back_to_args``
and ``test_web_server.py::TestOutputPathAlignment``). Those pin that callers
route through it, not that its four branches behave — and a mutation probe
confirmed the branch that matters least often is the one nothing covers: the
bundled fallback is the single uncovered line in the module.

That branch is load-bearing. It is what lets the shipped
``config.toml.defaults`` keep portable relative strings like
``render_script = "render_quote.py"`` and still resolve to the file inside the
installed package no matter what the operator's CWD is. Break it and every
appliance running the shipped config stops finding its own renderer, with a
FileNotFoundError naming a path that looks correct.

The CWD-vs-BASE_DIR asymmetry here is deliberate and easy to "tidy" wrongly
(outputs must be CWD-only because BASE_DIR now points inside site-packages;
inputs prefer CWD but fall back to bundled). These tests state the contract
directly so a refactor has something to fail against.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from idle_hours.path_resolution import resolve_input_path


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A CWD and a separate bundled dir, each holding a same-named file.

    Same basename in both is the interesting case: it is the only way to
    observe which of the two the function actually prefers.
    """
    cwd = tmp_path / "workdir"
    bundled = tmp_path / "site-packages" / "idle_hours"
    cwd.mkdir(parents=True)
    bundled.mkdir(parents=True)
    monkeypatch.chdir(cwd)
    return cwd, bundled


class TestAbsolutePaths:
    def test_absolute_path_passes_through_untouched(self, tree):
        cwd, bundled = tree
        target = bundled / "renderer.py"
        target.write_text("bundled")
        assert resolve_input_path(str(target), bundled) == target

    def test_absolute_path_is_returned_even_when_missing(self, tree):
        """An operator who typed an absolute path gets that path back.

        Rewriting it would produce an error message naming a file they never
        asked for; the pre-flight check is what reports the miss.
        """
        cwd, bundled = tree
        missing = bundled / "nope.py"
        assert resolve_input_path(str(missing), bundled) == missing

    def test_absolute_path_ignores_the_bundled_dir(self, tree):
        """An absolute path must never be re-anchored under ``base_dir``."""
        cwd, bundled = tree
        other = cwd / "elsewhere.py"
        other.write_text("cwd")
        assert resolve_input_path(str(other), bundled) == other


class TestRelativePaths:
    def test_cwd_file_wins_over_bundled_file(self, tree):
        """Requirement 2 of the module contract: an operator who drops their
        own ``./my_renderer.py`` in the working tree gets *their* file."""
        cwd, bundled = tree
        (cwd / "render_quote.py").write_text("operator override")
        (bundled / "render_quote.py").write_text("bundled")
        assert resolve_input_path("render_quote.py", bundled) == cwd / "render_quote.py"

    def test_falls_back_to_bundled_when_cwd_has_no_match(self, tree):
        """Requirement 1: the shipped ``config.toml.defaults`` keeps relative
        strings and still resolves inside the installed package."""
        cwd, bundled = tree
        (bundled / "render_quote.py").write_text("bundled")
        assert resolve_input_path("render_quote.py", bundled) == bundled / "render_quote.py"

    def test_missing_everywhere_returns_the_cwd_candidate(self, tree):
        """Neither location has it: report the path the operator typed.

        Returning the bundled translation instead would make the pre-flight
        error message point into site-packages for a filename the operator
        wrote relative to their own tree.
        """
        cwd, bundled = tree
        assert resolve_input_path("ghost.py", bundled) == cwd / "ghost.py"

    def test_nested_relative_path_resolves_under_cwd(self, tree):
        cwd, bundled = tree
        nested = cwd / "scripts" / "custom.py"
        nested.parent.mkdir()
        nested.write_text("operator")
        assert resolve_input_path("scripts/custom.py", bundled) == nested

    def test_nested_relative_path_falls_back_under_base_dir(self, tree):
        cwd, bundled = tree
        nested = bundled / "assets" / "goodnight.png"
        nested.parent.mkdir()
        nested.write_bytes(b"png")
        assert resolve_input_path("assets/goodnight.png", bundled) == nested

    def test_dot_prefixed_relative_path_is_cwd_relative(self, tree):
        """``./x`` and ``x`` must resolve identically — the shipped configs use
        the bare form, operators habitually type the dotted one."""
        cwd, bundled = tree
        (cwd / "mine.py").write_text("operator")
        assert resolve_input_path("./mine.py", bundled) == resolve_input_path("mine.py", bundled)

    def test_directory_counts_as_an_existing_candidate(self, tree):
        """``Path.exists()`` is true for directories.

        Worth stating: ``--quiet-image`` pointed at a directory resolves here
        rather than falling through to the bundled copy, so the failure the
        operator sees comes from the image loader naming their directory —
        not a confusing "bundled goodnight.png" substitution.
        """
        cwd, bundled = tree
        (cwd / "assets").mkdir()
        (bundled / "assets").mkdir()
        assert resolve_input_path("assets", bundled) == cwd / "assets"


class TestReturnContract:
    def test_accepts_a_path_object_as_well_as_a_string(self, tree):
        """Callers pass ``args.render_script`` (str) and occasionally a Path."""
        cwd, bundled = tree
        (cwd / "mine.py").write_text("x")
        assert resolve_input_path(Path("mine.py"), bundled) == cwd / "mine.py"

    def test_always_returns_an_absolute_path(self, tree):
        """Every branch must return something absolute.

        Downstream this value is handed to ``subprocess.run`` and to Pillow;
        a relative leak would re-resolve against whatever CWD those inherit.
        """
        cwd, bundled = tree
        (cwd / "here.py").write_text("x")
        (bundled / "there.py").write_text("x")
        for value in ("here.py", "there.py", "nowhere.py", str(cwd / "here.py")):
            assert resolve_input_path(value, bundled).is_absolute(), value

    def test_expands_a_user_home_prefix(self, tree, monkeypatch, tmp_path):
        """``~`` is expanded before the CWD/bundled decision.

        Operators write ``--quiet-image ~/frames/night.png`` in unit files;
        without expansion that becomes a literal ``./~`` directory lookup that
        silently falls through to the bundled default.
        """
        cwd, bundled = tree
        home = tmp_path / "home"
        (home / "frames").mkdir(parents=True)
        target = home / "frames" / "night.png"
        target.write_bytes(b"png")
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        assert resolve_input_path("~/frames/night.png", bundled) == target
