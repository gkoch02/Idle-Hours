<!--
Thanks for contributing to Idle Hours. Fill in what applies and delete the
rest. A corpus-only change (new quotes, a content override, a re-bake) is
fine at one line under Summary. See docs/CONTRIBUTING.md for conventions.
-->

## Summary

<!-- What changed, and why. If this fixes a bug, say what a user saw on the
panel (or in the CLI / UI) and what the root cause turned out to be. Link
the issue: "Fixes #123". -->

## Trade-offs

<!-- Anything you chose deliberately that a reviewer might question: a
narrower fix than the obvious one, a behaviour left alone, a constant read
off a measurement. Delete this section if there is nothing to say. -->

## Testing

<!-- Check what you ran. Every PR needs the first two. -->

- [ ] `ruff check .` passes
- [ ] `pytest` passes locally
- [ ] New or changed behaviour has a test that fails on `main` without the fix
- [ ] Renderer change: golden fixtures either still pass, or were intentionally
      re-baselined with `UPDATE_RENDER_GOLDEN=1 pytest tests/test_render_golden.py`
      and the regenerated PNGs are in this PR
- [ ] Corpus change: `idle-hours bake` was run and `quote_database.jsonl` is
      committed alongside the raw corpus

## Appliance impact

<!-- Does this change what an operator sees on the panel or has to do on
their Pi? For example: a render looks different, a new config key or flag,
a systemd unit change, a migration step. Say "None" if it is invisible. -->

## Docs

- [ ] `CLAUDE.md` updated if this touches architecture, invariants, a theme,
      or anything it already documents
- [ ] `README.md` updated if this changes a user-facing command or the theme table
