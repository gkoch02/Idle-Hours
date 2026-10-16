"""The theme roster: every registered theme name and the rotation order, stdlib only.

``THEME_ORDER`` lives here rather than in ``render_quote`` because importing
anything from the renderer package pulls in Pillow, and :mod:`run_clock`,
:mod:`runtime_state`, :mod:`runtime_theme`, :mod:`runtime_actions` and
:mod:`web_server` need the names without it: for ``--theme`` choices, to
validate persisted manual themes, and to drive the button-A / web cycle.
``render_quote.theme_tables`` re-exports both constants, so ``rq.THEME_ORDER``
reads are unchanged.
"""
from __future__ import annotations

# Every registered theme, in button-A / web-dropdown cycle order. This is the
# one literal list of theme names: ``run_clock``'s ``--theme`` choices and the
# renderer (``render_quote.THEME_ORDER``, re-exported by ``theme_tables``) both
# read it from here. Every name must also be a key in ``render_quote.THEMES``
# (enforced in tests).
THEME_ORDER: tuple[str, ...] = (
    "default",
    "dark",
    "newsprint",
    "nightvision",
    "gothic",
    "bauhaus",
    "comic",
    "dispatch",
    "atomic",
    "marker",
    "saloon",
    "roman",
    "alchemy",
    "deco",
    "chalkboard",
    "placard",
    "chanbara",
    "lcars",
    "fillmore",
    "firmament",
    "astrarium",
    "kanagawa",
    "marquee",
    "tarot",
    "vitrail",
    "cartograph",
    "questline",
    "chrono",
    "outrun",
    "circuit",
    "letter",
    "sampler",
    "anna_atkins",
    "lieder",
    "izakaya",
    "abyssal",
    "pride",
    "pulp",
    "synoptic",
    "vhs",
    "bakelite",
    "cardcatalog",
    "metro",
    "nocturne",
    "plaque",
    "daguerreotype",
    "autochrome",
    "photo",
    "betweenus",
    "betweenus_dark",
    "hippochomp",
    "pourjudgment",
    "reactornight",
    "carcosa",
    "control",
    "observation",
    "trisolaris",
    "biomech",
    "codex",
    "culture",
    "orbital",
    "furies",
    "bosch",
    "semiotic",
    "atropos",
    "saros",
    "expedition",
    "witcher",
    "hades",
    "expanse",
    "beksinski",
    "goya",
    "hal",
    "lumon",
    "dsky",
    "oblivion",
    "yorha",
    "hitchhiker",
    "escritoire",
    "lasvegas",
    "bladerunner",
    "traumateam",
    "redacted",
    "gantry",
    "platform",
    "splitflap",
    "imprimatur",
    "diags",
)
# Themes registered in THEMES but excluded from every rotation (button A, web
# dropdown, auto, random); reachable only via explicit `--theme NAME`.
# RANDOM_EXCLUDED_THEMES filters only --theme random. Use this for themes worth
# keeping as opt-in but not ready for unattended rotation.
CYCLE_EXCLUDED_THEMES: frozenset[str] = frozenset()


# Themes whose frame draws the time it is given: an hour carrier (a numeral, a
# camera number, a due stamp) or HH:MM on an object that is a clock. Every
# other theme renders the same frame at any time. Idle Weather leaves these
# out unless it has judged the time decoration rather than a clock, since its
# frames stay on the panel for half an hour.
# tests/test_render_golden.py renders every theme at two times and fails if
# this list is wrong in either direction.
TIME_SURFACE_THEMES: frozenset[str] = frozenset({
    "abyssal", "atropos", "bakelite", "beksinski", "betweenus", "betweenus_dark", "biomech", "bladerunner",
    "cardcatalog", "codex", "culture", "diags", "dsky", "expanse", "expedition", "gantry", "hades", "hal",
    "hippochomp", "hitchhiker", "izakaya", "lasvegas", "lieder", "lumon", "metro", "oblivion", "observation",
    "orbital", "plaque", "platform", "pourjudgment", "pulp", "reactornight", "saros", "semiotic", "synoptic",
    "tarot", "traumateam", "trisolaris", "vhs", "vitrail", "witcher", "yorha",
})

# Themes whose furniture prints the Idle Hours name (an imprint, a maker's
# line, a header). Nothing excludes these today: Idle Weather keeps them, the
# name reading as a maker's mark. tests/test_render_golden.py
# fails if a theme module carries the name and is not listed here.
BRANDED_THEMES: frozenset[str] = frozenset({
    "astrarium", "bakelite", "cardcatalog", "circuit", "diags", "lieder", "metro", "pulp", "sampler",
})


def known_theme_names() -> frozenset[str]:
    """Every registered theme name.

    Used to validate persisted manual-theme values and gate
    ``resolve_effective_theme`` overrides. Membership-style lookups; order
    does not matter (use :func:`theme_cycle` when you need the curated
    button-A / web-dropdown ordering). Equal to ``render_quote.THEMES``'s
    keys; ``set(THEME_ORDER) == set(THEMES)`` is fenced in tests.
    """
    return frozenset(THEME_ORDER)


def theme_cycle() -> tuple[str, ...]:
    """Curated order for button-A / web-dropdown theme advancement.

    ``THEME_ORDER`` minus ``CYCLE_EXCLUDED_THEMES``, so a theme can stay
    registered (and reachable via explicit ``--theme NAME``) while being
    skipped by every rotation path. Excluded themes stay in the tuple and are
    filtered here, which keeps ``set(THEME_ORDER) == set(THEMES)`` true.
    """
    return tuple(name for name in THEME_ORDER if name not in CYCLE_EXCLUDED_THEMES)
