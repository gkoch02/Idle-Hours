# Follow-ups

Deferred work items — deliberately carved out of a larger change so the
landed commit stayed focused and low-risk. Not a bug tracker; each item
is something the codebase is fine without but would be cleaner with.

## Theme system (from PR #72 review, scoped out)

- **Goodnight frame ignores the active theme.** `assets/goodnight.png`
  is a pre-rendered dark-theme "sleep" frame, so a user running
  `--theme scholar` or `--theme newsprint` at 22:00 still sees a black
  frame slide in. Options: (a) render the goodnight frame on-the-fly
  in the currently-active theme (simple, small cost), or (b) ship
  per-theme goodnight PNGs and pick one at quiet-entry time. Same
  issue applies to `--startup-image`. Low priority — the existing
  behaviour is consistent, just not theme-aware.

- **Three near-duplicate lazy-import helpers.**
  `runtime_state._known_theme_names`,
  `runtime_theme._registered_themes`, and
  `runtime_actions._theme_cycle` all do the same
  `from render_quote import ...` dance with a legacy fallback. The
  fallbacks are even different types (`frozenset` vs `tuple`). Worth
  consolidating into a single PIL-free `theme_names.py` module (or
  dropping the fallback entirely — if `render_quote` can't be imported
  the appliance is broken in ways the fallback can't paper over).

- **`--theme auto` is binary (default/dark only).** The eight operator
  themes (`scholar`, `newsprint`, `nightvision`, `blueprint`,
  `illuminated`, `bauhaus`, `risograph`, `comic`) can't be
  wall-clock-derived. If we ever want an `auto-scholar` / "light theme
  rotation" feature, `auto_theme_for` would need to grow a preference
  table — likely gated on a new `--auto-day-theme` / `--auto-night-theme`
  flag pair. Deliberately punted from PR #72 because the current
  binary contract is well-understood.

- **`subtle` theme field is unused.** Every theme populates
  `subtle` but `render_quote` never references it (confirmed by
  grep). Either wire it into an existing element (subheading, maybe?)
  or remove from the theme contract and the `TestThemes` field-count
  invariant.
