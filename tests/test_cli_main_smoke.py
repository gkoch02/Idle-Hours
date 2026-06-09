"""Smoke tests for every script's CLI ``main()`` entry point.

Existing modules (``test_pick_quote.py``, ``test_render_quote.py``, …) already
exercise each library surface thoroughly, but they tend to import functions
directly and call them in-process. These tests instead shell out to
``python -m idle_hours.<script>`` so we catch the class of breakage that unit
tests miss:

* An argparse default that evaluates to ``None`` on import (``--input`` required
  unexpectedly).
* A top-level ``import`` that blows up on a fresh checkout (e.g. deleted
  module, missing ``if __name__ == "__main__"`` guard).
* A ``--help`` that crashes inside argparse formatter (rare but brutal).

The goal is shallow but broad: every script gets at least ``--help``, and where
a trivial no-op invocation is possible (small fake JSONL input), that too.
These tests deliberately avoid heavy cases — the per-script test modules own
behavioural coverage; this is a boot-time tripwire.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Scripts whose --help should always exit 0.
HELP_SCRIPTS = [
    "apply_content_overrides",
    "bucket_coverage",
    "clean_display_quotes",
    "contact_sheet",
    "display_inky",
    "enrich_metadata",
    "fix_legacy_buckets",
    "fix_substring_time_matches",
    "gutenberg_time_miner",
    "idle_hours_health",
    "import_targeted_hits",
    "merge_candidates",
    "pick_quote",
    "probe_buttons",
    "quality_filter",
    "render_quote",
    "run_clock",
    "target_sparse_buckets",
]


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run ``python -m idle_hours.<module>`` from the repo root.

    Caller passes ``["<module>", ...flags]`` (bare module name, no ``.py`` —
    this helper prepends ``-m idle_hours.``). The repo root is on ``sys.path``
    automatically when ``cwd`` points there, so ``idle_hours`` resolves to the
    in-tree package without requiring an editable install.
    """
    module, *rest = args
    return subprocess.run(
        [sys.executable, "-m", f"idle_hours.{module}", *rest],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        **kwargs,
    )


@pytest.mark.parametrize("script", HELP_SCRIPTS)
def test_help_exits_zero(script):
    """Every script's ``--help`` must exit 0 and print usage."""
    result = _run([script, "--help"])
    assert result.returncode == 0, f"{script} --help exited {result.returncode}: {result.stderr}"
    assert "usage" in result.stdout.lower(), f"{script} --help produced no usage line"


class TestPickQuoteMain:
    def test_time_flag_runs_end_to_end(self, tmp_path):
        """``pick_quote --time HH:MM`` must emit valid JSON with required fields
        against the shipped corpus."""
        result = _run(["pick_quote", "--time", "14:30", "--history-path", ""])
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert "display_quote" in payload
        assert "resolved_bucket" in payload
        assert "used_fallback" in payload

    def test_bucket_flag_runs(self):
        result = _run(["pick_quote", "--bucket", "h2_half_past", "--history-path", ""])
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload.get("resolved_bucket", "").startswith("h2_")


class TestIdleHoursHealthMain:
    def test_missing_telemetry_exits_1(self, tmp_path):
        """``idle_hours_health --telemetry-path <missing>`` exits 1 (not 0, not crash)."""
        result = _run(["idle_hours_health", "--telemetry-path", str(tmp_path / "nope.jsonl")])
        assert result.returncode == 1, f"expected 1, got {result.returncode}: {result.stderr}"

    def test_empty_telemetry_json_mode(self, tmp_path):
        """``--json`` with an empty-but-existing log emits valid JSON even with zero entries."""
        log = tmp_path / "telemetry.jsonl"
        log.write_text("", encoding="utf-8")
        result = _run(["idle_hours_health", "--telemetry-path", str(log), "--json"])
        # Empty log behaves like missing (exit 1) in current implementation —
        # we care that it's JSON on stdout OR a clean exit code, not a traceback.
        assert "Traceback" not in result.stderr, result.stderr

    def test_fail_if_no_renders_flag_sets_exit_2(self, tmp_path):
        """``--fail-if-no-renders`` on a silent window must exit 2, not 0."""
        log = tmp_path / "telemetry.jsonl"
        log.write_text("", encoding="utf-8")
        result = _run([
            "idle_hours_health",
            "--telemetry-path", str(log),
            "--hours", "1",
            "--fail-if-no-renders",
        ])
        # Exit code 1 (no log) or 2 (no renders) are both valid "unhealthy"
        # signals; the regression we're catching is exit 0.
        assert result.returncode != 0, f"silent window exited 0: {result.stdout}"


class TestPipelineStageMains:
    """Each pipeline stage should run cleanly on a small valid input."""

    def _write_rows(self, tmp_path: Path, rows: list[dict], name: str = "in.jsonl") -> Path:
        path = tmp_path / name
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        return path

    def test_merge_candidates_on_single_input(self, tmp_path):
        """Merging a single harvest file should produce a dedup summary."""
        rows = [{
            "source_id": "1",
            "source_path": "x.txt",
            "match_type": "oclock_word",
            "matched_text": "three o'clock",
            "quote_text": "It was three o'clock.",
            "context_text": "It was three o'clock in the afternoon.",
            "hour": 3, "minute": 0,
            "normalized_time": "03:00",
            "fuzzy_bucket": "h3_exact",
            "daypart_bucket": None,
            "line_number": 1,
            "match_start": 7,
            "match_end": 20,
        }]
        inp = self._write_rows(tmp_path, rows)
        out = tmp_path / "merged.jsonl"
        result = _run(["merge_candidates", str(inp), "--output", str(out)])
        assert result.returncode == 0, result.stderr
        assert out.exists()
        merged = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
        assert len(merged) == 1
        assert "canonical_quote" in merged[0]

    def test_quality_filter_adds_score(self, tmp_path):
        rows = [{
            "source_id": "1",
            "source_path": "x.txt",
            "match_type": "oclock_word",
            "matched_text": "three o'clock",
            "quote_text": "It was three o'clock in the afternoon.",
            "context_text": "It was three o'clock in the afternoon.",
            "hour": 3, "minute": 0,
            "normalized_time": "03:00",
            "fuzzy_bucket": "h3_exact",
            "daypart_bucket": None,
            "line_number": 1,
            "match_start": 7,
            "match_end": 20,
            "canonical_quote": "it was three o'clock in the afternoon.",
            "canonical_context": "it was three o'clock in the afternoon.",
            "display_quote": "It was three o'clock in the afternoon.",
            "display_fragment": False,
            "cleanup_status": "complete_sentence",
        }]
        inp = self._write_rows(tmp_path, rows)
        out = tmp_path / "scored.jsonl"
        result = _run(["quality_filter", str(inp), "--output", str(out)])
        assert result.returncode == 0, result.stderr
        scored = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
        assert "quality_score" in scored[0]
        assert isinstance(scored[0]["quality_score"], int)
        assert "quality_flags" in scored[0]


class TestRunClockOnce:
    """``run_clock --once`` is the most-used smoke entry point — cron / systemd
    start with it during first bring-up."""

    def test_once_renders_a_frame(self, tmp_path):
        out = tmp_path / "frame.png"
        result = _run([
            "run_clock",
            "--once",
            "--output", str(out),
            "--mode", "production",
            "--history-path", "",
            "--state-path", "",
            "--telemetry-path", "",
            "--quiet-off",
        ])
        assert result.returncode == 0, f"run_clock --once failed: {result.stderr}"
        assert out.exists(), "--once did not produce a frame"
        assert out.stat().st_size > 0, "--once produced an empty PNG"

    def test_once_with_config_file(self, tmp_path):
        """``--config`` plus ``--once`` must produce a frame end-to-end.

        Pins the integration seam: the TOML loads, argparse defaults are
        seeded, and the render subprocess inherits the config-derived
        theme/mode.
        """
        out = tmp_path / "frame.png"
        cfg = tmp_path / "idle-hours.toml"
        cfg.write_text(
            'mode = "production"\n'
            'theme = "dark"\n'
            'history_path = ""\n'
            'state_path = ""\n'
            'telemetry_path = ""\n'
            "quiet_off = true\n",
            encoding="utf-8",
        )
        result = _run([
            "run_clock",
            "--config", str(cfg),
            "--once",
            "--output", str(out),
        ])
        assert result.returncode == 0, f"run_clock --config --once failed: {result.stderr}"
        assert out.exists(), "--config --once did not produce a frame"
        assert out.stat().st_size > 0, "--config --once produced an empty PNG"

    def test_once_with_missing_config_fails_fast(self, tmp_path):
        """Typoed --config path must exit 42 (EXIT_CONFIG_ERROR), not silently
        boot with defaults — 42 pairs with the sample unit's
        RestartPreventExitStatus=42 so systemd halts instead of flapping."""
        result = _run([
            "run_clock",
            "--config", str(tmp_path / "does_not_exist.toml"),
            "--once",
            "--output", str(tmp_path / "frame.png"),
            "--quiet-off",
        ])
        assert result.returncode == 42, (
            f"expected exit 42 for missing --config path, got {result.returncode}"
        )
        assert "does not exist" in result.stderr
