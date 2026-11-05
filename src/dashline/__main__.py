"""Command line: render from stdin, or one of the --doctor / --preview / --version modes.

Imports stay inside the functions so a render only pays for what it uses.
"""

from __future__ import annotations

import sys

GLYPH_SETS = ("nerd", "unicode", "ascii")

USAGE = """\
usage: statusline.py [--glyphs SET] [--doctor | --preview [SCENARIO] | --version | --help]

With no mode, reads Claude Code's statusline JSON on stdin and prints the status lines.

  --glyphs SET         nerd, unicode (default) or ascii
  --doctor             check the install, credentials, endpoints and cache
  --preview [SCENARIO] render built-in scenarios with fake data
  --version            print the version
  --help               show this help
"""


class UsageError(Exception):
    pass


def parse_args(argv: list[str]) -> dict:
    """Parse argv into {"mode", "glyphs", "scenario"}. Raises UsageError."""
    opts = {"mode": "render", "glyphs": "unicode", "scenario": None}
    modes = {"--doctor": "doctor", "--preview": "preview", "--version": "version", "--help": "help"}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "-h":
            arg = "--help"
        if arg.startswith("--glyphs"):
            if "=" in arg:
                value = arg.split("=", 1)[1]
            else:
                i += 1
                if i >= len(argv):
                    raise UsageError("--glyphs needs a value: nerd, unicode or ascii")
                value = argv[i]
            if value not in GLYPH_SETS:
                raise UsageError(f"unknown glyph set {value!r}: use nerd, unicode or ascii")
            opts["glyphs"] = value
        elif arg in modes:
            if opts["mode"] != "render":
                raise UsageError(f"{arg} can't be combined with --{opts['mode']}")
            opts["mode"] = modes[arg]
            if arg == "--preview" and i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                i += 1
                opts["scenario"] = argv[i]
        else:
            raise UsageError(f"unknown argument {arg!r}")
        i += 1
    return opts


def main(argv: list[str] | None = None) -> int:
    try:
        opts = parse_args(sys.argv[1:] if argv is None else argv)
    except UsageError as e:
        sys.stderr.write(f"dashline: {e}\n\n{USAGE}")
        return 2

    mode = opts["mode"]
    if mode == "help":
        sys.stdout.write(USAGE)
        return 0
    if mode == "version":
        from dashline import __version__

        print(f"dashline {__version__}")
        return 0
    if mode == "doctor":
        from dashline import doctor

        return doctor.run(glyphs=opts["glyphs"])
    if mode == "preview":
        from dashline import preview

        return preview.run(opts["scenario"], glyphs=opts["glyphs"])
    return render(sys.stdin, sys.stdout, glyphs=opts["glyphs"])


def render(stdin, stdout, glyphs: str = "unicode", env=None, now: float | None = None) -> int:
    """Render the status lines. Never fails loudly: Claude Code shows stdout verbatim."""
    state = None
    try:
        import os
        import time

        from dashline import account, layout, theme, usage
        from dashline import glyphs as glyph_sets
        from dashline import stdin as stdin_mod

        env = os.environ if env is None else env
        now = time.time() if now is None else now
        session = stdin_mod.load(stdin.read())
        if session.model is None:
            return 0  # not Claude Code's input: nothing to show
        glyph_set = glyph_sets.get(glyphs)
        palette = theme.load(session.project_dir, env)
        acct = account.load(env, session)
        state = usage.load(env, acct, now)
        columns = env.get("COLUMNS", "")
        lines = layout.render(
            session,
            glyph_set,
            palette,
            int(columns) if columns.isdigit() else None,
            now,
            usage.plan_bars(session, acct, state.data, now),
            account.label_text(acct, glyph_set, now),
            state.stale_age,
        )
    except Exception:  # the statusline must never show a traceback
        import traceback

        traceback.print_exc(file=sys.stderr)
        lines = ["dashline: internal error (run statusline.py --doctor)"]
    if lines:
        stdout.write("\n".join(lines) + "\n")
        stdout.flush()
    if state is not None and state.fetch:
        try:  # after the output, so Claude Code never waits on it
            usage.spawn(env, now)
        except Exception:
            import traceback

            traceback.print_exc(file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
