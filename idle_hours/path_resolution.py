"""Path-resolution helpers for the run_clock orchestrator + its siblings.

The v2.x package restructure moved ``BASE_DIR`` (the directory each module
lives in) *inside* the installed ``idle_hours/`` package, so the
pre-restructure idiom of joining every relative path with ``BASE_DIR`` now
buries operator artifacts inside site-packages. We need two contracts:

* **Outputs** (``--output``, the render PNG target): always CWD-relative. The
  operator owns these; ``Path(value).expanduser().resolve()`` is enough.
* **Inputs** (``--render-script``, ``--display-script``, ``--quiet-image``,
  ``--startup-image``): try CWD first, fall back to the bundled location
  under ``BASE_DIR`` if the CWD candidate doesn't exist. This satisfies
  three otherwise-conflicting requirements simultaneously:
    1. The shipped ``config.toml.defaults`` can stay portable (it lists
       ``render_script = "render_quote.py"`` as a relative string; that
       still resolves to the bundled script regardless of where the
       operator installed the package or what their CWD is).
    2. An operator who drops a ``./my_renderer.py`` in their working tree
       and points the config at it gets *their* file, not the bundled
       one — CWD-relative wins when the file exists.
    3. An operator passing an absolute path gets exactly that path.

The fallback is asymmetric on purpose: outputs MUST go to CWD (BASE_DIR
would mean writing into site-packages), inputs ALSO go to CWD when the
file is there, falling back to BASE_DIR only for the bundled-default
case. Two regression tests pin this behaviour:
``tests/test_run_clock.py::TestParseArgsBasic::test_main_persists_resolved_output_back_to_args``
and ``tests/test_web_server.py::TestOutputPathAlignment``.
"""
from __future__ import annotations

from pathlib import Path


def resolve_input_path(value: str | Path, base_dir: Path) -> Path:
    """Resolve an input path with CWD-then-bundled fallback.

    See module docstring for the rationale. Returns the CWD-resolved path
    when nothing matches so the eventual ``FileNotFoundError`` (or the
    pre-flight error message) references the path the operator actually
    typed, not a confusing site-packages translation.
    """
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    cwd_candidate = (Path.cwd() / path).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    bundled = (base_dir / path).resolve()
    if bundled.exists():
        return bundled
    return cwd_candidate
