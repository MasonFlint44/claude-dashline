---
name: doctor
description: Diagnose and fix the dashline statusline — run its checks, explain each problem in plain words, and apply the safe fixes. Use when the user runs /dashline:doctor, or says the statusline is missing, blank, stuck, out of date, shows "internal error", shows no plan bars (5h / 7d / credits / month) or an old age tag like ·12m, shows the wrong plan, or looks wrong; or asks whether dashline is working.
---

# dashline doctor

Below, `DASHLINE` stands for `python3 -I -S "${CLAUDE_PLUGIN_ROOT}/statusline.py"`.
On Windows (not WSL), use the first of `py -3`, `python` or `python3` that runs Python
3.9 or newer in place of `python3`. To tell them apart: in Claude's shell `uname -s` prints `MINGW…` or `MSYS…` on Windows (Git Bash) and
`Linux` in WSL. Where `uname` isn't found, the shell is PowerShell: that's Windows too.
Running it from the plugin lets doctor compare the installed copy with this version.

## 1. Run it

Run `DASHLINE --doctor` once. It checks each part in order and prints one line per
check: `ok`, `warn`, `fail` or `info`, the check's name, and what it found. Any problem
has a `fix:` line under it. It exits 1 if anything failed, and 2 on a usage error
(relay its message; nothing was checked).

Doctor fetches plan usage once, the way the statusline's background fetch does, so it
retries now instead of waiting out dashline's own backoff. The exception: when the
server asked dashline to wait, doctor doesn't fetch, and its `usage` line says
`server asked to wait` and until when (see §3). `--fetch-now` makes it fetch anyway.

Each run is a live request, so run doctor at most twice per request from the user:
once, and once more after applying fixes from §3. Never in a loop. If the `usage` line
says `a fetch is running`, a background fetch held the lock: tell the user, and don't
run doctor again just for that (the second run, if any, still counts).

## 2. Report

Start with the outcome in one line: all good, or which parts fail. Then for each
`warn` and `fail`, say what it means and what you'll do or what the user needs to do.
Skip the `ok` lines unless the user asked about one. Never show the user's token or
credentials, and don't read the credentials file.

What the checks mean:

| check | what it covers |
|---|---|
| `python` | the Python running doctor; the statusline runs the Python its command names (`python3`, or on Windows `py -3`, `python` or `python3`) from the PATH Claude Code sees |
| `install` | the copy in `<config>/scripts/statusline/` and whether it matches this plugin version |
| `settings` | which settings file's `statusLine` wins, and whether it runs dashline; `disableAllHooks` |
| `login` | subscription vs API key / Bedrock / Vertex / Foundry; where the token comes from |
| `usage` | one live fetch of plan usage (none while the server asked to wait): the bars it would draw, or why it failed |
| `cache` | `<config>/cache/statusline/`: writable, dashline's files private, when last fetched, fetch lock |
| `command` | runs the exact settings command on a sample session, like Claude Code does |
| `git` | git for the directory row (2.15 or newer) |
| `theme` | the Claude Code theme whose colors the statusline uses |
| `font` | whether Nerd Font icons are likely to render, and the glyph set in use |

## 3. Fix what's safe

After applying any of these, run doctor once more to confirm (§1: no more than that).

Do this without asking, only when the `settings` line is `ok` (or warns only about
`refreshInterval`) AND names the user settings file: `~/.claude/settings.json`, or
`settings.json` in `$CLAUDE_CONFIG_DIR`. When it names a project or managed file, ask
first (next list): `--install` writes the user file, which would turn dashline on in
every other project too.
- `install` warns that the copy is old or differs, `command` says its statusline.py is
  missing or its fix says install `rewrites this command for Windows`, or `settings`
  warns that there's no `refreshInterval`: run `DASHLINE --install`. With the entry already dashline's, it updates the copy and
  keeps the command and glyph set as written. If it exits 3 or 4 anyway, stop and
  handle it as in the ask-first list below.
  Not when `install` says the installed copy is newer than this one: that means this
  plugin is out of date, so tell the user to update it (`/plugin`) instead.

Ask first (AskUserQuestion), and act only on a yes:
- `settings` isn't `ok` because user settings.json has no statusLine or one that runs
  another statusline, or `install` fails with `nothing installed`: run
  `DASHLINE --install`. It copies dashline and writes the statusLine entry, which turns
  the statusline on, so the user may have removed it on purpose. If it exits 3, show
  what its output says is there (the existing entry, or another tool's files in
  `scripts/statusline/`) and ask before `DASHLINE --install --replace`. If it exits 4,
  the installed copy is newer than this plugin: recommend updating the plugin
  (`/plugin`), and only on an explicit yes run `DASHLINE --install --downgrade`.
- `usage` says `server asked to wait`: the server turned the usage request away and
  said when to come back (usually a rate limit); dashline waits until then on its own, and the statusline
  keeps the last numbers meanwhile. Tell the user when it will retry and the reason
  doctor gives, then ask whether to try now anyway (recommend waiting). Only on a yes,
  run `DASHLINE --doctor --fetch-now`, once; it counts as the one re-run. If it's still
  refused, stop: don't retry.
- `cache` says other users can read one of its files: run the `chmod 600` in its `fix:` line.
  (Windows has no such check: files there take the profile folder's access.)
- `command`'s fix says the command's `$`-variables are Bash and `--replace` writes the
  Windows command (Windows only: a command the user edited, which PowerShell can't
  run): show the user the command and ask before `DASHLINE --install --replace`.
- `command` warns that `its symbols came back changed` (Windows, PowerShell on a
  system whose code page lacks them): ask whether to switch to `ascii` glyphs
  (`DASHLINE --install --glyphs ascii`) or to install Git for Windows, so Claude Code
  runs the statusline in Git Bash (then restart Claude Code).
- `settings` warns that `--glyphs <x> isn't a glyph set` (a typo like `Nerd`): don't
  reset it to unicode. Run the glyph step of `/dashline:install` (the preview, then the
  user picks), then `DASHLINE --install --glyphs <set>`. If that exits 1 saying it
  can't change `--glyphs` automatically, show the user the edit its message gives;
  editing settings.json is theirs to do.

Explain, and leave to the user:
- `settings` says a project file (`.claude/settings.json`, `settings.local.json`) or
  managed settings wins: `--install` only writes user settings, so it can't help, and
  doctor's `fix:` line says what can. A project's statusLine is the user's to remove;
  managed settings only an administrator can change.
- `disableAllHooks`: it turns off hooks too, so removing it is the user's decision.
- `login` / `usage` asking for `/login` (also after a 401 or 403 where the server
  asked to wait: follow the `fix:` line): only the user can sign in. A 403 with
  `CLAUDE_CODE_OAUTH_TOKEN` set means a `claude setup-token` token, which can't read
  plan usage. The statusline still works; only the plan bars are missing.
- `login` / `usage` saying `the macOS Keychain is locked or denied access`: relay
  doctor's fix (unlock the login Keychain, and allow access if macOS asks). `/login`
  won't help.
- `git` fails as too old (dashline needs 2.15 or newer): relay its fix; updating git is
  the user's call. Until then the directory row shows the folder only.
- `usage` network failures: the statusline keeps the last numbers (marked with their
  age) and retries on its own. Point at proxy settings (`HTTPS_PROXY`) only if the user
  is behind one.
- `usage` says `redirect refused`: api.anthropic.com doesn't redirect, so a proxy or
  network is rewriting the request; dashline won't follow it with the token. Point at
  `HTTPS_PROXY` or the network.
- `usage` says `fetch failed (…)`: the answer broke off or was malformed. It retries on
  its own; worth reporting only if it keeps happening.
- An expired token (`warn`): Claude Code renews it on its next request. No action
  needed.
- `command` failing with `python3` not found (on Windows, also `is not recognized`):
  Claude Code's PATH lacks the Python the command names. The user can install Python
  (see `/dashline:install` step 1) or, on macOS and Linux, edit the command to use a
  full path to Python 3.9+; `--install` keeps that edit. On Windows no full path with
  spaces runs in both Git Bash and PowerShell, so there the fix is Python on PATH and a
  restart of Claude Code, as the `fix:` line says.
- `command` failing because `a policy on this PC blocks` Python (AppLocker, Software
  Restriction): only whoever manages the PC can allow it.
- `command` slow: usually a large git repo or slow disk. Mention it, nothing to fix.
  On Windows the line also names the shell it ran in (Git Bash, or PowerShell or
  PowerShell 7 when Git Bash isn't installed); starting the shell is part of the time.
- Icons showing as boxes or `?`, or the user wants icons: run the glyph step of
  `/dashline:install`.
- API key, Bedrock, Vertex, Foundry or a gateway: no plan bars is expected, because
  those bill per use.

## 4. Nothing failed but it still looks wrong

Ask what they see, and compare it with
`! python3 -I -S "${CLAUDE_PLUGIN_ROOT}/statusline.py" --preview` (write in the real
path, and on Windows the Python from above), which shows how each plan should look. Things to know:
- The `·12m` style tag after the plan bars means the numbers are that old: fetches are
  failing, and the `usage` line says why.
- Bars are hidden when the terminal is too narrow and turn into short text instead.
- A project's `.claude/settings.json` or `settings.local.json` can set its own
  statusLine that wins over the user's; the `settings` line names the file in use.
