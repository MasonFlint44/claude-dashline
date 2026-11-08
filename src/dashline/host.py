"""Where the system dashline runs on differs: Windows (PLAN §3, "Windows").

`WINDOWS` gates every Windows-only behavior, read as `host.WINDOWS` when it's needed,
so a test flips it in one place. `os.name` is read directly only where a real Windows
API is called (process creation flags, `os.kill`), which flipping it can't stand in for.
"""

from __future__ import annotations

import functools  # already loaded: re uses it
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


def plain_file(path: str, limit: int) -> bool:
    """Whether `path` is a regular file of at most `limit` bytes, safe to read in a
    render. Not a pipe or a device: reading one can block forever, or never end (a
    repo's `.claude/settings.json` can be a link to `/dev/zero`)."""
    import stat

    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return False
    return stat.S_ISREG(st.st_mode) and st.st_size <= limit


def program(name: str, env=None) -> str:
    """What to run for the program `name` (`git`, `python`): `name` itself, found on PATH
    as usual, except on Windows.

    There Windows (CreateProcess) and shutil.which look in the current folder before
    PATH, and dashline runs in the project's folder: a cloned repo's own `git.exe` would
    run on every render. So on Windows it's the full path found on PATH alone, without
    relative entries (`.`), which also mean the current folder. Raises FileNotFoundError
    when there is none, as running a program that isn't there would.
    """
    if not WINDOWS:
        return name
    found = which(name, env)
    if found is None:
        raise FileNotFoundError(2, "not found on PATH", name)
    return found


def which(name: str, env=None) -> str | None:
    """shutil.which, from `env`'s PATH; on Windows without the current folder (program)."""
    env = os.environ if env is None else env
    if not WINDOWS:
        import shutil

        return shutil.which(name, path=_get(env, "PATH") or None)
    return _on_path(name, _get(env, "PATH"), _get(env, "PATHEXT"))


def system_program(*parts: str) -> str:
    """A program of Windows' own, by its full path (`System32`, `taskkill.exe`)."""
    root = os.environ.get("SYSTEMROOT") or "C:\\Windows"  # any case there
    return os.path.join(root, *parts)


def _get(env, name: str) -> str:
    """`name` from `env` in any case (os.environ's keys are upper case on Windows)."""
    return env.get(name) or env.get(name.upper()) or env.get(name.capitalize()) or ""


@functools.cache
def _on_path(name: str, path: str, pathext: str) -> str | None:
    """The first `name` (with each of PATHEXT's extensions) in PATH's absolute folders."""
    exts = [""] if os.path.splitext(name)[1] else (pathext or ".COM;.EXE;.BAT;.CMD").split(";")
    for folder in path.split(os.pathsep):
        folder = folder.strip().strip('"')
        if not folder or not os.path.isabs(folder):
            continue
        for ext in exts:
            candidate = os.path.join(folder, name + ext.strip())
            if os.path.isfile(candidate):
                return candidate
    return None
