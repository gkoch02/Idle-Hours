"""Packaging-boundary tests.

These guard two install-time invariants that are otherwise invisible to a
``pip install -e .`` developer setup (which puts the repo on ``sys.path``
regardless of how ``setuptools.packages.find`` is configured):

1. **The wheel ships every ``idle_hours/*.py`` module plus the bundled
   static assets.** Setuptools ships exactly what ``packages.find`` /
   ``package-data`` declare — a module on disk that doesn't end up in the
   wheel silently breaks the installed app. Caught here at ``pytest`` time
   instead of at deploy time.

2. **Importing any production module never pulls hardware deps**
   (``gpiozero`` / ``inky`` / ``RPi.GPIO``) **into ``sys.modules``.** Today
   every such import is locally scoped inside a function body. A refactor
   that hoists one to module level would silently break ``pip install`` on
   non-Pi hosts (and the import-time of every pipeline script). Subprocess
   isolation is required because once any test in the same interpreter
   imports ``idle_hours.run_clock``, in-process ``sys.modules`` is already
   populated.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "idle_hours"

# Hardware-dep namespaces that must NEVER appear in ``sys.modules`` after
# importing any Idle Hours production module on a non-Pi host.
FORBIDDEN_HARDWARE_NAMESPACES = ("gpiozero", "inky", "RPi")


def _package_modules_on_disk() -> set[str]:
    """Every importable ``idle_hours.<name>`` excluding the package marker."""
    return {
        path.stem
        for path in PACKAGE_ROOT.glob("*.py")
        if path.stem != "__init__"
    }


class TestPackageDeclaration:
    """Guard the [tool.setuptools.packages.find] + package-data shape."""

    def test_pyproject_declares_idle_hours_package(self):
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        find_cfg = pyproject["tool"]["setuptools"]["packages"]["find"]
        assert "idle_hours*" in find_cfg["include"], (
            "[tool.setuptools.packages.find] must include 'idle_hours*' so "
            "setuptools picks up the package on `pip install`."
        )

    def test_package_data_ships_static_assets(self):
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        pkg_data = pyproject["tool"]["setuptools"]["package-data"]["idle_hours"]
        # The three asset trees the renderer / curator UI / corpus need at
        # runtime. Without these the wheel installs but the CLI is unusable.
        for pattern in ("assets/**/*", "fonts/**/*", "web/**/*"):
            assert pattern in pkg_data, (
                f"package-data['idle_hours'] is missing {pattern!r} — the "
                "wheel will install without the bundled static assets."
            )

    def test_console_script_targets_package(self):
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        scripts = pyproject["project"]["scripts"]
        assert scripts["idle-hours"] == "idle_hours.idle_hours_cli:main", (
            "Console script target drifted; check [project.scripts] in pyproject.toml."
        )


class TestNoOptionalDepLeakage:
    """Importing a production module on a non-Pi host must not pull hardware
    deps into sys.modules. Each module is imported in a fresh subprocess so
    the assertion is independent of test ordering."""

    @pytest.mark.parametrize("module_name", sorted(_package_modules_on_disk()))
    def test_module_import_does_not_pull_hardware_deps(self, module_name):
        qualified = f"idle_hours.{module_name}"
        probe = (
            f"import {qualified}; "
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
            f"importing {qualified!r} in a fresh subprocess failed:\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )

        leaked = json.loads(result.stdout.strip() or "[]")
        assert leaked == [], (
            f"importing {qualified!r} pulled hardware deps into sys.modules: "
            f"{leaked}. All gpiozero/inky/RPi imports must stay inside function "
            "bodies so non-Pi installs work."
        )
