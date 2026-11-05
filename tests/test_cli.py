"""The entry shim and command-line modes, run the way Claude Code runs them."""

import json
import subprocess
import sys

import pytest

from conftest import ROOT, read_json
from dashline import __version__
from dashline.__main__ import UsageError, parse_args


def run_shim(*args, stdin=""):
    # -I -S matches the installed settings entry: no script dir on sys.path, no site.
    return subprocess.run(
        [sys.executable, "-I", "-S", str(ROOT / "statusline.py"), *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_versions_agree():
    plugin = read_json(ROOT / ".claude-plugin" / "plugin.json")
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert plugin["version"] == __version__
    assert f'version = "{__version__}"' in pyproject


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
    assert __main__.render(io.StringIO("{}"), out, env={}) == 0
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
    assert r.stdout == ""


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], {"mode": "render", "glyphs": "unicode", "scenario": None}),
        (["--glyphs", "nerd"], {"mode": "render", "glyphs": "nerd", "scenario": None}),
        (["--glyphs=ascii", "--preview"], {"mode": "preview", "glyphs": "ascii", "scenario": None}),
        (
            ["--preview", "pro", "--glyphs", "nerd"],
            {"mode": "preview", "glyphs": "nerd", "scenario": "pro"},
        ),
        (["-h"], {"mode": "help", "glyphs": "unicode", "scenario": None}),
    ],
)
def test_parse_args(argv, expected):
    assert parse_args(argv) == expected


@pytest.mark.parametrize(
    "argv", [["--glyphs"], ["--glyphs", "emoji"], ["--doctor", "--preview"], ["extra"]]
)
def test_parse_args_rejects(argv):
    with pytest.raises(UsageError):
        parse_args(argv)
