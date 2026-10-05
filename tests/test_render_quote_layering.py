"""The ``render_quote`` package's import layering (issue #335).

The split moves code out of ``_monolith`` into modules that may only import
downward. A module that imports from a higher layer reintroduces the cycles the
split exists to remove, and usually means a helper was filed in the wrong
layer. Every module must be listed in ``LAYERS``, so a new one is placed
deliberately rather than slipping in unchecked.
"""

from __future__ import annotations

import ast
from pathlib import Path

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
    "_monolith",
)

# Package plumbing, not part of the render layers.
PLUMBING = {"__init__", "__main__", "_facade"}


def _modules() -> dict[str, ast.Module]:
    return {
        path.stem: ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(PACKAGE_DIR.glob("*.py"))
        if path.stem not in PLUMBING
    }


def _package_imports(tree: ast.Module) -> set[str]:
    """Sibling modules a module imports: ``from .x import …`` and ``from . import x``."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                found.add(node.module.split(".")[0])
            else:
                found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("idle_hours.render_quote"):
            rest = node.module.removeprefix("idle_hours.render_quote").lstrip(".")
            found.add(rest.split(".")[0] if rest else "__init__")
    return found


def test_every_module_has_a_layer():
    unplaced = sorted(set(_modules()) - set(LAYERS))
    assert unplaced == [], f"render_quote modules missing from LAYERS: {unplaced}; place them in the layer order"


def test_imports_only_point_downward():
    rank = {name: i for i, name in enumerate(LAYERS)}
    violations = []
    for name, tree in _modules().items():
        for target in sorted(_package_imports(tree)):
            if target in PLUMBING or target not in rank:
                violations.append(f"{name} imports {target}, which is not a render layer")
            elif rank[target] >= rank[name]:
                violations.append(f"{name} (layer {rank[name]}) imports {target} (layer {rank[target]})")
    assert violations == [], "render_quote layering broken:\n  " + "\n  ".join(violations)


def test_facade_resolves_lowest_layer_first():
    """``__init__`` installs the facade in layer order, so a name bound in
    several modules reads from where it is defined, not from an importer."""
    installed = [module.__name__.rsplit(".", 1)[1] for module in vars(rq)["__facade_submodules__"]]
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
