"""``python -m idle_hours.render_quote``: how ``run_clock`` launches the renderer."""

import sys

from ._monolith import main

# argparse names the program after argv[0], which -m sets to this file's path;
# "usage: __main__.py" tells an operator reading the journal nothing.
sys.argv[0] = "python -m idle_hours.render_quote"
raise SystemExit(main())
