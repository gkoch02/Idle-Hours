"""Theme modules for ``render_quote`` (issue #335).

Each theme moves here from ``_monolith`` as its own module. A theme module
imports only from the shared layers and ``themes._shared``, never from another
theme, so code two themes use lives in ``_shared``.
"""
