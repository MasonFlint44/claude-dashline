"""--install: copy dashline into the config dir and point settings.json at it (PLAN §3, §9).

The install skill runs this from the plugin. The package is copied, not linked, because
the plugin's own folder changes with every version. The settings entry names the copy
through `${CLAUDE_CONFIG_DIR:-$HOME/.claude}`, so it still resolves in a devcontainer that
mounts ~/.claude under another user.

A statusLine that runs something else is never replaced without --replace: the skill
shows it to the user and asks first. Neither is a scripts/statusline/ folder that holds
another tool's files. Everything is checked before anything is written, so an install
that stops to ask has changed nothing.
"""

from __future__ import annotations

import json
import os
import re
import sys

from dashline.theme import config_dir, home_dir

COMMAND = 'python3 -I -S "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/scripts/statusline/statusline.py"'
# In a command: it runs the copy in the config dir. Other tools can use the same path, so
# an entry is only dashline's if that folder holds dashline too (folder_state).
MARK = "/scripts/statusline/statusline.py"
CONFIG_PREFIXES = ("}", "/.claude")  # ${CLAUDE_CONFIG_DIR:-…}, ~/.claude, $HOME/.claude
REFRESH = 60
GLYPH_SETS = ("nerd", "unicode", "ascii")
GLYPHS = re.compile(r"\s*--glyphs(?:=|\s+)(\S+)")
LEFTOVER = re.compile(r"^statusline\.(?:new|old)-(\d+)$")
LEFTOVER_AGE = 3600  # where a process can't be asked whether it's alive (Windows)
# What an install consists of, at the top of its folder. Anything else there is the
# user's, and an update carries it over.
OWN_NAMES = ("statusline.py", "VERSION", "dashline")
# Files a file manager leaves in any folder it shows: they don't make a folder someone's.
DESKTOP_JUNK = (".DS_Store", "Thumbs.db", "desktop.ini")

# Exit codes beyond 0 and 1.
NEEDS_REPLACE = 3
NEEDS_DOWNGRADE = 4  # the installed copy is newer than this one


class InstallError(Exception):
    pass


def install_dir(env) -> str:
    return os.path.join(config_dir(env), "scripts", "statusline")


def user_settings(env) -> str:
    return os.path.join(config_dir(env), "settings.json")


def command(glyphs: str) -> str:
    return COMMAND if glyphs == "unicode" else f"{COMMAND} --glyphs {glyphs}"


def runs_install_dir(entry, env=None) -> bool:
    """A statusLine entry whose command runs statusline.py in the config dir."""
    if not isinstance(entry, dict):
        return False
    cmd = entry.get("command")
    if not isinstance(cmd, str):
        return False
    cmd = cmd.replace("\\", "/")
    target = config_dir(os.environ if env is None else env).replace("\\", "/").rstrip("/")
    prefixes = (*CONFIG_PREFIXES, target)
    return any(prefix + MARK in cmd for prefix in prefixes)


def is_ours(entry, env=None) -> bool:
    """A statusLine entry that runs the installed copy of dashline.

    The command must run the config dir's scripts/statusline/statusline.py, and that
    folder must hold dashline or nothing yet: another statusline may live at that path.
    """
    env = os.environ if env is None else env
    return runs_install_dir(entry, env) and folder_state(install_dir(env)) != "theirs"


def glyphs_of(entry) -> str:
    """The glyph set an entry's command asks for: unicode when it names none or a bad one."""
    cmd = entry.get("command") if isinstance(entry, dict) else None
    match = GLYPHS.search(cmd) if isinstance(cmd, str) else None
    value = match.group(1).strip("'\"") if match else "unicode"
    return value if value in GLYPH_SETS else "unicode"


def with_glyphs(cmd: str, glyphs: str) -> str:
    """`cmd` asking for `glyphs`: any --glyphs flag replaced, the rest kept as written.

    The flag goes right after the statusline.py argument, so a hand-edited command that
    goes on (`… 2>/dev/null || echo off`) still passes it to dashline.
    """
    bare = GLYPHS.sub("", cmd).rstrip()
    if glyphs == "unicode":
        return bare
    at = bare.replace("\\", "/").find(MARK)
    if at < 0:
        return f"{bare} --glyphs {glyphs}"
    end = at + len(MARK)
    while end < len(bare) and not bare[end].isspace() and bare[end] not in ";|&<>()":
        end += 1  # a closing quote
    return f"{bare[:end]} --glyphs {glyphs}{bare[end:]}"


def home_short(path: str, env=None) -> str:
    """`/home/me/.claude/x` → `~/.claude/x`, for messages."""
    home = home_dir(os.environ if env is None else env).rstrip("/")
    if home and (path == home or path.startswith(home + os.sep)):
        return "~" + path[len(home) :]
    return path


# ---- the files ----


def source_root() -> str:
    """The folder holding the running `dashline/` package."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def source_shim(root: str) -> str | None:
    """statusline.py next to the package (installed copy), or above src/ (the plugin)."""
    for path in (os.path.join(root, "statusline.py"), os.path.join(root, "..", "statusline.py")):
        if os.path.isfile(path):
            return os.path.normpath(path)
    return None


def files(root: str, shim: str | None) -> dict:
    """Relative name → absolute path, for every file an install consists of."""
    pkg = os.path.join(root, "dashline")
    out = {}
    if shim:
        out["statusline.py"] = shim
    try:
        names = sorted(os.listdir(pkg))
    except OSError:
        names = []
    for name in names:
        if name.endswith(".py"):
            out[f"dashline/{name}"] = os.path.join(pkg, name)
    return out


def digest(found: dict) -> str | None:
    """One hash over a set of files' names and contents, or None if there are none."""
    import hashlib

    if not found:
        return None
    h = hashlib.sha256()
    for rel in sorted(found):
        try:
            with open(found[rel], "rb") as f:
                data = f.read()
        except OSError:
            return None
        h.update(rel.encode() + b"\0" + data + b"\0")
    return h.hexdigest()


def installed_files(env) -> dict:
    target = install_dir(env)
    shim = os.path.join(target, "statusline.py")
    return files(target, shim if os.path.isfile(shim) else None)


def installed_version(env) -> str | None:
    try:
        with open(os.path.join(install_dir(env), "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def version_tuple(text: str | None) -> tuple | None:
    """`0.1.6` → (0, 1, 6); None for anything else."""
    if not text or not re.fullmatch(r"\d+(\.\d+)*", text):
        return None
    return tuple(int(part) for part in text.split("."))


def newer_installed(env) -> str | None:
    """The installed version, if it is newer than this copy."""
    from dashline import __version__

    installed = installed_version(env)
    theirs, mine = version_tuple(installed), version_tuple(__version__)
    return installed if theirs and mine and theirs > mine else None


def folder_state(target: str) -> str:
    """ "missing" (or empty), "ours" (holds the dashline package) or "theirs"."""
    if not os.path.isdir(target):
        return "theirs" if os.path.lexists(target) and not os.path.islink(target) else "missing"
    try:
        names = os.listdir(target)
    except OSError:
        return "theirs"
    if not [name for name in names if name not in DESKTOP_JUNK]:
        return "missing"
    if os.path.isfile(os.path.join(target, "dashline", "__init__.py")):
        return "ours"
    return "theirs"


def _rmtree(path: str) -> None:
    import shutil

    if os.path.islink(path):
        os.unlink(path)
    elif os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def _alive(pid: int) -> bool | None:
    """Whether a process runs; None where that can't be asked (Windows)."""
    if os.name == "nt":
        return None  # os.kill(pid, 0) sends Ctrl-C there
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # someone else's process
    return True


def clean_leftovers(parent: str, now: float) -> list:
    """Remove statusline.new-PID / .old-PID folders an interrupted install left behind."""
    removed = []
    try:
        names = os.listdir(parent)
    except OSError:
        return removed
    for name in names:
        match = LEFTOVER.match(name)
        if not match or int(match.group(1)) == os.getpid():
            continue
        path = os.path.join(parent, name)
        alive = _alive(int(match.group(1)))
        if alive is None:
            try:
                alive = now - os.lstat(path).st_mtime < LEFTOVER_AGE
            except OSError:
                continue
        if not alive:
            _rmtree(path)
            removed.append(name)
    return removed


def set_aside(target: str) -> str:
    """Move another tool's folder out of the way: statusline.backup, .backup-2, …"""
    n, aside = 1, f"{target}.backup"
    while os.path.lexists(aside):
        n += 1
        aside = f"{target}.backup-{n}"
    try:
        os.rename(target, aside)
    except OSError as e:
        raise InstallError(f"couldn't move {target} aside: {e.strerror or e}") from e
    return aside


def _extras(target: str) -> list:
    """Top-level names in an install folder that an install didn't put there."""
    if os.path.islink(target) or not os.path.isdir(target):
        return []
    try:
        return sorted(name for name in os.listdir(target) if name not in OWN_NAMES)
    except OSError:
        return []


def _copy_entry(src: str, dst: str) -> None:
    """Copy a file, folder or link as it is."""
    import shutil

    if os.path.islink(src):
        os.symlink(os.readlink(src), dst)
    elif os.path.isdir(src):
        shutil.copytree(src, dst, symlinks=True)
    else:
        shutil.copy2(src, dst)


def put_back(aside: str, target: str, env) -> str:
    """Undo set_aside after a failed --replace. Returns what happened, in words."""
    where, backup = home_short(target, env), home_short(aside, env)
    try:
        _rmtree(target)
        os.rename(aside, target)
    except OSError as e:
        return f"couldn't move {backup} back to {where} ({e.strerror or e}): move it yourself\n"
    return f"moved the files in {backup} back to {where}\n"


def copy(env) -> tuple:
    """Copy this package into the install dir. Returns (target, what happened).

    Files the user added at the top of the folder (notes, a wrapper script) are copied
    into the new folder too, so an update doesn't lose them.
    """
    import shutil
    import time

    from dashline import __version__

    root = source_root()
    target = install_dir(env)
    if os.path.realpath(root) == os.path.realpath(target):
        return target, "this is the installed copy"
    source = files(root, source_shim(root))
    if "statusline.py" not in source:
        raise InstallError(f"no statusline.py next to {root}")
    clean_leftovers(os.path.dirname(target), time.time())
    if digest(source) == digest(installed_files(env)) and installed_version(env) == __version__:
        return target, "unchanged"

    # Build the new copy beside the old one, then swap folders with two renames. A render
    # never reads a half-copied folder, but one starting between the renames finds no
    # folder and draws nothing that once.
    os.makedirs(os.path.dirname(target), exist_ok=True)
    new, old = f"{target}.new-{os.getpid()}", f"{target}.old-{os.getpid()}"
    _rmtree(new)
    _rmtree(old)
    had = os.path.lexists(target)
    try:
        os.makedirs(os.path.join(new, "dashline"))
        for rel, path in source.items():
            shutil.copyfile(path, os.path.join(new, *rel.split("/")))
        with open(os.path.join(new, "VERSION"), "w", encoding="utf-8") as f:
            f.write(__version__ + "\n")
        for name in _extras(target):
            _copy_entry(os.path.join(target, name), os.path.join(new, name))
        if had:
            os.rename(target, old)
        try:
            os.rename(new, target)
        except OSError:
            if had:  # put the old copy back, so a render still finds one
                os.rename(old, target)
            raise
    except OSError as e:
        _rmtree(new)
        raise InstallError(f"couldn't copy to {target}: {e.strerror or e}") from e
    _rmtree(old)
    return target, "updated" if had else "installed"


# ---- settings.json ----


BOM = "\ufeff"


def read_settings(path: str) -> dict:
    """The settings file as a dict ({} if missing). Raises InstallError if unreadable.

    A byte-order mark (some Windows editors add one) is read past.
    """
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise InstallError(f"can't read {path}: {e.strerror or e}") from e
    except UnicodeDecodeError as e:
        raise InstallError(f"{path} isn't UTF-8 text; fix it and run again") from e
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as e:
        raise InstallError(f"{path} isn't valid JSON ({e}); fix it and run again") from e
    if not isinstance(data, dict):
        raise InstallError(f"{path} isn't a JSON object; fix it and run again")
    return data


def has_bom(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(3) == BOM.encode()
    except OSError:
        return False


def check_writable(path: str) -> None:
    """Raise InstallError if settings.json can't be rewritten: the file is read-only
    (someone made it so), or its folder is, where the new file is written first."""
    real = os.path.realpath(path)
    try:
        mode = os.stat(real).st_mode
    except OSError:
        mode = None  # missing: it gets made
    if mode is not None and (not mode & 0o200 or not os.access(real, os.W_OK)):
        raise InstallError(
            f"{path} is read-only, so it was left alone; make it writable, or add the "
            "statusLine entry yourself, then run again"
        )
    folder = os.path.dirname(real)
    while not os.path.isdir(folder) and os.path.dirname(folder) != folder:
        folder = os.path.dirname(folder)  # the nearest folder that exists gets the rest
    if not os.access(folder, os.W_OK | os.X_OK):
        raise InstallError(
            f"can't write in {folder}, so {path} was left alone; make the folder "
            "writable, or add the statusLine entry yourself, then run again"
        )


def write_settings(path: str, data: dict) -> None:
    """Write atomically, through a symlink to the real file, keeping its permissions
    and a byte-order mark if it had one."""
    real = os.path.realpath(path)
    os.makedirs(os.path.dirname(real), exist_ok=True)
    try:
        mode = os.stat(real).st_mode & 0o777
    except OSError:
        mode = None
    bom = BOM if has_bom(real) else ""
    tmp = f"{real}.dashline-{os.getpid()}.tmp"
    if os.path.lexists(tmp):
        os.unlink(tmp)  # left by an earlier run that had this pid
    # Made private, then given the old file's mode once written: settings can hold
    # secrets (an `env` block), so the copy is never readable by more people than the
    # file was. A new settings.json gets the usual mode (0666 less the umask), like any
    # file Claude Code makes.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if mode is not None else 0o666)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(bom + json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            if mode is not None:
                os.chmod(tmp, mode)
        os.replace(tmp, real)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def plan_entry(current, glyphs: str | None, replace: bool, ours: bool) -> tuple:
    """(new entry or None, glyphs used). None means: the entry is someone else's.

    ours: `current` is dashline's (is_ours). It keeps its command as written (say, with
    a full path to Python): only the --glyphs flag changes, and only when asked for
    another set or when it names an unknown one.
    """
    if current is not None and not ours and not replace:
        return None, None
    if ours:
        entry = dict(current)
        glyphs = glyphs or glyphs_of(current)
        cmd = current["command"]
        match = GLYPHS.search(cmd)
        if (match.group(1).strip("'\"") if match else "unicode") != glyphs:
            cmd = with_glyphs(cmd, glyphs)
        entry["command"] = cmd
    else:
        glyphs = glyphs or "unicode"
        entry = {"type": "command", "command": command(glyphs)}
    entry["type"] = "command"
    entry.setdefault("refreshInterval", REFRESH)
    return entry, glyphs


def write_entry(path: str, data: dict, entry: dict) -> None:
    data["statusLine"] = entry
    try:
        write_settings(path, data)
    except OSError as e:
        raise InstallError(f"couldn't write {path}: {e.strerror or e}") from e


def overridden_by(env, project_dir: str | None) -> tuple | None:
    """(path, entry) of a statusLine that wins over user settings and isn't dashline."""
    from dashline.theme import _read_json, settings_files

    user = os.path.realpath(user_settings(env))
    for path in settings_files(project_dir, env):
        if os.path.realpath(path) == user:
            return None
        entry = _read_json(path).get("statusLine")
        if entry is not None:
            return None if is_ours(entry, env) else (path, entry)
    return None


def project_dir(env, cwd: str | None) -> str:
    """The project whose settings may override the user's: Claude Code's, else cwd."""
    return cwd if cwd is not None else env.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def describe(entry: dict) -> str:
    glyphs = glyphs_of(entry)
    refresh = entry.get("refreshInterval")
    text = f"{glyphs} glyphs"
    if isinstance(refresh, (int, float)) and not isinstance(refresh, bool):
        text += f", refreshing every {refresh:g} s"
    return text


def run(
    glyphs: str | None,
    replace: bool = False,
    env=None,
    out=None,
    cwd=None,
    downgrade: bool = False,
) -> int:
    """Copy dashline and point settings at it. Exit 3 (nothing changed) when either the
    settings entry or the install folder belongs to something else and --replace wasn't
    given; exit 4 (nothing changed) when the installed copy is newer and --downgrade
    wasn't given."""
    from dashline import __version__

    env = os.environ if env is None else env
    out = out or sys.stdout
    path = user_settings(env)
    settings = home_short(path, env)
    try:
        # Everything that can stop the install is checked before anything is written.
        data = read_settings(path)
        current = data.get("statusLine")
        target = install_dir(env)
        where = home_short(target, env)
        theirs_folder = folder_state(target) == "theirs"
        ours = runs_install_dir(current, env) and not theirs_folder
        entry, _ = plan_entry(current, glyphs, replace, ours)
        if not replace and (theirs_folder or entry is None):
            if theirs_folder:
                out.write(
                    f"{where} holds files that aren't dashline's, so it was left alone. "
                    f"--replace moves them to {where}.backup first.\n"
                )
            if entry is None:
                shown = json.dumps(current, indent=2, ensure_ascii=False).replace("\n", "\n  ")
                out.write(f"{settings} has a statusLine that runs something else:\n  {shown}\n")
            out.write("Nothing was changed. Run again with --replace to use dashline instead.\n")
            return NEEDS_REPLACE
        newer = None if theirs_folder else newer_installed(env)
        if newer and not downgrade:
            out.write(
                f"{where} has dashline {newer}, newer than this copy ({__version__}), "
                "so it was left alone. Update the dashline plugin (/plugin) and install "
                "from there, or run again with --downgrade to install this older copy.\n"
                "Nothing was changed.\n"
            )
            return NEEDS_DOWNGRADE
        if entry != current:
            check_writable(path)
    except InstallError as e:
        sys.stderr.write(f"dashline: {e}\n")
        return 1
    aside = None
    try:
        if theirs_folder:
            aside = set_aside(target)
            out.write(f"moved the files in {where} to {home_short(aside, env)}\n")
        target, copied = copy(env)
        if copied == "unchanged":
            out.write(f"{where} already has dashline {__version__}\n")
        elif copied == "this is the installed copy":
            out.write(f"running from {where}: nothing to copy\n")
        else:
            out.write(f"{copied} dashline {__version__} in {where}\n")
        if entry != current:
            write_entry(path, data, entry)
    except InstallError as e:
        sys.stderr.write(f"dashline: {e}\n")
        if aside:  # the other tool's statusline still runs from its folder: put it back
            out.write(put_back(aside, target, env))
        return 1
    verb = "already runs" if entry == current else "now runs"
    out.write(f"{settings}: statusLine {verb} it with {describe(entry)}\n")
    other = overridden_by(env, project_dir(env, cwd))
    if other:
        out.write(
            f"note: {home_short(other[0], env)} sets its own statusLine, which wins over "
            f"{settings} in this project\n"
        )
    return 0
