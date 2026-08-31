"""CI-configuration fences: the required-status-check list must not drift.

``.github/rulesets/main-branch.json`` is the source of truth for what blocks a
merge into ``main``, but nothing in the repo consumes it — it is a payload a
human pushes to GitHub — so it can silently disagree with
``.github/workflows/ci.yml`` forever. That is exactly what happened (issue
#241): four real jobs ran on every pull request while only ``lint`` and the two
``test`` legs gated anything, leaving ``golden-render`` / ``web-ui-js`` /
``package-build`` / ``coverage`` advisory. Three of those four exist
*specifically because* the ``test`` matrix structurally cannot catch what they
catch, so an advisory one is a hole shaped like the reason it was written.

The invariant fenced here: **every CI job that runs unconditionally on a pull
request is a required status check, and every required context names a real
job.** Set equality, not containment, so adding a job forces a decision instead
of defaulting to advisory. A job that genuinely should not gate a merge goes in
``ADVISORY_JOBS`` below with a reason.

None of this can verify the *live* branch protection on GitHub — the committed
JSON is a description of intent until someone runs the sync command in
``.github/rulesets/README.md``. It can only guarantee the description stays
truthful about the workflow beside it.
"""
from __future__ import annotations

import json
from pathlib import Path

# PyYAML is declared in the [dev] extra and imported hard, not through
# ``importorskip``: a missing parser must fail this fence loudly rather than
# turn it into a silent green skip (the same reasoning as the ``web-ui-js``
# CI job existing beside ``tests/test_web_ui_js.py``).
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
RULESET_PATH = REPO_ROOT / ".github" / "rulesets" / "main-branch.json"

# Jobs deliberately excluded from the required set, with the reason. A job with
# a top-level ``if:`` is skipped automatically (see ``_pr_job_contexts``) — this
# list is for jobs that run on a pull request and still should not gate it.
# Empty today, on purpose: every job that runs on a PR currently gates it.
ADVISORY_JOBS: dict[str, str] = {}


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    """The ``on:`` block.

    PyYAML follows YAML 1.1, where the bare token ``on`` is a *boolean*, so
    the parsed key is ``True`` rather than the string ``"on"``. Accept either
    so this keeps working if the workflow ever quotes the key.
    """
    for key in (True, "on"):
        if key in workflow:
            return workflow[key]
    raise AssertionError("ci.yml has no `on:` trigger block")


def _load_required_contexts() -> list[str]:
    ruleset = json.loads(RULESET_PATH.read_text(encoding="utf-8"))
    checks = [rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks"]
    assert len(checks) == 1, "expected exactly one required_status_checks rule"
    return [entry["context"] for entry in checks[0]["parameters"]["required_status_checks"]]


def _matrix_contexts(job_id: str, job: dict) -> list[str]:
    """Expand a job into the status-check context name(s) GitHub reports.

    A matrix job reports one context per combination, named ``job (value)``
    (or ``job (v1, v2)`` for multiple dimensions), which is why the ruleset
    lists ``test (3.11)`` rather than ``test``.
    """
    matrix = job.get("strategy", {}).get("matrix", {})
    dimensions = [value for key, value in matrix.items() if key not in {"include", "exclude"} and isinstance(value, list)]
    if not dimensions:
        return [job_id]
    if len(dimensions) > 1:  # pragma: no cover - no multi-axis matrix in this repo yet
        pytest.fail(
            f"job {job_id!r} has a multi-axis matrix; extend _matrix_contexts to "
            "reproduce GitHub's context naming before relying on this fence"
        )
    return [f"{job_id} ({value})" for value in dimensions[0]]


def _pr_job_contexts() -> dict[str, list[str]]:
    """Contexts reported on a pull request, keyed by job id.

    A job-level ``if:`` means the job may report ``skipped``, and GitHub never
    treats a skipped context as satisfying a required check — such a job would
    block every merge forever if required, so it is excluded here rather than
    demanded.
    """
    jobs = _load_workflow()["jobs"]
    return {job_id: _matrix_contexts(job_id, job) for job_id, job in jobs.items() if "if" not in job}


class TestWorkflowTriggers:
    def test_ci_runs_on_pull_requests(self):
        assert "pull_request" in _triggers(_load_workflow())

    def test_coverage_job_is_not_conditional(self):
        """The ``--cov-fail-under`` floor has to run on the PR to gate it.

        This job was ``if: github.event_name == 'push'``, which made the
        workflow's own "blocks the merge" comment false: the gate could only
        fail after the code was already on ``main``.
        """
        coverage = _load_workflow()["jobs"]["coverage"]
        assert "if" not in coverage, (
            "coverage must run on pull_request — a required context reported as "
            "'skipped' is never satisfied, and a gate that only runs post-merge "
            "turns a rejected change into a red default branch (issue #241)"
        )

    def test_coverage_job_still_enforces_the_floor(self):
        steps = _load_workflow()["jobs"]["coverage"]["steps"]
        assert any("--cov-fail-under" in step.get("run", "") for step in steps), (
            "the coverage job is required precisely because it enforces a floor; "
            "without --cov-fail-under it is an artifact upload nothing acts on"
        )


class TestRequiredStatusChecks:
    def test_required_contexts_match_the_pull_request_jobs(self):
        expected = {
            context
            for job_id, contexts in _pr_job_contexts().items()
            if job_id not in ADVISORY_JOBS
            for context in contexts
        }
        actual = set(_load_required_contexts())

        missing = sorted(expected - actual)
        assert not missing, (
            f"CI job(s) run on every pull request but do not gate the merge: {missing}. "
            "Add them to .github/rulesets/main-branch.json (and re-apply the ruleset "
            "on GitHub — see .github/rulesets/README.md), or record them in "
            "ADVISORY_JOBS with a reason."
        )

        unknown = sorted(actual - expected)
        assert not unknown, (
            f"required status check(s) name no unconditional CI job: {unknown}. "
            "GitHub blocks a merge forever on a context nothing ever reports."
        )

    def test_required_contexts_have_no_duplicates(self):
        contexts = _load_required_contexts()
        assert len(contexts) == len(set(contexts))

    def test_conditional_jobs_are_not_required(self):
        """A tag-only job reports nothing on a PR, so requiring it deadlocks."""
        jobs = _load_workflow()["jobs"]
        conditional = {job_id for job_id, job in jobs.items() if "if" in job}
        assert "release-version" in conditional, "guard assumes release-version stays tag-only"
        assert conditional.isdisjoint(set(_load_required_contexts()))

    def test_ruleset_keeps_deletion_and_force_push_protection(self):
        rule_types = {rule["type"] for rule in json.loads(RULESET_PATH.read_text(encoding="utf-8"))["rules"]}
        assert {"deletion", "non_fast_forward"} <= rule_types
