# Changelog

## 0.1.6 — 2026-11-05

A hardening release from a review of the whole project.

**Statusline**
- Odd input no longer turns the line into `internal error`. That covers `NaN` or
  `Infinity` from Claude Code or the cache, a custom theme whose `base` isn't a name,
  odd types in `.claude.json`, and a `COLUMNS` like `²`.
- Names can't break the lines or reach the terminal as escapes. Control characters
  in model, agent, plan, branch, folder and remote names show as `?`.
- A long model name (a Bedrock ARN, say) is cut with `…` instead of pushing cost and
  context off line 1.
- The context bar keeps the plan bars' width while line 1 drops the agent and the
  cache detail, so a wider terminal never shows a narrower bar. (It was 13 cells at
  81 columns and 8 at 82 with a cold cache.)
- Widths are counted in terminal columns, so CJK and emoji names (two columns each)
  no longer overflow their line.
- A window from Claude Code whose reset time has passed reads 0%, so an old 95% no
  longer shows while you're idle.
- A bar with any use says at least `1%`, never `0%` beside a filled cell.
- Output is always UTF-8, and a closed pipe no longer prints a traceback.
- A bad flag in the settings command shows an error on the statusline instead of
  leaving it blank.

**Plan usage**
- A cut-off answer, or any other failure, now backs off instead of refetching on
  every render.
- Redirects are refused, so the token can't follow one to another host.
- The server's `Retry-After` is followed, in seconds or as a date, up to a day.
- Two sessions can no longer both break a stale fetch lock, and a fetch only
  releases its own lock.
- A clock set back (NTP, a restored VM) no longer freezes fetching.
- With `CLAUDE_CODE_OAUTH_TOKEN`, cached usage is tagged by that token, not by
  `.claude.json`'s login.

**Directory row**
- A hung git hook can't stall the render: git and anything it starts are killed at
  the 1 s timeout. Repo fsmonitor hooks don't run, and submodule edits don't count.
- No "never pushed" mark while rebasing a pushed branch.
- `GIT_INDEX_FILE` and similar variables inherited from a git hook or editor are
  ignored.
- Symlinked projects are found, with no false "shell moved" path.
- An interrupted cherry-pick or revert sequence shows.
- A remote written with a git `insteadOf` shorthand (`gh:owner/repo`) gets its
  GitHub link.
- Line counts work on a branch with no commits in a SHA-256 repo.
- `HOME=/` no longer turns every path into `~/…`.
- A narrow row shortens the branch, then gives up the worktree and subfolder,
  instead of cutting the line.

**Install and doctor**
- Install changes nothing when it stops to ask. It won't overwrite a
  `scripts/statusline/` folder that holds another tool's files: `--replace` moves
  them to `statusline.backup`.
- A hand-edited command (say, a full path to Python) is kept; only `--glyphs`
  changes.
- Install asks before replacing a newer installed copy with an older one (exit 4;
  `--downgrade` goes ahead).
- If the swap fails, the old copy is put back. Folders left by an interrupted
  install are removed.
- A BOM in settings.json is handled. Read-only or non-UTF-8 settings are refused,
  and an unknown `--glyphs` value is dropped.
- Doctor names the file to edit when a project, local or managed settings file
  wins. It tells a missing script from a missing Python and quotes its `chmod` fix.
  It follows settings precedence for `disableAllHooks`, and says so when the
  installed copy is newer than the plugin instead of suggesting a downgrade. It
  explains refused redirects and failed fetches.
- The install skill runs doctor once, not twice.

**Development**
- Tests can't reach the real usage endpoint: every subprocess gets a dead proxy, and
  a check fails any test that starts one without it.
- CI actions are pinned to Node 24 releases by commit, with a read-only token.

## 0.1.5 — 2026-11-05

- Plan bars stay on line 2. In a narrow terminal, the last bar turns into text
  (`credits 12%`) instead of moving up to line 1, then the rest do. Line 1 keeps just
  the session, and the context bar no longer shrinks to make room for a plan bar. It
  turns into text only when line 1 itself is too narrow.

## 0.1.4 — 2026-11-05

- A model's weekly bar (e.g. `Fable`) also shows on other models once it has any use
  this week, since subagents and other sessions spend it. Unused, it still shows only
  while you're on that model.

## 0.1.3 — 2026-11-05

- The context bar is the same width as the plan bars (it was twice as wide), so all
  bars scale together.

## 0.1.2 — 2026-11-05

- Bars scale with the terminal instead of stopping at 24 cells (48 for context). Plan
  bars share line 2's free space, a third each at most, so three bars fill the row;
  the context bar is up to twice a plan bar.
- A limit you've hit is a full coral bar with its percent and countdown
  (`100% (1h12m)`) instead of the `limit · resets` text.

## 0.1.1 — 2026-11-05

- `--doctor` no longer warns about a cache folder other users can list. It checks
  dashline's own files, which are always written readable only by you; the folder may
  belong to another tool.

## 0.1.0 — 2026-11-04

First release.

- Lines 1–2 from Claude Code's input: model, effort, fast mode, agent, cost, context bar,
  prompt-cache state, and the 5h / 7d bars, fitted to the terminal width without wrapping.
- Colors from the active Claude Code theme (built-in, `auto`, custom), `NO_COLOR` honored.
- `--glyphs nerd|unicode|ascii`.
- Plan bars from the usage endpoint: `5h`, `7d`, the model-scoped bar for the current
  model (e.g. `Fable`, shown even at 0%), `credits` once used, Team / Enterprise
  `month`, and any new kind of limit by its name. Fetched in a detached background
  process at most every 3 minutes across all sessions, with backoff on errors.
- Plan label from Claude Code's cached profile (Ultra, Max, Pro, Team, Enterprise),
  `trial 5d` during a trial; `API`, `Bedrock`, `Vertex`, `Foundry` or `Gateway` without
  a subscription.
- `limit · resets 2h10m` when a limit blocks you, and the data's age (`·12m`) when the
  fetch keeps failing.
- Line 3, the directory row: project (with worktree and subfolder), branch, tag or
  detached commit, uncommitted `+lines −lines`, untracked, ahead / behind / diverged,
  never pushed, upstream gone, rebase / merge / cherry-pick / revert / bisect / am in
  progress, conflicts, and where Claude's shell has wandered. Fits narrow terminals by
  dropping detail in a fixed order.
- Clickable project folder and, on GitHub, branch (its compare page).
- `--preview [SCENARIO|all]`: ten built-in scenarios (Pro trial, Pro, Ultra on Fable,
  Team, Enterprise, API key, limit reached, rebase, two narrow widths) with fake data.
- `--doctor`: checks Python, the installed copy, settings, login, the usage endpoint,
  the cache, the statusline command itself, git, theme and font, with a fix for each
  problem.
- `--install [--replace]`: copies dashline into the config folder and points
  settings.json at it, without replacing another statusline unless asked.
- `/dashline:install` and `/dashline:doctor` skills.
