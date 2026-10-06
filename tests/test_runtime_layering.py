"""Fence the runtime import graph: the orchestrator imports its helpers, never the reverse.

``run_clock`` used to re-export its ``runtime_*`` siblings, and those siblings
did a lazy ``import run_clock`` so that tests patching ``run_clock.X`` reached
their call paths (issue #353). The helpers now live in the module that defines
them and are read through it, so a test patches a name where it is defined.
These checks keep the old shape from coming back.
"""
from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "idle_hours"

# The CLI dispatches to run_clock by module name, which is what it is for.
_MAY_IMPORT_RUN_CLOCK = {"idle_hours_cli.py", "run_clock.py"}


def _package_modules() -> list[Path]:
    return sorted(PACKAGE_DIR.rglob("*.py"))


def _imported_modules(tree: ast.AST) -> list[tuple[str, list[str]]]:
    """Every ``(module, names)`` an import statement in ``tree`` binds, nested ones included."""
    found: list[tuple[str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, []) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [alias.name for alias in node.names]
            found.append((node.module, names))
            if node.module == "idle_hours":
                found.extend((f"idle_hours.{name}", []) for name in names)
    return found


class TestRunClockIsTheTopOfTheGraph:
    def test_no_package_module_imports_run_clock(self):
        offenders = []
        for path in _package_modules():
            if path.name in _MAY_IMPORT_RUN_CLOCK:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for module, _names in _imported_modules(tree):
                if module in ("run_clock", "idle_hours.run_clock"):
                    offenders.append(str(path.relative_to(PACKAGE_DIR)))
        assert offenders == [], f"modules importing run_clock: {offenders}"

    def test_run_clock_has_no_reexports(self):
        source = (PACKAGE_DIR / "run_clock.py").read_text(encoding="utf-8")
        assert "noqa: F401" not in source

    def test_the_walk_sees_a_nested_import(self):
        """The check above must catch the lazy in-function form the old code used."""
        tree = ast.parse("def f():\n    from idle_hours import run_clock\n")
        assert ("idle_hours.run_clock", []) in _imported_modules(tree)


class TestHelpersAreReadThroughTheirModule:
    def test_no_render_function_is_imported_by_name(self):
        """A ``from runtime_render import render_now`` binds a second name that a
        patch on ``runtime_render.render_now`` cannot reach. Constants are fine."""
        offenders = []
        for path in _package_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for module, names in _imported_modules(tree):
                if module != "idle_hours.runtime_render":
                    continue
                offenders.extend(
                    f"{path.relative_to(PACKAGE_DIR)}: {name}" for name in names if not name.isupper()
                )
        assert offenders == [], f"read these through the module instead: {offenders}"
