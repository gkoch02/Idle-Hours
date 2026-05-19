"""Tests for ``idle_hours_cli`` — the unified CLI dispatcher.

These tests pin three properties:

* ``--help`` and an unknown subcommand produce sensible output without
  importing every backing module (the lazy-import contract).
* Every registered subcommand resolves to a real module with a callable
  ``main`` (catch packaging drift early).
* Dispatch correctly rewrites ``sys.argv`` so the backing module's own
  argparse sees a clean invocation.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import patch

import pytest

import idle_hours_cli


def _fake_module(main_fn):
    """Build a fake module-like object with a ``main`` attribute.

    Using ``types.SimpleNamespace`` (not ``type("M", (), {...})()``) so the
    callable isn't bound as a method — a lambda assigned as a class attr
    becomes an unbound method via descriptor protocol and would receive
    ``self`` as a surprise first arg.
    """
    return types.SimpleNamespace(main=main_fn)


class TestHelpAndDispatch:
    def test_no_argv_prints_help(self, capsys):
        rc = idle_hours_cli.main([])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Usage: idle-hours" in out
        assert "Subcommands:" in out
        # A handful of expected subcommands should appear.
        for sub in ("run", "render", "pick", "health", "bake"):
            assert sub in out

    def test_help_flag(self, capsys):
        rc = idle_hours_cli.main(["--help"])
        assert rc == 0
        assert "Subcommands:" in capsys.readouterr().out

    def test_help_subcommand_word(self, capsys):
        rc = idle_hours_cli.main(["help"])
        assert rc == 0
        assert "Subcommands:" in capsys.readouterr().out

    def test_version_flag(self, capsys):
        rc = idle_hours_cli.main(["--version"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "idle-hours" in out

    def test_unknown_subcommand_returns_2(self, capsys):
        rc = idle_hours_cli.main(["bogus-subcommand"])
        err = capsys.readouterr().err
        assert rc == 2
        assert "unknown subcommand" in err

    def test_dispatch_calls_backing_main(self):
        """Dispatch should import the backing module lazily and call its main()."""
        # We patch importlib so we don't actually run the heavy backing module;
        # the lazy-import contract is exactly what we want to verify.
        fake_module = _fake_module(lambda: 0)
        with patch("idle_hours_cli.importlib.import_module", return_value=fake_module) as imp:
            rc = idle_hours_cli.main(["pick", "--time", "03:00"])
        assert rc == 0
        # SUBCOMMANDS["pick"][0] is "pick_quote"
        imp.assert_called_once_with("pick_quote")

    def test_dispatch_rewrites_sys_argv_for_backing_main(self):
        """The backing module's parse_args() reads sys.argv directly; we have
        to rewrite it so it sees a clean ``[script_name, *flags]`` invocation."""
        captured: dict = {}

        def fake_main():
            captured["argv"] = list(sys.argv)
            return 0

        fake_module = _fake_module(fake_main)
        original_argv = sys.argv
        try:
            with patch("idle_hours_cli.importlib.import_module", return_value=fake_module):
                idle_hours_cli.main(["render", "--time", "12:00", "--mode", "debug"])
            # argv[0] becomes the umbrella + subcommand name; the rest is
            # forwarded verbatim.
            assert captured["argv"][0] == "idle-hours render"
            assert captured["argv"][1:] == ["--time", "12:00", "--mode", "debug"]
        finally:
            sys.argv = original_argv

    def test_main_propagates_int_return(self):
        with patch("idle_hours_cli.importlib.import_module", return_value=_fake_module(lambda: 42)):
            rc = idle_hours_cli.main(["health"])
        assert rc == 42

    def test_main_normalises_none_return_to_zero(self):
        """Many existing scripts return None (success). Don't surface that as
        ``raise SystemExit(None)`` — normalise to 0."""
        with patch("idle_hours_cli.importlib.import_module", return_value=_fake_module(lambda: None)):
            rc = idle_hours_cli.main(["health"])
        assert rc == 0

    def test_missing_main_attribute_raises_systemexit(self):
        """A SUBCOMMANDS pointer to a module without a main() is a packaging
        bug; we surface it loudly rather than crashing with AttributeError."""
        broken = types.SimpleNamespace()  # no .main attribute
        with patch("idle_hours_cli.importlib.import_module", return_value=broken):
            with pytest.raises(SystemExit):
                idle_hours_cli.main(["pick"])


class TestSubcommandRegistry:
    def test_every_subcommand_maps_to_real_module(self):
        """Every registered subcommand must point at an importable module
        with a callable ``main``. Catches drift between the SUBCOMMANDS
        registry and the actual files on disk."""
        import importlib
        for sub, (module_name, _description) in idle_hours_cli.SUBCOMMANDS.items():
            module = importlib.import_module(module_name)
            assert callable(getattr(module, "main", None)), (
                f"subcommand {sub!r} -> module {module_name!r} has no callable main()"
            )

    def test_subcommand_names_kebab_case(self):
        """Subcommand names should be CLI-friendly: lowercase + dashes only.
        Pinning so a future addition doesn't accidentally use snake_case
        (which would make ``idle-hours contact_sheet`` necessary instead of
        the more natural ``idle-hours contact-sheet``)."""
        import re
        valid = re.compile(r"^[a-z][a-z0-9-]*$")
        for sub in idle_hours_cli.SUBCOMMANDS:
            assert valid.match(sub), f"subcommand {sub!r} is not kebab-case"


class TestEntryPoint:
    def test_pyproject_registers_console_script(self):
        """``pip install`` should produce an ``idle-hours`` command. Verify the
        entry point is declared in pyproject.toml so the wheel ships it."""
        import tomllib  # type: ignore[import-not-found]
        from pathlib import Path
        repo_root = Path(__file__).resolve().parent.parent
        with open(repo_root / "pyproject.toml", "rb") as handle:
            config = tomllib.load(handle)
        scripts = config.get("project", {}).get("scripts", {})
        assert scripts.get("idle-hours") == "idle_hours_cli:main", (
            "pyproject.toml must declare [project.scripts] idle-hours = 'idle_hours_cli:main'; "
            "without it `pip install` won't register the umbrella command on the appliance."
        )
