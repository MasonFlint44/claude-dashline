"""dashline entry point: Claude Code runs this file as the statusline command.

Installed as ${CLAUDE_CONFIG_DIR:-~/.claude}/scripts/statusline/statusline.py next to
the copied `dashline/` package. Claude Code runs it with `python3 -I -S`, which leaves the
script's own folder off sys.path, so we add it here. In the repo the package is under src/.
It goes first, so no other `dashline` can win, and comes off again once the package is
imported: later imports resolve inside the package, and a stray .py file in the folder
can't stand in for a standard-library module.
"""

import os
import sys

_here = os.path.dirname(os.path.realpath(__file__))
_src = os.path.join(_here, "src")
_root = _src if os.path.isdir(os.path.join(_src, "dashline")) else _here
sys.path.insert(0, _root)
try:
    from dashline.__main__ import main
finally:
    if _root in sys.path:
        sys.path.remove(_root)

if __name__ == "__main__":
    sys.exit(main())
