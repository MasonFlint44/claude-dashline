"""--install: copy dashline into the config dir and point settings.json at it (PLAN §3, §9).

The install skill runs this from the plugin. The package is copied, not linked, because
the plugin's own folder changes with every version. The settings entry names the copy
through `${CLAUDE_CONFIG_DIR:-$HOME/.claude}`, so it still resolves in a devcontainer that
mounts ~/.claude under another user.

On Windows, Claude Code runs the command in Git Bash, or in PowerShell when there's no
Git Bash, so the entry is one both read: a Python on PATH by name (`py -3`, `python` or
`python3`, whichever runs Python 3.9 or newer) and the copy's full path in forward
slashes and double quotes. An entry still running the command dashline wrote before it
ran on Windows (Bash only) is rewritten that way too.

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

from dashline import host
from dashline.host import retry_held
from dashline.theme import config_dir, home_dir

COMMAND = 'python3 -I -S "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/scripts/statusline/statusline.py"'
# In a command: it runs the copy in the config dir. Other tools can use the same path, so
# an entry is only dashline's if that folder holds dashline too (folder_state).
MARK = "/scripts/statusline/statusline.py"
CONFIG_PREFIXES = ("}", "/.claude")  # ${CLAUDE_CONFIG_DIR:-…}, ~/.claude, $HOME/.claude
REFRESH = 60
GLYPH_SETS = ("nerd", "unicode", "ascii")
# Finds a --glyphs flag anywhere in a command, for reading: the value never takes in a
# quote or a shell character. dashline_args() says which flag dashline itself gets.
GLYPHS = re.compile(r"\s*--glyphs(?:=|\s+)['\"]?([A-Za-z0-9_.-]+)")
# What may run statusline.py directly: python3, python3.12, py (Windows), with options.
PYTHON = re.compile(r"(?i)^(?:python[0-9.]*|py)(?:\.exe)?$")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
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


# Pythons a Windows command can name, in order: the python.org launcher, then the
# names python.org and the Microsoft Store installs put on PATH.
WINDOWS_PYTHONS = ("py -3", "python", "python3")
PROBE_TIMEOUT = 15  # seconds for each to say its version (a cold start can be slow)


def command(glyphs: str, base: str = COMMAND) -> str:
    return base if glyphs == "unicode" else f"{base} --glyphs {glyphs}"


def windows_command(env, python: str) -> str:
    """The command for Windows: `python` (a WINDOWS_PYTHONS name) and a full path."""
    script = os.path.join(install_dir(env), "statusline.py").replace("\\", "/")
    if "$" in script or "`" in script:
        raise InstallError(
            f"the install path {script} has a $ or `, which both Git Bash and PowerShell "
            "would expand in the statusLine command. Set CLAUDE_CONFIG_DIR to a folder "
            "without them, or add the statusLine entry yourself. Nothing was changed."
        )
    return f'{python} -I -S "{script}"'


# What follows the Python in COMMAND, and the options py takes to pick one (-3, -3.13-64).
OLD_ARGS = COMMAND[len("python3") :]
PY_VERSION = re.compile(r"^-\d+(?:\.\d+)?(?:-(?:32|64|arm64))?$")
VARIABLE = re.compile(r"\$(?:\{|[A-Za-z_])")  # $HOME, ${X:-y}, PowerShell's $env:X


def old_form(entry) -> bool:
    """An entry whose command is the one dashline wrote before it ran on Windows, but
    for `--glyphs` and which Python runs it (`python`, `py -3`, a full path: what a user
    there had to change to make it run). Its `${CLAUDE_CONFIG_DIR:-…}` is Bash, which
    PowerShell can't run, so on Windows install rewrites it. Other edits are kept.
    """
    cmd = entry.get("command") if isinstance(entry, dict) else None
    if not isinstance(cmd, str):
        return False
    rest = GLYPHS.sub("", cmd).strip()
    if not rest.endswith(OLD_ARGS):
        return False
    words = _split(rest[: -len(OLD_ARGS)])
    if not words or any(kind != "word" for kind, *_ in words):
        return False
    program, *options = (text for _, text, _, _ in words)
    name = program.replace("\\", "/").rsplit("/", 1)[-1]
    if not PYTHON.match(name):
        return False
    launcher = name.lower() in ("py", "py.exe")
    return all(launcher and PY_VERSION.match(o) for o in options)


def uses_variables(entry) -> bool:
    """A command with $-variables, which Git Bash and PowerShell read differently."""
    cmd = entry.get("command") if isinstance(entry, dict) else None
    return isinstance(cmd, str) and bool(VARIABLE.search(cmd))


def windows_entry(entry: dict, current, glyphs: str, ours: bool, replace: bool, env, python):
    """(entry, rewritten): plan_entry's entry as Windows needs it.

    A new entry, and dashline's own old Bash-only one (old_form; with --replace, any of
    dashline's that uses variables), get the Windows command (windows_command) with the
    Python `python()` finds; `rewritten` says it was such an old one. Another entry of
    dashline's is kept as written.
    """
    rewrite = ours and (old_form(current) or (replace and uses_variables(current)))
    if ours and not rewrite:
        return entry, False
    name = python()
    if name is None:
        raise InstallError(
            "no Python 3.9 or newer runs as py -3, python or python3 here, and the "
            "statusLine command needs one of them on PATH. Install Python (python.org, "
            "or `winget install Python.Python.3.13`), then run this again. If `py -0` "
            "lists a newer Python that `py -3` doesn't pick, py.ini or PY_PYTHON3 pins an "
            "older one. Nothing was changed."
        )
    return {**entry, "command": command(glyphs, windows_command(env, name))}, rewrite


def windows_python(which=None, run=None) -> str | None:
    """The first WINDOWS_PYTHONS name that runs Python 3.9 or newer, or None.

    Run, not just looked up: `python3` can be the Microsoft Store's stand-in, which
    opens the Store instead of running anything.
    """
    import shutil
    import subprocess

    which = which or shutil.which
    run = run or subprocess.run
    check = "import sys; print(sys.version_info >= (3, 9))"
    for name in WINDOWS_PYTHONS:
        program, *options = name.split()
        found = which(program)
        if not found:
            continue
        try:
            r = run(
                [found, *options, "-I", "-S", "-c", check],
                capture_output=True,
                text=True,
                timeout=PROBE_TIMEOUT,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and r.stdout.strip() == "True":
            return name
    return None


def runs_install_dir(entry, env=None) -> bool:
    """A statusLine entry whose command runs statusline.py in the config dir."""
    if not isinstance(entry, dict):
        return False
    cmd = entry.get("command")
    if not isinstance(cmd, str):
        return False
    cmd = cmd.replace("\\", "/")
    target = config_dir(os.environ if env is None else env).replace("\\", "/").rstrip("/")
    if host.WINDOWS:  # C:\Cfg and c:\cfg are the same folder there
        cmd, target = cmd.lower(), target.lower()
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
    value = flag_value(cmd) if isinstance(cmd, str) else None
    return value if value in GLYPH_SETS else "unicode"


def flag_value(cmd: str) -> str | None:
    """The --glyphs value dashline gets from `cmd`, or None when it names none.

    Read from dashline's own arguments when the command can be followed (a tail like
    `|| echo --glyphs x` isn't dashline's); otherwise from the first flag anywhere.
    """
    found = dashline_args(cmd)
    if found is None:
        match = GLYPHS.search(cmd)
        return match.group(1) if match else None
    value = None
    for _, flag in found[1]:
        value = flag
    return value


def _split(cmd: str) -> list | None:
    """A shell command as words and operators: [(kind, text, start, end)].

    A word's text has its quotes and escapes taken out; start and end are its place in
    `cmd`. None for a command this can't follow: an unclosed quote, `$(…)` or a backtick.
    """
    out = []
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c in " \t":
            i += 1
            continue
        if c in "\n;|&()<>":
            j = i + 1
            while j < n and c in "|&<>" and cmd[j] in "|&<>":
                j += 1  # ||, &&, >>, >&, 2>&1's >&
            out.append(("op", cmd[i:j], i, j))
            i = j
            continue
        start, text = i, []
        while i < n and cmd[i] not in " \t\n;|&()<>":
            c = cmd[i]
            if c == "`" or cmd.startswith("$(", i):
                return None
            if c == "'":
                end = cmd.find("'", i + 1)
                if end < 0:
                    return None
                text.append(cmd[i + 1 : end])
                i = end + 1
            elif c == '"':
                i += 1
                while i < n and cmd[i] != '"':
                    if cmd[i] == "`" or cmd.startswith("$(", i):
                        return None
                    if cmd[i] == "\\" and i + 1 < n and cmd[i + 1] in '"\\$`':
                        i += 1
                    text.append(cmd[i])
                    i += 1
                if i >= n:
                    return None
                i += 1
            elif cmd.startswith("${", i):
                end = cmd.find("}", i)
                if end < 0:
                    return None
                text.append(cmd[i : end + 1])
                i = end + 1
            elif c == "\\":
                text.append(cmd[i : i + 2])  # kept: a Windows path's separators
                i += 2
            else:
                text.append(c)
                i += 1
        out.append(("word", "".join(text), start, i))
    return out


def _is_separator(token) -> bool:
    """An operator that ends a simple command (not a redirection like `2>`)."""
    return token[0] == "op" and token[1][0] not in "<>"


def dashline_args(cmd: str) -> tuple | None:
    """(end of the statusline.py argument, [(span, value)] of its --glyphs flags).

    Only for a command that runs the script directly: in the last simple command naming
    statusline.py, Python (with options, after any VAR=value) runs it as its script.
    Anything else (the path inside `bash -lc '…'`, a `[ -f … ]` test) gives None:
    there's no telling where dashline's own arguments are.
    """
    tokens = _split(cmd)
    if tokens is None:
        return None
    script = None
    for i, token in enumerate(tokens):
        if token[0] == "word" and MARK in cmd[token[2] : token[3]].replace("\\", "/"):
            script = i
    if script is None:
        return None
    raw = cmd[tokens[script][2] : tokens[script][3]].replace("\\", "/")
    if not raw.rstrip("'\"").endswith(MARK):
        return None
    first = script
    while first > 0 and not _is_separator(tokens[first - 1]):
        first -= 1
    words = [t for t in tokens[first:script] if t[0] == "word"]
    if any(t[0] == "op" for t in tokens[first:script]):
        return None  # a redirection before the script: not a plain `python3 … script`
    while words and (ASSIGNMENT.match(words[0][1]) or words[0][1] == "exec"):
        words.pop(0)
    if not words or not PYTHON.match(os.path.basename(words[0][1].replace("\\", "/"))):
        return None
    options = words[1:]
    k = 0
    while k < len(options):
        if not options[k][1].startswith("-"):
            return None
        k += 2 if options[k][1] in ("-X", "-W") else 1
    flags = []
    j = script + 1
    while j < len(tokens) and not _is_separator(tokens[j]):
        kind, text = tokens[j][0], tokens[j][1]
        if kind == "op":
            j += 2  # a redirection and its target
            continue
        if text == "--glyphs" or text.startswith("--glyphs="):
            start = tokens[j - 1][3]  # from the end of the word before: its space goes too
            value, end = text[len("--glyphs=") :] or None, tokens[j][3]
            if text == "--glyphs" and j + 1 < len(tokens) and tokens[j + 1][0] == "word":
                j += 1
                value, end = tokens[j][1], tokens[j][3]
            flags.append(((start, end), value))
        j += 1
    return tokens[script][3], flags


def with_glyphs(cmd: str, glyphs: str) -> str | None:
    """`cmd` asking for `glyphs`, or None if that can't be done safely.

    dashline's own --glyphs flags are taken out and the new one goes right after the
    statusline.py argument, so a command that goes on (`… 2>/dev/null || echo off`)
    keeps working; a --glyphs in that tail isn't dashline's and stays. The rest of the
    command is kept as written.
    """
    found = dashline_args(cmd)
    if found is None:
        return None
    end, flags = found
    out = cmd
    for (start, stop), _ in reversed(flags):
        out = out[:start] + out[stop:]
    if glyphs == "unicode":
        return out
    return f"{out[:end]} --glyphs {glyphs}{out[end:]}"


def glyphs_edit(cmd: str, glyphs: str) -> str:
    """The edit to make by hand when with_glyphs can't: words for a message."""
    found = list(GLYPHS.finditer(cmd))
    if len(found) == 1:
        old = found[0].group(0).strip()
        if glyphs == "unicode":
            return f"remove `{old}`"
        return f"change `{old}` to `--glyphs {glyphs}`"
    return f"add `--glyphs {glyphs}` right after statusline.py, where dashline reads it"


def home_short(path: str, env=None) -> str:
    """`/home/me/.claude/x` → `~/.claude/x`, for messages (with `/` on Windows too).

    On Windows `~` there would be read by Git Bash, whose HOME can be another folder
    (H:\\ on a domain): then the path is spelled out.
    """
    from dashline.text import collapse_home

    env = os.environ if env is None else env
    home = home_dir(env)
    if host.WINDOWS:
        bash = env.get("HOME")
        same = os.path.normcase(os.path.normpath(bash or home))
        if same != os.path.normcase(os.path.normpath(home)):
            home = None
    return collapse_home(path, home)


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
    """ "missing" (or empty), "ours" (holds the dashline package) or "theirs".

    A link (dotfiles kept in a repo, say) counts as the folder it points to; one that
    points nowhere yet is missing.
    """
    if os.path.islink(target) and not os.path.exists(target):
        return "missing"
    if not os.path.isdir(target):
        return "theirs" if os.path.lexists(target) else "missing"
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


def _extras(folder: str) -> list:
    """Top-level names in an install folder that an install didn't put there."""
    if not os.path.isdir(folder):
        return []
    try:
        return sorted(name for name in os.listdir(folder) if name not in OWN_NAMES)
    except OSError:
        return []


def _unique(path: str) -> str:
    """`path`, or `path-2`, `path-3`, … whichever doesn't exist yet."""
    n, found = 1, path
    while os.path.lexists(found):
        n += 1
        found = f"{path}-{n}"
    return found


def _move_back(moved: list, src: str, dst: str) -> list:
    """Move `moved` names from src back to dst; returns those that couldn't go."""
    stuck = []
    for name in moved:
        try:
            os.rename(os.path.join(src, name), os.path.join(dst, name))
        except OSError:
            stuck.append(name)
    return stuck


def _keep(old: str) -> str:
    """What's left of the old folder once only the user's files are in it: renamed to
    statusline.kept (never removed, since those files are theirs). Returns its path."""
    for name in OWN_NAMES:
        path = os.path.join(old, name)
        if os.path.isdir(path) and not os.path.islink(path):
            _rmtree(path)
        elif os.path.lexists(path):
            os.unlink(path)
    kept = _unique(os.path.join(os.path.dirname(old), "statusline.kept"))
    os.rename(old, kept)
    return kept


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
    """Copy this package into the install dir. Returns (target, what happened, notes).

    Files the user added at the top of the folder (notes, a wrapper script, a venv) are
    moved into the new folder, so an update doesn't lose them or copy them. One that
    can't be moved stays behind in statusline.kept, and a note says so. When the folder
    is a link (dotfiles), the copy goes where it points and the link stays.
    """
    import shutil
    import time

    from dashline import __version__

    root = source_root()
    target = install_dir(env)
    real = os.path.realpath(target)
    if os.path.realpath(root) == real:
        return target, "this is the installed copy", []
    source = files(root, source_shim(root))
    if "statusline.py" not in source:
        raise InstallError(f"no statusline.py next to {root}")
    parent = os.path.dirname(real)
    if os.path.islink(target) and not os.path.isdir(parent):
        raise InstallError(f"{target} is a link to {real}, whose folder doesn't exist")
    clean_leftovers(parent, time.time())
    if digest(source) == digest(installed_files(env)) and installed_version(env) == __version__:
        return target, "unchanged", []

    # Build the new copy beside the old one, then swap folders with two renames. A render
    # never reads a half-copied folder, but one starting between the renames finds no
    # folder and draws nothing that once.
    os.makedirs(parent, exist_ok=True)
    new, old = f"{real}.new-{os.getpid()}", f"{real}.old-{os.getpid()}"
    _rmtree(new)
    _rmtree(old)
    had = os.path.lexists(real)
    moved, stuck = [], []
    swapped = False
    try:
        os.makedirs(os.path.join(new, "dashline"))
        for rel, path in source.items():
            shutil.copyfile(path, os.path.join(new, *rel.split("/")))
        with open(os.path.join(new, "VERSION"), "w", encoding="utf-8", newline="\n") as f:
            f.write(__version__ + "\n")
        for name in _extras(real):
            try:
                os.rename(os.path.join(real, name), os.path.join(new, name))
                moved.append(name)
            except OSError as e:
                stuck.append((name, e.strerror or str(e)))
        # retry_held: on Windows a folder with a file open in it (a scan of the new
        # copy, a render importing the old one) can't be renamed for a moment.
        if had:
            retry_held(os.rename, real, old)
        try:
            retry_held(os.rename, new, real)
        except BaseException:
            if had:  # put the old copy back, so a render still finds one
                retry_held(os.rename, old, real)
            raise
        swapped = True
    except BaseException as e:
        if not swapped:
            home = real if os.path.isdir(real) else old
            if _move_back(moved, new, home):  # never delete the user's files
                os.rename(new, _unique(os.path.join(parent, "statusline.kept")))
            else:
                _rmtree(new)
        if isinstance(e, OSError):
            raise InstallError(f"couldn't copy to {target}: {e.strerror or e}") from e
        raise
    notes = []
    if stuck:
        kept = home_short(_keep(old), env)
        for name, why in stuck:
            notes.append(f"couldn't move {name} into the new copy ({why}); it's in {kept}")
    else:
        _rmtree(old)
    return target, "updated" if had else "installed", notes


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
    except RecursionError as e:
        raise InstallError(f"{path} isn't readable JSON (nested too deeply)") from e
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
    if not host.can_write_in(folder):
        raise InstallError(
            f"can't write in {folder}, so {path} was left alone; make the folder "
            "writable, or add the statusLine entry yourself, then run again"
        )


def settings_text(path: str, data: dict) -> str:
    """settings.json's new text. Made before anything is written, so a file that can't
    be written back fails the install while nothing has changed yet.

    Non-ASCII stays as written. A lone surrogate (a `\\ud83d` escape: valid JSON, but no
    character) can't be UTF-8, so then every non-ASCII character is written as an escape.
    """
    try:
        text = json.dumps(data, indent=2, ensure_ascii=False)
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            text = json.dumps(data, indent=2)
    except (RecursionError, ValueError) as e:
        raise InstallError(f"{path} can't be written back ({e}); fix it and run again") from e
    return text + "\n"


def write_settings(path: str, text: str) -> None:
    """Write `text` atomically, through a symlink to the real file, keeping its
    permissions and a byte-order mark if it had one."""
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
        # "\n" as written: no CRLF on Windows, so a settings.json kept in git doesn't
        # change on every line.
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(bom + text)
            if mode is not None:
                os.chmod(tmp, mode)
        # Claude Code or an antivirus scan can hold the file open for a moment.
        retry_held(os.replace, tmp, real)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def plan_entry(
    current,
    glyphs: str | None,
    replace: bool,
    ours: bool,
    settings: str = "settings.json",
) -> tuple:
    """(new entry or None, glyphs used). None means: the entry is someone else's.

    ours: `current` is dashline's (is_ours). It keeps its command as written (say, with
    a full path to Python): only the --glyphs flag changes, and only when asked for
    another set or when it names an unknown one. A command where dashline's arguments
    can't be told apart (`bash -lc '…'`) is left as it is; asked for another set there,
    this raises InstallError with the edit to make by hand.
    """
    if current is not None and not ours and not replace:
        return None, None
    if ours:
        entry = dict(current)
        asked = glyphs
        glyphs = glyphs or glyphs_of(current)
        cmd = current["command"]
        if (flag_value(cmd) or "unicode") != glyphs:
            changed = with_glyphs(cmd, glyphs)
            if changed is not None:
                cmd = changed
            elif asked:
                raise InstallError(
                    "can't change --glyphs in this statusLine command automatically, "
                    f"because it doesn't run statusline.py directly:\n  {cmd}\n"
                    f"To use {glyphs} glyphs, edit {settings} yourself: "
                    f"{glyphs_edit(cmd, glyphs)}. Nothing was changed."
                )
            else:
                glyphs = glyphs_of(current)
        entry["command"] = cmd
    else:
        glyphs = glyphs or "unicode"
        entry = {"type": "command", "command": command(glyphs)}
    entry["type"] = "command"
    entry.setdefault("refreshInterval", REFRESH)
    return entry, glyphs


def write_entry(path: str, text: str) -> None:
    try:
        write_settings(path, text)
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
    windows: bool | None = None,
    python=windows_python,
) -> int:
    """Copy dashline and point settings at it. Exit 3 (nothing changed) when either the
    settings entry or the install folder belongs to something else and --replace wasn't
    given; exit 4 (nothing changed) when the installed copy is newer and --downgrade
    wasn't given.

    windows: write the Windows command (default: when running on Windows), for a new
    entry and in place of the old Bash-only one (old_form); python finds the Python it
    names (windows_python), for tests to stand in for.
    """
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
        entry, used = plan_entry(current, glyphs, replace, ours, settings)
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
        # Past both stops, so Python is looked for only when a command will be written.
        rewrite = False
        if host.WINDOWS if windows is None else windows:
            entry, rewrite = windows_entry(entry, current, used, ours, replace, env, python)
        text = None
        if entry != current:
            check_writable(path)
            text = settings_text(path, {**data, "statusLine": entry})
    except InstallError as e:
        sys.stderr.write(f"dashline: {e}\n")
        return 1
    aside, done = None, False
    try:
        if theirs_folder:
            aside = set_aside(target)
            out.write(f"moved the files in {where} to {home_short(aside, env)}\n")
        target, copied, notes = copy(env)
        if copied == "unchanged":
            out.write(f"{where} already has dashline {__version__}\n")
        elif copied == "this is the installed copy":
            out.write(f"running from {where}: nothing to copy\n")
        else:
            out.write(f"{copied} dashline {__version__} in {where}\n")
        for note in notes:
            out.write(f"note: {note}\n")
        if text is not None:
            write_entry(path, text)
        done = True
    except (InstallError, OSError) as e:
        sys.stderr.write(f"dashline: {e}\n")
        return 1
    finally:
        # Any failure, Ctrl-C included: the other tool's statusline still runs from its
        # folder, so put it back.
        if aside and not done:
            out.write(put_back(aside, target, env))
    if rewrite:
        out.write(
            "note: the old statusLine command was Bash only (PowerShell can't run it); "
            f"it's now {entry['command']}\n"
        )
    verb = "already runs" if entry == current else "now runs"
    out.write(f"{settings}: statusLine {verb} it with {describe(entry)}\n")
    other = overridden_by(env, project_dir(env, cwd))
    if other:
        out.write(
            f"note: {home_short(other[0], env)} sets its own statusLine, which wins over "
            f"{settings} in this project\n"
        )
    return 0
