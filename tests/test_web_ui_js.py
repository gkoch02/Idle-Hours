"""Run the curator UI's JavaScript test suite as part of pytest.

``idle_hours/web/main.js`` is 726 lines of operator-facing behaviour that no
Python test can reach: hash routing, the lazy per-tab fetch gating, the focus
guard that stops the 30s poll from collapsing an open dropdown, 401 token
recovery, and the read-modify-write in ``banQuoteKey`` that rewrites the shared
``selection_overrides.json`` sidecar straight from the browser. A bug in that
last one silently drops an operator's bans and boosts, and the server accepts
the truncated payload either way.

The tests live in ``tests/js/`` and run under ``node --test`` against the real
``main.js`` (loaded into a ``node:vm`` sandbox with a DOM stub — see
``tests/js/harness.mjs``), so there is no transcribed copy to drift. This
module is a thin bridge so a plain ``pytest`` run exercises them too.

Node is not a hard dependency of the project, so a missing interpreter skips
rather than fails. CI runs ``node --test`` directly as its own step as well,
so the skip can never quietly hide a JS regression there.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

JS_TEST_DIR = Path(__file__).parent / "js"
REPO_ROOT = Path(__file__).parent.parent
NODE = shutil.which("node")


def _test_files() -> list[str]:
    """Explicit file list rather than ``node --test tests/js/``.

    Node's directory discovery needs the directory to look like a package;
    without a ``package.json`` at the repo root, ``node --test tests/js/``
    tries to resolve the directory as a module entry point and dies with
    MODULE_NOT_FOUND before running anything. Passing files explicitly also
    keeps ``harness.mjs`` (a helper, not a test) out of the run.
    """
    return sorted(str(p) for p in JS_TEST_DIR.glob("*.test.mjs"))


def _run_node_suite() -> subprocess.CompletedProcess:
    return subprocess.run(
        [NODE, "--test", *_test_files()],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=REPO_ROOT,
    )


@pytest.mark.skipif(NODE is None, reason="node is not installed; JS suite runs in CI")
def test_web_ui_javascript_suite_passes():
    result = _run_node_suite()
    assert result.returncode == 0, (
        "node --test tests/js/*.test.mjs failed:\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


class TestJsSuiteWiring:
    """Guard the bridge itself — a silent skip is worse than a failure."""

    def test_js_test_files_exist(self):
        """A moved or renamed test file would make ``node --test`` exit 0 with
        nothing to run, turning this module into a permanent green no-op."""
        found = sorted(p.name for p in JS_TEST_DIR.glob("*.test.mjs"))
        assert found, f"no *.test.mjs files under {JS_TEST_DIR}"

    @pytest.mark.skipif(NODE is None, reason="node is not installed")
    def test_suite_reports_a_nonzero_test_count(self):
        """``node --test`` with no matching files exits 0. Assert it actually
        ran assertions rather than trusting the exit code alone."""
        result = _run_node_suite()
        pass_lines = [ln for ln in result.stdout.splitlines() if ln.startswith("# pass ")]
        assert pass_lines, f"no TAP summary in output:\n{result.stdout}"
        assert int(pass_lines[-1].split()[-1]) > 0, "JS suite ran zero passing tests"
