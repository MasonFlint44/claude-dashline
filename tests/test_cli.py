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


def latin1(data: bytes = b""):
    """A text stream the way a latin-1 locale opens stdin and stdout."""
    import io

    return io.TextIOWrapper(io.BytesIO(data), encoding="latin-1")


def test_render_reads_and_writes_utf8_whatever_the_locale(isolated_home):
    from dashline import __main__

    # ensure_ascii=False: the bytes on stdin are UTF-8, not \u escapes.
    text = json.dumps({"model": {"display_name": "Opus ✦ café"}}, ensure_ascii=False)
    stdout = latin1()
    env = {"HOME": str(isolated_home), "NO_COLOR": "1"}
    assert __main__.render(latin1(text.encode("utf-8")), stdout, env=env) == 0
    assert stdout.buffer.getvalue().decode("utf-8").startswith("Opus ✦ café")


def test_stdin_that_isnt_utf8_still_renders(isolated_home, capsys):
    from dashline import __main__

    data = b'{"model": {"display_name": "Opus \xff\xfe"}}'
    stdout = latin1()
    env = {"HOME": str(isolated_home), "NO_COLOR": "1"}
    assert __main__.render(latin1(data), stdout, env=env) == 0
    assert stdout.buffer.getvalue().decode("utf-8").startswith("Opus \ufffd\ufffd")
    assert "Traceback" not in capsys.readouterr().err


def test_a_byte_order_mark_on_stdin_is_ignored(isolated_home):
    from dashline import __main__

    data = b"\xef\xbb\xbf" + json.dumps({"model": {"display_name": "Opus 5.5"}}).encode()
    env = {"HOME": str(isolated_home), "NO_COLOR": "1"}
    stdout = latin1()
    assert __main__.render(latin1(data), stdout, env=env) == 0
    assert stdout.buffer.getvalue().decode("utf-8").startswith("Opus 5.5")
    import io

    out = io.StringIO()  # a text stream without a buffer
    stdin = io.StringIO("\ufeff" + json.dumps({"model": {"display_name": "Opus 5.5"}}))
    assert __main__.render(stdin, out, env=env) == 0
    assert out.getvalue().startswith("Opus 5.5")


def test_closed_stdin_prints_nothing(isolated_home, capsys):
    import io

    from dashline import __main__

    out = io.StringIO()
    assert __main__.render(None, out, env={"HOME": str(isolated_home)}) == 0
    assert out.getvalue() == ""
    assert "Traceback" not in capsys.readouterr().err


def test_huge_columns_still_renders(isolated_home):
    import io

    from dashline import __main__

    out = io.StringIO()
    stdin = io.StringIO(json.dumps({"model": {"display_name": "Opus 5.5"}}))
    env = {"HOME": str(isolated_home), "NO_COLOR": "1", "COLUMNS": "9" * 5000}
    assert __main__.render(stdin, out, env=env) == 0
    assert out.getvalue().startswith("Opus 5.5")
    assert "internal error" not in out.getvalue()


def test_stray_modules_in_the_install_folder_are_never_imported(tmp_path, stdin_fixture):
    """Files the user keeps next to the installed copy can't stand in for the standard
    library: as installed (-I -S) the folder comes last on sys.path."""
    import os
    import shutil

    folder = tmp_path / "statusline"
    shutil.copytree(ROOT / "src" / "dashline", folder / "dashline")
    shutil.copy(ROOT / "statusline.py", folder / "statusline.py")
    for name in ("json", "__future__", "subprocess", "functools", "unicodedata"):
        (folder / f"{name}.py").write_text(f"raise SystemExit('stray {name}.py was imported')\n")
    cmd = [sys.executable, "-I", "-S", str(folder / "statusline.py")]
    env = {**os.environ, "NO_COLOR": "1"}

    def run(*args, stdin=""):
        return subprocess.run(
            [*cmd, *args], input=stdin, capture_output=True, text=True, timeout=30, env=env
        )

    version = run("--version")
    assert (version.returncode, version.stdout) == (0, f"dashline {__version__}\n")
    preview = run("--preview", "pro")
    assert preview.returncode == 0 and "stray" not in preview.stdout + preview.stderr
    shown = run(stdin=stdin_fixture("after-first-response"))
    assert shown.returncode == 0, shown.stderr
    assert "stray" not in shown.stdout + shown.stderr
    assert "internal error" not in shown.stdout
    assert len(shown.stdout.splitlines()) >= 2


def test_a_failed_spawn_still_prints_the_statusline(isolated_home, monkeypatch, capsys):
    import io

    from dashline import __main__, usage

    class State:
        fetch = True
        data = None
        stale_age = None

    def boom(env, now):
        raise OSError("no fork")

    monkeypatch.setattr(usage, "load", lambda env, account, now: State())
    monkeypatch.setattr(usage, "spawn", boom)
    out = io.StringIO()
    stdin = io.StringIO(json.dumps({"model": {"display_name": "Opus 5.5"}}))
    env = {"HOME": str(isolated_home), "NO_COLOR": "1"}
    assert __main__.render(stdin, out, env=env) == 0
    assert out.getvalue().startswith("Opus 5.5")
    assert "internal error" not in out.getvalue()
    assert "OSError: no fork" in capsys.readouterr().err


def test_closed_stdout_is_quiet():
    cmd = [sys.executable, "-I", "-S", str(ROOT / "statusline.py")]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    proc.stdout.close()  # Claude Code went away before reading
    _, err = proc.communicate(json.dumps({"model": {"display_name": "Opus 5.5"}}).encode())
    assert proc.returncode == 0
    assert b"Traceback" not in err


def opts(
    mode="render", glyphs=None, scenario=None, replace=False, downgrade=False, fetch_now=False
):
    return {
        "mode": mode,
        "glyphs": glyphs,
        "scenario": scenario,
        "replace": replace,
        "downgrade": downgrade,
        "fetch_now": fetch_now,
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
        (["--doctor", "--fetch-now"], opts("doctor", fetch_now=True)),
        (["--fetch-now", "--doctor"], opts("doctor", fetch_now=True)),
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
        ["--fetch-now"],
        ["--install", "--fetch-now"],
        ["--preview", "--fetch-now"],
    ],
)
def test_parse_args_rejects(argv):
    with pytest.raises(UsageError):
        parse_args(argv)


def test_mode_option_errors_name_the_mode():
    with pytest.raises(UsageError, match="--fetch-now only works with --doctor"):
        parse_args(["--fetch-now"])
    with pytest.raises(UsageError, match="--downgrade only works with --install"):
        parse_args(["--doctor", "--downgrade"])


def test_help_lists_every_flag():
    from dashline.__main__ import USAGE

    flags = ("--glyphs", "--doctor", "--fetch-now", "--install", "--replace", "--downgrade")
    for flag in (*flags, "--preview", "--version", "--help"):
        assert flag in USAGE


@pytest.mark.parametrize(
    ("value", "columns"),
    [
        ("120", 120),
        (" 90 ", 90),
        ("3000000", 1000),
        ("0090", 90),
        ("000", None),
        ("9" * 5000, 1000),  # int() refuses more than 4300 digits
        ("0" * 5000 + "80", 80),
        ("\u00b2", None),
        ("-5", None),
        ("0", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_columns(value, columns):
    from dashline.__main__ import parse_columns

    assert parse_columns(value) == columns
