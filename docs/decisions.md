# Decisions and non-goals

What Idle Hours deliberately does not do, and why. Each entry links to where the full reasoning lives.

- **The `digital` matcher's in-prose defect stays unfixed** ([#159](https://github.com/gkoch02/Idle-Hours/issues/159), closed won't-fix). The bug is in a code path `--strict` never runs, and the committed corpus was never built from digital matches. A fix would need a non-strict re-mine to have any effect.
- **No minutes-less "ten past two" pattern.** "Ten to one" is betting odds as often as it is a time, so the false positives would outweigh the gain ([`CLAUDE.md`](../CLAUDE.md), Match Types).
- **The hanging opening quote mark stays at a fixed x.** A version that fitted the mark into the gutter was tried and reverted: the shrunken marks lost the gesture. The mark running under the first word on wider measures is a style choice, not a bug.
- **Hand fixes go in a sidecar, not in repair scripts.** Per-row fixes live in [`content_overrides.json`](../idle_hours/assets/content_overrides.json) and are re-applied at the end of every pipeline run, so a re-mine cannot silently undo them. Many overrides for the same reason count as a bug in the upstream stage, to be fixed there.
- **The curator UI reads the raw corpus, not the baked database.** An operator needs to see the rows the baker dropped (daypart-only, below the quality floor) to understand why a quote never appears.
- **Selection overrides are not baked.** Bans, boosts and preferred buckets stay a runtime file because the web UI edits them, and re-baking on every click would block the UI. A ban is a cheap post-filter.
- **The web UI runs inside the clock process.** A separate service would need its own path to the panel. In-process, every UI action goes through the same render lock and code path as the physical buttons.
- **Override loading fails open.** A truncated or mistyped `selection_overrides.json` degrades to no overrides plus a warning. Raising would put the panel into render backoff, which is worse than an ignored ban.
- **Themes do not print the time as digits** unless the object depicted is genuinely a clock (the `vhs` on-screen display). The quote's matched phrase carries the time.
- **Rejected design approaches are recorded per theme.** Most entries in [`docs/themes.md`](themes.md) have a "Tried and rejected" note so the same dead end is not explored twice.
