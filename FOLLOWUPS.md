# Follow-ups

Deferred work items — deliberately carved out of a larger change so the
landed commit stayed focused and low-risk. Not a bug tracker; each item
is something the codebase is fine without but would be cleaner with.

## v2.x

- **Wheel ships only Python modules, not static assets.** `pyproject.toml`
  uses `[tool.setuptools] py-modules` because the repo layout has the
  Python files at the root, but that means the wheel can't carry `web/`
  / `assets/` / `fonts/` (they aren't under any package directory). A
  `pip install litclock` install today produces a CLI that 404s the
  curator UI, can't find bundled fonts (degrades to bitmap fallback),
  and can't find the prebuilt corpus. Working install paths:
  `pip install -e .` from a git clone, or the bundled `Dockerfile`.
  A startup guard in `run_clock._preflight_paths` catches the corpus
  case loudly. The proper fix: restructure into a `litclock/` package
  (move every top-level `*.py` and the static directories under it) and
  declare them via `[tool.setuptools.package-data]`. That's a sweeping
  rename across imports, tests, and docs — separate PR.
