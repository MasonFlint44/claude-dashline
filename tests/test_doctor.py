"""--doctor: each check's ok / warn / fail, against a fake home and a local endpoint."""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import FIXTURES, NOW, ROOT, env_for, posix_only, read_json
from dashline import account, doctor, host, install, theme, usage

CLOSED = "http://127.0.0.1:9"  # nothing listens here


def usage_fixture(name):
    return read_json(FIXTURES / "usage" / f"{name}.json")


@pytest.fixture(autouse=True)
def no_lock_wait(monkeypatch):
    """Doctor waits up to LOCK_WAIT for a running fetch; a test with a live lock doesn't."""
    monkeypatch.setattr(doctor, "LOCK_WAIT", 0)


@pytest.fixture(autouse=True)
def no_other_python(monkeypatch):
    """On Windows, a command whose Python isn't found makes doctor look for another
    (install.windows_python): none here, unless a test says so."""
    monkeypatch.setattr(install, "windows_python", lambda *args, **kwargs: None)


@pytest.fixture
def env(isolated_home):
    (isolated_home / ".claude").mkdir(exist_ok=True)
    return env_for(isolated_home, PATH=os.environ.get("PATH", ""))


@pytest.fixture
def installed(env):
    assert install.run("nerd", env=env, out=io.StringIO(), cwd="/") == 0
    return env


@pytest.fixture
def sub(logged_in):
    """A subscriber with dashline installed (logged_in comes from conftest)."""
    env = dict(logged_in, PATH=os.environ.get("PATH", ""))
    assert install.run(None, env=env, out=io.StringIO(), cwd="/") == 0
    return env


def check(env, name, tmp_path, base_url=CLOSED, now=NOW, platform="linux"):
    """Run the whole doctor; return the (status, text, fix) for one check."""
    d = doctor.Doctor(env, now, str(tmp_path), base_url, platform)
    results = {n: (s, t, f) for s, n, t, f in d.run()}
    return results[name]


def report(env, tmp_path, base_url=CLOSED):
    out = io.StringIO()
    code = doctor.run(env, out, str(tmp_path), base_url, now=NOW)
    return code, out.getvalue()


# ---- the whole report ----


def test_api_user_all_good(installed, tmp_path):
    code, out = report(installed, tmp_path)
    assert code == 0, out
    assert out.startswith("dashline ")
    assert out.rstrip().endswith("All good.")
    for name in ("python", "install", "settings", "login", "cache", "command", "git", "theme"):
        assert f"ok    {name}" in out, name
    assert "info  usage" in out
    assert "no Claude login found, so no plan bars" in out


def test_nothing_installed(env, tmp_path):
    code, out = report(env, tmp_path)
    assert code == 1
    assert "fail  install   nothing installed in ~/.claude/scripts/statusline" in out
    assert "fix: run /dashline:install" in out
    assert "2 problems: install, settings" in out


def test_subscriber_fetches_once(sub, server, tmp_path):
    server.reply(200, json.dumps(usage_fixture("ultra")))
    code, out = report(sub, tmp_path, server.url)
    assert code == 0, out
    assert len(server.requests) == 1
    assert "7d 17% · Fable 24%" in out
    assert "token from ~/.claude/.credentials.json, renews in 1d0h" in out
    assert "fetched just now" in out
    assert "ok    command" in out


def test_no_color_when_not_a_terminal(installed, tmp_path):
    _, out = report(installed, tmp_path)
    assert "\x1b[" not in out


def test_write_colors_status_words():
    from dashline import theme
    from dashline.colors import THEMES

    out = io.StringIO()
    doctor.write([("fail", "usage", "HTTP 500", "later")], out, theme.Palette(THEMES["dark"]))
    text = out.getvalue()
    assert "\x1b[38;2;" in text
    assert "fix: later" in text
    assert "1 problem: usage" in text


def test_warnings_footer():
    out = io.StringIO()
    doctor.write([("ok", "python", "3.9", None), ("warn", "install", "old", "update")], out)
    assert out.getvalue().rstrip().endswith("Working, with warnings: install")


def test_a_broken_check_is_reported(installed, tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.Doctor, "git", lambda self: 1 / 0)
    status, text, _ = check(installed, "git", tmp_path)
    assert status == "fail"
    assert "ZeroDivisionError" in text


# ---- install ----


def test_install_matches(installed, tmp_path):
    status, text, _ = check(installed, "install", tmp_path)
    assert status == "ok"
    assert text.endswith("same as this copy")


def test_install_differs(installed, isolated_home, tmp_path):
    layout = isolated_home / ".claude" / "scripts" / "statusline" / "dashline" / "layout.py"
    layout.write_text("# edited\n")
    status, text, fix = check(installed, "install", tmp_path)
    assert status == "warn"
    assert "files differ" in text
    assert fix == "run /dashline:install to update it"


def test_install_older_version(installed, isolated_home, tmp_path):
    target = isolated_home / ".claude" / "scripts" / "statusline"
    (target / "VERSION").write_text("0.0.0-old\n")
    (target / "dashline" / "layout.py").write_text("# old\n")
    status, text, _ = check(installed, "install", tmp_path)
    assert status == "warn"
    assert "0.0.0-old; this copy is" in text


def test_install_newer_than_this_copy(installed, isolated_home, tmp_path):
    """An older plugin's doctor mustn't push its own version over a newer install."""
    target = isolated_home / ".claude" / "scripts" / "statusline"
    (target / "VERSION").write_text("99.0.0\n")
    (target / "dashline" / "layout.py").write_text("# newer\n")
    status, text, fix = check(installed, "install", tmp_path)
    assert status == "warn"
    assert "99.0.0 is newer than this copy" in text
    assert fix.startswith("update the dashline plugin")


@pytest.mark.parametrize(
    ("text", "parsed"),
    [("0.1.6", (0, 1, 6)), ("1", (1,)), ("unknown version", None), ("0.1.6rc1", None), ("", None)],
)
def test_version_tuple(text, parsed):
    assert doctor.version_tuple(text) == parsed


def test_doctor_from_the_installed_copy(installed, isolated_home):
    shim = isolated_home / ".claude" / "scripts" / "statusline" / "statusline.py"
    r = subprocess.run(
        [sys.executable, "-I", "-S", str(shim), "--doctor"],
        capture_output=True,
        text=True,
        timeout=60,
        env=dict(os.environ, **installed),
        cwd=str(isolated_home),
    )
    assert "(doctor ran from it)" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 0, r.stdout


# ---- settings ----


def settings_file(env):
    return Path(env["HOME"]) / ".claude" / "settings.json"


def get_settings(env):
    return json.loads(settings_file(env).read_text())


def set_settings(env, data):
    settings_file(env).write_text(json.dumps(data))


def test_settings_ok(installed, tmp_path):
    status, text, _ = check(installed, "settings", tmp_path)
    assert (status, text) == ("ok", "~/.claude/settings.json: nerd glyphs, refreshing every 60 s")


def test_settings_missing(installed, tmp_path):
    set_settings(installed, {})
    status, text, _ = check(installed, "settings", tmp_path)
    assert status == "fail"
    assert text == "no statusLine in ~/.claude/settings.json"
    assert check(installed, "command", tmp_path)[0] == "info"


def test_settings_someone_else(installed, tmp_path):
    set_settings(installed, {"statusLine": {"type": "command", "command": "bash ~/x.sh"}})
    status, text, fix = check(installed, "settings", tmp_path)
    assert status == "fail"
    assert text == "~/.claude/settings.json runs another statusline: bash ~/x.sh"
    assert "asks before replacing" in fix


def test_project_settings_win(installed, tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.local.json").write_text(
        json.dumps({"statusLine": {"type": "command", "command": "echo local"}})
    )
    status, text, fix = check(installed, "settings", tmp_path)
    assert status == "fail"
    assert "settings.local.json runs another statusline: echo local" in text
    # /dashline:install only writes user settings, so it can't fix this one.
    assert "/dashline:install" not in fix
    assert "settings.local.json wins over your user settings here" in fix


def test_managed_settings_win(installed, tmp_path, monkeypatch):
    from dashline import theme

    managed = tmp_path / "managed-settings.json"
    managed.write_text(json.dumps({"statusLine": {"type": "command", "command": "corp"}}))
    monkeypatch.setattr(theme, "MANAGED_SETTINGS", str(managed))
    status, text, fix = check(installed, "settings", tmp_path)
    assert status == "fail"
    assert text.endswith("runs another statusline: corp")
    assert "set by an administrator" in fix


def test_project_dashline_without_refresh(installed, tmp_path):
    entry = dict(get_settings(installed)["statusLine"])
    del entry["refreshInterval"]
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"statusLine": entry}))
    status, _, fix = check(installed, "settings", tmp_path)
    assert status == "warn"
    assert fix.endswith("add one to " + (tmp_path / ".claude" / "settings.json").as_posix())


def test_someone_elses_folder(installed, isolated_home, tmp_path):
    target = isolated_home / ".claude" / "scripts" / "statusline"
    (target / "dashline" / "__init__.py").unlink()
    status, text, _ = check(installed, "settings", tmp_path)
    assert status == "fail"
    assert "runs another statusline" in text


def test_disable_all_hooks(installed, tmp_path):
    data = get_settings(installed)
    data["disableAllHooks"] = True
    set_settings(installed, data)
    status, text, fix = check(installed, "settings", tmp_path)
    assert status == "fail"
    assert "disableAllHooks is on" in text
    assert "your call" in fix


def test_disable_all_hooks_follows_precedence(installed, tmp_path):
    """The CLI merges settings files: the first one that sets the key decides."""
    data = get_settings(installed)
    data["disableAllHooks"] = True
    set_settings(installed, data)
    (tmp_path / ".claude").mkdir()
    project = tmp_path / ".claude" / "settings.json"
    project.write_text(json.dumps({"disableAllHooks": False}))
    assert check(installed, "settings", tmp_path)[0] == "ok"

    data["disableAllHooks"] = False
    set_settings(installed, data)
    project.write_text(json.dumps({"disableAllHooks": True}))
    status, text, _ = check(installed, "settings", tmp_path)
    assert status == "fail"
    assert f"disableAllHooks is on in {project.as_posix()}" in text


def test_no_refresh_interval(installed, tmp_path):
    data = get_settings(installed)
    del data["statusLine"]["refreshInterval"]
    set_settings(installed, data)
    status, text, fix = check(installed, "settings", tmp_path)
    assert status == "warn"
    assert text.endswith("no refreshInterval")
    assert "sets 60" in fix


# ---- login and usage ----


def test_login_with_env_token(installed, tmp_path):
    env = dict(installed, CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat-x")
    status, text, _ = check(env, "login", tmp_path)
    assert status == "ok"
    assert "token from CLAUDE_CODE_OAUTH_TOKEN" in text
    assert "sk-ant" not in text


def test_login_label(sub, isolated_home, tmp_path):
    data = {
        "oauthAccount": {
            "accountUuid": "a",
            "organizationUuid": "o",
            "planDisplayName": "Ultra",
        }
    }
    (isolated_home / ".claude.json").write_text(json.dumps(data))
    status, text, _ = check(sub, "login", tmp_path)
    assert status == "ok"
    assert text.startswith("Ultra; token from ~/.claude/.credentials.json")


def test_login_expired_token_is_a_warning(sub, tmp_path):
    status, text, _ = check(sub, "login", tmp_path, now=NOW + 2 * 86400)
    assert status == "warn"
    assert "token expired" in text
    assert check(sub, "usage", tmp_path, now=NOW + 2 * 86400)[0] == "warn"


def test_no_credentials(sub, isolated_home, tmp_path):
    (isolated_home / ".claude" / ".credentials.json").unlink()
    status, text, fix = check(sub, "login", tmp_path)
    assert status == "fail"
    assert "no Claude login found" in text
    assert fix == "run /login in Claude Code"


def test_usage_rejected(sub, server, tmp_path):
    server.reply(401)
    status, text, fix = check(sub, "usage", tmp_path, server.url)
    assert status == "fail"
    assert text == "token rejected (401); renders retry in 5 min"
    assert fix == "run /login in Claude Code"


def test_usage_403_with_setup_token(sub, server, tmp_path):
    server.reply(403)
    env = dict(sub, CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat-x")
    status, _, fix = check(env, "usage", tmp_path, server.url)
    assert status == "fail"
    assert "setup-token" in fix


def test_usage_network(sub, tmp_path):
    status, text, fix = check(sub, "usage", tmp_path, CLOSED)
    assert status == "fail"
    assert text == "no answer (network); renders retry in 1 min"
    assert "proxy" in fix


def test_usage_server_error_backs_off(sub, server, tmp_path):
    server.reply(500)
    status, text, fix = check(sub, "usage", tmp_path, server.url)
    assert (status, text) == ("fail", "HTTP 500; renders retry in 1 min")
    assert fix == "run doctor again later"


def test_usage_skipped_for_api(installed, tmp_path):
    env = dict(installed, ANTHROPIC_API_KEY="sk-ant-api-x")
    assert check(env, "usage", tmp_path)[0] == "info"
    status, text, _ = check(env, "login", tmp_path)
    assert (status, text) == ("ok", "API: billed per use, so no plan bars")


def test_bedrock(installed, tmp_path):
    env = dict(installed, CLAUDE_CODE_USE_BEDROCK="1")
    assert check(env, "login", tmp_path)[1] == "Bedrock: billed per use, so no plan bars"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ultra", "7d 17% · Fable 24%"),
        ("enterprise", "credits 0%"),
    ],
)
def test_summarize(name, expected):
    assert doctor.summarize(usage_fixture(name)).startswith(expected.split(" · ")[0])
    assert expected in doctor.summarize(usage_fixture(name))


def test_summarize_empty():
    assert doctor.summarize({}) == "no limits on this plan"
    assert doctor.summarize({"limits": [{"kind": "new_thing", "percent": 5}]}) == "new thing 5%"


# ---- cache ----


def cache_path(env):
    return Path(usage.cache_dir(env))


def cache_file(env):
    """This login's cache file."""
    return cache_path(env) / usage.cache_name(account.identity(env))


def test_cache_not_needed_for_api(installed, tmp_path):
    status, text, _ = check(installed, "cache", tmp_path)
    assert (status, text) == ("ok", "~/.claude/cache/statusline: not needed without plan bars")


def test_shared_cache_folder_is_fine(sub, server, tmp_path):
    """A folder others can list (made by another tool) only shows them file names."""
    server.reply(200, json.dumps(usage_fixture("ultra")))
    cache_path(sub).mkdir(parents=True)
    cache_path(sub).chmod(0o775)
    status, text, fix = check(sub, "cache", tmp_path, server.url)
    assert (status, text, fix) == ("ok", "~/.claude/cache/statusline: fetched just now", None)
    if os.name != "nt":
        assert cache_file(sub).stat().st_mode & 0o777 == 0o600


@posix_only
def test_no_mode_check_on_windows_simulated(sub, tmp_path, monkeypatch):
    """Windows has no such mode bits: files take the profile folder's access."""
    monkeypatch.setattr(host, "WINDOWS", True)
    cache_path(sub).mkdir(mode=0o700, parents=True)
    cached = cache_file(sub)
    cached.write_text(json.dumps({"fetched_at": NOW - 60, "data": {}}))
    cached.chmod(0o644)
    _, text, fix = check(sub, "cache", tmp_path)
    assert "other users" not in text
    assert "chmod" not in (fix or "")


@posix_only
def test_cache_file_readable_by_others(sub, tmp_path):
    cache_path(sub).mkdir(mode=0o700, parents=True)
    cached = cache_file(sub)
    cached.write_text(json.dumps({"fetched_at": NOW - 60, "data": {}}))
    cached.chmod(0o644)
    status, text, fix = check(sub, "cache", tmp_path)  # the fetch fails: the cache stays
    assert status == "warn"
    assert text.endswith(f"other users can read {cached.name}")
    assert fix == f"chmod 600 ~/.claude/cache/statusline/{cached.name}"


@posix_only
def test_cache_checks_every_file_of_dashline_and_no_other(sub, tmp_path):
    cache_path(sub).mkdir(mode=0o700, parents=True)
    for name in (
        "usage-0123456789abcdef.json",
        "fetch-0123456789abcdef.hold",
        "plan-usage",
        "notes.txt",
        "usage-notes.json",
    ):
        (cache_path(sub) / name).write_text("{}")
        (cache_path(sub) / name).chmod(0o644)
    status, text, _ = check(sub, "cache", tmp_path)
    assert status == "warn"
    assert text.endswith(
        "other users can read fetch-0123456789abcdef.hold, usage-0123456789abcdef.json"
    )


@posix_only
def test_chmod_fix_is_quoted(sub, isolated_home, tmp_path):
    conf = isolated_home / "My Claude"
    env = dict(sub, CLAUDE_CONFIG_DIR=str(conf))
    cache = conf / "cache" / "statusline"
    cache.mkdir(parents=True)
    name = usage.cache_name(account.identity(env))
    (cache / name).write_text(json.dumps({"fetched_at": NOW - 60, "data": {}}))
    (cache / name).chmod(0o644)
    _, _, fix = check(env, "cache", tmp_path)
    assert fix == f"chmod 600 ~/'My Claude/cache/statusline/{name}'"


@posix_only
def test_chmod_fix_outside_home(sub, tmp_path):
    conf = tmp_path / "other place"
    env = dict(sub, CLAUDE_CONFIG_DIR=str(conf))
    cache = conf / "cache" / "statusline"
    cache.mkdir(parents=True)
    (cache / "usage-0123456789abcdef.json").write_text("{}")
    (cache / "usage-0123456789abcdef.json").chmod(0o640)
    status, _, fix = check(env, "cache", tmp_path)
    assert status == "warn"
    assert fix == f"chmod 600 '{cache / 'usage-0123456789abcdef.json'}'"


def test_cache_not_writable(sub, tmp_path):
    cache_path(sub).mkdir(parents=True)
    cache_path(sub).chmod(0o500)
    try:
        if os.access(cache_path(sub), os.W_OK):
            pytest.skip("running as root")
        status, text, _ = check(sub, "cache", tmp_path)
        assert (status, text) == ("fail", "~/.claude/cache/statusline isn't writable")
    finally:
        cache_path(sub).chmod(0o700)


def test_cache_stale_lock(sub, server, tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.Doctor, "usage", lambda self: None)  # it would clear the lock
    cache_path(sub).mkdir(mode=0o700, parents=True)
    lock = cache_path(sub) / "fetch.lock"
    lock.write_text("{}")
    lock.chmod(0o600)  # as take_lock makes it
    os.utime(lock, (NOW - 600, NOW - 600))
    status, text, _ = check(sub, "cache", tmp_path, server.url)
    assert status == "ok"
    assert "a stale fetch.lock (the next render clears it)" in text


@pytest.mark.parametrize(
    ("at", "note"),
    [
        (NOW - 10, "a fetch is running"),
        (NOW - 600, "a stale fetch.lock (the next render clears it)"),
        (NOW + 3600, "a stale fetch.lock (the next render clears it)"),  # clock set back
    ],
)
def test_cache_lock_uses_its_time(sub, server, tmp_path, monkeypatch, at, note):
    monkeypatch.setattr(doctor.Doctor, "usage", lambda self: None)  # it would clear the lock
    cache_path(sub).mkdir(mode=0o700, parents=True)
    lock = cache_path(sub) / "fetch.lock"
    lock.write_text(json.dumps({"at": at, "pid": 1, "nonce": "n"}))
    lock.chmod(0o600)
    (cache_path(sub) / "fetch.lock.break").write_text("")
    (cache_path(sub) / "fetch.lock.break").chmod(0o600)  # as _break_lock makes it
    status, text, _ = check(sub, "cache", tmp_path, server.url)
    assert status == "ok"
    assert note in text
    assert "break" not in text


@pytest.mark.parametrize(
    ("reason", "fix"),
    [
        ("redirect refused (HTTP 302)", "check HTTPS_PROXY"),
        ("fetch failed (IncompleteRead)", "report it if it keeps happening"),
    ],
)
def test_usage_new_reasons(sub, tmp_path, monkeypatch, reason, fix):
    monkeypatch.setattr(usage, "refresh", lambda *args: reason)
    status, text, got = check(sub, "usage", tmp_path)
    assert status == "fail"
    assert text.startswith(reason)
    assert fix in got


# ---- command, git, theme, font ----


def test_command_broken_python(installed, tmp_path):
    data = get_settings(installed)
    command = data["statusLine"]["command"]  # `python3 …`; on Windows `py -3 …` or `python …`
    data["statusLine"]["command"] = "no-such-python3" + command[command.index(" ") :]
    set_settings(installed, data)
    status, text, fix = check(installed, "command", tmp_path)
    assert status == "fail"
    assert "not found" in text
    if host.WINDOWS:  # no full path with spaces runs in both of its shells
        assert fix == (
            "no-such-python3 must be on the PATH Claude Code sees: install Python, or add "
            "it to PATH, then restart Claude Code"
        )
    else:
        assert fix == "no-such-python3 must be on the PATH Claude Code sees, or use a full path"


def test_command_script_missing(installed, isolated_home, tmp_path):
    (isolated_home / ".claude" / "scripts" / "statusline" / "statusline.py").unlink()
    status, text, fix = check(installed, "command", tmp_path)
    assert status == "fail"
    assert "can't open file" in text
    assert fix == "the command's statusline.py is missing: run /dashline:install"


def test_first_word():
    assert doctor.first_word('"/opt/my py/python3" -I x.py') == "/opt/my py/python3"
    assert doctor.first_word("python3 'unbalanced") == "python3"
    assert doctor.first_word("") == "python3"


def test_project_dir_from_claude(installed, tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"statusLine": {"type": "command", "command": "echo project"}})
    )
    out = io.StringIO()
    doctor.run(dict(installed, CLAUDE_PROJECT_DIR=str(tmp_path)), out, None, CLOSED, now=NOW)
    assert "runs another statusline: echo project" in out.getvalue()


def test_command_internal_error(installed, isolated_home, tmp_path):
    layout = isolated_home / ".claude" / "scripts" / "statusline" / "dashline" / "layout.py"
    layout.write_text("def render(*args):\n    raise RuntimeError('boom')\n")
    status, text, _ = check(installed, "command", tmp_path)
    assert status == "fail"
    assert "ImportError" in text


def test_git_missing(installed, tmp_path, monkeypatch):
    real = subprocess.run

    def fake(args, **kwargs):
        if args[0] == "git":
            raise FileNotFoundError("git")
        return real(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake)
    status, text, _ = check(installed, "git", tmp_path)
    assert (status, text) == ("warn", "not found: the directory row shows the folder only")


def test_theme_auto_and_no_color(installed, tmp_path):
    data = get_settings(installed)
    data["theme"] = "auto"
    set_settings(installed, data)
    env = dict(installed, COLORFGBG="0;15", NO_COLOR="1")
    _, text, _ = check(env, "theme", tmp_path)
    assert text == "auto: light (from COLORFGBG); NO_COLOR is set, so no colors"


def test_font_ghostty(installed, tmp_path):
    env = dict(installed, TERM_PROGRAM="ghostty")
    status, text, _ = check(env, "font", tmp_path)
    assert (status, text) == ("info", "Ghostty bundles Nerd Font symbols; using nerd glyphs")


def test_font_suggests_nerd(env, tmp_path):
    install.run(None, env=env, out=io.StringIO(), cwd="/")
    env = dict(env, TERM_PROGRAM="WezTerm")
    text = check(env, "font", tmp_path)[1]
    assert text == (
        "WezTerm bundles Nerd Font symbols; using unicode glyphs "
        "(/dashline:install can switch to nerd)"
    )


def test_font_fc_list(monkeypatch):
    def fake(args, **kwargs):
        out = "DejaVu Sans\nSymbols Nerd Font Mono,Symbols Nerd Font\nHack Nerd Font\n"
        return subprocess.CompletedProcess(args, 0, out, "")

    monkeypatch.setattr(subprocess, "run", fake)
    assert doctor.font_guess({}, "linux") == (True, "found Hack Nerd Font (+1 more)")


def test_font_fc_list_cascadia(monkeypatch):
    def fake(args, **kwargs):
        out = "Cascadia Code\nCascadia Mono NF,Cascadia Mono NF SemiBold\n"
        return subprocess.CompletedProcess(args, 0, out, "")

    monkeypatch.setattr(subprocess, "run", fake)
    assert doctor.font_guess({}, "linux") == (True, "found Cascadia Mono NF")


def test_font_none(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 0, "", "")
    )
    assert doctor.font_guess({}, "linux") == (False, "no Nerd Font found")


def test_font_macos(tmp_path, monkeypatch):
    fonts = tmp_path / "Library" / "Fonts"
    fonts.mkdir(parents=True)
    (fonts / "SymbolsNerdFontMono-Regular.ttf").write_text("")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # home on Windows
    assert doctor.font_guess({}, "darwin") == (True, "found SymbolsNerdFontMono-Regular.ttf")
    monkeypatch.setenv("HOME", "/nonexistent")
    monkeypatch.setenv("USERPROFILE", "/nonexistent")
    found = doctor.font_guess({"HOME": str(tmp_path)}, "darwin")  # the env's HOME wins
    assert found == (True, "found SymbolsNerdFontMono-Regular.ttf")


def test_font_wsl(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "WSL_DRIVES", str(tmp_path))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("fc-list ran"))
    wsl = {"WSL_DISTRO_NAME": "Ubuntu"}
    none = (False, "no Nerd Font in Windows' fonts (the terminal draws with those)")
    assert doctor.font_guess(wsl, "linux") == none  # Linux fonts don't count
    user = tmp_path / "c" / "Users" / "pat" / "AppData" / "Local" / "Microsoft" / "Windows"
    (user / "Fonts").mkdir(parents=True)
    (user / "Fonts" / "JetBrainsMonoNerdFont-Regular.ttf").write_text("")
    found = (True, "found JetBrainsMonoNerdFont-Regular.ttf in Windows' fonts")
    assert doctor.font_guess(wsl, "linux") == found
    (user / "Fonts" / "JetBrainsMonoNerdFont-Regular.ttf").unlink()
    (tmp_path / "c" / "Windows" / "Fonts").mkdir(parents=True)
    (tmp_path / "c" / "Windows" / "Fonts" / "CascadiaCodeNF.ttf").write_text("")
    (tmp_path / "c" / "Windows" / "Fonts" / "CascadiaCode.ttf").write_text("")  # no icons
    found = (True, "found CascadiaCodeNF.ttf in Windows' fonts")
    assert doctor.font_guess(wsl, "linux") == found
    assert doctor.font_guess(dict(wsl, TERM_PROGRAM="WezTerm"), "linux")[1] == (
        "WezTerm bundles Nerd Font symbols"
    )


def test_font_windows(tmp_path):
    fonts = tmp_path / "Windows" / "Fonts"
    fonts.mkdir(parents=True)
    env = {"WINDIR": str(tmp_path / "Windows"), "LOCALAPPDATA": str(tmp_path / "none")}
    assert doctor.font_guess(env, "win32")[0] is False
    (fonts / "SymbolsNerdFont-Regular.ttf").write_text("")
    assert doctor.font_guess(env, "win32") == (
        True,
        "found SymbolsNerdFont-Regular.ttf in Windows' fonts",
    )


def test_shim_doctor_exit_code(isolated_home):
    r = subprocess.run(
        [sys.executable, "-I", "-S", str(ROOT / "statusline.py"), "--doctor"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(isolated_home),
    )
    assert r.returncode == 1  # nothing installed in the fake home
    assert "fail  install" in r.stdout


# ---- a wait the server asked for ----


def server_hold(env, until, server=True, reason="HTTP 429"):
    cache_path(env).mkdir(mode=0o700, parents=True, exist_ok=True)
    who = account.identity(env)
    body = {"until": until, "at": NOW - 60, "account": who, "reason": reason, "server": server}
    (cache_path(env) / usage.hold_name(who)).write_text(json.dumps(body))


def usage_check(env, tmp_path, base_url, fetch_now=False):
    d = doctor.Doctor(env, NOW, str(tmp_path), base_url, "linux", fetch_now=fetch_now)
    return {n: (s, t, f) for s, n, t, f in d.run()}["usage"]


def test_usage_respects_the_servers_wait(sub, server, tmp_path):
    import re

    server_hold(sub, NOW + 3000)
    status, text, fix = usage_check(sub, tmp_path, server.url)
    assert server.requests == []
    assert status == "warn"
    assert re.fullmatch(
        r"not fetched: the server asked to wait until \d\d:\d\d \(50 min left\) after HTTP 429",
        text,
    ), text
    assert "--fetch-now" in fix  # a warning, so doctor's exit code stays 0


def test_usage_fetch_now_tries_anyway(sub, server, tmp_path):
    server_hold(sub, NOW + 3000)
    server.reply(200, json.dumps(usage_fixture("ultra")))
    status, _, _ = usage_check(sub, tmp_path, server.url, fetch_now=True)
    assert status == "ok"
    assert len(server.requests) == 1


def test_run_passes_fetch_now(sub, server, tmp_path):
    server_hold(sub, NOW + 3000)
    server.reply(200, json.dumps(usage_fixture("ultra")))
    doctor.run(sub, io.StringIO(), str(tmp_path), server.url, now=NOW, fetch_now=True)
    assert len(server.requests) == 1


def test_clock_names_the_day_when_not_today():
    import time

    later = NOW + 30 * 3600  # always another day
    assert doctor._clock(later, NOW) == time.strftime("%a %H:%M", time.localtime(later))
    assert doctor._clock(NOW, NOW) == time.strftime("%H:%M", time.localtime(NOW))


@pytest.mark.parametrize(
    ("until", "server_set"),
    [
        (NOW + 3000, False),  # our own backoff: doctor retries now, as before
        (NOW - 1, True),  # the server's wait is over
    ],
)
def test_usage_fetches_through_other_holds(sub, server, tmp_path, until, server_set):
    server_hold(sub, until, server=server_set)
    server.reply(200, json.dumps(usage_fixture("ultra")))
    assert usage_check(sub, tmp_path, server.url)[0] == "ok"
    assert len(server.requests) == 1


def test_usage_says_when_a_new_wait_is_the_servers(sub, server, tmp_path):
    server.reply(429, "", **{"Retry-After": "7200"})
    status, text, _ = usage_check(sub, tmp_path, server.url)
    assert status == "fail"
    assert text == "HTTP 429; renders retry in 2h00m (the server asked for that wait)"


@pytest.mark.parametrize(
    ("reason", "cure"),
    [
        ("token rejected (401)", "run /login in Claude Code"),
        ("not allowed (403): the login may lack the profile scope", "run /login in Claude Code"),
    ],
)
def test_servers_wait_on_a_login_problem_points_at_the_login(sub, server, tmp_path, reason, cure):
    """Waiting out a 401's Retry-After won't fix the token: say what will."""
    server_hold(sub, NOW + 3600, reason=reason)
    status, text, fix = usage_check(sub, tmp_path, server.url)
    assert server.requests == []
    assert status == "warn"
    assert text.endswith(f"left) after {reason}")
    assert fix == f"{cure}, then run doctor with --fetch-now to check"


# ---- the fetch lock ----


def usage_only(env, tmp_path, base_url, fetch_now=False):
    """The login and usage checks alone: the command check's real render, on the real
    clock, would break a lock written at NOW and start a background fetch."""
    d = doctor.Doctor(env, NOW, str(tmp_path), base_url, "linux", fetch_now=fetch_now)
    d.login()
    d.usage()
    return d.results[-1][0], d.results[-1][2], d.results[-1][3]


def live_lock(env, at=NOW - 10):
    cache_path(env).mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = cache_path(env) / "fetch.lock"
    lock.write_text(json.dumps({"at": at, "pid": 1, "nonce": "theirs"}))
    return lock


@pytest.mark.parametrize("fetch_now", [False, True])
def test_usage_leaves_a_running_fetch_alone(sub, server, tmp_path, fetch_now):
    lock = live_lock(sub)
    server.reply(200, json.dumps(usage_fixture("ultra")))
    status, text, fix = usage_only(sub, tmp_path, server.url, fetch_now=fetch_now)
    assert server.requests == []
    assert (status, text) == ("info", "not fetched: a fetch is running in the background")
    assert fix == "run doctor again in a moment to see its result"
    assert json.loads(lock.read_text())["nonce"] == "theirs"  # not taken, not removed


def test_usage_waits_for_a_running_fetch_to_finish(sub, server, tmp_path, monkeypatch):
    import threading

    monkeypatch.setattr(doctor, "LOCK_WAIT", 3)
    lock = live_lock(sub)
    threading.Timer(0.3, lock.unlink).start()  # the background fetch finishes
    server.reply(200, json.dumps(usage_fixture("ultra")))
    assert usage_only(sub, tmp_path, server.url)[0] == "ok"
    assert len(server.requests) == 1


def test_usage_breaks_a_stale_lock_and_releases_its_own(sub, server, tmp_path):
    live_lock(sub, at=NOW - 600)  # its child died
    server.reply(200, json.dumps(usage_fixture("ultra")))
    assert usage_only(sub, tmp_path, server.url)[0] == "ok"
    assert len(server.requests) == 1
    assert not (cache_path(sub) / "fetch.lock").exists()


def test_usage_releases_the_lock_when_the_fetch_raises(sub, tmp_path, monkeypatch):
    def boom(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(usage, "refresh", boom)
    d = doctor.Doctor(sub, NOW, str(tmp_path), CLOSED, "linux")
    d.login()
    d.usage()
    assert not (cache_path(sub) / "fetch.lock").exists()
    status, name, text, fix = d.results[-1]
    assert (status, name) == ("fail", "usage")
    assert text.startswith("fetch failed (RuntimeError); renders retry in ")
    assert "boom" not in text  # the type only: an error's text could hold anything
    assert fix == "run doctor again later; report it if it keeps happening"
    # As the background fetch does, it holds, so renders don't refetch at once.
    assert usage.hold(sub, account.identity(sub), NOW)["reason"] == "fetch failed (RuntimeError)"


# ---- the cache check and odd files ----


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_cache_odd_fetch_time(sub, tmp_path, monkeypatch, value):
    monkeypatch.setattr(doctor.Doctor, "usage", lambda self: None)
    cache_path(sub).mkdir(mode=0o700, parents=True)
    who = account.identity(sub)
    body = '{"fetched_at": ' + value + ', "account": "' + who + '", "data": {}}'
    (cache_path(sub) / usage.cache_name(who)).write_text(body)
    (cache_path(sub) / usage.cache_name(who)).chmod(0o600)
    status, text, _ = check(sub, "cache", tmp_path)
    assert status == "ok"
    assert "fetched" not in text


def test_cache_leaves_another_tools_usage_json_alone(sub, tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.Doctor, "usage", lambda self: None)
    cache_path(sub).mkdir(mode=0o700, parents=True)
    foreign = cache_path(sub) / "usage.json"
    foreign.write_text('{"another_tool": true}')
    foreign.chmod(0o644)
    status, text, fix = check(sub, "cache", tmp_path)
    assert (status, fix) == ("ok", None)
    assert "other users" not in text


# ---- a locked Keychain ----


def test_locked_keychain_is_not_a_login_problem(sub, isolated_home, tmp_path, monkeypatch):
    waits = []

    def locked(env, wait):
        waits.append(wait)
        raise account.KeychainError(account.KEYCHAIN_LOCKED)

    (isolated_home / ".claude" / ".credentials.json").unlink()
    monkeypatch.setattr(account, "_read_keychain", locked)
    d = doctor.Doctor(sub, NOW, str(tmp_path), CLOSED, "darwin")
    results = {n: (s, t, f) for s, n, t, f in d.run()}
    status, text, fix = results["login"]
    assert status == "fail"
    assert text.endswith(account.KEYCHAIN_LOCKED)
    assert "unlock" in fix
    assert "/login won't help" in fix
    status, text, fix = results["usage"]
    assert text.startswith(account.KEYCHAIN_LOCKED)
    assert "unlock" in fix
    # The login check, which the user watches, gives a Keychain prompt time; the fetch
    # after it doesn't wait as long (its lock would go stale).
    assert waits == [account.KEYCHAIN_WAIT_ASKED, account.KEYCHAIN_WAIT]


# ---- a bad --glyphs value ----


def test_bad_glyphs_in_the_command(installed, tmp_path):
    data = get_settings(installed)
    data["statusLine"]["command"] = data["statusLine"]["command"].replace("nerd", "Nerd")
    set_settings(installed, data)
    d = doctor.Doctor(installed, NOW, str(tmp_path), CLOSED, "linux")
    results = {n: (s, t, f) for s, n, t, f in d.run()}
    status, text, fix = results["settings"]
    assert status == "warn"
    assert text.endswith("--glyphs Nerd isn't a glyph set (nerd, unicode or ascii)")
    assert "/dashline:install" in fix
    status, text, _ = results["command"]
    assert status == "fail"
    assert text == "dashline: unknown glyph set 'Nerd': use nerd, unicode or ascii"
    assert results["command"][2] == "its --glyphs isn't a glyph set: see the settings line"
    assert "the command's --glyphs isn't a glyph set" in results["font"][1]


@pytest.mark.parametrize(
    ("err", "reason"),
    [
        (["dashline: x", "", "usage: y", "  --help  show this help"], "dashline: x"),
        (["Traceback", "ValueError: z"], "ValueError: z"),
        ([], None),
    ],
)
def test_stderr_reason(err, reason):
    assert doctor.stderr_reason(err) == reason


def test_reason_from_stdout_when_stderr_is_sent_away():
    out = ["dashline: unknown argument '--x' (run statusline.py --doctor)"]
    assert doctor.stderr_reason([], out) == out[0]
    assert doctor.stderr_reason([], ["Sonnet 5.5"]) is None
    assert doctor.stderr_reason(["ValueError: z"], out) == "ValueError: z"  # stderr first


def test_command_with_stderr_sent_away(installed, tmp_path):
    data = get_settings(installed)
    data["statusLine"]["command"] += " --bogus 2>/dev/null"
    set_settings(installed, data)
    status, text, _ = check(installed, "command", tmp_path)
    assert status == "fail"
    assert text == "dashline: unknown argument '--bogus' (run statusline.py --doctor)"


# ---- the command and git checks when things go wrong ----


# The shell doctor runs the command in, as fake_run matches it, and its name.
@pytest.fixture
def shell():
    """(program, name) of the shell doctor runs the command in here, for fake_run."""
    if not host.WINDOWS:
        return "sh", "sh"
    argv, name = doctor.windows_shell(os.environ)
    return argv[0], name


def fake_run(monkeypatch, program, error=None, stdout="", stderr="", returncode=0):
    """subprocess.run, with `program` faked: it raises `error` or prints `stdout` and
    `stderr`, exiting `returncode`."""
    real = subprocess.run

    class Done:
        pass

    def fake(args, **kwargs):
        if args[0] != program:
            return real(args, **kwargs)
        if error is not None:
            raise error
        done = Done()
        done.stdout, done.stderr, done.returncode = stdout, stderr, returncode
        return done

    monkeypatch.setattr(subprocess, "run", fake)


def test_command_timeout(installed, tmp_path, monkeypatch, shell):
    fake_run(monkeypatch, shell[0], error=subprocess.TimeoutExpired(shell[0], 10))
    status, text, _ = check(installed, "command", tmp_path)
    assert (status, text) == ("fail", "took over 10 s")


def test_command_without_sh(installed, tmp_path, monkeypatch, shell):
    fake_run(monkeypatch, shell[0], error=FileNotFoundError(shell[0]))
    status, text, _ = check(installed, "command", tmp_path)
    assert status == "fail"
    assert text.startswith(f"couldn't run {shell[1]}:")


def as_windows_writes_it(env):
    """The installed entry with the config folder spelled out, as a Windows install
    writes it (here still runnable by sh), not the Bash-only form."""
    data = get_settings(env)
    cmd = data["statusLine"]["command"]
    conf = Path(theme.config_dir(env)).as_posix()
    data["statusLine"]["command"] = cmd.replace("${CLAUDE_CONFIG_DIR:-$HOME/.claude}", conf)
    set_settings(env, data)


def test_command_slow_in_powershell_suggests_git(installed, tmp_path, monkeypatch):
    as_windows_writes_it(installed)
    monkeypatch.setattr(doctor, "SLOW_MS", -1)
    monkeypatch.setattr(doctor, "SLOW_MS_WINDOWS", -1)
    monkeypatch.setattr(host, "WINDOWS", True)
    monkeypatch.setattr(
        doctor, "windows_shell", lambda env, which=None: (["sh", "-c"], "PowerShell")
    )
    status, text, fix = check(installed, "command", tmp_path)
    assert (status, text.endswith("(PowerShell) (slow)")) == ("warn", True)
    assert "Git for Windows" in fix


def test_command_slow(installed, tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "SLOW_MS", -1)
    monkeypatch.setattr(doctor, "SLOW_MS_WINDOWS", -1)
    status, text, fix = check(installed, "command", tmp_path)
    assert status == "warn"
    assert text.endswith("(slow)")
    assert "git" in fix


def test_git_too_old(installed, tmp_path, monkeypatch):
    fake_run(monkeypatch, "git", stdout="git version 2.14.6\n")
    status, text, fix = check(installed, "git", tmp_path)
    assert status == "warn"
    assert text == "2.14.6: too old for the git row, which shows the folder only (needs 2.15)"
    assert fix == "update git"


def test_git_unreadable_version(installed, tmp_path, monkeypatch):
    fake_run(monkeypatch, "git", stdout="git, but not as we know it\n")
    status, text, _ = check(installed, "git", tmp_path)
    assert (status, text) == ("warn", "unexpected version: git, but not as we know it")


def test_statusline_type_not_command(installed, tmp_path):
    data = get_settings(installed)
    data["statusLine"]["type"] = "static"
    set_settings(installed, data)
    status, text, fix = check(installed, "settings", tmp_path)
    assert status == "fail"
    assert text == '~/.claude/settings.json: statusLine type isn\'t "command"'
    assert fix == "run /dashline:install"


def test_command_errors_through_powershell(installed, tmp_path, monkeypatch):
    """PowerShell 5.1 wraps stderr into an error record whose last line says nothing:
    the reason and its fix come from the program's own line."""
    as_windows_writes_it(installed)
    monkeypatch.setattr(host, "WINDOWS", True)
    monkeypatch.setattr(doctor, "windows_shell", lambda env, which=None: (["pwsh-x"], "PowerShell"))
    not_found = (
        "py : The term 'py' is not recognized as the name of a cmdlet, function, script "
        "file, or operable program.\n"
        "At line:1 char:1\n"
        "+ py -3 -I -S C:/Users/pat/.claude/scripts/statusline/statusline.py\n"
        "+ ~~\n"
        "    + CategoryInfo          : ObjectNotFound: (py:String) [], CommandNotFoundException\n"
        "    + FullyQualifiedErrorId : CommandNotFoundException\n"
    )
    fake_run(monkeypatch, "pwsh-x", stderr=not_found, returncode=1)
    status, text, fix = check(installed, "command", tmp_path)
    assert status == "fail"
    assert text.startswith("The term 'py' is not recognized")
    program = doctor.first_word(get_settings(installed)["statusLine"]["command"])  # py on Windows
    assert fix == (
        f"{program} must be on the PATH Claude Code sees: install Python, or add it to "
        "PATH, then restart Claude Code"
    )
    ours = (
        "py : dashline: unknown argument '--bogus' (run statusline.py --doctor)\n"
        "At line:1 char:1\n"
        "+ py -3 -I -S C:/x/statusline.py --bogus\n"
        "+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n"
        "    + CategoryInfo          : NotSpecified: (dashline: unknown...) [], RemoteException\n"
        "    + FullyQualifiedErrorId : NativeCommandError\n"
    )
    fake_run(monkeypatch, "pwsh-x", stderr=ours, returncode=2)
    status, text, _ = check(installed, "command", tmp_path)
    assert (status, text) == (
        "fail",
        "dashline: unknown argument '--bogus' (run statusline.py --doctor)",
    )


def test_powershell_unwrapped_leaves_other_stderr_alone():
    plain = ["Traceback (most recent call last):", "  x : y", "+ a line of mine", "ValueError: z"]
    assert doctor.powershell_unwrapped(plain) == plain


def test_powershell_unwrapped_in_any_language_and_width():
    """The message is the record's first lines, wrapped at the window's width; the
    line after says where, in the system's language (German here)."""
    record = [
        'py : Die Benennung "py" wurde nicht als Name eines Cmdlet, einer Funktion,',
        "einer Skriptdatei oder eines ausführbaren Programms erkannt.",
        "In Zeile:1 Zeichen:1",
        "+ py -3 -I -S C:/x/statusline.py",
        "+ ~~",
        "    + CategoryInfo          : ObjectNotFound: (py:String) [], CommandNotFoundException",
        "    + FullyQualifiedErrorId : CommandNotFoundException",
    ]
    assert doctor.powershell_unwrapped(record) == [
        'Die Benennung "py" wurde nicht als Name eines Cmdlet, einer Funktion, einer '
        "Skriptdatei oder eines ausführbaren Programms erkannt."
    ]
    # A program's stderr: its first line in the record, the rest after it as written.
    traceback = [
        "py : Traceback (most recent call last):",
        "At line:1 char:1",
        "+ py -3 -I -S C:/x/statusline.py",
        "+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~",
        "    + CategoryInfo          : NotSpecified: (Traceback (most rece...):String) [], "
        "RemoteException",
        "    + FullyQualifiedErrorId : NativeCommandError",
        " ",
        '  File "C:/x/statusline.py", line 3, in <module>',
        "ValueError: broken",
    ]
    assert doctor.powershell_unwrapped(traceback) == [
        "Traceback (most recent call last):",
        '  File "C:/x/statusline.py", line 3, in <module>',
        "ValueError: broken",
    ]


def windows_command_check(installed, tmp_path, monkeypatch, shell_name="PowerShell", **run):
    """The command check as on Windows, in `shell_name`, the command faking `run`."""
    monkeypatch.setattr(host, "WINDOWS", True)
    monkeypatch.setattr(doctor, "windows_shell", lambda env, which=None: (["shell-x"], shell_name))
    if run:
        fake_run(monkeypatch, "shell-x", **run)
    return check(installed, "command", tmp_path)


def test_command_blocked_by_a_policy(installed, tmp_path, monkeypatch):
    as_windows_writes_it(installed)
    blocked = (
        "Program 'python.exe' failed to run: This program is blocked by group policy. For "
        "more information, contact your system administrator"
    )
    status, _, fix = windows_command_check(
        installed, tmp_path, monkeypatch, stderr=blocked, returncode=1
    )
    assert status == "fail"
    assert fix.startswith("a policy on this PC blocks ")


def test_command_with_bash_variables_on_windows(installed, tmp_path, monkeypatch):
    """Not the old command, but $-variables all the same: --replace writes the Windows one."""
    data = get_settings(installed)
    data["statusLine"]["command"] = install.COMMAND + " 2>/dev/null"  # an edit: not old_form
    set_settings(installed, data)
    missing = "C:\\Py\\python.exe: can't open file 'C:\\scripts\\statusline\\statusline.py'"
    status, _, fix = windows_command_check(
        installed, tmp_path, monkeypatch, stderr=missing, returncode=2
    )
    assert status == "fail"
    assert "--replace" in fix
    status, text, fix = windows_command_check(
        installed, tmp_path, monkeypatch, "Git Bash", stdout="a │ b\nc\n"
    )
    assert status == "warn"
    # It works here: the warning says when it wouldn't.
    assert text.endswith(
        "(Git Bash); without Git Bash, Claude Code would run it in PowerShell, which can't"
    )
    assert "--replace" in fix
    status, text, fix = windows_command_check(installed, tmp_path, monkeypatch, stdout="a │ b\nc\n")
    assert status == "warn"
    assert text.endswith("(PowerShell), but PowerShell can't run this command")
    # In Git Bash, failing for another reason: that reason's fix, not --replace.
    status, _, fix = windows_command_check(
        installed,
        tmp_path,
        monkeypatch,
        "Git Bash",
        stderr="bash: python3: command not found",
        returncode=127,
    )
    assert status == "fail"
    assert fix.startswith("python3 must be on the PATH Claude Code sees")


def test_command_symbols_changed_by_powershell(installed, tmp_path, monkeypatch):
    """A console code page without `│` (Japanese, say): PowerShell passes `?` on."""
    as_windows_writes_it(installed)
    status, text, fix = windows_command_check(
        installed, tmp_path, monkeypatch, stdout="Sonnet 5.5 ? context ????\n~/x\n"
    )
    assert status == "warn"
    assert text.endswith("but its symbols came back changed")
    assert "ascii" in fix
    data = get_settings(installed)
    data["statusLine"]["command"] = install.with_glyphs(data["statusLine"]["command"], "ascii")
    set_settings(installed, data)
    status, _, _ = windows_command_check(
        installed, tmp_path, monkeypatch, stdout="Sonnet 5.5 | context ----\n~/x\n"
    )
    assert status == "ok"


def test_git_for_git_bash_only(installed, tmp_path, monkeypatch):
    """Git installed for Git Bash only isn't on PATH; the statusline, run in Git Bash,
    still has it, and so does doctor."""
    bash = git_for_windows(tmp_path / "Git")
    monkeypatch.setattr(host, "WINDOWS", True)
    monkeypatch.setattr(
        doctor, "windows_shell", lambda env, which=None: ([str(bash), "-c"], "Git Bash")
    )
    monkeypatch.setattr("shutil.which", lambda name, path=None: None)
    fake_run(monkeypatch, str(tmp_path / "Git" / "cmd" / "git.exe"), stdout="git version 2.50.1\n")
    status, text, _ = check(installed, "git", tmp_path)
    assert (status, text) == ("ok", "2.50.1")


def test_old_bash_only_command_on_windows(installed, tmp_path, monkeypatch):
    """The command dashline wrote before Windows support runs in Git Bash only: doctor
    says install rewrites it, whether it fails here or not."""
    monkeypatch.setattr(host, "WINDOWS", True)
    monkeypatch.setattr(doctor, "windows_shell", lambda env, which=None: (["sh", "-c"], "Git Bash"))
    if os.name == "nt":  # the installed entry is the Windows one: put the old one in
        data = get_settings(installed)
        data["statusLine"]["command"] = install.command("nerd")
        set_settings(installed, data)
        fake_run(monkeypatch, "sh", stdout="line 1\nline 2\n")
    status, text, fix = check(installed, "command", tmp_path)
    assert status == "warn"
    assert text.endswith("Claude Code would run it in PowerShell, which can't")
    assert fix == "run /dashline:install: it rewrites this command for Windows"
    fake_run(monkeypatch, "sh", stderr="sh: python3: command not found\n", returncode=127)
    status, _, fix = check(installed, "command", tmp_path)
    assert status == "fail"
    assert fix == "run /dashline:install: it rewrites this command for Windows"


def nowhere(tmp_path):
    """An env whose Program Files hold neither Git nor PowerShell 7."""
    return {"ProgramFiles": str(tmp_path / "pf"), "ProgramFiles(x86)": str(tmp_path / "pf86")}


def git_for_windows(root):
    """A Git for Windows folder: cmd\\git.exe, bin\\bash.exe, ucrt64\\bin\\git.exe."""
    for rel in ("cmd/git.exe", "bin/bash.exe", "ucrt64/bin/git.exe"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("")
    return root / "bin" / "bash.exe"


POWERSHELL = ["powershell", *doctor.POWERSHELL_OPTIONS]


@pytest.mark.parametrize("git", ["cmd/git.exe", "ucrt64/bin/git.exe"])
def test_windows_shell_finds_git_bash_from_git(tmp_path, git):
    """From git on PATH: <root>\\cmd\\git.exe, or in Git Bash itself
    <root>\\ucrt64\\bin\\git.exe (mingw64 in older versions); bash.exe is <root>\\bin's."""
    bash = git_for_windows(tmp_path / "Git")
    which = {"git": str(tmp_path / "Git" / git)}.get
    assert doctor.windows_shell(nowhere(tmp_path), which) == ([str(bash), "-c"], "Git Bash")


def test_windows_shell_skips_a_bash_that_isnt_git_for_windows(tmp_path):
    """MSYS2's own git and bash (no cmd\\git.exe): not the shell Claude Code picks."""
    for rel in ("usr/bin/git.exe", "usr/bin/bash.exe", "bin/bash.exe"):
        (tmp_path / "msys64" / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "msys64" / rel).write_text("")
    which = {"git": str(tmp_path / "msys64" / "usr" / "bin" / "git.exe")}.get
    assert doctor.windows_shell(nowhere(tmp_path), which) == (POWERSHELL, "PowerShell")


def test_windows_shell_in_claude_codes_order(tmp_path):
    """CLAUDE_CODE_GIT_BASH_PATH, then Git in Program Files (64-bit, then 32-bit), then
    git on PATH; without Git Bash, PowerShell 7 from Program Files, else Windows'."""
    env = nowhere(tmp_path)
    on_path = git_for_windows(tmp_path / "PortableGit")
    which = {"git": str(tmp_path / "PortableGit" / "cmd" / "git.exe")}.get
    assert doctor.windows_shell(env, which)[0] == [str(on_path), "-c"]
    x86 = git_for_windows(tmp_path / "pf86" / "Git")
    assert doctor.windows_shell(env, which)[0] == [str(x86), "-c"]
    pf = git_for_windows(tmp_path / "pf" / "Git")
    assert doctor.windows_shell(env, which)[0] == [str(pf), "-c"]
    own = tmp_path / "my-bash.exe"
    own.write_text("")
    mine = {**env, "CLAUDE_CODE_GIT_BASH_PATH": str(own)}
    assert doctor.windows_shell(mine, which) == ([str(own), "-c"], "Git Bash")
    gone = {**nowhere(tmp_path / "x"), "CLAUDE_CODE_GIT_BASH_PATH": str(tmp_path / "no.exe")}
    assert doctor.windows_shell(gone, {}.get) == (POWERSHELL, "PowerShell")
    pwsh = tmp_path / "x" / "pf" / "PowerShell" / "7" / "pwsh.exe"
    pwsh.parent.mkdir(parents=True)
    pwsh.write_text("")
    assert doctor.windows_shell(gone, {}.get) == (
        [str(pwsh), *doctor.POWERSHELL_OPTIONS],
        "PowerShell 7",
    )
    # os.environ's names are upper case on Windows.
    upper = {"PROGRAMFILES": str(tmp_path / "pf"), "PROGRAMFILES(X86)": str(tmp_path / "n")}
    assert doctor.windows_shell(upper, {}.get)[0] == [str(pf), "-c"]


@pytest.mark.skipif(os.name != "nt", reason="Windows' shells")
@pytest.mark.parametrize("shell", ["Git Bash", "PowerShell 7", "PowerShell"])
def test_windows_command_runs_in_each_shell(installed, tmp_path, monkeypatch, shell):
    """Claude Code runs the command in Git Bash, or in PowerShell without one: each
    shell as doctor starts it (the options Claude Code passes)."""

    def missing(what):
        if os.environ.get("CI"):  # the runner has all three: a skip there hides a break
            pytest.fail(f"no {what} on this runner")
        pytest.skip(f"no {what} here")

    if shell == "Git Bash":
        if doctor.windows_shell(os.environ)[1] != "Git Bash":
            missing("Git Bash")
        found = doctor.windows_shell(os.environ)
    elif shell == "PowerShell 7":
        pwsh = Path(doctor.program_files(os.environ)) / "PowerShell" / "7" / "pwsh.exe"
        if not pwsh.is_file():
            missing("PowerShell 7")
        found = ([str(pwsh), *doctor.POWERSHELL_OPTIONS], shell)
    else:
        found = (["powershell", *doctor.POWERSHELL_OPTIONS], shell)
    monkeypatch.setattr(doctor, "windows_shell", lambda env, which=None: found)
    monkeypatch.setattr(doctor, "SLOW_MS_WINDOWS", 60_000)  # it runs; CI's speed varies
    status, text, fix = check(installed, "command", tmp_path)
    assert (status, fix) == ("ok", None), text
    assert text.endswith(f"({shell})")


# ---- found in the third review ----


def test_command_not_found_in_powershell_7(installed, tmp_path, monkeypatch):
    """PowerShell 7 writes `python3: <message>` and a line of advice, no record."""
    as_windows_writes_it(installed)
    py = doctor.first_word(get_settings(installed)["statusLine"]["command"])  # python on Windows
    concise = (
        f"{py}: The term '{py}' is not recognized as a name of a cmdlet, function, "
        "script file, or executable program.\n"
        "Check the spelling of the name, or if a path was included, verify that the path "
        "is correct and try again."
    )
    status, text, fix = windows_command_check(
        installed, tmp_path, monkeypatch, "PowerShell 7", stderr=concise, returncode=1
    )
    assert status == "fail"
    assert text.startswith(f"The term '{py}' is not recognized")
    assert fix.startswith(f"{py} must be on the PATH Claude Code sees: install Python")


def test_powershell_unwrapped_needs_the_whole_record():
    """Text that only names an error record (a traceback quoting one) is left alone."""
    err = ["something about FullyQualifiedErrorId", "ValueError: z"]
    assert doctor.powershell_unwrapped(err) == err
    err = ["x FullyQualifiedErrorId y", "+ a detail line after it"]  # none before it
    assert doctor.powershell_unwrapped(err) == err


def test_entry_of_another_type_is_not_run(installed, tmp_path):
    """Claude Code runs only a "command" entry, so doctor doesn't run this one."""
    data = get_settings(installed)
    data["statusLine"]["type"] = "static"
    set_settings(installed, data)
    d = doctor.Doctor(installed, NOW, str(tmp_path), CLOSED, "linux")
    results = {n: (s, t, f) for s, n, t, f in d.run()}
    assert results["settings"][0] == "fail"
    assert results["command"] == ("info", "not run: settings don't run dashline", None)
    assert "glyphs" not in results["font"][1]


def test_glyphs_after_the_command_are_not_dashlines(installed, tmp_path):
    data = get_settings(installed)
    data["statusLine"]["command"] += " || echo --glyphs x"
    set_settings(installed, data)
    d = doctor.Doctor(installed, NOW, str(tmp_path), CLOSED, "linux")
    results = {n: (s, t, f) for s, n, t, f in d.run()}
    assert "isn't a glyph set" not in results["settings"][1]
    assert results["font"][1].endswith("using nerd glyphs")


def test_command_runs_at_a_width_that_draws_every_separator(installed, tmp_path, monkeypatch):
    """A narrow COLUMNS in doctor's own shell drops `│`: the glyph check would misfire."""
    seen = []
    real = subprocess.run

    def spy(args, **kwargs):
        if "input" in kwargs:  # the statusLine command, in whichever shell
            seen.append(kwargs["env"].get("COLUMNS"))
        return real(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    status, _, _ = check(dict(installed, COLUMNS="30"), "command", tmp_path)
    assert status == "ok"
    assert seen == ["120"]


def test_install_missing_only_its_shim(installed, tmp_path):
    (Path(install.install_dir(installed)) / "statusline.py").unlink()
    status, text, fix = check(installed, "install", tmp_path)
    assert (status, fix) == ("fail", "run /dashline:install")
    assert text == "statusline.py is missing from ~/.claude/scripts/statusline"


def test_doctor_run_from_the_installed_copy(installed, tmp_path, monkeypatch):
    target = install.install_dir(installed)
    monkeypatch.setattr(install, "source_root", lambda: target)
    status, text, _ = check(installed, "install", tmp_path)
    assert status == "ok"
    assert text.endswith("(doctor ran from it)")


# ---- found in the fourth review ----


def test_newer_install_with_the_same_files(installed, isolated_home, tmp_path):
    """A newer release can ship the same code (one that changed only docs): still
    newer, not "same as this copy"."""
    target = isolated_home / ".claude" / "scripts" / "statusline"
    (target / "VERSION").write_text("99.0.0\n")
    status, text, fix = check(installed, "install", tmp_path)
    assert status == "warn"
    assert "99.0.0 is newer than this copy" in text
    assert fix.startswith("update the dashline plugin")
    # The same files at an older version: an update writes the new VERSION.
    (target / "VERSION").write_text("0.0.1\n")
    status, text, _ = check(installed, "install", tmp_path)
    assert status == "warn"
    assert "0.0.1; this copy is" in text


def test_project_entry_that_only_names_the_install_path(installed, tmp_path):
    """A repo's settings can name dashline's path inside anything: that entry isn't
    dashline's, doctor doesn't run it, and no escape it holds reaches the terminal."""
    marker = tmp_path / "ran"
    cmd = (
        f"touch '{marker.as_posix()}'; printf '\x1b[31mEVIL'; "
        "python3 $HOME/.claude/scripts/statusline/statusline.py"
    )
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"statusLine": {"type": "command", "command": cmd}})
    )
    d = doctor.Doctor(installed, NOW, str(tmp_path), CLOSED, "linux")
    results = {n: (s, t, f) for s, n, t, f in d.run()}
    status, text, _ = results["settings"]
    assert status == "fail"
    assert "runs another statusline" in text
    assert "\x1b" not in text
    assert results["command"][0] == "info"
    assert not marker.exists()
    # The same entry in the user's own settings is theirs to write as they like.
    assert install.is_ours({"command": cmd}, installed)
    assert not install.is_ours({"command": cmd}, installed, direct=True)


def test_project_dashline_entry_of_another_type(installed, tmp_path):
    entry = dict(get_settings(installed)["statusLine"], type="static")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"statusLine": entry}))
    status, _, fix = check(installed, "settings", tmp_path)
    assert status == "fail"
    assert fix.startswith('set its statusLine\'s "type" to "command" in ')


def test_doctor_lines_carry_no_control_characters(installed, tmp_path):
    data = get_settings(installed)
    data["theme"] = "\x1b[31mred\x07"
    set_settings(installed, data)
    _, text, _ = check(installed, "theme", tmp_path)
    assert text == "?[31mred?"


def test_command_timeout_fix(installed, tmp_path, monkeypatch, shell):
    fake_run(monkeypatch, shell[0], error=subprocess.TimeoutExpired(shell[0], 10))
    _, _, fix = check(installed, "command", tmp_path)
    assert fix == "a hung git or a slow disk; report it if it keeps happening"


def test_command_that_prints_nothing_fails(installed, tmp_path, monkeypatch, shell):
    fake_run(monkeypatch, shell[0], stdout="", returncode=0)
    status, text, _ = check(installed, "command", tmp_path)
    assert (status, text) == ("fail", "exit 0, 0 lines")


def test_windows_has_its_own_slow_threshold(installed, tmp_path, monkeypatch):
    """Starting the shell takes most of a second on Windows: SLOW_MS_WINDOWS there,
    SLOW_MS elsewhere."""
    as_windows_writes_it(installed)
    monkeypatch.setattr(doctor, "SLOW_MS", -1)
    monkeypatch.setattr(doctor, "SLOW_MS_WINDOWS", 60_000)
    status, _, _ = windows_command_check(
        installed, tmp_path, monkeypatch, "Git Bash", stdout="a │ b\nc\n"
    )
    assert status == "ok"
    monkeypatch.setattr(host, "WINDOWS", False)
    monkeypatch.setattr(doctor, "SLOW_MS", 60_000)
    monkeypatch.setattr(doctor, "SLOW_MS_WINDOWS", -1)
    assert check(installed, "command", tmp_path)[0] == "ok"


def test_symbols_check_is_powershells_only(installed, tmp_path, monkeypatch):
    """Git Bash passes UTF-8 through: a `?` there is the statusline's own text."""
    as_windows_writes_it(installed)
    status, _, _ = windows_command_check(
        installed, tmp_path, monkeypatch, "Git Bash", stdout="Sonnet 5.5 ? x\n~/x\n"
    )
    assert status == "ok"


def test_first_word_keeps_windows_backslashes(monkeypatch):
    cmd = 'C:\\Python312\\python.exe -I -S "C:/Users/pat/.claude/scripts/statusline/statusline.py"'
    monkeypatch.setattr(host, "WINDOWS", True)
    assert doctor.first_word(cmd) == "C:\\Python312\\python.exe"
    assert doctor.first_word('"C:\\Program Files\\Py\\python.exe" -I x') == (
        "C:\\Program Files\\Py\\python.exe"
    )
    monkeypatch.setattr(host, "WINDOWS", False)
    assert doctor.first_word("'/opt/my py/python3' -I x") == "/opt/my py/python3"


def not_recognized(py):
    return (
        f"{py}: The term '{py}' is not recognized as a name of a cmdlet, function, "
        "script file, or executable program."
    )


def test_windows_python_gone_but_another_runs(installed, tmp_path, monkeypatch):
    """The Windows command's Python is gone (py, after a switch to the Store's Python):
    a plain install rewrites dashline's own command with one that runs."""
    as_windows_writes_it(installed)
    py = doctor.first_word(get_settings(installed)["statusLine"]["command"])
    monkeypatch.setattr(install, "windows_python", lambda *args, **kwargs: "python")
    status, _, fix = windows_command_check(
        installed, tmp_path, monkeypatch, "PowerShell 7", stderr=not_recognized(py), returncode=1
    )
    assert status == "fail"
    assert fix == (
        "run /dashline:install: it rewrites this command for Windows, "
        "with a Python that runs here (python)"
    )
    # A command the user edited (a full path): only --replace rewrites it.
    data = get_settings(installed)
    data["statusLine"]["command"] = data["statusLine"]["command"].replace(py, "C:/Py/python.exe", 1)
    set_settings(installed, data)
    status, _, fix = windows_command_check(
        installed,
        tmp_path,
        monkeypatch,
        "PowerShell 7",
        stderr=not_recognized("C:/Py/python.exe"),
        returncode=1,
    )
    assert status == "fail"
    assert fix.startswith("/dashline:install with --replace writes the Windows command")


def test_git_on_path_wins_over_git_bashs_own(installed, tmp_path, monkeypatch):
    """With git on PATH too, that's the one the statusline runs: doctor checks it."""
    bash = git_for_windows(tmp_path / "Git")
    monkeypatch.setattr(host, "WINDOWS", True)
    monkeypatch.setattr(
        doctor, "windows_shell", lambda env, which=None: ([str(bash), "-c"], "Git Bash")
    )
    monkeypatch.setattr("shutil.which", lambda name, path=None: "C:/other/git.exe")
    fake_run(monkeypatch, "git", stdout="git version 2.51.0\n")
    status, text, _ = check(installed, "git", tmp_path)
    assert (status, text) == ("ok", "2.51.0")
