# Retired themes

Themes taken out of Idle Hours, kept here rather than deleted. Nothing in this
directory is imported, rendered, tested, linted or shipped: `pytest` collects
only `tests/`, `mypy` checks only `idle_hours/`, ruff and `.dockerignore`
exclude `retired/`, and the wheel packages only `idle_hours/`. The live docs
no longer mention these themes; this directory is where their record lives.

Retired in October 2026, chosen by the maintainer as low-value: near-duplicates
of themes that stayed, or themes whose idea did not survive the panel at a
viewing distance.

| Theme | Was |
|---|---|
| `swiss` | Swiss International modernist |
| `scholar` | Academic textbook |
| `herbarium` | Pressed-plant specimen sheet |
| `blueprint` | Cyanotype drafting sheet |
| `illuminated` | Rubricated manuscript |
| `risograph` | Two-colour riso zine |
| `grimoire` | Faustian spellbook |
| `glacier` | Icy / aurora panel |
| `mucha` | Art Nouveau (Mucha vines) |
| `vinyl` | Turntable and spoken-word LP (already out of the rotation) |
| `grimdark` | Warhammer 40K Imperial Gothic |
| `intaglio` | Banknote engraving |

## What is kept

Each `themes/<name>/` holds:

- `<name>.py`: the theme module, unchanged (it still imports from the
  renderer's shared layers by relative import, as it did in
  `idle_hours/render_quote/themes/`).
- `README.md`: its README row, its design and font notes from
  `docs/themes.md`, its `THEMES` and `THEME_FONTS` entries, its
  `THEME_ORDER` position, its `display_inky` saturation, and any
  per-theme code that lived outside its module (the `_draw_text_body`
  colour branch in `render_quote/text.py`, table memberships).
- `golden/`: its golden fixtures from `tests/golden/renderer/`.
- `preview.png`: its README preview.
- `tests/`: its tests, moved verbatim from the live suite (whole classes and
  functions, and single methods taken out of shared test classes).

Also kept:

- `fonts/`: the font families no live theme loads any more, each with its
  licence: Berkshire Swash (`mucha`), Bitter (`scholar`), Eagle Lake
  (`grimoire`), Iceland (`glacier`) and Rubik (`risograph`).
- `themes/grimdark/assets/grimdark_gunmetal.png` and
  `themes/grimdark/scripts/generate_grimdark_plate.py`: its plate and the
  script that builds it.

Shared code a retired theme used and a live theme still uses stays where it
was (for example `_GUNMETAL_PALETTE` in `render_quote/themes/_shared.py`,
which `control` uses), so a restored module imports cleanly. The generic
mechanisms only retired themes used are also left in place, empty: the
`knockout` field on `BorderSpec` (`blueprint`), `_BOLD_STROKE_BY_THEME`
(`glacier`) and `CYCLE_EXCLUDED_THEMES` (`vinyl`).

## Restoring a theme

1. Move `themes/<name>/<name>.py` back to `idle_hours/render_quote/themes/`
   and list it in both places in `idle_hours/render_quote/themes/__init__.py`
   (the import list and `THEME_MODULES`, alphabetical).
2. Paste its `THEMES` and `THEME_FONTS` entries back into
   `idle_hours/render_quote/theme_tables.py` (copies are in its
   `README.md`), add it to `THEME_ORDER` at its old position, and restore any
   table membership the README lists. If it used a font in `fonts/`, move
   that directory back to `idle_hours/fonts/` and restore its path constant
   in `idle_hours/render_quote/_paths.py` and its import in `theme_tables.py`.
3. Restore its `_draw_text_body` branch in `idle_hours/render_quote/text.py`
   if the README shows one, its `display_inky.THEME_SATURATION` row, and its
   `--theme` choice in `idle_hours/run_clock.py`.
4. Put back any asset or script (only `grimdark` has them).
5. Move its goldens back to `tests/golden/renderer/`, its scenario into
   `tests/test_render_golden.py` if it had a hand-written one, its tests back
   into the files they came from, and re-add it to any roster test that fails
   (`CUSTOM_FRAME_THEMES` in `tests/test_theme_decoration.py` for a frame
   theme, and the lists in `tests/test_render_quote_themes.py`).
6. Docs: its README row and preview (`idle_hours/assets/previews/`), the
   README preview loop, the button-B chain in `docs/runtime.md`, its
   paragraphs in `docs/themes.md`, then
   `python3 scripts/generate_font_table.py`.
7. Run the suite. The renderer has moved on since a theme was retired, so a
   restored theme may need its golden regenerated
   (`UPDATE_RENDER_GOLDEN=1 pytest tests/test_render_golden.py`) and its
   tests brought up to date; the archived golden shows what it looked like.

Git history has the same files at their old paths, if you would rather
restore by `git checkout <commit> -- <paths>` from the commit before the
retirement.
