import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "release.py"
SPEC = importlib.util.spec_from_file_location("release_tool", SCRIPT)
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.1.0", (0, 1, 0)),
        ("2.6.0", (2, 6, 0)),
        ("10.20.30", (10, 20, 30)),
    ],
)
def test_parse_version_accepts_canonical_semver(value, expected):
    assert release.parse_version(value) == expected


@pytest.mark.parametrize("value", ["v2.6.0", "v.2.6.0", "2.6", "2.6.0rc1", "02.6.0"])
def test_parse_version_rejects_noncanonical_values(value):
    with pytest.raises(release.ReleaseError, match="canonical"):
        release.parse_version(value)


def test_replace_declared_version_changes_only_project_literal():
    text = '[project]\nversion = "2.5.0"\n# mention 2.5.0 elsewhere\n'
    assert release.replace_declared_version(text, "2.5.0", "2.6.0") == (
        '[project]\nversion = "2.6.0"\n# mention 2.5.0 elsewhere\n'
    )


def test_replace_declared_version_rejects_missing_or_duplicate_literal():
    with pytest.raises(release.ReleaseError, match="exactly one"):
        release.replace_declared_version('[project]\nversion = "2.4.0"\n', "2.5.0", "2.6.0")
    with pytest.raises(release.ReleaseError, match="exactly one"):
        release.replace_declared_version('version = "2.5.0"\nversion = "2.5.0"\n', "2.5.0", "2.6.0")


def test_promote_changelog_moves_unreleased_entries():
    source = """# Changelog

## [Unreleased]

### Added

- Safer releases.

## [2.5.0] - 2026-09-24

- Previous release.
"""
    result = release.promote_changelog(source, "2.6.0", "2026-09-25")
    assert "## [Unreleased]\n\n## [2.6.0] - 2026-09-25" in result
    assert "### Added\n\n- Safer releases.\n## [2.5.0]" in result


def test_promote_changelog_rejects_empty_unreleased_section():
    source = "# Changelog\n\n## [Unreleased]\n\nSome prose.\n\n## [2.5.0] - 2026-09-24\n"
    with pytest.raises(release.ReleaseError, match="no bullet"):
        release.promote_changelog(source, "2.6.0", "2026-09-25")


def test_promote_changelog_rejects_existing_version():
    source = "# Changelog\n\n## [Unreleased]\n\n- New.\n\n## [2.6.0] - 2026-09-24\n"
    with pytest.raises(release.ReleaseError, match="already contains"):
        release.promote_changelog(source, "2.6.0", "2026-09-25")


def test_confirm_push_requires_yes_when_noninteractive(monkeypatch):
    monkeypatch.setattr(release.sys.stdin, "isatty", lambda: False)
    with pytest.raises(release.ReleaseError, match="non-interactive"):
        release.confirm_push("v2.6.0", assume_yes=False)
    assert release.confirm_push("v2.6.0", assume_yes=True)


def test_cli_help_lists_both_phases(capsys):
    with pytest.raises(SystemExit) as exit_info:
        release.parser().parse_args(["--help"])
    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "prepare" in output
    assert "finalize" in output
