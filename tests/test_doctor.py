"""--doctor: each check's ok / warn / fail, against a fake home and a local endpoint."""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import FIXTURES, NOW, ROOT, read_json
from dashline import doctor, install, usage

CLOSED = "http://127.0.0.1:9"  # nothing listens here


def usage_fixture(name):
    return read_json(FIXTURES / "usage" / f"{name}.json")


@pytest.fixture
def env(isolated_home):
    (isolated_home / ".claude").mkdir(exist_ok=True)
    return {"HOME": str(isolated_home), "PATH": os.environ.get("PATH", "")}


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
    status, text, _ = check(installed, "settings", tmp_path)
    assert status == "fail"
    assert "settings.local.json runs another statusline: echo local" in text


def test_disable_all_hooks(installed, tmp_path):
    data = get_settings(installed)
    data["disableAllHooks"] = True
    set_settings(installed, data)
    status, text, fix = check(installed, "settings", tmp_path)
    assert status == "fail"
    assert "disableAllHooks is on" in text
    assert "your call" in fix


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
    assert (cache_path(sub) / "usage.json").stat().st_mode & 0o777 == 0o600


def test_cache_file_readable_by_others(sub, tmp_path):
    cache_path(sub).mkdir(mode=0o700, parents=True)
    cached = cache_path(sub) / "usage.json"
    cached.write_text(json.dumps({"fetched_at": NOW - 60, "data": {}}))
    cached.chmod(0o644)
    status, text, fix = check(sub, "cache", tmp_path)  # the fetch fails: usage.json stays
    assert status == "warn"
    assert text.endswith("other users can read usage.json")
    assert fix == "chmod 600 ~/.claude/cache/statusline/usage.json"


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


def test_cache_stale_lock(sub, server, tmp_path):
    server.reply(200, json.dumps(usage_fixture("ultra")))
    cache_path(sub).mkdir(mode=0o700, parents=True)
    lock = cache_path(sub) / "fetch.lock"
    lock.write_text("{}")
    lock.chmod(0o600)  # as take_lock makes it
    os.utime(lock, (NOW - 600, NOW - 600))
    status, text, _ = check(sub, "cache", tmp_path, server.url)
    assert status == "ok"
    assert "a stale fetch.lock (the next render clears it)" in text


# ---- command, git, theme, font ----


def test_command_broken_python(installed, tmp_path):
    data = get_settings(installed)
    data["statusLine"]["command"] = data["statusLine"]["command"].replace(
        "python3", "no-such-python3"
    )
    set_settings(installed, data)
    status, text, fix = check(installed, "command", tmp_path)
    assert status == "fail"
    assert "not found" in text
    assert "PATH" in fix


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
    assert doctor.font_guess({}, "darwin") == (True, "found SymbolsNerdFontMono-Regular.ttf")


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
