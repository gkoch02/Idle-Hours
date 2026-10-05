"""The ``render_quote`` package namespace: live reads, guarded writes (issue #335).

``render_quote`` used to be one module, and about a hundred test sites and two
scripts patch it by name: ``monkeypatch.setattr(rq, "_tarot_paint_card_name",
...)``. Python patches a name where it is looked up, not where it was defined.
Once a painter lives in a submodule, a patch on the package namespace succeeds
silently and changes nothing, and the test passes while testing nothing.

``install`` swaps the package module's class for :class:`_Facade`, which closes
that gap:

* **Reads fall through.** A name the package itself does not hold is read from
  the submodule that binds it, at the moment of the read. Nothing is copied, so
  a global the renderer rebinds (``_FONT_FALLBACK_WARNED``, a scene cache) can
  never go stale here.
* **Writes go to the owner, or nowhere.** A write or delete of a name bound by
  exactly one submodule is forwarded to it, so the patch reaches the code that
  reads the name. A name bound by several submodules, or by none, raises
  instead, naming the modules to patch. A silent no-op becomes a loud failure.

The owner map is taken once, at install time. ``mock.patch.object`` restores a
non-local attribute by deleting it and then setting it again; a live lookup
would find no owner between the two and refuse the restore.

Single-owner forwarding is transitional. Once the split is finished, tests patch
the module that reads a name, and the forwarding branch goes; see
``docs/render_quote_split.md``.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Iterable

_SUBMODULES = "__facade_submodules__"
_OWNERS = "__facade_owners__"


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


class _Facade(types.ModuleType):
    """A package module whose missing names resolve in its submodules."""

    def __getattr__(self, name: str):
        # Only reached when normal lookup fails, i.e. for names the package
        # itself does not hold.
        if not _is_dunder(name):
            for module in self.__dict__.get(_SUBMODULES, ()):
                try:
                    return getattr(module, name)
                except AttributeError:
                    continue
        raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}")

    def __dir__(self) -> list[str]:
        names = set(self.__dict__)
        for module in self.__dict__.get(_SUBMODULES, ()):
            names.update(dir(module))
        return sorted(names)

    def __setattr__(self, name: str, value) -> None:
        if self._passes_through(name, value):
            super().__setattr__(name, value)
            return
        setattr(self._owner(name, "set"), name, value)

    def __delattr__(self, name: str) -> None:
        if self._passes_through(name, None):
            super().__delattr__(name)
            return
        delattr(self._owner(name, "delete"), name)

    def _passes_through(self, name: str, value) -> bool:
        """Names that belong to the package itself rather than to a submodule."""
        if _is_dunder(name) or name in self.__dict__:
            return True
        # The import system attaching a submodule (``import pkg.sub`` sets
        # ``pkg.sub``) is the package's own business.
        return isinstance(value, types.ModuleType) and value.__name__ == f"{self.__name__}.{name}"

    def _owner(self, name: str, verb: str) -> types.ModuleType:
        owners = self.__dict__.get(_OWNERS, {}).get(name, ())
        if len(owners) == 1:
            return owners[0]
        if not owners:
            raise AttributeError(f"cannot {verb} {self.__name__}.{name}: no submodule binds {name!r}")
        where = ", ".join(module.__name__ for module in owners)
        raise AttributeError(
            f"cannot {verb} {self.__name__}.{name}: {name!r} is bound in {where}. "
            "A patch on the package would reach none of them; patch the module whose code reads it."
        )


def install(package_name: str, submodules: Iterable[types.ModuleType]) -> None:
    """Make ``package_name`` resolve missing names in ``submodules``, in order."""
    package = sys.modules[package_name]
    submodules = tuple(submodules)
    owners: dict[str, list[types.ModuleType]] = {}
    for module in submodules:
        for name in vars(module):
            if not _is_dunder(name):
                owners.setdefault(name, []).append(module)
    package.__dict__[_SUBMODULES] = submodules
    package.__dict__[_OWNERS] = {name: tuple(mods) for name, mods in owners.items()}
    package.__class__ = _Facade
