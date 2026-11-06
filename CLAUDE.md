# claude-dashline

`dashline` is one Claude Code statusline for every account type (Free, Pro, Max, Ultra,
Team, Enterprise, API key / gateway). A Python package under `src/dashline/`, an entry
shim `statusline.py`, and the install and doctor skills under `skills/`.
`docs/PLAN.md` is the design and is canon: settled decisions there are not reopened
without the author.

## Verify before committing

```
uv run ruff format
uv run ruff check
uv run pytest
scripts/smoke.sh "$(uv python find 3.9)"   # the shipped files on the oldest supported Python
uv run python scripts/preview.py --check   # the README images match the scenarios
uv lock --check                            # uv.lock matches pyproject.toml
```

CI runs the tests on 3.10 / 3.12 / 3.14 (pytest has dropped 3.9), and `scripts/smoke.sh`
on Python 3.9 and on macOS with Apple's `/usr/bin/python3`.

## Rules

- Runtime is the standard library only, Python ≥ 3.9: `from __future__ import
  annotations`, no `match`, no `dataclass(slots=...)`. Dev tools (ruff, pytest, and
  fonttools for `scripts/preview.py`) live in the uv dev group and never become runtime
  imports; pytest and fonttools are marked 3.10+, so Dependabot can raise them freely.
- A render must stay fast (budget 40 ms with a warm cache): imports are lazy, inside the
  functions that need them, and the render path uses `os.path`, not `pathlib`.
- The statusline never shows a traceback. `__main__.render` catches everything and
  prints a one-line error; the traceback goes to stderr.
- The OAuth token stays in-process: never in argv, an environment variable, a file or a log.
- Tests never reach the real endpoints. Fetch tests use a local `http.server`; pure
  functions take `now` and `columns` as arguments. `tests/conftest.py` gives every test
  a throwaway home, clears token, provider and proxy variables, fails any subprocess
  started without the dead `HTTPS_PROXY`, and stubs the macOS `security` command.
- dashline knows nothing about any other statusline plugin: no migration code, no
  references to them.
- `__version__`, `.claude-plugin/plugin.json`, `pyproject.toml` and the newest
  `CHANGELOG.md` entry carry the same version; `tests/test_cli.py` checks it. Run
  `uv lock` after a bump so `uv.lock` follows.

## Releasing

1. Add a `## X.Y.Z — YYYY-MM-DD` section to `CHANGELOG.md` and set the version in the
   four places above (`uv lock` after).
2. Run the checks above, commit, push, and wait for CI to pass on that commit.
3. `git tag -a vX.Y.Z -m "dashline X.Y.Z"` on it, push the tag, and
   `gh release create vX.Y.Z` with the changelog section as the notes.
4. Ship it: the marketplace (`~/git/claude-toolbox`) pins each plugin to a release tag
   and its commit, so nothing reaches users until it's re-pinned. There, run
   `scripts/pin.sh dashline vX.Y.Z`, then commit and push.

## Conventions

- Commits end with a `Co-Authored-By: Claude <model> <noreply@anthropic.com>` line and
  nothing else. No session-link trailer: the repository is public.
- Commit only when the author asks.
