"""The ``render_quote`` package namespace: live reads, refused writes (issue #335).

``render_quote`` used to be one module. Its code now lives in submodules, and
Python patches a name where it is looked up, not where it was defined: a patch
on the package namespace would succeed silently and change nothing, so the test
would pass while testing nothing. ``install`` swaps the package module's class
for :class:`_Facade`, which closes that gap:

* **Reads fall through.** A name the package itself does not hold is read from
  the first submodule (in layer order) that binds it, at the moment of the
  read. Nothing is copied, so a global the renderer rebinds (a warning latch, a
  scene cache) never goes stale, and a patch on the defining module is seen by
  everyone who reads through the package (``web_server`` calls
  ``render_quote.render``).
* **Writes are refused.** Setting or deleting a name on the package raises,
  naming the submodules that bind it, so a test patches the module whose code
  reads the name. ``tests/test_render_quote_facade.py`` also fences, by
  reading the source, that no test or script writes through the package.

Library code imports from the submodule that defines a name. The fall-through
exists for tests, scripts and callers of the public API in ``__all__``.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Iterable

_SUBMODULES = "__facade_submodules__"


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
        if not self._passes_through(name, value):
            self._refuse(name, "set")
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if not self._passes_through(name, None):
            self._refuse(name, "delete")
        super().__delattr__(name)

    def _passes_through(self, name: str, value) -> bool:
        """Dunders and the import system attaching a submodule (``import pkg.sub``)."""
        if _is_dunder(name):
            return True
        return isinstance(value, types.ModuleType) and value.__name__ == f"{self.__name__}.{name}"

    def _refuse(self, name: str, verb: str):
        binders = [module.__name__ for module in self.__dict__.get(_SUBMODULES, ()) if name in vars(module)]
        where = f"it is bound in {', '.join(binders)}" if binders else f"no submodule binds {name!r}"
        raise AttributeError(
            f"cannot {verb} {self.__name__}.{name}: {where}. The package only reads through to its "
            "submodules; patch the module whose code reads the name."
        )


def install(package_name: str, submodules: Iterable[types.ModuleType]) -> None:
    """Make ``package_name`` resolve missing names in ``submodules``, in order."""
    package = sys.modules[package_name]
    package.__dict__[_SUBMODULES] = tuple(submodules)
    package.__class__ = _Facade
