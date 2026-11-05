"""--install: copy dashline into the config dir and point settings.json at it (PLAN §3, §9).

The install skill runs this from the plugin. The package is copied, not linked, because
the plugin's own folder changes with every version. The settings entry names the copy
through `${CLAUDE_CONFIG_DIR:-$HOME/.claude}`, so it still resolves in a devcontainer that
mounts ~/.claude under another user.

A statusLine that runs something else is never replaced without --replace: the skill
shows it to the user and asks first.
"""

from __future__ import annotations

import json
import os
import re
import sys

from dashline.theme import config_dir

COMMAND = 'python3 -I -S "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/scripts/statusline/statusline.py"'
MARK = "scripts/statusline/statusline.py"  # in the command: it runs the installed copy
REFRESH = 60
GLYPHS = re.compile(r"--glyphs(?:=|\s+)(\S+)")

# Exit codes beyond 0 and 1.
NEEDS_REPLACE = 3


class InstallError(Exception):
    pass


def install_dir(env) -> str:
    return os.path.join(config_dir(env), "scripts", "statusline")


def user_settings(env) -> str:
    return os.path.join(config_dir(env), "settings.json")


def command(glyphs: str) -> str:
    return COMMAND if glyphs == "unicode" else f"{COMMAND} --glyphs {glyphs}"


def is_ours(entry) -> bool:
    """A statusLine entry that runs the installed copy of dashline."""
    if not isinstance(entry, dict):
        return False
    cmd = entry.get("command")
    return isinstance(cmd, str) and MARK in cmd.replace("\\", "/")


def glyphs_of(entry) -> str:
    """The glyph set an entry's command asks for (unicode when it names none)."""
    cmd = entry.get("command") if isinstance(entry, dict) else None
    match = GLYPHS.search(cmd) if isinstance(cmd, str) else None
    return match.group(1).strip("'\"") if match else "unicode"


def home_short(path: str, env=None) -> str:
    """`/home/me/.claude/x` → `~/.claude/x`, for messages."""
    home = (env or os.environ).get("HOME") or os.path.expanduser("~")
    home = home.rstrip("/")
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


def _rmtree(path: str) -> None:
    import shutil

    if os.path.islink(path):
        os.unlink(path)
    elif os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def copy(env) -> tuple:
    """Copy this package into the install dir. Returns (target, what happened)."""
    import shutil

    from dashline import __version__

    root = source_root()
    target = install_dir(env)
    if os.path.realpath(root) == os.path.realpath(target):
        return target, "this is the installed copy"
    source = files(root, source_shim(root))
    if "statusline.py" not in source:
        raise InstallError(f"no statusline.py next to {root}")
    if digest(source) == digest(installed_files(env)) and installed_version(env) == __version__:
        return target, "unchanged"

    # Build the new copy beside the old one, then swap folders, so a render running
    # meanwhile sees one whole version or the other.
    os.makedirs(os.path.dirname(target), exist_ok=True)
    new, old = f"{target}.new-{os.getpid()}", f"{target}.old-{os.getpid()}"
    _rmtree(new)
    try:
        os.makedirs(os.path.join(new, "dashline"))
        for rel, path in source.items():
            shutil.copyfile(path, os.path.join(new, *rel.split("/")))
        with open(os.path.join(new, "VERSION"), "w", encoding="utf-8") as f:
            f.write(__version__ + "\n")
        had = os.path.lexists(target)
        if had:
            os.rename(target, old)
        os.rename(new, target)
    except OSError as e:
        _rmtree(new)
        raise InstallError(f"couldn't copy to {target}: {e.strerror or e}") from e
    _rmtree(old)
    return target, "updated" if had else "installed"


# ---- settings.json ----


def read_settings(path: str) -> dict:
    """The settings file as a dict ({} if missing). Raises InstallError if unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise InstallError(f"can't read {path}: {e.strerror or e}") from e
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as e:
        raise InstallError(f"{path} isn't valid JSON ({e}); fix it and run again") from e
    if not isinstance(data, dict):
        raise InstallError(f"{path} isn't a JSON object; fix it and run again")
    return data


def write_settings(path: str, data: dict) -> None:
    """Write atomically, through a symlink to the real file, keeping its permissions."""
    real = os.path.realpath(path)
    os.makedirs(os.path.dirname(real), exist_ok=True)
    try:
        mode = os.stat(real).st_mode & 0o777
    except OSError:
        mode = None
    tmp = f"{real}.dashline-{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, real)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def plan_entry(current, glyphs: str | None, replace: bool) -> tuple:
    """(new entry or None, glyphs used). None means: the entry is someone else's."""
    if current is not None and not is_ours(current) and not replace:
        return None, None
    if is_ours(current):
        entry = dict(current)
        glyphs = glyphs or glyphs_of(current)
    else:
        entry = {}
        glyphs = glyphs or "unicode"
    entry["type"] = "command"
    entry["command"] = command(glyphs)
    entry.setdefault("refreshInterval", REFRESH)
    return entry, glyphs


def update_settings(env, glyphs: str | None, replace: bool) -> tuple:
    """Point user settings at the installed copy: ("changed"|"unchanged"|"theirs", entry)."""
    path = user_settings(env)
    data = read_settings(path)
    current = data.get("statusLine")
    entry, _ = plan_entry(current, glyphs, replace)
    if entry is None:
        return "theirs", current
    if entry == current:
        return "unchanged", entry
    data["statusLine"] = entry
    try:
        write_settings(path, data)
    except OSError as e:
        raise InstallError(f"couldn't write {path}: {e.strerror or e}") from e
    return "changed", entry


def overridden_by(env, project_dir: str | None) -> tuple | None:
    """(path, entry) of a statusLine that wins over user settings and isn't dashline."""
    from dashline.theme import _read_json, settings_files

    user = os.path.realpath(user_settings(env))
    for path in settings_files(project_dir, env):
        if os.path.realpath(path) == user:
            return None
        entry = _read_json(path).get("statusLine")
        if entry is not None:
            return None if is_ours(entry) else (path, entry)
    return None


def describe(entry: dict) -> str:
    glyphs = glyphs_of(entry)
    refresh = entry.get("refreshInterval")
    text = f"{glyphs} glyphs"
    if isinstance(refresh, (int, float)) and not isinstance(refresh, bool):
        text += f", refreshing every {refresh:g} s"
    return text


def run(glyphs: str | None, replace: bool = False, env=None, out=None, cwd=None) -> int:
    from dashline import __version__

    env = os.environ if env is None else env
    out = out or sys.stdout
    try:
        target, copied = copy(env)
        where = home_short(target, env)
        if copied == "unchanged":
            out.write(f"{where} already has dashline {__version__}\n")
        elif copied == "this is the installed copy":
            out.write(f"running from {where}: nothing to copy\n")
        else:
            out.write(f"{copied} dashline {__version__} in {where}\n")
        state, entry = update_settings(env, glyphs, replace)
    except InstallError as e:
        sys.stderr.write(f"dashline: {e}\n")
        return 1
    settings = home_short(user_settings(env), env)
    if state == "theirs":
        shown = json.dumps(entry, indent=2, ensure_ascii=False).replace("\n", "\n  ")
        out.write(
            f"{settings} has a statusLine that runs something else:\n  {shown}\n"
            "settings.json was not changed. Run again with --replace to use dashline instead.\n"
        )
        return NEEDS_REPLACE
    verb = "now runs" if state == "changed" else "already runs"
    out.write(f"{settings}: statusLine {verb} it with {describe(entry)}\n")
    other = overridden_by(env, os.getcwd() if cwd is None else cwd)
    if other:
        out.write(
            f"note: {home_short(other[0], env)} sets its own statusLine, which wins over "
            f"{settings} in this project\n"
        )
    return 0
