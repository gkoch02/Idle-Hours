"""The ``render_quote`` package facade (issue #335).

``render_quote`` is a package whose code lives in submodules. ``_facade`` makes
reads through the package resolve live in the submodule that binds a name, and
refuses every write: Python patches a name where it is looked up, so a patch on
the package namespace would change nothing and the test would pass while testing
nothing. ``TestNoWritesThroughThePackage`` also fences the source, so a write in
a code path no test runs (a script, a rarely hit branch) is caught too.
"""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

from idle_hours import render_quote as rq
from idle_hours.render_quote import _facade, core, fonts
from idle_hours.render_quote.themes import diags

REPO = Path(__file__).resolve().parent.parent


class TestReads:
    def test_names_resolve_in_the_submodule(self):
        assert rq.render is core.render
        assert rq._diags_system_info is diags._diags_system_info

    def test_reads_are_live_after_the_code_rebinds_a_global(self, monkeypatch):
        """The renderer rebinds some globals itself (latches, caches); a copy
        taken at import would go stale."""
        monkeypatch.setattr(fonts, "_FONT_FALLBACK_WARNED", "rebound-in-submodule")
        assert rq._FONT_FALLBACK_WARNED == "rebound-in-submodule"

    def test_a_patch_on_the_defining_module_is_seen_through_the_package(self):
        """``web_server`` calls ``render_quote.render``; patching ``core.render`` reaches it."""
        with mock.patch("idle_hours.render_quote.core.render") as fake:
            assert rq.render is fake

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

    def test_every_public_name_resolves(self):
        assert [name for name in rq.__all__ if not hasattr(rq, name)] == []


class TestWritesAreRefused:
    def test_monkeypatch_on_the_package_raises_naming_the_module(self, monkeypatch):
        with pytest.raises(AttributeError, match=r"bound in idle_hours\.render_quote\.themes\.diags"):
            monkeypatch.setattr(rq, "_diags_system_info", lambda: "patched")
        assert "_diags_system_info" not in vars(rq), "a refused patch must not leave a shadow on the package"

    def test_mock_patch_by_dotted_path_raises(self):
        # ``mock.patch`` is refused at its delete or its set, depending on the
        # attribute; either way the patch never lands.
        with pytest.raises(AttributeError, match="cannot (set|delete)"):
            with mock.patch("idle_hours.render_quote.render"):
                pass  # pragma: no cover

    def test_plain_assignment_and_delete_raise(self):
        with pytest.raises(AttributeError, match="cannot set"):
            rq.render = print
        with pytest.raises(AttributeError, match="cannot delete"):
            del rq.render
        assert rq.render is core.render

    def test_writing_a_name_no_submodule_binds_raises(self):
        with pytest.raises(AttributeError, match="no submodule binds"):
            rq.no_such_name_anywhere = 1


def _package_aliases(tree: ast.Module) -> set[str]:
    """Names a module binds to the ``render_quote`` package."""
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "idle_hours":
            aliases |= {a.asname or a.name for a in node.names if a.name == "render_quote"}
        elif isinstance(node, ast.Import):
            aliases |= {a.asname for a in node.names if a.name == "idle_hours.render_quote" and a.asname}
    return aliases


def _resolve(dotted: str):
    """The object ``dotted`` names, importing its longest importable prefix; None if it has none."""
    parts = dotted.split(".")
    if parts[0] != "idle_hours":
        return None
    for cut in range(len(parts), 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:cut]))
        except ImportError:
            continue
        try:
            for part in parts[cut:]:
                obj = getattr(obj, part)
        except AttributeError:
            return None
        return obj
    return None


def _resolves_to_package(dotted: str) -> bool:
    """Whether the object ``dotted`` patches an attribute of is the package.

    Resolves the parent by import, so an alias held by another module
    (``idle_hours.contact_sheet.render_quote_module.render``) is caught however
    it is spelled.
    """
    parent = dotted.rpartition(".")[0]
    return bool(parent) and _resolve(parent) is rq


def _dotted(expr) -> str | None:
    """``a.b.c`` for a Name / Attribute chain, else None."""
    parts = []
    while isinstance(expr, ast.Attribute):
        parts.append(expr.attr)
        expr = expr.value
    if not isinstance(expr, ast.Name):
        return None
    return ".".join([expr.id, *reversed(parts)])


def _is_package(expr, aliases: set[str]) -> bool:
    """Whether ``expr`` is the package: a bound alias, or a dotted path from ``idle_hours`` that resolves to it."""
    dotted = _dotted(expr)
    if dotted is None:
        return False
    return dotted in aliases or (dotted.startswith("idle_hours.") and _resolve(dotted) is rq)


def _patch_call_target(call: ast.Call):
    """The first argument of a call that patches an attribute, or None."""
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
    is_patch_object = name == "object" and isinstance(func, ast.Attribute) and (
        (isinstance(func.value, ast.Name) and func.value.id == "patch")
        or (isinstance(func.value, ast.Attribute) and func.value.attr == "patch")
    )
    if name in {"setattr", "delattr", "patch"} or is_patch_object:
        return call.args[0] if call.args else None
    return None


def _package_writes(path: Path) -> list[str]:
    """Every write through the package in ``path``: patches, setattr/delattr, assignment and ``del``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    aliases = _package_aliases(tree)
    where = path.relative_to(REPO) if path.is_relative_to(REPO) else path
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = _patch_call_target(node)
            if target is not None and _is_package(target, aliases):
                found.append(f"{where}:{node.lineno}: patch on {_dotted(target)}")
            elif isinstance(target, ast.Constant) and isinstance(target.value, str) and _resolves_to_package(target.value):
                found.append(f"{where}:{node.lineno}: patch on {target.value}")
        targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target] if isinstance(node, ast.AugAssign) else []
        for target in targets:
            if isinstance(target, ast.Attribute) and _is_package(target.value, aliases):
                found.append(f"{where}:{node.lineno}: {_dotted(target.value)}.{target.attr}")
    return found


class TestNoWritesThroughThePackage:
    """No test, script or module writes a name through ``render_quote``.

    The runtime refusal catches a write that runs; this catches one that
    doesn't (a script, an unexercised branch), in every form: ``setattr`` /
    ``patch.object`` on the package, a dotted ``patch`` / ``setattr`` string
    whose parent is the package (by any module's alias), and plain assignment
    or ``del``. This file is exempt: it tests the refusal. Patching a submodule
    (``idle_hours.render_quote.core.render``) is the right form and passes.
    """

    def test_nothing_writes_through_the_package(self):
        here = Path(__file__).resolve()
        hits = [
            hit
            for root in ("tests", "scripts", "idle_hours")
            for path in sorted((REPO / root).rglob("*.py"))
            if path.resolve() != here
            for hit in _package_writes(path)
        ]
        assert hits == [], "patch the module whose code reads the name, not render_quote:\n  " + "\n  ".join(hits)

    def test_the_fence_sees_each_write_form(self, tmp_path):
        sample = tmp_path / "sample.py"
        sample.write_text(
            "from idle_hours import render_quote as rq\n"
            "rq.render = print\n"
            "del rq.THEMES\n"
            "monkeypatch.setattr(\n    rq, 'x', 1)\n"
            "patch.object(rq, 'x')\n"
            "mock.patch.object(rq, 'x')\n"
            "patch('idle_hours.render_quote.render')\n"
            "monkeypatch.setattr('idle_hours.render_quote.render', print)\n"
            "patch('idle_hours.contact_sheet.render_quote_module.render')\n"
            "import idle_hours.render_quote\n"
            "idle_hours.render_quote.render = print\n"
            "setattr(idle_hours.render_quote, 'render', print)\n"
            "idle_hours.contact_sheet.render_quote_module.render = print\n"
            "patch('idle_hours.render_quote.core.render')\n"
            "idle_hours.render_quote.core.render = print\n"
            "monkeypatch.setattr(rq_themes.vhs, 'x', 1)\n"
        )
        assert len(_package_writes(sample)) == 11


class TestAmbiguousNames:
    """A name bound in two submodules reads from the first; writing it names both."""

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

    def test_a_write_is_refused_even_with_one_owner(self, package):
        pkg, first, _second = package
        with pytest.raises(AttributeError, match="bound in fakepkg.first"):
            pkg.only_here = 2
        assert first.only_here == 1

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
