"""Packaging-boundary tests.

These guard two install-time invariants that are otherwise invisible to a
``pip install -e .`` developer setup (which puts the repo on ``sys.path``
regardless of what's listed in ``[tool.setuptools] py-modules``):

1. **Every top-level production ``*.py`` module is listed in ``py-modules``.**
   Setuptools ships exactly what ``py-modules`` lists into the wheel — a
   module that exists on disk but is missing from the list silently breaks
   the installed wheel (and the appliance won't start). Caught here at
   ``pytest`` time instead of at deploy time.

2. **Importing any production module never pulls hardware deps**
   (``gpiozero`` / ``inky`` / ``RPi.GPIO``) **into ``sys.modules``.** Today
   every such import is locally scoped inside a function body. A refactor
   that hoists one to module level would silently break ``pip install`` on
   non-Pi hosts (and the import-time of every pipeline script). Subprocess
   isolation is required because once any test in the same interpreter
   imports ``run_clock``, in-process ``sys.modules`` is already populated.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Top-level files that exist on disk but are deliberately not Python modules
# to ship in the wheel. Keep this list short and explicit — anything not
# listed here must appear in ``py-modules``.
EXCLUDED_TOP_LEVEL = frozenset({
    # Test helpers / packaging — never imported as a runtime module.
    "setup",  # if anyone ever adds a vestigial setup.py
    "conftest",  # pytest discovers these implicitly under ``tests/``
})

# Hardware-dep namespaces that must NEVER appear in ``sys.modules`` after
# importing any Idle Hours production module on a non-Pi host.
FORBIDDEN_HARDWARE_NAMESPACES = ("gpiozero", "inky", "RPi")


def _pyproject_py_modules() -> list[str]:
    pyproject = REPO_ROOT / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return list(data["tool"]["setuptools"]["py-modules"])


def _top_level_modules_on_disk() -> set[str]:
    return {
        path.stem
        for path in REPO_ROOT.glob("*.py")
        if path.stem not in EXCLUDED_TOP_LEVEL
    }


class TestPyModulesList:
    """Guard the ``[tool.setuptools] py-modules`` list against drift."""

    def test_py_modules_covers_top_level_modules(self):
        on_disk = _top_level_modules_on_disk()
        listed = set(_pyproject_py_modules())

        missing = sorted(on_disk - listed)
        extra = sorted(listed - on_disk)

        assert not missing and not extra, (
            "pyproject.toml [tool.setuptools] py-modules is out of sync with "
            "top-level *.py files in the repo root.\n"
            f"  Missing from py-modules (will not ship in the wheel): {missing}\n"
            f"  Listed but not on disk (will fail wheel build):       {extra}"
        )

    def test_py_modules_list_is_sorted_and_deduped(self):
        listed = _pyproject_py_modules()
        assert listed == sorted(listed), (
            "py-modules should be alphabetically sorted so diffs stay small "
            "when modules are added; got "
            f"{listed!r}"
        )
        assert len(listed) == len(set(listed)), "py-modules contains duplicates"


class TestNoOptionalDepLeakage:
    """Importing a production module on a non-Pi host must not pull hardware
    deps into sys.modules. Each module is imported in a fresh subprocess so
    the assertion is independent of test ordering."""

    @pytest.mark.parametrize("module_name", sorted(_top_level_modules_on_disk()))
    def test_module_import_does_not_pull_hardware_deps(self, module_name):
        # Run the import in a subprocess with the repo root on PYTHONPATH so
        # the module resolves the same way it will inside the installed wheel
        # (top-level, no package qualifier).
        probe = (
            f"import {module_name}; "
            "import json, sys; "
            f"forbidden = {FORBIDDEN_HARDWARE_NAMESPACES!r}; "
            "leaked = sorted(m for m in sys.modules if m.split('.', 1)[0] in forbidden); "
            "print(json.dumps(leaked))"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, (
            f"importing {module_name!r} in a fresh subprocess failed:\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )

        leaked = json.loads(result.stdout.strip() or "[]")
        assert leaked == [], (
            f"importing {module_name!r} pulled hardware deps into sys.modules: "
            f"{leaked}. All gpiozero/inky/RPi imports must stay inside function "
            "bodies so non-Pi installs work."
        )
