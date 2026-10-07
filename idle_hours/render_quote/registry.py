"""The dispatch tables, built from what each theme module declares (issue #335).

Each module in ``themes.THEME_MODULES`` ends with a ``SPEC`` (see ``spec``).
This module collects them, checks them against ``THEMES``, and builds the
tables ``render`` dispatches through. A theme is wired up by its own module,
and a mistake fails at import rather than leaving a theme silently
undecorated.

``BORDER_SPECS`` and ``FRAME_SPECS`` are what ``render`` reads. To stub a
painter in a test, replace its spec in ``BORDER_SPECS`` (one place covers
both paints). ``_BORDER_PAINTERS``, ``_FRAME_RENDERERS`` and
``_DEBUG_LABEL_RIGHT_INSET`` are read-only views of the specs, kept under the
names tests and docs already use; writing to one raises, so a patch cannot
land where ``render`` never looks.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType, ModuleType

from .spec import BorderSpec, FrameSpec
from .theme_tables import THEMES
from .themes import THEME_MODULES

# Themes drawn by the shared layout alone, with no border and no frame.
PLAIN_THEMES: frozenset[str] = frozenset({"default", "dark"})


@dataclass(frozen=True)
class Registry:
    borders: dict[str, BorderSpec]
    frames: dict[str, FrameSpec]


def build_registry(modules: Iterable[ModuleType], theme_names: Iterable[str], plain: frozenset[str] = PLAIN_THEMES) -> Registry:
    """Collect every module's ``SPEC`` and check the set is complete.

    Raises ``RuntimeError`` naming every problem at once: a module with no
    spec, a theme claimed twice, a spec for a theme ``THEMES`` lacks, or a
    registered theme that is neither plain nor claimed by a spec.
    """
    borders: dict[str, BorderSpec] = {}
    frames: dict[str, FrameSpec] = {}
    owner: dict[str, str] = {}
    problems: list[str] = []
    known = set(theme_names)
    for module in modules:
        spec = getattr(module, "SPEC", None)
        if not isinstance(spec, (BorderSpec, FrameSpec)):
            problems.append(f"{module.__name__} has no BorderSpec or FrameSpec SPEC")
            continue
        for theme in spec.themes:
            if theme in owner:
                problems.append(f"{theme} is claimed by both {owner[theme]} and {module.__name__}")
                continue
            if theme not in known:
                problems.append(f"{module.__name__} declares {theme}, which is not in THEMES")
            if theme in plain:
                problems.append(f"{module.__name__} declares {theme}, which is a plain theme")
            owner[theme] = module.__name__
            if isinstance(spec, BorderSpec):
                borders[theme] = spec
            else:
                frames[theme] = spec
    unclaimed = sorted(known - set(owner) - plain)
    if unclaimed:
        problems.append(f"themes with no SPEC and not plain: {', '.join(unclaimed)}")
    if problems:
        raise RuntimeError("render_quote theme registry is inconsistent:\n  " + "\n  ".join(problems))
    return Registry(borders, frames)


_REGISTRY = build_registry(THEME_MODULES, THEMES)

BORDER_SPECS: dict[str, BorderSpec] = _REGISTRY.borders
FRAME_SPECS: dict[str, FrameSpec] = _REGISTRY.frames



def sleep_renderer(theme: str):
    """The theme's own sleep-frame renderer, or ``None`` when it sleeps under
    the bundled quote.

    Read off the live spec tables on every call, so a test that swaps a spec
    in ``BORDER_SPECS`` / ``FRAME_SPECS`` swaps its sleep frame with it.
    """
    spec = FRAME_SPECS.get(theme) or BORDER_SPECS.get(theme)
    return spec.sleep if spec is not None else None


_BORDER_PAINTERS: Mapping = MappingProxyType({theme: spec.paint for theme, spec in BORDER_SPECS.items()})
_FRAME_RENDERERS: Mapping = MappingProxyType({theme: spec.render for theme, spec in FRAME_SPECS.items()})
# Bordered themes with no ``debug_label_inset`` clear the banner's y=14-29 band
# by construction:
#   - newsprint, grimdark: the right frame rule ends ~7 px outside the
#     default label edge (x=width-SIDE_MARGIN).
#   - nightvision: the TR bracket's vertical arm likewise; its horizontal
#     arm sits at y=12-13, above the label.
#   - dispatch: the stamp sits at y=40-70.
#   - atomic, grimdark: the top ornament is centred horizontally.
#   - kanagawa: the TR sun's top edge is at y=59.
#   - deco: the stepped corner stays at x <= width-14; the fan is centred.
#   - swiss (header square at y=42), mucha (TR left bare), fillmore (rings
#     centred at y=110), firmament (moon at y=54, Milky Way at x <= width-100).
_DEBUG_LABEL_RIGHT_INSET: Mapping = MappingProxyType({
    theme: spec.debug_label_inset for theme, spec in BORDER_SPECS.items() if spec.debug_label_inset is not None
})
