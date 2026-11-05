"""dashline entry point: Claude Code runs this file as the statusline command.

Installed as ${CLAUDE_CONFIG_DIR:-~/.claude}/scripts/statusline/statusline.py next to
the copied `dashline/` package. Claude Code runs it with `python3 -I -S`, which leaves the
script's own folder off sys.path, so we add it here. In the repo the package is under src/.
"""

import os
import sys

_here = os.path.dirname(os.path.realpath(__file__))
_src = os.path.join(_here, "src")
sys.path.insert(0, _src if os.path.isdir(os.path.join(_src, "dashline")) else _here)

from dashline.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
