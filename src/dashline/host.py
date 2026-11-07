"""Where the system dashline runs on differs: Windows (PLAN §3, "Windows").

`WINDOWS` gates every Windows-only behavior, read as `host.WINDOWS` when it's needed,
so a test flips it in one place. `os.name` is read directly only where a real Windows
API is called (process creation flags, `os.kill`), which flipping it can't stand in for.
"""

from __future__ import annotations

import os

WINDOWS = os.name == "nt"
HELD_TRIES = 5  # Windows: a file or folder another process has open can't be moved yet
HELD_WAIT = 0.05  # seconds before the first retry; each one waits a step longer (0.5 s in all)


def retry_held(op, *args):
    """`op(*args)`, tried again for a moment on Windows while another process holds the
    file or folder (a render reading it, an antivirus scan, Claude Code writing
    settings.json): there a file that's open can't be replaced, renamed or removed.
    """
    for attempt in range(HELD_TRIES - 1):
        try:
            return op(*args)
        except PermissionError:
            if not WINDOWS:
                raise
            import time

            time.sleep(HELD_WAIT * (attempt + 1))
    return op(*args)


def can_write_in(folder: str) -> bool:
    """Whether a file can be made in `folder`.

    On Windows os.access ignores a folder's permissions, so there a file is made and
    removed to find out. One left by an earlier run that couldn't remove it (same pid)
    is removed now.
    """
    if not WINDOWS:
        return os.access(folder, os.W_OK | os.X_OK)
    probe = os.path.join(folder, f".dashline-probe-{os.getpid()}.tmp")
    try:
        os.close(os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    except FileExistsError:
        pass  # an earlier run's: it could be made, then
    except OSError:
        return False
    import contextlib

    with contextlib.suppress(OSError):
        os.unlink(probe)
    return True
