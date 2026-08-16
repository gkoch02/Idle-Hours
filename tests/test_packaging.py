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

import importlib.metadata
import json
import re
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


class TestReleaseVersion:
    """Guard against release/package-metadata drift.

    The repo shipped v1.0.0 / v1.1.0 / v2.0.0 tags while ``pyproject.toml``
    still declared ``0.1.0``, so every wheel built from those releases
    identified itself as 0.1.0 — installed diagnostics reported the wrong
    release and no package manager could tell the 1.x and 2.x wheels apart.
    The old CLI test only asserted ``"idle-hours" in out``, which passes for
    literally any version string, so the drift was invisible.

    ``pyproject.toml`` is the single source of truth; ``--version`` reads it
    back through ``importlib.metadata``. The CI ``release-version`` job
    additionally fails a ``vX.Y.Z`` tag build whose ref disagrees with it.
    """

    def _declared_version(self) -> str:
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return pyproject["project"]["version"]

    def test_declared_version_is_pep440_release(self):
        declared = self._declared_version()
        assert re.fullmatch(r"\d+\.\d+\.\d+", declared), (
            f"pyproject version {declared!r} is not a plain X.Y.Z release "
            "version; the CI tag check compares it against a vX.Y.Z git tag."
        )

    def test_declared_version_is_not_the_placeholder(self):
        # Explicitly pins the regression: 0.1.0 was the never-updated
        # scaffold default that shipped through three tagged releases.
        assert self._declared_version() != "0.1.0", (
            "pyproject still declares the 0.1.0 scaffold placeholder — bump it "
            "to the release version before tagging."
        )

    def test_installed_metadata_matches_pyproject(self):
        """The installed dist reports what pyproject declares.

        Skipped when the dist isn't installed (bare checkout, no
        ``pip install -e .``) since there is no metadata to compare against.
        """
        try:
            installed = importlib.metadata.version("idle-hours")
        except importlib.metadata.PackageNotFoundError:
            pytest.skip("idle-hours dist not installed; nothing to compare")
        assert installed == self._declared_version(), (
            f"installed metadata {installed!r} != pyproject "
            f"{self._declared_version()!r}. Re-run `pip install -e .` after a "
            "version bump so the console script reports the right release."
        )

    def test_cli_version_flag_reports_the_release_version(self):
        """``idle-hours --version`` must print the real version, not a stub."""
        try:
            expected = importlib.metadata.version("idle-hours")
        except importlib.metadata.PackageNotFoundError:
            pytest.skip("idle-hours dist not installed; --version falls back")

        proc = subprocess.run(
            [sys.executable, "-m", "idle_hours.idle_hours_cli", "--version"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            check=True,
        )
        assert proc.stdout.strip() == f"idle-hours {expected}"


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
