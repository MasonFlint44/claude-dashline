# dashline

One Claude Code statusline for every kind of account: Free, Pro, Max, Ultra, Team,
Enterprise, and API-key, Bedrock, Vertex, Foundry or gateway sessions. It shows the
session (model, effort, cost, context, prompt cache), your plan's usage limits, and
where you are in git, in three lines that fit the terminal's width.

![dashline on an Ultra plan, using Fable in fast mode](docs/preview.svg)

## Install

```
/plugin marketplace add MasonFlint44/claude-toolbox
/plugin install dashline@claude-toolbox
/dashline:install
```

`/dashline:install` checks for Python, copies dashline to
`~/.claude/scripts/dashline/` (or under `$CLAUDE_CONFIG_DIR`), and points the
`statusLine` setting at it. It asks first if you already have a statusline, if
that folder holds another tool's files, or if a newer dashline is already installed
there. Updates keep any files of your own you put in that folder. On a first install
it asks which glyph set you want, recommending `nerd` for its icons, tells you how to
get a Nerd Font if your terminal doesn't seem to have one, and what to look for in the
statusline to confirm it draws correctly.

Works on macOS, Linux, Windows and WSL. Needs Python 3.9 or newer as `python3`; on
Windows, as `py -3`, `python` or `python3` (`winget install Python.Python.3.13`).
macOS's command-line tools are enough. git is optional (2.15 or newer); without it the
third line shows just the folder. Built on Linux with Claude Code 2.1.318, and for
Windows against 2.1.319; CI runs the tests on Linux, macOS and Windows.

On Windows, Claude Code runs the statusline in Git Bash, or in PowerShell if Git isn't
installed; dashline's command works in either.

## What it shows

![dashline on Pro, Team, Enterprise and API-key accounts, at a limit, and mid-rebase](docs/plans.svg)

**Line 1, the session:** model, effort level, fast mode, the agent you're talking to,
the session's cost so far (subagents included), and a context-window bar. A prompt cache
about to expire shows a countdown. Once it has gone cold, the line says why (e.g.
"tools changed") and how many tokens the next request will write back into the cache.

**Line 2, the plan:** the plan's name (and days left in a trial), then one bar per
limit: the 5-hour window, the week, a model's weekly limit (e.g. Fable) while you use
that model or once it has any use this week, extra-usage credits once you've used
some, and a Team or Enterprise monthly cap. Bars go from green through gold to coral
as they fill. From 70% on, they show when the window resets, and a limit you've hit is
a full coral bar. If the numbers are more than 5 minutes old because fetching keeps
failing, their age follows (`·12m`). API-key and cloud-provider sessions bill per use
and have no plan line; their label moves up to line 1.

**Line 3, the directory:** the project (with its worktree and the subfolder you're in),
the branch, tag or detached commit, uncommitted lines added and removed, untracked files,
commits ahead of or behind the upstream, a branch that was never pushed or whose upstream
is gone, a rebase, merge, cherry-pick, revert, bisect or `am` in progress, and
conflicts. It also shows where Claude's shell has moved to if that's outside the
project. In terminals that support links, the project name opens its folder, and a
branch pushed to GitHub opens its compare page. That includes GitHub Enterprise
(`github.<company>.com`, `<name>.ghe.com`), SSH host aliases like `github-work` or
`work.github.com`, and `insteadOf` shorthands like `gh:owner/repo`.

When the terminal is narrow, detail goes in a fixed order. Bars stay on their own
line: plan bars turn into text from the last one back (`credits 12%`), then all of
them (`5h 81%`). Line 1 keeps the context bar as wide as the plan bars while it drops
the agent and the cache detail and cuts a long model name short with `…`; only then
does the bar shrink, and it turns into text last. Line 3 drops line counts before
names. Nothing wraps.

## Glyph sets

| set | needs | looks like |
|---|---|---|
| `nerd` | a [Nerd Font](https://github.com/ryanoasis/nerd-fonts/releases/latest) for icons ("Symbols Only" is enough); Ghostty and WezTerm include one | icons for git, the branch, fast mode, the cache |
| `unicode` (default) | any modern terminal font | `⎇ main  ✎ +12  ⇡2` |
| `ascii` | nothing | `(main)  * +12  >2` |

Switch with `/dashline:install`, or try one with
`python3 ~/.claude/scripts/dashline/statusline.py --preview --glyphs nerd`
(on Windows, `py -3` or `python` in place of `python3`).

Colors follow your Claude Code theme, including custom themes. `NO_COLOR`
turns them off.

## When something's wrong

Run `/dashline:doctor`. It checks Python, the installed copy, which settings file's
statusline wins, your login, one live usage fetch, the cache, the statusline command
itself, git, the theme and fonts, then explains each problem and fixes what's safe.
Outside Claude Code: `python3 ~/.claude/scripts/dashline/statusline.py --doctor`
(on Windows, `py -3` or `python` in place of `python3`).

## How plan usage is fetched

Claude Code sends the 5-hour and weekly numbers with each response, but not the
per-model limits, credits or monthly cap. For those, dashline asks the same endpoint
Claude Code's `/usage` screen uses (`api.anthropic.com/api/oauth/usage`) with your
existing Claude login. That token is read from Claude Code's own store: the macOS
Keychain, or `~/.claude/.credentials.json`.

- The request runs in a background process after the statusline has printed, so it
  never slows the statusline.
- At most one request every 3 minutes per login, shared by all your Claude Code
  sessions, with backoff on errors. When the server asks for a longer wait
  (`Retry-After`), dashline waits that long, up to a day; `/dashline:doctor` tells you
  so and only fetches early if you say to.
- The token goes only to `api.anthropic.com`: redirects are refused, so it can't follow
  one elsewhere. It is never written anywhere, passed on a command line or put in an
  environment variable.
- The answer is cached in `~/.claude/cache/dashline/` (files only you can read; on
  Windows, as private as your user folder) and tagged
  with your account (or, with `CLAUDE_CODE_OAUTH_TOKEN`, a hash of that token), so
  switching logins never shows someone else's numbers.

The endpoint isn't documented. If it changes, the affected bars disappear until
dashline catches up; the rest of the statusline keeps working.

## Uninstall

Remove the `statusLine` entry from `~/.claude/settings.json`, delete
`~/.claude/scripts/dashline/` (and `dashline.backup` or `dashline.kept` next to
it, if `/dashline:install` set another tool's files or one of yours aside there), then
`/plugin uninstall dashline@claude-toolbox`. Delete dashline's cache,
`~/.claude/cache/dashline/`, too. With `CLAUDE_CONFIG_DIR` set, all
of these are under that folder instead of `~/.claude`. On Windows, `~` is your user
folder (`%USERPROFILE%`).

## Development

```
uv run ruff format && uv run ruff check
uv run pytest
uv run python scripts/preview.py     # redraw docs/*.svg after a visual change
uv run python scripts/preview.py --check   # the images match the scenarios
scripts/smoke.sh "$(uv python find 3.9)"   # the shipped files on Python 3.9
uv lock --check                      # uv.lock matches pyproject.toml
python3 statusline.py --preview      # every built-in scenario in your terminal
```

The design and its reasons are in [docs/PLAN.md](docs/PLAN.md).

## License

MIT. The preview images embed a few icons from
[Symbols Nerd Font](https://github.com/ryanoasis/nerd-fonts) (MIT), drawn from
[Material Design Icons](https://pictogrammers.com/library/mdi/) (Apache 2.0); see
[scripts/assets/](scripts/assets/).
