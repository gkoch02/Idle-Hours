# Plan: split `render_quote.py` into a package (issue #335)

## Context

`idle_hours/render_quote.py` is now 34,527 lines with 938 top-level defs (it was trimmed by #336, so it is no longer ~40k). It holds the layout engine, the dither and bloom primitives, 38 border-painter themes, 50 custom-frame themes, the registries and the CLI. Every theme change touches it, which makes diffs hard to review and duplicated helpers hard to spot.

The issue's proposed shape (`core` / `primitives` / `themes/<name>.py`, built in stages) is right. It understates one thing that decides whether the split works at all.

**Python patches names where they are looked up, not where they are defined.** About 85 test sites, plus `scripts/generate_theme_previews.py`, do `monkeypatch.setattr(rq, "X", …)` or `rq.X = …`. Today that works because every function reads its globals from the single `rq` namespace. Once a function lives in `themes/tarot.py`, patching `rq._tarot_paint_card_name` succeeds without error and changes nothing. Tests then pass while testing nothing. The decoration fence (`tests/test_theme_decoration.py`) and the `rq.datetime` swap for the clock-dependent themes both have this problem. The plan below is mostly about turning that silent failure into a loud one.

Other constraints found in exploration:

- **`run_clock` runs the renderer by file path.** The default is `--render-script "render_quote.py"` (`run_clock.py:161`), resolved at :859 and executed with `subprocess.run([sys.executable, path, …])`. Preflight checks for the file at :1734 and :1781. Both config files set `render_script = "render_quote.py"`. If the file disappears, every appliance whose config was copied from `config.toml.example` fails preflight with exit 42 and stays down.
- **`BASE_DIR = Path(__file__).resolve().parent`** (line 26) anchors about 120 font paths and 8 plate paths. Inside a subpackage it would resolve one directory too deep.
- **Cross-theme coupling is small but real.** About 20 theme-to-theme private calls: orbital→culture, codex→vitrail, photo→autochrome, vinyl/lieder→`_astrarium_paint_cream_wash`, hal/lumon/hitchhiker→`_crt_paint_scanlines`, `_TAROT_ROMAN_NUMERALS` used by four themes, yorha→lumon, escritoire→codex/metro. Several widely shared helpers also live inside theme regions: `_row_digest` (22 themes) in lieder, `position_noise` (9) in betweenus, `paint_craquelure` (3) in bosch, and `fit_text_to_width` / `draw_tracked` (14–19) under "mount furniture".
- **Module state.** There are `global` rebinds (`_FONT_FALLBACK_WARNED`, `_TRISOLARIS_*`, `_BOSCH_RANK_FIELD`), about 30 scene and plate caches, and painter-function-keyed caches. Nothing uses `globals()` or builds names dynamically, so dispatch goes only through `_BORDER_PAINTERS` and `_FRAME_RENDERERS`. That keeps the move mechanical.
- **`render()` calls some border painters by global name**, not through the registry: the `_CLEAR_RECT_PADS` themes at about :34280. That is why the border fence patches two places.

## Target shape

```
idle_hours/render_quote/
  __init__.py      facade: the public API (__all__) + the patch guard (below)
  __main__.py      `python -m idle_hours.render_quote` → cli.main()
  _paths.py        PACKAGE_DIR (= idle_hours/), font and plate path constants; BASE_DIR kept as an alias of PACKAGE_DIR
  clock.py         now(): the single wall-clock seam (sleep frame, astrarium, vinyl)
  palette.py       SPECTRA6, BAYER tables, snap_image_to_palette, _PANEL_INKS, _dither_calibrated
  fonts.py         _FONT_CACHE, load_font, glyph fallback, theme_font_candidates
  layout.py        LAYOUTS, choose_layout, tokenize/wrap/fit/fit_quote_balanced, justify_flags
  text.py          draw_text*, dithered / faux-gray / chroma-shift text, _draw_text_body
  primitives/      dither.py (dither_image_to_palette, _load_dithered_plate), bloom.py (paint_neon_mask),
                   relief.py (relief, hatched tone, flow strokes, shade_height_field, craquelure),
                   noise.py (_white_noise, _smooth_noise, position_noise, _bayer_threshold_field, swatch stipple)
  furniture.py     _clock_hour12/_clock_hh_mm, _row_digest, tracked text, fit_text_to_width, byline helpers,
                   _place_quote/_paint_placed, paint_mount_card, wrap_quote_into_masks
  frames.py        source card, static message, sleep frame, diags
  themes/
    __init__.py    explicit, ordered import list → registry (no pkgutil auto-discovery)
    _shared.py     helpers promoted from one theme to several (crt scanlines, roman numerals, cream wash, stained-glass fill)
    _culture_common.py   culture + orbital family
    <theme>.py     one per theme: painters, frame or border, scene caches, tuning constants
  registry.py      ThemeSpec + derived tables (final phase)
  render.py        render(), dispatch
  cli.py           parse_args, pick_quote wrapper, parse_pin_quote, main
```

**Layering rule, enforced by a test.** Imports may only point downward:

1. `_paths` / `clock`
2. `palette`
3. `fonts`
4. `layout` / `text`
5. `primitives`
6. `furniture`
7. `themes/_shared*`
8. `themes/<x>`
9. `registry`
10. `render`
11. `cli`

A theme module never imports another theme module. If two themes need the same thing, it is promoted with a neutral name.

**Import convention inside the package.** Use `from ..primitives.bloom import paint_neon_mask`, so function bodies move without edits. The consequence is that a test patches the binding in the module that reads it, e.g. `themes.bakelite.paint_neon_mask`. That is more precise than today, not less.

**One exception: the clock seam.** It is reached through its module object (`clock.now()` after `from .. import clock`), never imported by name. A name import gives each caller its own binding. The golden suite, the preview script and the fingerprint would then have to patch every clock-reading module rather than one function, and a module they missed would expire its golden overnight. The AST fence in `tests/test_render_golden.py` rejects `from … import _now` / `now` anywhere in the package.

## The patch guard (how the facade avoids becoming a permanent silent shim)

`render_quote/__init__.py` sets `sys.modules[__name__].__class__` to a small `ModuleType` subclass whose `__setattr__` checks every write to a non-public name:

- **Exactly one submodule binds the name:** forward the write there, and to the facade. This is transitional.
- **Zero or several submodules bind it:** raise `AttributeError`, naming the module(s) to patch instead.

This keeps PR 1 (the mechanical move into `_monolith.py`) at zero test churn, because everything has one owner then. As code spreads out, any patch that would silently stop working raises instead. The final phase deletes the forwarding branch. After that, writes to private names on the facade always raise, and reads of private names go away with the private re-exports.

What remains permanently is `__all__`: `render`, `main`, `THEMES`, `THEME_ORDER`, `CYCLE_EXCLUDED_THEMES`, `load_font`, `META_FONT_CANDIDATES`, `photo_source_stamp`, `clear_photo_cache`, `render_sleep_frame`, `render_source_card`, `snap_image_to_palette`, `dither_image_to_palette`, `BASE_DIR`, and whatever else `contact_sheet`, `web_server`, `theme_names` and the scripts actually use. That is an intentional API, not a shim.

## PR sequence (each one green, each one proven pixel-identical)

**Proof tool, added in PR 0a.** `scripts/render_fingerprint.py` renders every theme across the golden scenarios with the clock pinned and writes a sha256 of each PNG's bytes to JSON. Every split PR must produce exactly the same fingerprints as `main`. The golden suite's 0.1% tolerance is too loose to prove a pure move. The tool stays afterwards for any future refactor.

**PR 0a: clock seam (still in the monolith). Done.** Add `_now()` and route `render_sleep_frame`, astrarium and vinyl through it. Switch `test_render_golden.py` (:708, :870), `test_render_quote_themes.py:1713`, `test_generate_theme_previews.py` and `scripts/generate_theme_previews.py:173` from swapping `rq.datetime` to patching that one seam. Keep `CLOCK_DEPENDENT_THEMES` in the test. Add the fingerprint script.

**PR 0b: run the renderer as a module. Done.** The sentinel landed as `"auto"`, not `""`; it matches `--quiet-image auto`, and an empty value stays a preflight error. In `run_clock.render_now`:
- When `render_script` is empty or the legacy literal `render_quote.py`, run `[sys.executable, "-m", "idle_hours.render_quote", …]`. Any other value keeps today's path behaviour, so operators' custom renderers still work.
- Log a one-time deprecation note for the legacy literal.
- Make preflight (`_preflight_paths`) skip the file check in module mode.
- Change the default to `""` in `CONFIG_SCHEMA`, `config.toml.defaults`, `config.toml.example` and the docs.
- Update `test_repo_default_render_script_exists` and the fake-script tests (`test_run_clock.py:5347–5419`).
- The CI `--once` smoke test exercises the real path.

This lands before the split, so the split never touches the runtime and deployed configs keep working through the alias.

**PR 1: mechanical package conversion. Done.** The guard lives in `_facade.py`, not `__init__.py`. Reads fall through to the submodules live instead of being copied, so a global the renderer rebinds can't go stale. The owner map is a snapshot, because `mock.patch.object` restores by delete-then-set.
- `git mv idle_hours/render_quote.py idle_hours/render_quote/_monolith.py`, which preserves blame.
- `_monolith` imports `BASE_DIR` from `_paths` (`PACKAGE_DIR = Path(__file__).resolve().parent.parent`).
- Add the `__init__.py` facade, which re-exports everything from `_monolith` and installs the guard, plus `__main__.py`.
- Make `tests/test_packaging.py`'s `_package_modules_on_disk` recurse into subpackages.
- No other test changes. Fingerprints identical.

**PR 2: core extraction. Done**, with these departures from the list below:
- `primitives` is one module, not a subpackage. At about 780 lines it doesn't need splitting yet.
- A `theme_tables` layer holds `THEMES`, `THEME_ORDER`, `THEME_FONTS` and the per-theme flags until the registry stage derives them. `THEME_FONTS` is built from the font fallback chains, and `fonts` reads `THEME_FONTS`. So the chains live in `_paths`, below `theme_tables`, and the loader lives in `fonts`, above it.
- `frames` stays in `_monolith`: the sleep frame and source card call `render()`, so they move with it.
- The clock seam became `clock.now()`.
- Every test patch the guard refused was repointed at the module that reads the name: `_monolith` for a theme's call site, `text` for `_draw_text_body`'s. Three helpers (`normalize_dashes`, `_bold_stroke_for_theme`, `fallback_title`) landed one layer lower than first planned, because the layer check found them used from below.

The original plan for this PR:
- Move `_paths`, `palette`, `fonts`, `layout`, `text`, `primitives/*`, `furniture` and `frames` out of `_monolith`.
- Promote the shared helpers that sit in theme regions: `_row_digest`, `position_noise`, `paint_craquelure`, `_fill_swatch_stipple`, `tracked_width`, `draw_tracked`, `fit_text_to_width` and the byline helpers.
- Migrate the patches the guard now rejects (`paint_neon_mask`, `draw_text_dithered`, `_FONT_FALLBACK_WARNED`, …) to their binding modules.
- Teach `test_theme_decoration.py` a `theme_module(theme)` lookup: the theme module if it exists, else `_monolith`. Its `dir()` scan and patches then target the right namespace mid-migration.
- Add `tests/test_render_quote_layering.py`, an AST check of the import DAG and of "no theme imports a theme".

**PR 5a: `themes/` skeleton and shared theme code. Done.** `render_quote/themes/` exists, with `_shared.py` as a layer between `furniture` and `_monolith`. These departures from the plan below:
- Borrowed code moved under its **original names**. That covers tarot's numerals, astrarium's cream wash, vitrail's glass fill, codex's script (with its reach constants), metro's ellipsis, lumon's phrase boxes, the CRT raster and the autochrome plate. Neutral names would have churned codex's constants, the tests that cite these names and the `docs/themes.md` design notes, and bought no behaviour.
- Culture and orbital were left for their own PR, as a family.
- Instead of a `theme_module(theme)` lookup, the decoration fence's `_neuter` patches **every module binding the same object**. A shared helper is bound in `_shared` and again in each importer, so patching only the definer would let the importers call the original. This also needs no change as each theme moves.
- The layering test recurses into subpackages, resolves relative imports by level, and fails any theme module that imports another theme module.

**PR 5b: the border themes. Done**, in one PR rather than two. The fingerprint and the AST check prove a move, so reading the moved lines buys little. 152 statements became 36 modules under `themes/`: `betweenus` and `betweenus_dark` share a painter and a module. A statement moved with a theme if its name carries the theme's prefix, or if only that theme's code uses it. Departures:
- `_GUNMETAL_PALETTE` moved to `_shared`, because grimdark (border) and control (frame, through `_CONCRETE_PALETTE`) both use it.
- `themes/__init__.py` lists the modules in `THEME_MODULES`, and the facade installs them between `themes._shared` and `_monolith`. The layering test fails if a module on disk is missing from it or from the `TYPE_CHECKING` re-export.
- No test needed repointing. A patch on a border helper reaches its one binding in the theme module, and the decoration fence's `_neuter` covers the painters `_monolith` also imports.
- `_BORDER_PAINTERS` and the by-name calls in `render` stay in `_monolith` until the registry PR.

**PR 5c: the frame themes. Done**, all 50 in one PR rather than about five. The map that was meant to guide the batching found almost nothing to batch around: 48 frames borrow nothing from another theme, and the borrowing that was there had already moved to `_shared` in 5a. 1,528 statements became 50 modules, and `_monolith` is down to about 1,000 lines. Departures:
- `themes/_culture_common.py` holds the 16 statements culture and orbital share: the Marain script, `_culture_clock`, `_culture_face_ink`, `_culture_signal` and the data they read. It sits in `LAYERS` after `_shared`.
- The patches in eleven tests had to move, from `_monolith` to the theme module that reads the name. The facade made each of them fail loudly rather than pass without testing anything: `paint_neon_mask` (control, observation, biomech, culture), `paint_craquelure` (bosch), `draw_text_chroma_shift` (vhs) and `AUTOCHROME_PLATE` (autochrome, photo). The facade's own tests now patch `themes.diags._diags_system_info`.

**PRs 3…N: themes, in batches.** Two PRs for the 38 border themes (about 7.4k lines), then about 5 for the 50 frame themes (about 20k lines), roughly 10 themes each, grouped by family.
- Promote shared code to `themes/_shared.py` before its dependents move (crt scanlines, tarot numerals, cream wash, vitrail fill).
- Culture and orbital move together with `_culture_common.py`.
- Each theme's scene caches, `global` latches, plates and tuning constants travel with it.
- That theme's test patches move to `themes.<name>`.
- `_BORDER_PAINTERS` and `_FRAME_RENDERERS` stay where they are, importing from the theme modules.

Generate each theme module's import header with a throwaway AST helper, `scripts/_split_tool.py`. It computes a section's free names and maps each to its owning module, and gets deleted in the final PR. Ruff F401/F821 back it up.

**PR N+1: registry built from theme modules. Done**, narrower than planned. Each theme module ends with a `SPEC`: a `BorderSpec` (painter, `clear_rect_pad`, `wants_time`, an optional `knockout` painter, `debug_label_inset`) or a `FrameSpec` (the frame renderer). `registry.py` (above the theme modules, below `_monolith`) builds `BORDER_SPECS` / `FRAME_SPECS` from them and refuses to import if a theme is unclaimed, claimed twice or unknown. `render`'s eight-branch by-name ladder and its local `_CLEAR_RECT_PADS` became one `spec.paint_knockout` call; blueprint's three-step knockout moved into `themes/blueprint.py`. The border fence patches one place. `_BORDER_PAINTERS`, `_FRAME_RENDERERS` and `_DEBUG_LABEL_RIGHT_INSET` survive as read-only views, so a stale patch raises. Fingerprints identical; `tests/test_render_quote_registry.py` pins the derived tables to the old literals. Departures:
- **Colours, fonts and text flags stay in `theme_tables`.** `fonts`, `layout` and `text` read them from below the theme modules, so moving them into a spec means an upward import or import-time registration into low-level tables. Neither was worth co-locating a theme's colours with its painter.
- **`render` still paints every border twice.** Measured while designing this: dropping the first paint changes pixels for ten themes (blueprint, cartograph, circuit, dispatch, firmament, herbarium, nightvision, roman, scholar, synoptic), whose painters do not reproduce their own output. Making them idempotent and dropping the first paint is a visual change, so it is a separate issue, not part of the split. Issue #361 later dropped the first paint for the other border themes and recorded the ten with `BorderSpec.paints_twice`.
- Adding a theme is one module with its `SPEC`, one line in `THEME_MODULES`, and its data rows (`theme_tables`, `THEME_SATURATION`, `run_clock`'s choices), all of which tests check, plus the golden and the docs.

The original plan for this PR:
- Each theme module exports a `SPEC = ThemeSpec(name, palette, fonts, kind, renderer|border, ragged_right, debug_label_inset, clear_rect_pad, bold_stroke, rigid_match_spacing, no_ornament_marks)`.
- `registry.py` derives `THEMES`, `THEME_FONTS`, `_BORDER_PAINTERS`, `_FRAME_RENDERERS` and the frozensets from the ordered list in `themes/__init__.py`. `THEME_ORDER` stays explicit there.
- `render()` dispatches every border through `spec` with the knockout rect, which removes the by-name calls. The border fence then patches one place.
- A one-time snapshot test asserts the derived tables equal the old literals. Fingerprints identical.
- Adding a theme becomes one file, one import line, the golden, the docs and `display_inky.THEME_SATURATION`.

**PR final: close the shim. Done**, which completes the split. Departures from the plan below:
- `_monolith.py` was renamed `core.py` (with `git mv`, so `git log --follow` reaches the original module) rather than emptied. What remained, `render()`, the source card, the sleep frame and the command line, is the package's top layer, not leftovers.
- **Reads still fall through; writes are refused.** The facade's forwarding branch is gone: a write through the package raises and names the module to patch. Making the package plain (explicit re-exports only) would have rewritten about 1,050 reads of private names in tests, which cannot misfire; a write is what lands in the wrong place, and there were 51 of them, plus 17 the first fence missed (multi-line calls and `contact_sheet`'s own alias of the package). All now patch the reading module.
- `__all__` lists the public API (the names production code and scripts read through the package), and the `TYPE_CHECKING` block imports exactly those, replacing the star imports of every layer.
- The fence is AST-based rather than a grep: `setattr` / `patch.object` on the package by any alias, a dotted `patch` / `setattr` string whose parent resolves to the package (so another module's alias is caught), and assignment or `del`.
- The registry's migration snapshot test was retired. There was no `_split_tool.py` to delete: the extraction helper lived outside the repo throughout.

The original plan for this PR:
- Delete the now-empty `_monolith.py` and the guard's forwarding branch.
- Have the facade export only `__all__`.
- Add a test that no test or script writes a private name on `idle_hours.render_quote` (grep fence).
- Delete `_split_tool.py`.
- Update CLAUDE.md, `docs/themes.md`, `docs/testing.md`, `docs/CONTRIBUTING.md`, `docs/runtime.md` and the README path mentions.

## Critical files

- `idle_hours/render_quote.py` → `idle_hours/render_quote/**`
- `idle_hours/run_clock.py` (:161, :859–888, :1734, :1781), `idle_hours/runtime_config.py` schema, `idle_hours/assets/config.toml.{defaults,example}`
- `tests/test_theme_decoration.py` (:176–268, :298–312), `tests/test_render_golden.py` (:677–715, :836–883), `tests/test_render_quote_themes.py`, `tests/test_render_quote.py`, `tests/test_packaging.py:42–48`, `tests/test_run_clock.py:5347–5419`
- `scripts/generate_theme_previews.py` (:63, :173, :215)
- Unchanged but verified: `contact_sheet.py`, `web_server.py:1680–1745` (`patch("idle_hours.render_quote.render")` stays valid because `render` is public and read through the facade at call time), `theme_names.py`, `idle_hours_cli.py:43`, `ci.yml:257` wheel import check.

## Verification (every PR)

1. `python scripts/render_fingerprint.py --out /tmp/after.json` on the branch, and the same on `main`. They must be byte-equal.
2. `pytest -n auto --dist loadscope`, plus `pytest tests/test_render_golden.py`, and `python scripts/generate_theme_previews.py --check`.
3. `ruff check .`, then `node --test tests/js/*.test.mjs`. The web UI is untouched, so this is a sanity check.
4. `python -m idle_hours.render_quote --time 14:30`, `idle-hours render --time 14:30`, `idle-hours run --once --buttons-off`, and from PR 0b on, `idle-hours run --once --config assets/config.toml.example` with the legacy `render_script` value.
5. Build the wheel, install it into a clean venv, and run the `ci.yml` import check plus one render. This proves fonts and plates resolve through the new `PACKAGE_DIR`.
6. Coverage stays at or above the 95% floor (`COVERAGE_CORE=sysmon pytest -n auto --cov=idle_hours`).
