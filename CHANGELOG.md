# Changelog

## 0.2.0 — 2026-11-07

**Windows**
- dashline now runs on Windows itself, not only in WSL. Claude Code runs the statusline
  there in Git Bash, or in PowerShell when Git isn't installed, and the command
  `/dashline:install` writes works in both: a Python by name (`py -3`, `python` or
  `python3`, whichever runs Python 3.9 or newer) and the full path to the copy, in
  forward slashes. With no such Python, the install stops and says how to get one;
  with a `$` or `` ` `` in that path, which both shells would expand, it stops too.
- An entry still running the command older versions wrote, which only Git Bash can
  run, is rewritten that way by `/dashline:install`, with its glyph set kept. A command
  you edited yourself is kept as written.
- The statusline's output is UTF-8, as Claude Code reads it (Python there writes a
  pipe in the ANSI code page, which has no bars or `│`); so is doctor's and install's.
- Your home folder is `%USERPROFILE%`, as Claude Code has it.
- Paths in the statusline and in doctor's and install's messages use `/`, which both
  shells read.
- The project name links to its folder as `file:///C:/…`, which Windows Terminal opens,
  or `file://server/share/…` on a network share or `\\wsl.localhost`.
- A git command that hangs is ended along with everything it started, so the
  statusline isn't held up.
- A file another program has open for a moment (settings.json while Claude Code writes
  it, the cache while a render reads it, a fresh copy an antivirus is scanning) no
  longer fails an install or a fetch: dashline tries again briefly. The background
  fetch no longer runs from the install folder, which Windows then wouldn't let an
  update replace.
- Two renders taking the fetch lock at once no longer trip over Windows' "permission
  denied" for a lock that's being removed.
- settings.json keeps `\n` line endings when `/dashline:install` rewrites it.
- A `CLAUDE_CONFIG_DIR` spelled in another case is still recognized as the same folder.
- `/dashline:doctor` runs the statusline command in the shell Claude Code would use
  (it finds Git Bash from inside Git Bash too) and names it, and allows Windows' slower
  shell start before calling the command slow. It reads PowerShell's wrapped error
  messages for the real reason and fix. It skips the file-permission check, which
  doesn't apply there.
- The install and doctor skills find Python on Windows (`py -3`, `python`, `python3`)
  and tell Windows from WSL; the install skill says how to get Python
  (`winget install Python.Python.3.13`).

**CI**
- The tests run on Windows too, and the Python 3.9 smoke test runs on Windows in Git
  Bash.

## 0.1.10 — 2026-11-06

**Install**
- `/dashline:install` now recommends the nerd glyph set every time, for its icons. When
  your terminal doesn't seem to have a Nerd Font, it says so and gives the one-line
  install along with what to check.
- On Windows and WSL, the font advice is Cascadia Code NF, the Nerd Font version of
  Windows Terminal's own Cascadia, installed on Windows and picked as the profile's
  font face. Before, WSL got the Linux command, which installs a font the terminal
  never sees.

**Doctor**
- The `font` check looks in Windows' font folders under WSL and on Windows (system-wide
  and your own), instead of in Linux's.
- Cascadia Code NF and Cascadia Mono NF count as Nerd Fonts.

**Statusline**
- On WSL, the project name links to `file://wsl.localhost/<distro>/…`, so clicking it
  in Windows Terminal opens the folder in Explorer. Windows Terminal ignores the
  `file://<hostname>/…` link used before.

## 0.1.9 — 2026-11-06

**Install**
- Picking a glyph set no longer needs a preview command. On a first install,
  `/dashline:install` offers nerd, unicode and ascii with a one-line description each,
  recommends one from what your terminal has, and tells you what to look for in the
  statusline itself (with nerd, the git or folder icon on line 3). A plain update keeps
  your set without asking. The side-by-side preview is still there if you want to
  compare first.

## 0.1.8 — 2026-11-06

Fixes from a third review, mostly of 0.1.7's new code.

**Install**
- Switching glyph sets no longer breaks a hand-edited command such as
  `bash -lc '…statusline.py'` or one behind a `[ -f … ]` guard. Where `--glyphs` can't
  be placed safely, install changes nothing and shows the edit to make by hand.
- An odd escape in settings.json (`"\ud83d"`) no longer crashes install after it has
  copied files, and deeply nested settings read as invalid JSON.
- Any failure during `--replace`, Ctrl-C included, puts the other tool's files back.
- Your own files in `scripts/statusline/` are moved into each update instead of copied,
  so an unreadable file or a pipe no longer blocks updates and a big folder isn't
  copied every time. One that can't be moved is kept in `scripts/statusline.kept`.
- A symlinked install folder (a dotfiles setup, say) stays a link.

**Doctor**
- Doctor waits for a background fetch that's already running instead of fetching
  beside it.
- A server-asked wait after a 401 or 403 now points to `/login`, not `--fetch-now`.
- The command check shows the error even when the command sends stderr away, and a
  `NaN` fetch time no longer breaks the cache check.
- The skill only skips asking when your user settings run dashline, and handles an
  unknown glyph set, a locked Keychain, a running fetch and an old git.

**Plan usage**
- An error the fetch didn't foresee no longer prints a thread traceback or reads as a
  network failure, and a timeout says "no answer within 30 s".
- Another tool's `usage.json` or `fetch.hold` in the shared cache folder is no longer
  deleted or reported, and dashline's own leftover `.tmp` files are cleaned up.
- A stray module kept in the install folder can't break the background fetch.
- `.claude.json` is found through the given home folder, and a deeply nested one no
  longer shows `internal error`.

**Statusline**
- A stray `.py` file in the install folder can't stand in for a standard-library module.
- Deeply nested settings no longer show `internal error` on Python 3.9–3.13.
- A `COLUMNS` value thousands of digits long, a byte-order mark on stdin, and a closed
  stdin are handled.
- Flags are never cut in half, decomposed Korean names measure correctly, and the trial
  countdown stops at 999 days.

**Directory row**
- git 2.15 or newer is needed. Older git shows the folder alone, because it can't run
  `git status` without taking the index lock, which could make your `git commit` fail.
- GitHub links for remotes without `git@` (`github-work:o/r`), `ssh.github.com` and
  `<name>.github.com` aliases. `github.com-mirror.corp.example` no longer links to
  github.com, and wiki clones get no link.
- An emptied `.git` folder no longer passes for a repo, the search stops at mount points
  as git's does, and an odd `GIT_CONFIG_NOSYSTEM` no longer prints a traceback.

**Development**
- The tests run on Python 3.10 and newer, since pytest has dropped 3.9; dashline
  itself still supports 3.9. A new `scripts/smoke.sh` checks that on Python 3.9 and on
  Apple's `/usr/bin/python3` (every module imports, preview, install, render, doctor),
  and fails on a broken render.
- pytest and fonttools are marked 3.10+, so Dependabot's weekly updates no longer fail.
- A queued CI run on main is no longer cancelled.
- `capture_fixtures.py` keeps only strings known to be safe and lists money amounts for
  review.
- CLAUDE.md lists every check CI runs; `.gitignore` covers agent worktrees.

## 0.1.7 — 2026-11-06

Fixes from a second review of the whole project.

**Plan usage**
- Each login has its own usage cache and backoff. Two logins in use at once (say,
  `CLAUDE_CODE_OAUTH_TOKEN` in one session) no longer refetch over each other on every
  render or clear each other's `Retry-After`. 0.1.6's `usage.json` and `fetch.hold` are
  removed on the next fetch.
- Two sessions rendering together can't start a second fetch: the fetch checks the
  cache again once it holds the lock.
- `Retry-After` also stretches the waits after a 401, 403 or 404.
- A request has 30 s in all, DNS included, so a server trickling bytes can't keep a
  fetch alive past its lock.
- A locked or denied macOS Keychain is reported as such, instead of "no login" with
  advice to `/login`.
- A deeply nested answer counts as unreadable instead of failing oddly.

**Doctor**
- While the server has asked dashline to wait, doctor says until when and doesn't
  fetch. `--doctor --fetch-now` fetches anyway, and the skill asks you first.
- A command naming an unknown glyph set (`--glyphs Nerd`) gets a clear warning, and a
  failing command shows its error instead of the last line of the help.
- The skill no longer turns a statusline you removed back on without asking. The
  install and doctor skills agree on re-running doctor: once after fixes, never in a
  loop.

**Install**
- A failed `--replace` moves the other tool's files back instead of leaving your
  statusline broken.
- A read-only config folder is caught before anything is copied.
- The temporary settings file is never readable by others, even for a moment.
- In a hand-edited command with a shell tail (`… 2>/dev/null || echo x`), `--glyphs`
  goes right after the script path instead of at the very end.
- Updates keep files you added to `scripts/statusline/`, and a stray `.DS_Store` or
  `Thumbs.db` no longer makes the folder look like another tool's.

**Statusline**
- Input is read as UTF-8 whatever the system locale, so `Opus ✦` or a folder named
  `café` no longer turns into mojibake; invalid bytes show as `�` instead of
  `internal error`.
- Absurd numbers stay short: percents stop at 999%, countdowns at 999 days, token
  counts at 999.0M, cost at $99999.99. A negative cost or token count reads as missing.
- Emoji written with VS16 (❤️, ⚠️) count as two columns, and cutting text never splits
  one. A wide character that doesn't fit no longer lets a narrow one from the next
  piece slip in.
- `--preview` with an odd `COLUMNS` (`²`, `3000000`) no longer crashes or prints
  megabytes.
- Very deeply nested input, and a path containing a NUL byte, read as bad input
  instead of `internal error`.
- The entry script takes its folder back off Python's import path, so a stray `.py`
  file there can't stand in for a standard-library module.

**Directory row**
- A rebase of a detached commit no longer shows `local`.
- git 2.11–2.14 shows git state again (`--no-optional-locks` made it fail), and git
  2.16–2.35 no longer runs the program `false` on every render.
- GitHub links for SSH host aliases (`git@github-work:o/r`, `github.com-work`),
  `www.github.com` and GitHub Enterprise Cloud (`<name>.ghe.com`).
- Reftable repos (git 2.45+) get the compare link and gone-upstream detection.
- `GIT_CEILING_DIRECTORIES` is respected, and `GIT_CONFIG_NOSYSTEM=0` no longer counts
  as set.
- The folder link no longer imports `urllib`, about 2 ms off each render.

**Development**
- Tests no longer pick up your proxy, provider or git settings (a global
  `commit.gpgsign`, a pre-commit hook's `GIT_INDEX_FILE`), and on macOS never query
  your login Keychain. The hung-hook test now checks something on macOS too.
- CI checks `uv.lock` is current (`--locked`), has job timeouts, cancels superseded PR
  runs, runs once per PR, smoke-tests Apple's `/usr/bin/python3`, and Dependabot keeps
  the pinned actions current.
- `scripts/capture_fixtures.py` refuses redirects (it would have sent the token to a
  redirect's host) and scrubs every id, not just UUIDs.
- `.gitignore` covers coverage output, `.DS_Store` and captured fixtures.

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
