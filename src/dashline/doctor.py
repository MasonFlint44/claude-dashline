"""--doctor: check everything a statusline needs, one line each (PLAN §9).

Each check prints `ok`, `warn`, `fail` or `info`, a name and what it found; a problem gets
a `fix:` line under it. The doctor skill reads this output, so names and wording stay
stable. Exit 1 when something fails: the statusline or its plan bars won't show.

Doctor fetches the usage endpoint once, in the foreground, the same way the background
child does: it takes the same lock, refreshes the cache, and on failure sets the same
hold a render would. It doesn't while the server has asked this login to wait
(Retry-After): it says until when instead, and `--fetch-now` (fetch_now) tries anyway.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time

from dashline import install
from dashline.usage import API_URL

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"
STATUS_TOKENS = {OK: "success", WARN: "warning", FAIL: "error", INFO: "inactive"}
MIN_PYTHON = (3, 9)
MIN_GIT = (2, 15)  # porcelain v2 (2.11) and --no-optional-locks (2.15)
LOCK_WAIT = 5.0  # seconds doctor waits for a background fetch to finish
SLOW_MS = 500
# On Windows starting the shell alone (Git Bash, PowerShell) takes most of that.
SLOW_MS_WINDOWS = 2500
WINDOWS = os.name == "nt"
NERD_TERMINALS = {"ghostty": "Ghostty", "wezterm": "WezTerm"}  # bundle the symbols
WSL_DRIVES = "/mnt"  # where WSL mounts the Windows drives (its default)
# Font files with the Nerd Font icons: Nerd Fonts' own, and Cascadia Code / Mono NF
# (CascadiaCodeNF.ttf), which carry every icon in the nerd set (checked 11/6, 2407.24).
NERD_FILES = ("*Nerd*", "Cascadia*NF*")


def _ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "just now" if seconds < 5 else f"{seconds} s ago"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m ago"


def _span(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 3600:
        return f"{max(1, seconds // 60)} min"
    if seconds < 86400:
        return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"
    return f"{seconds // 86400}d{seconds % 86400 // 3600}h"


def _clock(when: float, now: float) -> str:
    """A local time: `14:05`, or `Fri 14:05` when that isn't today."""
    shown, today = time.localtime(when), time.localtime(now)
    if shown[:3] == today[:3]:
        return time.strftime("%H:%M", shown)
    return time.strftime("%a %H:%M", shown)


def stderr_reason(err: list, out: list = ()) -> str | None:
    """The line of a command's output that says what went wrong.

    dashline's own errors start with `dashline:`; a usage error follows its line with
    the help text, so the last line would be a line of help. Otherwise the last line of
    stderr (a traceback's ends with the error). A command that sends stderr away
    (`2>/dev/null`) still prints its `dashline:` line on stdout, where the statusline
    shows it.
    """
    for line in err:
        if line.startswith("dashline:"):
            return line
    if err:
        return err[-1]
    return next((line for line in out if line.startswith("dashline:")), None)


def summarize(data: dict) -> str:
    """The usage answer in a few words: `5h 22% · 7d 48% · Fable 24% · credits 12%`."""
    from dashline.stdin import _dig, _num, _str
    from dashline.usage import WINDOW_LABELS

    parts = []
    limits = data.get("limits") if isinstance(data, dict) else None
    for row in limits if isinstance(limits, list) else []:
        if not isinstance(row, dict):
            continue
        kind, percent = _str(row.get("kind")), _num(row.get("percent"))
        if kind is None or percent is None:
            continue
        label = WINDOW_LABELS.get(kind) or _str(_dig(row, "scope", "model", "display_name"))
        parts.append(f"{label or kind.replace('_', ' ')} {percent:.0f}%")
    spend = data.get("spend") if isinstance(data, dict) else None
    if isinstance(spend, dict) and spend.get("enabled"):
        percent = _num(spend.get("percent"))
        if percent is not None:
            parts.append(f"credits {percent:.0f}%")
    return " · ".join(parts) or "no limits on this plan"


def windows_shell(env, which=None) -> tuple:
    """(argv before the command, name): the shell Claude Code runs a statusLine command
    in on Windows. Git Bash when there is one (CLAUDE_CODE_GIT_BASH_PATH, else next to
    git on PATH), otherwise PowerShell.
    """
    import shutil

    which = which or shutil.which
    bash = env.get("CLAUDE_CODE_GIT_BASH_PATH")
    if not (bash and os.path.isfile(bash)):
        bash = None
        git = which("git")
        # Git for Windows keeps bash.exe in <root>\bin, and git.exe in <root>\cmd, or in
        # <root>\ucrt64\bin (or mingw64\bin), first on PATH in Git Bash itself, where the
        # skill runs us.
        folder = os.path.dirname(git) if git else ""
        for _ in range(3):
            parent = os.path.dirname(folder)
            if not folder or parent == folder:
                break
            folder = parent
            found = os.path.join(folder, "bin", "bash.exe")
            if os.path.isfile(found):
                bash = found
                break
    if bash:
        return [bash, "-c"], "Git Bash"
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command"], "PowerShell"


# The lines PowerShell 5.1 adds around what a program wrote to stderr.
PS_DECORATION = re.compile(r"^\s*(?:At line:\d+ char:\d+|\+ )")
PS_PREFIX = re.compile(r"^(\S+) : ")


def powershell_unwrapped(err: list) -> list:
    """`err` without PowerShell's error-record dressing, as the program wrote it.

    PowerShell 5.1 turns a program's stderr, and a command it can't find, into an error
    record: `py : <the line>`, then `At line:1 char:1`, `+ …` lines and
    `+ FullyQualifiedErrorId : …` last, where stderr_reason looks.
    """
    if not any("FullyQualifiedErrorId" in line for line in err):
        return err
    lines = [line for line in err if line.strip() and not PS_DECORATION.match(line)]
    m = PS_PREFIX.match(lines[0]) if lines else None
    if m:
        lines = [line[len(m.group(0)) :] if line.startswith(m.group(0)) else line for line in lines]
    return lines


def first_word(cmd: str) -> str:
    """The program a shell command runs: `python3` in `python3 -I -S x.py`."""
    try:
        words = shlex.split(cmd)
    except ValueError:
        words = cmd.split()
    return words[0] if words else "python3"


version_tuple = install.version_tuple


KEYCHAIN_FIX = (
    "unlock the login Keychain (Keychain Access, or `security unlock-keychain` over SSH) "
    "and allow access if macOS asks; /login won't help"
)


def login_fix(why: str) -> str:
    from dashline.account import KEYCHAIN_LOCKED

    return KEYCHAIN_FIX if why == KEYCHAIN_LOCKED else "run /login in Claude Code"


def unknown_glyphs(entry) -> str | None:
    """The --glyphs value of an entry's command when it names no glyph set, else None.

    install.glyphs_of reads such a value as unicode, but the statusline refuses it.
    """
    cmd = entry.get("command") if isinstance(entry, dict) else None
    match = install.GLYPHS.search(cmd) if isinstance(cmd, str) else None
    if not match:
        return None
    value = match.group(1).strip("'\"")
    return None if value in install.GLYPH_SETS else value


def font_guess(env, platform: str) -> tuple:
    """(True if a Nerd Font is likely to render, what was found)."""
    term = (env.get("TERM_PROGRAM") or "").lower()
    if term in NERD_TERMINALS:
        return True, f"{NERD_TERMINALS[term]} bundles Nerd Font symbols"
    if env.get("WSL_DISTRO_NAME") or platform == "win32":
        return _windows_fonts(env, platform)
    if platform.startswith("linux"):
        import subprocess

        try:
            r = subprocess.run(
                ["fc-list", ":", "family"], capture_output=True, text=True, timeout=5
            )
            families = r.stdout.splitlines() if r.returncode == 0 else []
        except (OSError, subprocess.SubprocessError):
            families = []
        names = {f.split(",")[0] for f in families}
        nerd = sorted(
            n for n in names if "Nerd Font" in n or (n.startswith("Cascadia") and n.endswith(" NF"))
        )
        if nerd:
            more = f" (+{len(nerd) - 1} more)" if len(nerd) > 1 else ""
            return True, f"found {nerd[0]}{more}"
    elif platform == "darwin":
        import glob

        from dashline.theme import home_dir

        dirs = [os.path.join(home_dir(env), "Library", "Fonts"), "/Library/Fonts"]
        found = [p for d in dirs for n in NERD_FILES for p in glob.glob(os.path.join(d, n))]
        if found:
            return True, f"found {os.path.basename(sorted(found)[0])}"
    return False, "no Nerd Font found"


def _windows_fonts(env, platform: str) -> tuple:
    """font_guess where the terminal is a Windows program: Windows' own font folders.

    Under WSL those are on the Windows drives (`/mnt/<drive>/`): system-wide and each
    user's own. The Linux side's fonts don't reach the terminal.
    """
    import glob

    if platform == "win32":
        local = env.get("LOCALAPPDATA") or ""
        dirs = [os.path.join(env.get("WINDIR") or r"C:\Windows", "Fonts")]
        dirs += [os.path.join(local, "Microsoft", "Windows", "Fonts")] if local else []
    else:
        dirs = glob.glob(os.path.join(WSL_DRIVES, "*", "Windows", "Fonts"))
        user = ("Users", "*", "AppData", "Local", "Microsoft", "Windows", "Fonts")
        dirs += glob.glob(os.path.join(WSL_DRIVES, "*", *user))
    found = sorted(
        os.path.basename(p) for d in dirs for n in NERD_FILES for p in glob.glob(os.path.join(d, n))
    )
    if found:
        return True, f"found {found[0]} in Windows' fonts"
    return False, "no Nerd Font in Windows' fonts (the terminal draws with those)"


class Doctor:
    def __init__(
        self, env, now: float, cwd: str, base_url: str = API_URL, platform=None, fetch_now=False
    ):
        self.env = env
        self.now = now
        self.cwd = cwd
        self.base_url = base_url
        self.platform = platform or sys.platform
        self.fetch_now = fetch_now  # fetch even while the server has asked us to wait
        self.results = []  # (status, name, text, fix)
        self.entry = None  # dashline's statusLine entry, once found
        self.account = None

    def add(self, status: str, name: str, text: str, fix: str | None = None) -> None:
        self.results.append((status, name, text, fix))

    def short(self, path: str) -> str:
        return install.home_short(path, self.env)

    def shell_path(self, path: str) -> str:
        """A path to paste into a shell: `~/` kept for short, the rest quoted."""
        short = self.short(path)
        if short.startswith("~/"):
            return "~/" + shlex.quote(short[2:])
        return shlex.quote(path)

    def run(self) -> list:
        names = ("python", "installed", "settings", "login", "usage", "cache", "command")
        names += ("git", "theme", "font")
        for name in names:
            try:
                getattr(self, name)()
            except Exception as e:  # a broken check is a finding, not a crash
                shown = "install" if name == "installed" else name
                self.add(FAIL, shown, f"the check itself failed: {type(e).__name__}: {e}")
        return self.results

    # ---- checks, in the order they print ----

    def python(self):
        v = sys.version_info
        text = f"{v.major}.{v.minor}.{v.micro} ({sys.executable})"
        if v[:2] < MIN_PYTHON:
            self.add(FAIL, "python", text, "dashline needs Python 3.9 or newer")
        else:
            self.add(OK, "python", text)

    def installed(self):
        from dashline import __version__

        target = install.install_dir(self.env)
        where = self.short(target)
        found = install.installed_files(self.env)
        if "statusline.py" not in found or not any(k.startswith("dashline/") for k in found):
            self.add(FAIL, "install", f"nothing installed in {where}", "run /dashline:install")
            return
        version = install.installed_version(self.env) or "unknown version"
        root = install.source_root()
        if os.path.realpath(root) == os.path.realpath(target):
            self.add(OK, "install", f"{where}: {version} (doctor ran from it)")
            return
        mine = install.digest(install.files(root, install.source_shim(root)))
        if mine == install.digest(found):
            self.add(OK, "install", f"{where}: {version}, same as this copy")
            return
        if version == __version__:
            text = f"{where}: {version}, but its files differ from this copy"
        else:
            text = f"{where}: {version}; this copy is {__version__}"
        theirs, mine = version_tuple(version), version_tuple(__version__)
        if theirs and mine and theirs > mine:
            self.add(
                WARN,
                "install",
                f"{where}: {version} is newer than this copy ({__version__})",
                "update the dashline plugin (/plugin), then run /dashline:install",
            )
            return
        self.add(WARN, "install", text, "run /dashline:install to update it")

    def settings(self):
        from dashline.theme import _read_json, settings_files

        sources = [(p, _read_json(p)) for p in settings_files(self.cwd, self.env)]
        user = os.path.realpath(install.user_settings(self.env))
        # The CLI merges the files, so the first one that sets a key decides it.
        hooks = next(((p, d) for p, d in sources if "disableAllHooks" in d), None)
        winner = next(((p, d["statusLine"]) for p, d in sources if "statusLine" in d), None)
        if winner is None:
            where = self.short(install.user_settings(self.env))
            self.add(FAIL, "settings", f"no statusLine in {where}", "run /dashline:install")
            return
        path, entry = winner
        where = self.short(path)
        is_user = os.path.realpath(path) == user
        if not install.is_ours(entry, self.env):
            cmd = entry.get("command") if isinstance(entry, dict) else None
            shown = f": {cmd}" if isinstance(cmd, str) else ""
            self.add(
                FAIL, "settings", f"{where} runs another statusline{shown}", self.fix_for(path)
            )
            return
        self.entry = entry
        if entry.get("type") != "command":
            self.add(
                FAIL,
                "settings",
                f'{where}: statusLine type isn\'t "command"',
                "run /dashline:install" if is_user else self.fix_for(path),
            )
            return
        if hooks is not None and hooks[1]["disableAllHooks"] is True:
            self.add(
                FAIL,
                "settings",
                f"disableAllHooks is on in {self.short(hooks[0])}, which also turns off "
                "the statusline",
                "remove disableAllHooks (it turns off hooks too, so that's your call)",
            )
            return
        text = f"{where}: {install.describe(entry)}"
        unknown = unknown_glyphs(entry)
        if unknown is not None:
            self.add(
                WARN,
                "settings",
                f"{where}: --glyphs {unknown} isn't a glyph set (nerd, unicode or ascii)",
                "run /dashline:install, which fixes the flag"
                if is_user
                else f"fix --glyphs in {where}",
            )
            return
        if not isinstance(entry.get("refreshInterval"), (int, float)):
            self.add(
                WARN,
                "settings",
                text + "; no refreshInterval",
                "plan bars only move when Claude Code redraws; "
                + ("/dashline:install sets 60" if is_user else f"add one to {where}"),
            )
            return
        self.add(OK, "settings", text)

    def fix_for(self, path: str) -> str:
        """How to get dashline's statusLine used when `path` sets the one that wins."""
        from dashline.theme import managed_settings_path

        where = self.short(path)
        if os.path.realpath(path) == os.path.realpath(install.user_settings(self.env)):
            return "run /dashline:install (it asks before replacing it)"
        managed = managed_settings_path()
        if managed and os.path.realpath(path) == os.path.realpath(managed):
            return f"{where} is managed settings, set by an administrator; only they can change it"
        return (
            f"{where} wins over your user settings here: remove its statusLine to use "
            "dashline, or leave it for this project"
        )

    def login(self):
        from dashline import account

        acct = account.load(self.env)
        self.account = acct
        if acct.mode != "subscription":
            keyed = any(self.env.get(v) for v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))
            if acct.label == "API" and not keyed:
                self.add(
                    OK,
                    "login",
                    "no Claude login found, so no plan bars (fine with an API key)",
                    None,
                )
            else:
                self.add(OK, "login", f"{acct.label}: billed per use, so no plan bars")
            return
        label = account.label_text(acct, {"sep_item": " · "}, self.now) or "subscription"
        token, source, expires = account.find_token(self.env, self.now, self.platform)
        if token is None:
            if source.startswith("token expired"):
                self.add(WARN, "login", f"{label}; {source}")
            else:
                self.add(FAIL, "login", f"{label}; {source}", login_fix(source))
            return
        del token
        where = (
            source if source.startswith("CLAUDE_") or "Keychain" in source else self.short(source)
        )
        text = f"{label}; token from {where}"
        if expires is not None:
            text += f", renews in {_span(expires - self.now)}"
        self.add(OK, "login", text)

    def user_fix(self, reason) -> str | None:
        """The fix for a fetch that failed for `reason`, when it is the user's to make."""
        from dashline.account import KEYCHAIN_LOCKED

        relogin = "run /login in Claude Code"
        return {
            "no Claude login found": relogin,
            KEYCHAIN_LOCKED: KEYCHAIN_FIX,
            "token rejected (401)": relogin,
            "not allowed (403): the login may lack the profile scope": (
                "a token from `claude setup-token` can't read usage; use /login instead"
                if self.env.get("CLAUDE_CODE_OAUTH_TOKEN")
                else relogin
            ),
        }.get(reason)

    def usage(self):
        from dashline import usage

        if self.account is None or self.account.mode != "subscription":
            self.add(INFO, "usage", "not fetched: plan bars are for Claude subscriptions")
            return
        who = self.account.fingerprint
        held = usage.hold(self.env, who, self.now)
        if not self.fetch_now and held and held.get("server") is True and held["until"] > self.now:
            # Respect the server's Retry-After; the user can still choose to try now.
            until = held["until"]
            reason = held.get("reason") if isinstance(held.get("reason"), str) else "a wait"
            fix = "it retries on its own after that; to try now anyway, run doctor with --fetch-now"
            cure = self.user_fix(reason)
            if cure:  # waiting won't help: the login needs fixing first
                fix = f"{cure}, then run doctor with --fetch-now to check"
            self.add(
                WARN,
                "usage",
                f"not fetched: the server asked to wait until {_clock(until, self.now)} "
                f"({_span(until - self.now)} left) after {reason}",
                fix,
            )
            return
        nonce = self.take_lock(usage)
        if nonce is None:
            self.add(
                INFO,
                "usage",
                "not fetched: a fetch is running in the background",
                "run doctor again in a moment to see its result",
            )
            return
        try:
            start = time.monotonic()
            result = usage.refresh(self.env, self.now, self.base_url, self.platform)
            ms = (time.monotonic() - start) * 1000
        finally:
            usage.release(self.env, nonce)
        if result == "ok":
            data, _ = usage.cached(self.env, who, self.now)
            self.add(OK, "usage", f"{ms:.0f} ms: {summarize(data or {})}")
            return
        held = usage.hold(self.env, who) or {}
        until = held.get("until")
        wait = f"; renders retry in {_span(until - self.now)}" if until else ""
        if held.get("server") is True:
            wait += " (the server asked for that wait)"
        if result.startswith("token expired"):
            self.add(WARN, "usage", result + wait)
            return
        fix = self.user_fix(result) or "run doctor again later"
        if result.startswith("no answer"):
            fix = "check the network or proxy (HTTPS_PROXY) to api.anthropic.com"
        elif result.startswith("redirect refused"):
            # api.anthropic.com doesn't redirect: a proxy or network is rewriting traffic.
            fix = "something between here and api.anthropic.com redirects it: check HTTPS_PROXY"
        elif result.startswith("fetch failed"):
            fix = "run doctor again later; report it if it keeps happening"
        self.add(FAIL, "usage", result + wait, fix)

    def take_lock(self, usage):
        """The fetch lock, waiting up to LOCK_WAIT for a background fetch to finish; None
        if one still holds it. A stale lock is broken as a render would break it."""
        waited, step = 0.0, 0.2
        while True:
            nonce = usage.take_lock(self.env, self.now + waited)
            if nonce is not None or waited >= LOCK_WAIT:
                return nonce
            time.sleep(step)
            waited += step

    def cache(self):
        from dashline import usage

        path = usage.cache_dir(self.env)
        where = self.short(path)
        if not os.path.isdir(path):
            if self.account is not None and self.account.mode != "subscription":
                self.add(OK, "cache", f"{where}: not needed without plan bars")
            else:
                self.add(
                    FAIL,
                    "cache",
                    f"{where} doesn't exist and couldn't be made",
                    f"check that {self.short(os.path.dirname(path))} is writable",
                )
            return
        if not os.access(path, os.W_OK):
            self.add(FAIL, "cache", f"{where} isn't writable", f"check the owner of {where}")
            return
        notes = []
        who = self.account.fingerprint if self.account is not None else None
        cache = usage._read_json(usage._path(self.env, usage.cache_name(who)))
        fetched = usage._num(cache.get("fetched_at"))  # never NaN or infinite
        if fetched is not None:
            notes.append(f"fetched {_ago(self.now - fetched)}")
        # The lock says when it was taken (`at`), else its mtime does. One from the
        # future means the clock was set back; either way the next render breaks it.
        # fetch.lock.break is a breaker's guard for a moment: not worth a note.
        found = usage._lock_id(os.path.join(path, "fetch.lock"))
        if found is not None:
            _, at, mtime = found
            if usage._lock_live(self.now - (at if at is not None else mtime)):
                notes.append("a fetch is running")
            else:
                notes.append("a stale fetch.lock (the next render clears it)")
        # dashline's own files, not the folder: it may be shared with other tools, and a
        # folder others can list only shows them file names.
        # Windows has no such mode bits (files inherit the profile folder's access).
        exposed = []
        try:
            names = [] if WINDOWS else usage.own_files(os.listdir(path), path)
        except OSError:
            names = []
        for name in names:
            try:
                mode = os.stat(os.path.join(path, name)).st_mode
            except OSError:
                continue
            if mode & 0o077:
                exposed.append(name)
        status, fix = OK, None
        if exposed:
            status = WARN
            notes.append(f"other users can read {', '.join(exposed)}")
            fix = "chmod 600 " + " ".join(self.shell_path(os.path.join(path, n)) for n in exposed)
        text = f"{where}" + (f": {', '.join(notes)}" if notes else "")
        self.add(status, "cache", text, fix)

    def command(self):
        """Run the settings command the way Claude Code does, on a sample session."""
        import subprocess

        if self.entry is None:
            self.add(INFO, "command", "not run: settings don't run dashline")
            return
        shell, shell_name = ["sh", "-c"], "sh"
        if WINDOWS:
            shell, shell_name = windows_shell(self.env)
        sample = {
            "session_id": "dashline-doctor",
            "model": {"id": "claude-sonnet-5-5", "display_name": "Sonnet 5.5"},
            "workspace": {"current_dir": self.cwd, "project_dir": self.cwd},
            "cwd": self.cwd,
            "context_window": {"used_percentage": 0},
            "cost": {"total_cost_usd": 0},
        }
        start = time.monotonic()
        try:
            r = subprocess.run(
                [*shell, self.entry["command"]],
                input=json.dumps(sample),
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                env=dict(self.env),
                cwd=self.cwd,
            )
        except subprocess.TimeoutExpired:
            self.add(FAIL, "command", "took over 10 s", "run /dashline:doctor again; report it")
            return
        except OSError as e:
            self.add(FAIL, "command", f"couldn't run {shell_name}: {e}")
            return
        ms = (time.monotonic() - start) * 1000
        lines = [line for line in r.stdout.splitlines() if line.strip()]
        err = r.stderr.strip().splitlines()
        if shell_name == "PowerShell":
            err = powershell_unwrapped(err)
        # The command dashline wrote before it ran on Windows: Bash only.
        rewrite = WINDOWS and install.old_form(self.entry)
        if r.returncode != 0 or not lines or "internal error" in r.stdout:
            why = stderr_reason(err, lines) or f"exit {r.returncode}, {len(lines)} lines"
            fix = "run /dashline:install"
            if rewrite:
                fix = "run /dashline:install: it rewrites this command for Windows"
            elif "can't open file" in why:
                fix = "the command's statusline.py is missing: run /dashline:install"
            elif any(s in why for s in ("No such file", "not found", "is not recognized")):
                program = first_word(self.entry["command"])
                fix = f"{program} must be on the PATH Claude Code sees, or use a full path"
            self.add(FAIL, "command", why, fix)
            return
        text = f"printed {len(lines)} line{'s' if len(lines) != 1 else ''} in {ms:.0f} ms"
        if WINDOWS:
            text += f" ({shell_name})"
        if rewrite:
            fix = "run /dashline:install: it rewrites this command for Windows"
            self.add(WARN, "command", text + ", but PowerShell can't run this command", fix)
            return
        if ms > (SLOW_MS_WINDOWS if WINDOWS else SLOW_MS):
            fix = "a slow git repo or disk; see the git line"
            if shell_name == "PowerShell":
                fix = (
                    "PowerShell is slow to start; with Git for Windows installed, Claude Code "
                    "runs the statusline in Git Bash instead"
                )
            self.add(WARN, "command", text + " (slow)", fix)
            return
        self.add(OK, "command", text)

    def git(self):
        import subprocess

        try:
            r = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            self.add(WARN, "git", "not found: the directory row shows the folder only")
            return
        match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", r.stdout)
        if not match:
            self.add(WARN, "git", f"unexpected version: {r.stdout.strip()}")
            return
        version = match.group(0)
        if (int(match.group(1)), int(match.group(2))) < MIN_GIT:
            self.add(
                WARN,
                "git",
                f"{version}: too old for the git row, which shows the folder only (needs 2.15)",
                "update git",
            )
            return
        self.add(OK, "git", version)

    def theme(self):
        from dashline import theme

        setting = theme.theme_setting(self.cwd, self.env)
        text = setting
        if setting == "auto":
            picked = theme.auto_theme(self.env)
            how = "from COLORFGBG" if self.env.get("COLORFGBG") else "COLORFGBG isn't set"
            text = f"auto: {picked} ({how})"
        if self.env.get("NO_COLOR"):
            text += "; NO_COLOR is set, so no colors"
        self.add(OK, "theme", text)

    def font(self):
        likely, found = font_guess(self.env, self.platform)
        glyphs = install.glyphs_of(self.entry) if self.entry else None
        if glyphs and unknown_glyphs(self.entry) is not None:
            text = f"{found}; the command names no glyph set (see the settings line)"
        elif glyphs:
            text = f"{found}; using {glyphs} glyphs"
            if likely and glyphs != "nerd":
                text += " (/dashline:install can switch to nerd)"
        else:
            text = found
        self.add(INFO, "font", text)


def write(results: list, out, palette=None) -> None:
    from dashline import __version__

    def paint(text: str, token: str) -> str:
        code = palette.sgr(token) if palette is not None else ""
        return f"\x1b[{code}m{text}\x1b[0m" if code else text

    out.write(f"dashline {__version__} doctor\n\n")
    for status, name, text, fix in results:
        word = paint(f"{status:<4}", STATUS_TOKENS[status])
        out.write(f"  {word}  {name:<8}  {text}\n")
        if fix:
            out.write(f"  {'':<4}  {'':<8}  fix: {fix}\n")
    failed = [name for status, name, _, _ in results if status == FAIL]
    warned = [name for status, name, _, _ in results if status == WARN]
    out.write("\n")
    if failed:
        out.write(f"{len(failed)} problem{'s' if len(failed) > 1 else ''}: {', '.join(failed)}\n")
    elif warned:
        out.write(f"Working, with warnings: {', '.join(warned)}\n")
    else:
        out.write("All good.\n")


def run(
    env=None, out=None, cwd=None, base_url: str = API_URL, now=None, fetch_now: bool = False
) -> int:
    """fetch_now: fetch even while the server has asked this login to wait."""
    from dashline import theme

    env = os.environ if env is None else env
    out = out or sys.stdout
    cwd = cwd or env.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    now = time.time() if now is None else now
    doctor = Doctor(env, now, cwd, base_url, fetch_now=fetch_now)
    results = doctor.run()
    palette = None
    if hasattr(out, "isatty") and out.isatty() and not env.get("NO_COLOR"):
        palette = theme.load(cwd, env)
    write(results, out, palette)
    return 1 if any(status == FAIL for status, _, _, _ in results) else 0
