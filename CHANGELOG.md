# Changelog

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
