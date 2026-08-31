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

The invariant fenced here: **every job in ci.yml is either a required status
check or an explicit entry in ``ADVISORY_JOBS``, and every required context
names a real job.** Set equality, not containment, so adding a job forces a
decision instead of defaulting to advisory.

Everything this module cannot model, it fails on rather than guesses at — an
explicit ``name:``, a matrix ``include`` / ``exclude``, an unresolved ``${{ }}``
expression. A fence that quietly stops covering a case is worse than no fence,
because the green tick keeps implying it still does.

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

# Jobs deliberately excluded from the required set, mapped to the reason.
#
# A job-level ``if:`` is NOT grounds for automatic exclusion, and assuming it
# was is the trap this map exists to close. GitHub reports a job skipped by its
# ``if:`` with conclusion ``skipped``, and a skipped check **counts as success**
# for a required status check — so requiring a conditional job never deadlocks a
# merge, it just yields a context that is vacuously green whenever the condition
# is false. That cuts both ways: a future job conditioned on something true on
# some pull requests (a path filter, a label, a non-fork head) would run and
# could fail, and excluding it by the mere presence of an ``if:`` would leave it
# advisory exactly when it matters. So every job is classified by hand.
#
# (The pending-forever case is a *workflow* skipped by path or branch filtering,
# where the check never reports at all. ci.yml has no such filter on
# ``pull_request``, so it cannot arise here.)
ADVISORY_JOBS: dict[str, str] = {
    "release-version": (
        "tag-only (if: startsWith(github.ref, 'refs/tags/v')). It reports "
        "'skipped' on every pull request, and a skipped check counts as "
        "success, so requiring it would add a context that is green without "
        "having checked anything — assurance theatre, not a gate."
    ),
}


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


def _matrix_legs(job_id: str, job: dict) -> list[str] | None:
    """The matrix values GitHub appends to a context name, or None if no matrix.

    Fails on ``include`` / ``exclude`` rather than ignoring them: both change
    which legs exist, so silently dropping them would let an added leg run
    un-required, or leave an excluded leg demanded by a context that never
    reports (the one case that really does block a merge forever).
    """
    matrix = job.get("strategy", {}).get("matrix")
    if not matrix:
        return None
    for key in ("include", "exclude"):
        if key in matrix:
            pytest.fail(
                f"job {job_id!r} uses a matrix {key!r} clause, which changes the set of "
                "legs GitHub reports. Teach _matrix_legs to expand it before relying on "
                "this fence — an unexpanded include leaves a running leg un-required, and "
                "an unexpanded exclude demands a context nothing ever reports."
            )
    dimensions = [value for value in matrix.values() if isinstance(value, list)]
    if len(dimensions) != 1:
        pytest.fail(
            f"job {job_id!r} has a {len(dimensions)}-axis matrix; extend _matrix_legs to "
            "reproduce GitHub's context naming ('job (v1, v2)') before relying on this fence"
        )
    return [str(value) for value in dimensions[0]]


def _job_contexts(job_id: str, job: dict) -> list[str]:
    """The status-check context name(s) GitHub reports for one job.

    Default naming is the job *id*, with a matrix job reporting one context per
    leg as ``id (value)`` — which is why the ruleset lists ``test (3.11)``
    rather than ``test``. An explicit ``name:`` overrides the id entirely, so
    ignoring it would let the ruleset keep requiring the old id: a context
    nothing reports, which leaves every pull request pending forever once the
    ruleset is applied. Neither that nor an unresolved expression is guessed at.
    """
    legs = _matrix_legs(job_id, job)
    name = job.get("name")
    if name is None:
        return [job_id] if legs is None else [f"{job_id} ({leg})" for leg in legs]
    if "${{" in name:
        pytest.fail(
            f"job {job_id!r} has a templated name {name!r}; this fence cannot resolve "
            "workflow expressions. Give the job a literal name, or teach _job_contexts "
            "to render this one."
        )
    if legs is not None:
        pytest.fail(
            f"job {job_id!r} combines an explicit name {name!r} with a matrix. GitHub "
            "renders the name per leg instead of appending the matrix suffix, so the "
            "context names cannot be derived here — teach _job_contexts the rendering rule."
        )
    return [name]


def _workflow_contexts() -> dict[str, list[str]]:
    """Every job in ci.yml, mapped to the context name(s) it reports."""
    return {job_id: _job_contexts(job_id, job) for job_id, job in _load_workflow()["jobs"].items()}


def _load_required_contexts() -> list[str]:
    ruleset = json.loads(RULESET_PATH.read_text(encoding="utf-8"))
    checks = [rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks"]
    assert len(checks) == 1, "expected exactly one required_status_checks rule"
    return [entry["context"] for entry in checks[0]["parameters"]["required_status_checks"]]


class TestWorkflowTriggers:
    def test_ci_runs_on_pull_requests(self):
        assert "pull_request" in _triggers(_load_workflow())

    def test_coverage_job_is_not_conditional(self):
        """The ``--cov-fail-under`` floor has to actually run to mean anything.

        This job was ``if: github.event_name == 'push'``, which made the
        workflow's own "blocks the merge" comment false. Note the failure mode
        is the *opposite* of a deadlock: a job-level skip reports as success,
        so adding ``coverage`` to the ruleset while keeping the ``if:`` would
        have produced a required check that went green on every pull request
        without running a single test — a worse outcome than leaving it
        advisory, because it looks enforced.
        """
        coverage = _load_workflow()["jobs"]["coverage"]
        assert "if" not in coverage, (
            "coverage must run on pull_request: a required check that is skipped "
            "counts as success, so a conditional coverage job would report green "
            "without measuring anything (issue #241)"
        )

    def test_coverage_job_still_enforces_the_floor(self):
        steps = _load_workflow()["jobs"]["coverage"]["steps"]
        assert any("--cov-fail-under" in step.get("run", "") for step in steps), (
            "the coverage job is required precisely because it enforces a floor; "
            "without --cov-fail-under it is an artifact upload nothing acts on"
        )


class TestRequiredStatusChecks:
    def test_every_job_is_classified(self):
        """No job may be neither required nor explicitly advisory."""
        unknown = sorted(set(ADVISORY_JOBS) - set(_workflow_contexts()))
        assert not unknown, f"ADVISORY_JOBS names job(s) that no longer exist in ci.yml: {unknown}"

    def test_required_contexts_match_the_non_advisory_jobs(self):
        contexts = _workflow_contexts()
        expected = {
            context
            for job_id, job_contexts in contexts.items()
            if job_id not in ADVISORY_JOBS
            for context in job_contexts
        }
        actual = set(_load_required_contexts())

        missing = sorted(expected - actual)
        assert not missing, (
            f"CI job(s) run but do not gate the merge: {missing}. Add them to "
            ".github/rulesets/main-branch.json (and re-apply the ruleset on GitHub — see "
            ".github/rulesets/README.md), or record them in ADVISORY_JOBS with a reason."
        )

        unknown = sorted(actual - expected)
        assert not unknown, (
            f"required status check(s) name no non-advisory CI job: {unknown}. A context "
            "nothing ever reports stays pending and blocks every merge."
        )

    def test_required_contexts_have_no_duplicates(self):
        contexts = _load_required_contexts()
        assert len(contexts) == len(set(contexts))

    def test_advisory_jobs_carry_a_reason(self):
        for job_id, reason in ADVISORY_JOBS.items():
            assert reason.strip(), f"advisory job {job_id!r} needs a reason, not an empty string"

    def test_ruleset_keeps_deletion_and_force_push_protection(self):
        rule_types = {rule["type"] for rule in json.loads(RULESET_PATH.read_text(encoding="utf-8"))["rules"]}
        assert {"deletion", "non_fast_forward"} <= rule_types
