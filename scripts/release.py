#!/usr/bin/env python3
"""Prepare and finalize Idle Hours releases without publishing packages."""

from __future__ import annotations

import argparse
import datetime as dt
import email.parser
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class ReleaseError(RuntimeError):
    """A release precondition failed."""


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=capture,
    )


def git(*args: str, capture: bool = True) -> str:
    result = run(["git", *args], capture=capture)
    return result.stdout.strip() if result.stdout is not None else ""


def parse_version(value: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(value)
    if not match:
        raise ReleaseError(f"{value!r} is not a canonical MAJOR.MINOR.PATCH version")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def declared_version(text: str | None = None) -> str:
    import tomllib

    payload = PYPROJECT.read_bytes() if text is None else text.encode()
    value = tomllib.loads(payload.decode())["project"]["version"]
    parse_version(value)
    return value


def replace_declared_version(text: str, old: str, new: str) -> str:
    needle = f'version = "{old}"'
    if text.count(needle) != 1:
        raise ReleaseError(f"expected exactly one {needle!r} in pyproject.toml")
    return text.replace(needle, f'version = "{new}"', 1)


def promote_changelog(text: str, version: str, release_date: str) -> str:
    marker = "## [Unreleased]"
    if text.count(marker) != 1:
        raise ReleaseError("CHANGELOG.md must contain exactly one '## [Unreleased]' heading")
    start = text.index(marker) + len(marker)
    next_heading = text.find("\n## [", start)
    if next_heading == -1:
        raise ReleaseError("CHANGELOG.md needs a released-version heading after Unreleased")
    body = text[start:next_heading].strip()
    if not body or not re.search(r"(?m)^\s*[-*] ", body):
        raise ReleaseError("the Unreleased changelog section has no bullet entries")
    if f"## [{version}]" in text:
        raise ReleaseError(f"CHANGELOG.md already contains a {version} release")
    replacement = f"{marker}\n\n## [{version}] - {release_date}\n\n{body}"
    return text[: text.index(marker)] + replacement + text[next_heading:]


def require_clean_tree() -> None:
    status = git("status", "--porcelain")
    if status:
        raise ReleaseError("working tree is not clean:\n" + status)


def require_main_at_origin() -> None:
    branch = git("branch", "--show-current")
    if branch != "main":
        raise ReleaseError(f"expected branch 'main', found {branch!r}")
    git("fetch", "origin", "main", capture=False)
    head = git("rev-parse", "HEAD")
    upstream = git("rev-parse", "origin/main")
    if head != upstream:
        raise ReleaseError("local main does not exactly match origin/main")


def ref_exists(ref: str) -> bool:
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", ref],
        cwd=ROOT,
        check=False,
    )
    return result.returncode == 0


def remote_tag_exists(tag: str) -> bool:
    return bool(git("ls-remote", "--tags", "origin", f"refs/tags/{tag}"))


def build_and_verify(version: str) -> None:
    with tempfile.TemporaryDirectory(prefix="idle-hours-release-") as tmp:
        run([sys.executable, "-m", "build", "--outdir", tmp])
        wheels = list(Path(tmp).glob("*.whl"))
        if len(wheels) != 1:
            raise ReleaseError(f"expected one wheel, found {len(wheels)}")
        with zipfile.ZipFile(wheels[0]) as archive:
            metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1:
                raise ReleaseError("wheel does not contain exactly one METADATA file")
            metadata = email.parser.Parser().parsestr(archive.read(metadata_names[0]).decode())
        if metadata["Name"] != "idle-hours" or metadata["Version"] != version:
            raise ReleaseError(
                f"wheel metadata is {metadata['Name']!r} {metadata['Version']!r}, expected 'idle-hours' {version!r}"
            )


def run_release_checks(version: str) -> None:
    # An editable install's dist-info does not automatically refresh after
    # pyproject.toml changes. Reinstall before pytest so the packaging and CLI
    # version checks see the version being prepared rather than the previous
    # release's cached metadata.
    run([sys.executable, "-m", "pip", "install", "--no-deps", "-e", "."])
    run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-n",
            "auto",
            "--dist",
            "loadscope",
            "--ignore=tests/test_render_golden.py",
        ]
    )
    build_and_verify(version)


def prepare(args: argparse.Namespace) -> None:
    target = parse_version(args.version)
    require_clean_tree()
    require_main_at_origin()
    current = declared_version()
    if target <= parse_version(current):
        raise ReleaseError(f"new version {args.version} must be greater than current version {current}")
    tag = f"v{args.version}"
    if ref_exists(f"refs/tags/{tag}") or remote_tag_exists(tag):
        raise ReleaseError(f"tag {tag} already exists")

    new_pyproject = replace_declared_version(PYPROJECT.read_text(), current, args.version)
    new_changelog = promote_changelog(
        CHANGELOG.read_text(), args.version, dt.date.today().isoformat()
    )

    branch = f"release/{tag}"
    if ref_exists(f"refs/heads/{branch}"):
        raise ReleaseError(f"branch {branch} already exists")
    git("switch", "-c", branch, capture=False)

    PYPROJECT.write_text(new_pyproject)
    CHANGELOG.write_text(new_changelog)

    if not args.skip_checks:
        run_release_checks(args.version)

    git("add", str(PYPROJECT.relative_to(ROOT)), str(CHANGELOG.relative_to(ROOT)), capture=False)
    git("commit", "-m", f"release: prepare {tag}", capture=False)

    if args.push or args.open_pr:
        git("push", "-u", "origin", branch, capture=False)
    if args.open_pr:
        run(
            [
                "gh",
                "pr",
                "create",
                "--base",
                "main",
                "--head",
                branch,
                "--title",
                f"release: {tag}",
                "--body",
                f"Prepare Idle Hours {args.version}.\n\nAfter merge, run `python scripts/release.py finalize {args.version}`.",
            ]
        )

    print(f"Prepared {tag} on {branch}.")
    if not (args.push or args.open_pr):
        print(f"Review the commit, then push with: git push -u origin {branch}")


def confirm_push(tag: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise ReleaseError("refusing to push from a non-interactive shell without --yes")
    return input(f"Push annotated tag {tag} to origin? [y/N] ").strip().lower() in {"y", "yes"}


def finalize(args: argparse.Namespace) -> None:
    parse_version(args.version)
    require_clean_tree()
    require_main_at_origin()
    current = declared_version()
    if current != args.version:
        raise ReleaseError(f"pyproject.toml declares {current}, not requested version {args.version}")
    changelog = CHANGELOG.read_text()
    if not re.search(rf"(?m)^## \[{re.escape(args.version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog):
        raise ReleaseError(f"CHANGELOG.md has no dated {args.version} release entry")

    tag = f"v{args.version}"
    if ref_exists(f"refs/tags/{tag}") or remote_tag_exists(tag):
        raise ReleaseError(f"tag {tag} already exists")
    build_and_verify(args.version)
    git("tag", "-a", tag, "-m", f"Idle Hours {args.version}", capture=False)
    print(f"Created annotated tag {tag} at {git('rev-parse', '--short', 'HEAD')}.")

    if args.push:
        if confirm_push(tag, args.yes):
            git("push", "origin", tag, capture=False)
            print(f"Pushed {tag}. CI will independently verify the tag against package metadata.")
        else:
            print(f"Tag not pushed. Push later with: git push origin {tag}")
    else:
        print(f"Tag not pushed. After review: git push origin {tag}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="bump metadata and changelog on a release branch")
    prepare_parser.add_argument("version", help="canonical MAJOR.MINOR.PATCH version")
    prepare_parser.add_argument("--skip-checks", action="store_true", help="skip pytest and wheel verification")
    prepare_parser.add_argument("--push", action="store_true", help="push the release branch")
    prepare_parser.add_argument("--open-pr", action="store_true", help="push and open the release PR with gh")
    prepare_parser.set_defaults(func=prepare)

    finalize_parser = subparsers.add_parser("finalize", help="verify merged main and create the release tag")
    finalize_parser.add_argument("version", help="canonical MAJOR.MINOR.PATCH version")
    finalize_parser.add_argument("--push", action="store_true", help="offer to push the annotated tag")
    finalize_parser.add_argument("--yes", action="store_true", help="confirm --push non-interactively")
    finalize_parser.set_defaults(func=finalize)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        args.func(args)
    except (ReleaseError, subprocess.CalledProcessError) as error:
        print(f"release error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
