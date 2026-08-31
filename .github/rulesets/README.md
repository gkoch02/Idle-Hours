# Branch rulesets

`main-branch.json` is the **source of truth** for the protection applied to the
default branch. It is a GitHub ruleset payload, not a snapshot: edit it here,
then push the change to GitHub (below). Nothing in GitHub Actions applies it
automatically, so a merged edit to this file has not taken effect until someone
runs the sync command.

## Applying it

```bash
# First time (creates the ruleset):
gh api --method POST /repos/gkoch02/Idle-Hours/rulesets \
  --input .github/rulesets/main-branch.json

# Subsequent edits (replaces the existing ruleset in place):
gh api /repos/gkoch02/Idle-Hours/rulesets --jq '.[] | select(.name=="Protect main") | .id'
gh api --method PUT /repos/gkoch02/Idle-Hours/rulesets/<id> \
  --input .github/rulesets/main-branch.json
```

Verify afterwards with:

```bash
gh api /repos/gkoch02/Idle-Hours/rulesets/<id> --jq \
  '.rules[] | select(.type=="required_status_checks") | .parameters'
```

## Which checks are required, and why all of them are

Every job in `.github/workflows/ci.yml` that runs unconditionally on a pull
request is a required status check. `tests/test_ci_required_checks.py` fences
that as a set equality, so adding a CI job without deciding what it gates fails
the suite rather than landing silently as an advisory job.

That rule exists because the repo had drifted the other way (issue #241). Only
`lint` and the two `test` legs were required, which left the three jobs that
exist *precisely because the `test` matrix structurally cannot catch what they
catch* unable to block anything:

- **`golden-render`** — the only guard on the 63 committed PNG fixtures. Run
  [32632086003](https://github.com/gkoch02/Idle-Hours/actions/runs/32632086003),
  the merge commit for #217, went red on `main` with `golden-render` failing,
  while the PR's own run was fully green.
- **`web-ui-js`** — the only thing that actually runs the curator UI's
  JavaScript. `tests/test_web_ui_js.py` bridges the same suite into pytest but
  *skips* when node is absent, and it lives inside the required `test (3.12)`
  context — which goes green on a skip. So a JS regression could reach `main`
  past a green required gate, which is the exact failure the dedicated job was
  created to prevent.
- **`package-build`** — the only guard on install-time failure modes
  (`packages.find` misconfiguration, missing `package-data`, optional-dep
  leakage at import). Every other job installs with `pip install -e .`, which
  cannot see any of them.
- **`coverage`** — the `--cov-fail-under=95` line+branch floor. It was also
  `if: github.event_name == 'push'`, so it did not run on pull requests at all.
  Making it required and making it run on PRs are one decision, though not for
  the reason you might expect: GitHub reports a job skipped by its `if:` with
  conclusion `skipped`, and **a skipped check counts as success** for a
  required status check. Requiring it while it stayed conditional would not
  have deadlocked merges — it would have produced a gate that went green on
  every pull request without measuring a line, which is worse than leaving it
  advisory, because it looks enforced.

`release-version` is deliberately **not** required. It is tag-only
(`if: startsWith(github.ref, 'refs/tags/v')`), so on a pull request it reports
`skipped` → success: requiring it would add a context that is vacuously green,
not a gate. Note this means a job-level `if:` is *not* by itself grounds for
leaving a job advisory — a future job conditioned on something that can be true
on a pull request (a path filter, a label, a non-fork head) would really run and
could really fail. `tests/test_ci_required_checks.py` therefore classifies every
job by hand rather than excusing conditional ones automatically.

## `strict_required_status_checks_policy`

Currently `false`: a pull request may merge without being up to date with
`main`. This is the setting the #217 failure above turns on — that run was the
semantic-merge case, green against the PR head and red once combined with what
had landed on `main` in the meantime, and no list of required contexts can
prevent it because the contexts all passed.

Setting it to `true` is the only fix for that class, and the only change here
with an ongoing cost: every out-of-date pull request needs a merge or rebase
(and a full CI re-run) before it can go in, and each merge invalidates the
others. Left `false` pending an explicit call; flip this one boolean and re-run
the sync command above to change it.
