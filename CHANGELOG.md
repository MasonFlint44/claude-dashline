# Changelog

## Unreleased

- Project skeleton: package layout, entry shim, ruff + pytest under uv, CI.
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
