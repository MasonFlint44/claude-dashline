"""--preview: every scenario renders, fits its width, and honors NO_COLOR."""

import io
import re

import pytest

from conftest import ANSI
from dashline import layout, preview

SGR = re.compile(r"\x1b\[")
NAMES = list(preview.scenarios())


def run(*args, env=None):
    out = io.StringIO()
    code = preview.run(*args, env={"COLUMNS": "120", **(env or {})}, out=out)
    return code, out.getvalue()


def test_plan_scenarios_present():
    for name in ("pro-trial", "pro", "ultra-fable", "team", "enterprise", "api", "narrow",
                 "rebase", "limit", "tiny"):  # fmt: skip
        assert name in NAMES


@pytest.mark.parametrize("glyph_set", ["nerd", "unicode", "ascii"])
@pytest.mark.parametrize("name", NAMES)
def test_scenario_fits_its_width(name, glyph_set):
    code, text = run(name, glyph_set)
    assert code == 0
    fixed = preview.scenarios()[name][5]
    lines = [ANSI.sub("", line) for line in text.splitlines()]
    assert 2 <= len(lines) <= 3
    for line in lines:
        assert line.startswith(preview.INDENT)
        assert len(line) <= (fixed or 120) - layout.RESERVE + len(preview.INDENT)


def test_all_scenarios_with_headers():
    code, text = run(None, "unicode")
    assert code == 0
    plain = ANSI.sub("", text)
    for name in NAMES:
        assert f"\n{name}: " in "\n" + plain
    assert run("all", "unicode") == (code, text)


def test_no_color_means_no_color_codes():
    _, text = run(None, "nerd", env={"NO_COLOR": "1"})
    assert not SGR.search(text)


def test_color_by_default():
    _, text = run("pro", "unicode")
    assert SGR.search(text)


def test_unknown_scenario(capsys):
    code, text = run("nope", "unicode")
    assert code == 2
    assert text == ""
    assert "pro-trial" in capsys.readouterr().err


def test_trial_label_uses_the_set_separator():
    _, text = run("pro-trial", "ascii", env={"NO_COLOR": "1"})
    assert "Pro / trial 5d | 5h" in text


def test_preview_reads_nothing(isolated_home, monkeypatch):
    """No account, network or git: the subprocess module is never touched."""
    import subprocess

    def boom(*a, **k):
        raise AssertionError("preview ran a process")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    assert run(None, "nerd")[0] == 0


def test_shim_preview():
    from test_cli import run_shim

    r = run_shim("--preview", "api", "--glyphs", "ascii")
    assert r.returncode == 0
    assert "API" in r.stdout
