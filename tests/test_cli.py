"""The entry shim and command-line modes, run the way Claude Code runs them."""

import json
import subprocess
import sys

import pytest

from conftest import ROOT, read_json
from dashline import __version__
from dashline.__main__ import UsageError, parse_args


def run_shim(*args, stdin="", env_extra=None):
    # -I -S matches the installed settings entry: no script dir on sys.path, no site.
    # The env is the test's (conftest.isolated_home): a fake HOME, a dead HTTPS proxy.
    import os

    return subprocess.run(
        [sys.executable, "-I", "-S", str(ROOT / "statusline.py"), *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env={**os.environ, **(env_extra or {})},
    )


def test_versions_agree():
    plugin = read_json(ROOT / ".claude-plugin" / "plugin.json")
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert plugin["version"] == __version__
    assert f'version = "{__version__}"' in pyproject
    # The newest CHANGELOG entry is this version.
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = next(line for line in changelog.splitlines() if line.startswith("## "))
    assert first.startswith(f"## {__version__} ")


def test_shim_version():
    r = run_shim("--version")
    assert r.returncode == 0
    assert r.stdout == f"dashline {__version__}\n"


def test_shim_help():
    r = run_shim("--help")
    assert r.returncode == 0
    assert r.stdout.startswith("usage:")


def test_shim_renders_startup_capture(stdin_fixture):
    r = run_shim(stdin=stdin_fixture("startup"))
    assert r.returncode == 0
    assert "Opus 5.5" in r.stdout
    assert r.stdout.endswith("\n")


def test_render_errors_show_one_line(monkeypatch, capsys):
    import io

    from dashline import __main__, layout

    def boom(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(layout, "render", boom)
    out = io.StringIO()
    stdin = io.StringIO(json.dumps({"model": {"display_name": "Opus 5.5"}}))
    assert __main__.render(stdin, out, env={}) == 0
    assert out.getvalue() == "dashline: internal error (run statusline.py --doctor)\n"
    assert "RuntimeError: boom" in capsys.readouterr().err


@pytest.mark.parametrize("text", ["", "not json", "[1, 2]", json.dumps({"model": None})])
def test_bad_stdin_prints_nothing(text):
    r = run_shim(stdin=text)
    assert r.returncode == 0
    assert r.stdout == ""


def test_unknown_argument_is_a_usage_error():
    r = run_shim("--nope")
    assert r.returncode == 2
    assert "unknown argument" in r.stderr
    # As the statusline, a bad command says so on the line instead of going blank.
    assert r.stdout == "dashline: unknown argument '--nope' (run statusline.py --doctor)\n"


def test_usage_error_in_a_mode_prints_only_to_stderr():
    r = run_shim("--doctor", "--nope")
    assert r.returncode == 2
    assert r.stdout == ""


def test_render_writes_utf8_whatever_the_locale():
    r = run_shim(
        stdin=json.dumps({"model": {"display_name": "Opus ✦"}}),
        env_extra={"PYTHONIOENCODING": "latin-1", "NO_COLOR": "1"},
    )
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr
    assert r.stdout.startswith("Opus ✦")


def test_closed_stdout_is_quiet():
    cmd = [sys.executable, "-I", "-S", str(ROOT / "statusline.py")]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    proc.stdout.close()  # Claude Code went away before reading
    _, err = proc.communicate(json.dumps({"model": {"display_name": "Opus 5.5"}}).encode())
    assert proc.returncode == 0
    assert b"Traceback" not in err


def opts(mode="render", glyphs=None, scenario=None, replace=False, downgrade=False):
    return {
        "mode": mode,
        "glyphs": glyphs,
        "scenario": scenario,
        "replace": replace,
        "downgrade": downgrade,
    }


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], opts()),
        (["--glyphs", "nerd"], opts(glyphs="nerd")),
        (["--glyphs=ascii", "--preview"], opts("preview", "ascii")),
        (["--preview", "pro", "--glyphs", "nerd"], opts("preview", "nerd", "pro")),
        (["--preview", "pro", "--glyphs", "all"], opts("preview", "all", "pro")),
        (["--install"], opts("install")),
        (["--install", "--glyphs", "nerd", "--replace"], opts("install", "nerd", replace=True)),
        (["--doctor"], opts("doctor")),
        (["-h"], opts("help")),
        (["--glyphs=nerd", "--install"], opts("install", "nerd")),
        (["--install", "--downgrade"], opts("install", downgrade=True)),
    ],
)
def test_parse_args(argv, expected):
    assert parse_args(argv) == expected


@pytest.mark.parametrize(
    "argv",
    [
        ["--glyphs"],
        ["--glyphs", "emoji"],
        ["--doctor", "--preview"],
        ["--install", "--doctor"],
        ["extra"],
        ["--glyphs", "all"],
        ["--install", "--glyphs", "all"],
        ["--replace"],
        ["--doctor", "--replace"],
        ["--glyphsnerd"],
        ["--glyphsX", "nerd"],  # not --glyphs: it mustn't take the next argument
        ["--install", "--install"],
        ["--downgrade"],
        ["--doctor", "--downgrade"],
    ],
)
def test_parse_args_rejects(argv):
    with pytest.raises(UsageError):
        parse_args(argv)
