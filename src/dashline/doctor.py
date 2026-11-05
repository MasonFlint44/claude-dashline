"""--doctor: check everything a statusline needs, one line each (PLAN §9).

Each check prints `ok`, `warn`, `fail` or `info`, a name and what it found; a problem gets
a `fix:` line under it. The doctor skill reads this output, so names and wording stay
stable. Exit 1 when something fails: the statusline or its plan bars won't show.

Doctor fetches the usage endpoint once, in the foreground, the same way the background
child does: it refreshes the cache, and on failure sets the same hold a render would.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

from dashline import install
from dashline.usage import API_URL

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"
STATUS_TOKENS = {OK: "success", WARN: "warning", FAIL: "error", INFO: "inactive"}
MIN_PYTHON = (3, 9)
MIN_GIT = (2, 11)  # porcelain v2
SLOW_MS = 500
NERD_TERMINALS = {"ghostty": "Ghostty", "wezterm": "WezTerm"}  # bundle the symbols


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


def font_guess(env, platform: str) -> tuple:
    """(True if a Nerd Font is likely to render, what was found)."""
    term = (env.get("TERM_PROGRAM") or "").lower()
    if term in NERD_TERMINALS:
        return True, f"{NERD_TERMINALS[term]} bundles Nerd Font symbols"
    if platform.startswith("linux"):
        import subprocess

        try:
            r = subprocess.run(
                ["fc-list", ":", "family"], capture_output=True, text=True, timeout=5
            )
            families = r.stdout.splitlines() if r.returncode == 0 else []
        except (OSError, subprocess.SubprocessError):
            families = []
        nerd = sorted({f.split(",")[0] for f in families if "Nerd Font" in f})
        if nerd:
            more = f" (+{len(nerd) - 1} more)" if len(nerd) > 1 else ""
            return True, f"found {nerd[0]}{more}"
    elif platform == "darwin":
        import glob

        dirs = [os.path.expanduser("~/Library/Fonts"), "/Library/Fonts"]
        found = [p for d in dirs for p in glob.glob(os.path.join(d, "*Nerd*"))]
        if found:
            return True, f"found {os.path.basename(sorted(found)[0])}"
    return False, "no Nerd Font found"


class Doctor:
    def __init__(self, env, now: float, cwd: str, base_url: str = API_URL, platform=None):
        self.env = env
        self.now = now
        self.cwd = cwd
        self.base_url = base_url
        self.platform = platform or sys.platform
        self.results = []  # (status, name, text, fix)
        self.entry = None  # dashline's statusLine entry, once found
        self.account = None

    def add(self, status: str, name: str, text: str, fix: str | None = None) -> None:
        self.results.append((status, name, text, fix))

    def short(self, path: str) -> str:
        return install.home_short(path, self.env)

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
        self.add(WARN, "install", text, "run /dashline:install to update it")

    def settings(self):
        from dashline.theme import _read_json, settings_files

        sources = [(p, _read_json(p)) for p in settings_files(self.cwd, self.env)]
        disabled = [p for p, data in sources if data.get("disableAllHooks") is True]
        winner = next(((p, d["statusLine"]) for p, d in sources if "statusLine" in d), None)
        if winner is None:
            where = self.short(install.user_settings(self.env))
            self.add(FAIL, "settings", f"no statusLine in {where}", "run /dashline:install")
            return
        path, entry = winner
        where = self.short(path)
        if not install.is_ours(entry):
            cmd = entry.get("command") if isinstance(entry, dict) else None
            shown = f": {cmd}" if isinstance(cmd, str) else ""
            self.add(
                FAIL,
                "settings",
                f"{where} runs another statusline{shown}",
                "run /dashline:install (it asks before replacing it)",
            )
            return
        self.entry = entry
        if entry.get("type") != "command":
            self.add(
                FAIL,
                "settings",
                f'{where}: statusLine type isn\'t "command"',
                "run /dashline:install",
            )
            return
        if disabled:
            self.add(
                FAIL,
                "settings",
                f"disableAllHooks is on in {self.short(disabled[0])}, which also turns off "
                "the statusline",
                "remove disableAllHooks (it turns off hooks too, so that's your call)",
            )
            return
        text = f"{where}: {install.describe(entry)}"
        if not isinstance(entry.get("refreshInterval"), (int, float)):
            self.add(
                WARN,
                "settings",
                text + "; no refreshInterval",
                "plan bars only move when Claude Code redraws; /dashline:install sets 60",
            )
            return
        self.add(OK, "settings", text)

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
                self.add(FAIL, "login", f"{label}; {source}", "run /login in Claude Code")
            return
        del token
        where = (
            source if source.startswith("CLAUDE_") or "Keychain" in source else self.short(source)
        )
        text = f"{label}; token from {where}"
        if expires is not None:
            text += f", renews in {_span(expires - self.now)}"
        self.add(OK, "login", text)

    def usage(self):
        from dashline import usage

        if self.account is None or self.account.mode != "subscription":
            self.add(INFO, "usage", "not fetched: plan bars are for Claude subscriptions")
            return
        start = time.monotonic()
        result = usage.refresh(self.env, self.now, self.base_url, self.platform)
        ms = (time.monotonic() - start) * 1000
        if result == "ok":
            cache = usage._read_json(usage._path(self.env, "usage.json"))
            self.add(OK, "usage", f"{ms:.0f} ms: {summarize(cache.get('data') or {})}")
            return
        held = usage.hold(self.env, self.account.fingerprint) or {}
        until = held.get("until")
        wait = f"; renders retry in {_span(until - self.now)}" if until else ""
        fixes = {
            "no Claude login found": "run /login in Claude Code",
            "token rejected (401)": "run /login in Claude Code",
            "not allowed (403): the login may lack the profile scope": (
                "a token from `claude setup-token` can't read usage; use /login instead"
                if self.env.get("CLAUDE_CODE_OAUTH_TOKEN")
                else "run /login in Claude Code"
            ),
            "no answer (network)": "check the network or proxy (HTTPS_PROXY) to api.anthropic.com",
        }
        if result.startswith("token expired"):
            self.add(WARN, "usage", result + wait)
            return
        self.add(FAIL, "usage", result + wait, fixes.get(result, "run doctor again later"))

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
        cache = usage._read_json(usage._path(self.env, "usage.json"))
        fetched = cache.get("fetched_at")
        if isinstance(fetched, (int, float)):
            notes.append(f"fetched {_ago(self.now - fetched)}")
        lock = os.path.join(path, "fetch.lock")
        if os.path.exists(lock):
            age = self.now - os.stat(lock).st_mtime
            if age >= usage.LOCK_STALE:
                notes.append("a stale fetch.lock (the next render clears it)")
            else:
                notes.append("a fetch is running")
        status = OK
        if os.stat(path).st_mode & 0o077:
            status = WARN
            notes.append("other users can read it")
        text = f"{where}" + (f": {', '.join(notes)}" if notes else "")
        fix = f"chmod 700 {where}" if status == WARN else None
        self.add(status, "cache", text, fix)

    def command(self):
        """Run the settings command the way Claude Code does, on a sample session."""
        import subprocess

        if self.entry is None:
            self.add(INFO, "command", "not run: settings don't run dashline")
            return
        if os.name == "nt":
            self.add(INFO, "command", "not run on Windows")
            return
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
                ["sh", "-c", self.entry["command"]],
                input=json.dumps(sample),
                capture_output=True,
                text=True,
                timeout=10,
                env=dict(self.env),
                cwd=self.cwd,
            )
        except subprocess.TimeoutExpired:
            self.add(FAIL, "command", "took over 10 s", "run /dashline:doctor again; report it")
            return
        except OSError as e:
            self.add(FAIL, "command", f"couldn't run sh: {e}")
            return
        ms = (time.monotonic() - start) * 1000
        lines = [line for line in r.stdout.splitlines() if line.strip()]
        err = r.stderr.strip().splitlines()
        if r.returncode != 0 or not lines or "internal error" in r.stdout:
            why = err[-1] if err else f"exit {r.returncode}, {len(lines)} lines"
            fix = "run /dashline:install"
            if "No such file" in why or "not found" in why:
                fix = "python3 must be on the PATH Claude Code sees; then /dashline:install"
            self.add(FAIL, "command", why, fix)
            return
        text = f"printed {len(lines)} line{'s' if len(lines) != 1 else ''} in {ms:.0f} ms"
        if ms > SLOW_MS:
            self.add(WARN, "command", text + " (slow)", "a slow git repo or disk; see the git line")
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
            self.add(WARN, "git", f"{version}: too old for the git row (needs 2.11)", "update git")
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
        if glyphs:
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


def run(env=None, out=None, cwd=None, base_url: str = API_URL, now=None) -> int:
    from dashline import theme

    env = os.environ if env is None else env
    out = out or sys.stdout
    cwd = cwd or os.getcwd()
    doctor = Doctor(env, time.time() if now is None else now, cwd, base_url)
    results = doctor.run()
    palette = None
    if hasattr(out, "isatty") and out.isatty() and not env.get("NO_COLOR"):
        palette = theme.load(cwd, env)
    write(results, out, palette)
    return 1 if any(status == FAIL for status, _, _, _ in results) else 0
