"""The ``render_quote`` package's import layering (issue #335).

The split moves code out of ``_monolith`` into modules that may only import
downward. A module that imports from a higher layer reintroduces the cycles the
split exists to remove, and usually means a helper was filed in the wrong
layer. Every module must be listed in ``LAYERS``, so a new one is placed
deliberately rather than slipping in unchecked.

Theme modules live in the ``themes`` subpackage, above the shared layers and
below ``_monolith``. A theme never imports another theme: code two themes use
belongs in ``themes._shared``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from idle_hours import render_quote as rq

PACKAGE_DIR = Path(rq.__file__).parent

# Lowest first. A module may import only from modules listed before it.
LAYERS = (
    "_paths",
    "clock",
    "palette",
    "theme_tables",
    "fonts",
    "layout",
    "text",
    "primitives",
    "furniture",
    "themes._shared",
    "_monolith",
)

# Package plumbing, not part of the render layers.
PLUMBING = {"__init__", "__main__", "_facade", "themes.__init__"}

THEME_PACKAGE = "themes"


def _modules() -> dict[str, ast.Module]:
    """Every module in the package by dotted name relative to it (``themes._shared``)."""
    modules = {}
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        name = ".".join(path.relative_to(PACKAGE_DIR).with_suffix("").parts)
        if name not in PLUMBING:
            modules[name] = ast.parse(path.read_text(encoding="utf-8"))
    return modules


def _resolve(importer: str, node: ast.ImportFrom) -> set[str]:
    """Package modules one ``from … import`` statement in ``importer`` reaches."""
    if node.level == 0:
        if not (node.module and node.module.startswith("idle_hours.render_quote")):
            return set()
        base: list[str] = []
        module = node.module.removeprefix("idle_hours.render_quote").lstrip(".")
    else:
        base = importer.split(".")[:-node.level]
        if len(base) != len(importer.split(".")) - node.level:
            raise AssertionError(f"{importer}: relative import climbs out of render_quote")
        module = node.module or ""
    if module:
        return {".".join(base + module.split("."))}
    # ``from . import x`` imports submodules (or names) of the package itself.
    return {".".join(base + [alias.name]) for alias in node.names}


def _package_imports(name: str, tree: ast.Module) -> set[str]:
    """Package modules ``name`` imports, by dotted name; a package import counts as its ``__init__``."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for target in _resolve(name, node):
                found.add(target if target != THEME_PACKAGE else "themes.__init__")
    return found


def _is_theme(name: str) -> bool:
    return name.startswith(THEME_PACKAGE + ".") and name not in LAYERS and name not in PLUMBING


def _rank() -> dict[str, int]:
    """Layer rank of every module. Theme modules all share the rank just below ``_monolith``."""
    rank = {name: i for i, name in enumerate(LAYERS)}
    for name in _modules():
        if _is_theme(name):
            rank[name] = rank["_monolith"] - 0.5
    return rank


def test_every_module_has_a_layer():
    unplaced = sorted(name for name in _modules() if name not in LAYERS and not _is_theme(name))
    assert unplaced == [], f"render_quote modules missing from LAYERS: {unplaced}; place them in the layer order"


def test_imports_only_point_downward():
    rank = _rank()
    violations = []
    for name, tree in _modules().items():
        for target in sorted(_package_imports(name, tree)):
            if target in PLUMBING or target not in rank:
                violations.append(f"{name} imports {target}, which is not a render layer")
            elif _is_theme(name) and _is_theme(target):
                violations.append(f"{name} imports {target}: themes never import each other; share via themes._shared")
            elif rank[target] >= rank[name]:
                violations.append(f"{name} (layer {rank[name]}) imports {target} (layer {rank[target]})")
    assert violations == [], "render_quote layering broken:\n  " + "\n  ".join(violations)


def test_relative_imports_resolve_from_subpackages():
    """``from ..palette import x`` in ``themes/_shared`` is the ``palette`` layer, not ``themes.palette``."""
    tree = ast.parse("from ..palette import SPECTRA6\nfrom ._shared import x\nfrom .. import clock\n")
    assert _package_imports("themes.tarot", tree) == {"palette", "themes._shared", "clock"}


def test_a_theme_importing_another_theme_is_caught(monkeypatch):
    fake = {
        "themes.tarot": ast.parse("from ._shared import x\n"),
        "themes.vitrail": ast.parse("from .tarot import _tarot_paint_card\n"),
    }
    monkeypatch.setattr(sys.modules[__name__], "_modules", lambda: fake)
    with pytest.raises(AssertionError, match="themes never import each other"):
        test_imports_only_point_downward()


def test_facade_resolves_lowest_layer_first():
    """``__init__`` installs the facade in layer order, so a name bound in
    several modules reads from where it is defined, not from an importer."""
    installed = [module.__name__.removeprefix(rq.__name__ + ".") for module in vars(rq)["__facade_submodules__"]]
    assert installed == list(LAYERS)


def test_type_checkers_see_every_layer():
    """The facade resolves names at runtime, so ``__init__``'s ``TYPE_CHECKING``
    block is what editors and type checkers see. A layer missing from it hides
    every public name that moved there and isn't re-imported elsewhere, as
    ``THEME_ORDER`` was when it moved to ``theme_tables``."""
    tree = ast.parse((PACKAGE_DIR / "__init__.py").read_text(encoding="utf-8"))
    blocks = [
        node for node in tree.body
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
    ]
    assert len(blocks) == 1, "expected one `if TYPE_CHECKING:` block in render_quote/__init__.py"
    shown = {node.module for node in blocks[0].body if isinstance(node, ast.ImportFrom) and node.level == 1}
    assert shown == set(LAYERS), f"layers missing from the TYPE_CHECKING re-export: {sorted(set(LAYERS) - shown)}"
