# Contributing to LitClock

Thanks for considering a contribution. LitClock is a small hobby project, so
process is deliberately light — the goal is to make it easy for someone who
just wants to fix a typo, improve a quote, or add a pipeline stage.

This doc covers the dev environment, how the pipeline fits together, and what
to do when contributing each kind of change. The deep architecture reference
lives in [`CLAUDE.md`](CLAUDE.md) — if you're modifying the runtime or
pipeline, skim that first.

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
Security issues go through the reporting process in [`SECURITY.md`](SECURITY.md),
not public issues.

## Dev setup

Python 3.11 or 3.12. The runtime is pure stdlib + Pillow; the Pi deployment
additionally needs `inky` and `gpiozero`.

```bash
git clone https://github.com/gkoch02/litclock.git
cd litclock
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Verify:

```bash
pytest
ruff check .
python3 run_clock.py --once --buttons-off     # one-shot render to output/current.png
```

`pip install -e ".[dev]"` is the single source of truth for dev deps; CI
installs the same way. Don't hardcode `pytest pytest-cov ruff Pillow` in new
workflow files — they'll drift.

## Before you open a PR

- **Run the tests.** `pytest` should pass locally. The suite is fast (seconds,
  not minutes).
- **Run the linter.** `ruff check .` — rules `E`, `W`, `F`, `I`; line length
  130; `E501` ignored. `ruff check --fix .` handles import ordering.
- **Don't commit generated artifacts you didn't mean to.** `output/` is
  gitignored except for `.gitkeep`. `data/gutenberg/` is gitignored entirely.
- **Keep commits focused.** One logical change per commit makes bisect useful
  later.

## What kind of change are you making?

### Runtime code (`run_clock.py`, `runtime_*.py`, `render_quote.py`, `pick_quote.py`, `web_server.py`, …)

The runtime is a thin orchestrator (`run_clock.py`) that delegates to seven
`runtime_*` siblings. The module boundary, lock discipline, and thread
ownership rules are documented in the "Runtime Module Architecture" section of
`CLAUDE.md` — please read that section before restructuring any of those
modules. Highlights:

- Three locks: `render_lock` (coarse, serialises panel pushes),
  `state.lock` (fine, guards `RuntimeState` fields), and `ledger_lock` (file
  I/O for `history.jsonl`). Nesting is allowed **only** in the documented
  direction.
- Button and web handlers route through the same `action_*` functions via
  `_button_render_gate`. Don't add a parallel "web render path" — convergence
  on one path is the point of the refactor.
- Any new file the next tick reads needs to go through
  `atomic_io.atomic_write_*`. Don't reintroduce naive `open("w")`.

### Corpus / quote content

Two different files depending on the kind of change:

| You want to… | Edit this | Effect |
|---|---|---|
| Fix the wording of a specific quote (bad excerpt boundary, typo, wrong author) | `assets/content_overrides.json` | Re-applied every time the pipeline re-bakes; durable |
| Ban a source, boost a source, pin a source to a bucket | `assets/selection_overrides.json` | Runtime, also editable via the curator UI |

**Never edit `assets/quote_database.jsonl` or `assets/candidates-attributed.jsonl`
by hand.** They're derived artifacts; your edit will be clobbered on the next
pipeline re-run. If you find yourself wanting to override more than a handful
of rows for the same reason, that's a signal that a pipeline stage has a bug —
push the fix into the miner / cleaner / quality filter rather than
accumulating per-row patches.

After editing `content_overrides.json`, re-run the tail of the pipeline:

```bash
python3 apply_content_overrides.py assets/candidates-attributed.jsonl
python3 bake_quote_database.py assets/candidates-attributed.jsonl
```

Commit the updated `assets/quote_database.jsonl` alongside your override
change — a raw-corpus commit with no matching bake means your fix is
invisible to the appliance.

### Adding quotes from a new Gutenberg book

There's a one-shot driver:

```bash
# Add the ID to gutenberg_dawn_expansion_ids.txt, then:
bash run_dawn_expansion.sh
```

That drives the full pipeline and commits the updated
`candidates-attributed.jsonl`, `quote_database.jsonl`, and coverage snapshot
together. Safe to re-run (downloads cache, merge dedupes).

### Pipeline stages

If you're touching a pipeline script, the flow (also in `CLAUDE.md`) is:

```
gutenberg_time_miner → merge_candidates → clean_display_quotes →
  quality_filter → enrich_metadata → apply_content_overrides →
  bake_quote_database
```

- `buckets.py` is the single source of truth for the fuzzy-bucket rounding
  rule. Don't reintroduce a second copy of the state table in a new script.
- JSONL rows accumulate fields as they flow through — preserve the existing
  schema, add new fields rather than renaming.
- The baked DB's scoring components are cross-checked between
  `bake_quote_database.py` and `pick_quote.py` via `BAKED_SCORE_COMPONENTS`.
  Bump `BAKED_SCORE_SCHEMA_VERSION` if you change order, length, or
  semantics.

### Rendering / typography

`render_quote.py` is designed around the Inky Impression 7.3 Spectra 6 (800×480,
6-colour palette). Any colour change goes through `snap_image_to_palette`.

Ten themes ship today (`default`, `dark`, `scholar`, `newsprint`, `nightvision`,
`blueprint`, `illuminated`, `bauhaus`, `risograph`, `comic`). Adding an
eleventh means wiring it into all of:

- `render_quote.THEMES` — palette dict (every colour must come from `SPECTRA6`)
- `render_quote.THEME_ORDER` — append; this is what button B cycles through
- `render_quote.THEME_FONTS` — typeface chain (otherwise the renderer falls
  back to Playfair Display, defeating the per-theme typography)
- `display_inky.THEME_SATURATION` — `0.5` for light grounds, `0.7` for
  dark / coloured grounds
- `--theme` argparse `choices` in `run_clock.py` (the
  `TestActionThemeCycle::test_cli_theme_choices_match_theme_order` test
  pins this in lockstep with `THEME_ORDER`)

Test visually with the contact sheet — re-render at least one light-ground
and one dark-ground theme to catch palette / contrast regressions:

```bash
python3 contact_sheet.py --theme default --output output/contact-default.png
python3 contact_sheet.py --theme dark    --output output/contact-dark.png
# add the new theme:
python3 contact_sheet.py --theme <new>   --output output/contact-<new>.png
```

## Testing

- One `tests/test_<script>.py` per main script, class-based. Use the
  `make_row` / `sample_row` / `tmp_jsonl` fixtures from `tests/conftest.py`
  rather than building rows inline.
- The autouse `_isolate_home` fixture points `$HOME` at a per-test tmp dir,
  so tests can safely use default `--state-path` / `--history-path` /
  `--telemetry-path` / `--pidfile` values.
- Hardware-touching modules (`display_inky.py`, `inky_buttons.py`) are tested
  with the hardware call mocked; new hardware code should follow the same
  pattern (local import inside a function, Pillow/GPIO stubbed in the test).
- Renderer changes must either preserve the committed golden images in
  `tests/golden/renderer/` (most common — the Spectra 6 palette snap makes
  the fixtures stable across FreeType drift) or regenerate them in the same
  PR with `UPDATE_RENDER_GOLDEN=1 pytest tests/test_render_golden.py`.
  Inspect the regenerated PNGs in review: a legitimate redesign changes many
  pixels in structurally sensible ways; an accidental regression usually
  moves a single element (e.g. the bold time phrase loses its accent colour).

## Commit messages and PRs

- Commit subjects: present tense, under ~70 characters
  ("Add quiet-hours manual toggle", not "Added …"). Body explains the *why*
  if it's not obvious from the diff.
- PRs: short summary of what changed and any intentional trade-offs. Link
  relevant issues. If the change is corpus-only, the PR body is fine at one
  line.
- CI runs on every push to `main` and every PR (lint + pytest matrix on
  Python 3.11/3.12). Green CI is a prerequisite for merge.

## Reporting bugs

Open a GitHub issue with:

- what you expected to happen,
- what actually happened,
- reproduction steps (command-line flags, time of day if relevant — some
  bugs only surface in specific buckets),
- relevant log lines from `journalctl -u litclock` or the terminal.

For the appliance specifically, `python3 litclock_health.py --hours 24`
output is usually the fastest way to share state.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE) that covers the rest of the project.
