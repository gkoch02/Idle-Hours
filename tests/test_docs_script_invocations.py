"""Fence the docs against invocations of flat scripts that no longer exist.

After the v2.x restructure every module lives under ``idle_hours/``; there
are no ``*.py`` files at the repo root. CONTRIBUTING.md, the Pi setup guide
and the ``idle-hours --help`` epilogue nevertheless kept telling people to
run ``python3 run_clock.py`` and friends (issue #299), so the first command
a new contributor or installer was handed failed with "No such file". The
supported spellings are ``idle-hours <subcommand>`` and
``python3 -m idle_hours.<module>``; anything of the form
``python3 <name>.py`` is a stale instruction.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from idle_hours import idle_hours_cli

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every prose file an operator or contributor is pointed at.
DOCS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "docs" / "CONTRIBUTING.md",
    REPO_ROOT / "docs" / "pi_setup_inky_impression.md",
    REPO_ROOT / "docs" / "UPGRADE.md",
    REPO_ROOT / "docs" / "spectra6_color_recipes.md",
    REPO_ROOT / "idle_hours" / "assets" / "config.toml.example",
    REPO_ROOT / "idle_hours" / "assets" / "config.toml.defaults",
    REPO_ROOT / "ops" / "idle-hours.service.example",
]

# ``python3 run_clock.py …`` / ``python idle_hours_health.py …`` — a bare
# script name with no directory component. ``python3 scripts/foo.py`` (a real
# path under scripts/) and ``python3 -m idle_hours.foo`` are both fine.
FLAT_SCRIPT_INVOCATION = re.compile(r"\bpython3?\s+(?:<script>|[a-z_]+)\.py\b")


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_docs_never_invoke_a_flat_script(doc: Path) -> None:
    assert doc.exists(), f"{doc} is missing — update DOCS if it moved"
    hits = [
        f"{doc.relative_to(REPO_ROOT)}:{n}: {line.strip()}"
        for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1)
        if FLAT_SCRIPT_INVOCATION.search(line)
    ]
    assert not hits, "stale flat-script invocation(s); use `idle-hours <sub>` or `python3 -m idle_hours.<module>`:\n" + "\n".join(hits)


def test_no_flat_scripts_exist_at_the_repo_root() -> None:
    """The premise of the fence: the layout really is package-only."""
    assert not list(REPO_ROOT.glob("*.py"))


def test_cli_help_does_not_promise_flat_script_compat() -> None:
    text = idle_hours_cli._format_help()
    assert not FLAT_SCRIPT_INVOCATION.search(text), text
    assert "python3 -m idle_hours." in text


def test_the_fence_regex_catches_the_reported_forms() -> None:
    for sample in (
        "python3 run_clock.py --once",
        "`python3 idle_hours_health.py --hours 24`",
        "python apply_content_overrides.py assets/x.jsonl",
        "with `python3 <script>.py` continuing to work",
    ):
        assert FLAT_SCRIPT_INVOCATION.search(sample), sample
    for sample in (
        "python3 -m idle_hours.run_clock --once",
        "python3 scripts/generate_theme_previews.py --check",
        "idle-hours run --once",
        "`run_clock.py` is a thin orchestrator",
    ):
        assert not FLAT_SCRIPT_INVOCATION.search(sample), sample
