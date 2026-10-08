"""Path-resolution helpers for the run_clock orchestrator and its siblings.

``BASE_DIR`` lives inside the installed package, so joining every relative
path onto it would bury operator files in site-packages. Outputs are always
CWD-relative; operator-supplied inputs (``--render-script``,
``--display-script``, ``--quiet-image``, ``--startup-image``) resolve CWD
first and fall back to the bundled copy, so a shipped relative config stays
portable while an operator's own file wins. The full rules: docs/runtime.md
("Default paths").
"""
from __future__ import annotations

from pathlib import Path

# The `photo` theme's source, named here rather than in ``render_quote`` so
# ``run_clock`` can export it without importing Pillow — the same reason
# ``theme_names`` exists. It travels by environment rather than by render-
# subprocess argv because that argv may only carry flags an operator's own
# ``--render-script`` already recognises (see ``run_clock._corpus_render_args``):
# an unknown flag exits argparse with status 2 and takes the appliance into
# render backoff, where an unknown environment variable is simply ignored.
PHOTO_PATH_ENV = "IDLE_HOURS_PHOTO_PATH"


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
