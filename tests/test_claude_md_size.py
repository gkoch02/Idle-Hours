"""CLAUDE.md is loaded into every Claude Code session, so its size is a budget.

Claude Code warns once the file passes 150k characters. It reached ~559k by
accreting full design write-ups for every theme; those now live in
``docs/themes.md``, ``docs/runtime.md``, ``docs/web_ui.md``,
``docs/testing.md`` and ``docs/pipeline.md``, with CLAUDE.md keeping
invariants and pointers (issue #352). This
fence keeps it that way: when it fails, move detail into ``docs/`` rather
than raising the limit.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIMIT = 150_000
# Headroom so a single large PR fails here rather than tipping the file over
# the warning threshold the day it merges.
BUDGET = 130_000


def test_claude_md_stays_under_budget():
    size = len((REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
    assert size <= BUDGET, (
        f"CLAUDE.md is {size:,} characters (budget {BUDGET:,}; Claude Code warns "
        f"at {LIMIT:,}). Move long design notes into docs/themes.md, docs/runtime.md, "
        "docs/web_ui.md or docs/testing.md and leave a pointer."
    )


def test_split_docs_are_linked_from_claude_md():
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for doc in ("docs/pipeline.md", "docs/themes.md", "docs/runtime.md", "docs/web_ui.md", "docs/testing.md"):
        assert (REPO_ROOT / doc).exists(), f"{doc} is missing"
        assert doc in text, f"CLAUDE.md no longer points at {doc}"
