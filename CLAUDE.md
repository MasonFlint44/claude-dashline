# claude-dashline

`dashline` is one Claude Code statusline for every account type (Free, Pro, Max, Ultra,
Team, Enterprise, API key / gateway). A Python package under `src/dashline/`, an entry
shim `statusline.py`, and (Phase 6) install and doctor skills under `skills/`.
`docs/PLAN.md` is the design and is canon: settled decisions there are not reopened
without the author.

## Verify before committing

```
uv run ruff format
uv run ruff check
uv run pytest
uv run --isolated --python 3.9 pytest   # oldest supported; CI runs 3.9 / 3.12 / 3.14
```

## Rules

- Runtime is the standard library only, Python ≥ 3.9: `from __future__ import
  annotations`, no `match`, no `dataclass(slots=...)`. Dev tools (ruff, pytest) live in
  the uv dev group and never become runtime imports.
- A render must stay fast (budget 40 ms with a warm cache): imports are lazy, inside the
  functions that need them, and the render path uses `os.path`, not `pathlib`.
- The statusline never shows a traceback. `__main__.render` catches everything and
  prints a one-line error; the traceback goes to stderr.
- The OAuth token stays in-process: never in argv, an environment variable, a file or a log.
- Tests never reach the real endpoints. Fetch tests use a local `http.server`; pure
  functions take `now` and `columns` as arguments.
- dashline knows nothing about any other statusline plugin: no migration code, no
  references to them.
- `__version__`, `.claude-plugin/plugin.json` and `pyproject.toml` carry the same
  version; `tests/test_cli.py` checks it.

## Conventions

- Commits end with a `Co-Authored-By: Claude <model> <noreply@anthropic.com>` line and
  nothing else. No session-link trailer: the repository will be public.
- Commit only when the author asks.
