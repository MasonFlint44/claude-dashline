---
name: doctor
description: Diagnose and fix the dashline statusline — run its checks, explain each problem in plain words, and apply the safe fixes. Use when the user runs /dashline:doctor, or says the statusline is missing, blank, stuck, out of date, shows "internal error", shows no plan bars (5h / 7d / credits / month) or an old age tag like ·12m, shows the wrong plan, or looks wrong; or asks whether dashline is working.
---

# dashline doctor

Below, `DASHLINE` stands for `python3 -I -S "${CLAUDE_PLUGIN_ROOT}/statusline.py"`.
Running it from the plugin lets doctor compare the installed copy with this version.

## 1. Run it

Run `DASHLINE --doctor` once. It checks each part in order and prints one line per
check: `ok`, `warn`, `fail` or `info`, the check's name, and what it found. Any problem
has a `fix:` line under it. It exits 1 if anything failed.

Doctor fetches plan usage once, the way the statusline's background fetch does. Running
it again therefore retries now instead of waiting out a backoff. Don't run it in a loop.

## 2. Report

Start with the outcome in one line: all good, or which parts fail. Then for each
`warn` and `fail`, say what it means and what you'll do or what the user needs to do.
Skip the `ok` lines unless the user asked about one. Never show the user's token or
credentials, and don't read the credentials file.

What the checks mean:

| check | what it covers |
|---|---|
| `python` | the Python running doctor; the statusline runs `python3` from the PATH Claude Code sees |
| `install` | the copy in `<config>/scripts/statusline/` and whether it matches this plugin version |
| `settings` | which settings file's `statusLine` wins, and whether it runs dashline; `disableAllHooks` |
| `login` | subscription vs API key / Bedrock / Vertex / Foundry; where the token comes from |
| `usage` | one live fetch of plan usage: the bars it would draw, or why it failed |
| `cache` | `<config>/cache/statusline/`: writable, dashline's files private, when last fetched, fetch lock |
| `command` | runs the exact settings command on a sample session, like Claude Code does |
| `git` | git for the directory row (2.11 or newer) |
| `theme` | the Claude Code theme whose colors the statusline uses |
| `font` | whether Nerd Font icons are likely to render, and the glyph set in use |

## 3. Fix what's safe

Do these without asking, then run doctor again:
- `install` warns that the copy is old or differs, or `command` says its statusline.py
  is missing: run `DASHLINE --install`. It keeps the glyph set and the command as
  written, and only touches settings.json when the entry is already dashline's.
  Not when `install` says the installed copy is newer than this one: that means this
  plugin is out of date, so tell the user to update it (`/plugin`) instead.

Ask first (AskUserQuestion), and act only on a yes:
- `settings` says your user settings.json has no statusLine, or one that runs another
  statusline: run `DASHLINE --install`. If it exits 3, show what its output says is
  there (the existing entry, or another tool's files in `scripts/statusline/`) and ask
  before `DASHLINE --install --replace`. If it exits 4, the installed copy is newer than
  this plugin: recommend updating the plugin (`/plugin`), and only on an explicit yes
  run `DASHLINE --install --downgrade`.
- `cache` says other users can read one of its files: run the `chmod 600` in its `fix:` line.

Explain, and leave to the user:
- `settings` says a project file (`.claude/settings.json`, `settings.local.json`) or
  managed settings wins: `--install` only writes user settings, so it can't help, and
  doctor's `fix:` line says what can. A project's statusLine is the user's to remove;
  managed settings only an administrator can change.
- `disableAllHooks`: it turns off hooks too, so removing it is the user's decision.
- `login` / `usage` asking for `/login`: only the user can sign in. A 403 with
  `CLAUDE_CODE_OAUTH_TOKEN` set means a `claude setup-token` token, which can't read
  plan usage. The statusline still works; only the plan bars are missing.
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
- `command` failing with `python3` not found: Claude Code's PATH lacks `python3`. The
  user can install Python (see `/dashline:install` step 1) or edit the command to use
  a full path to Python 3.9+; `--install` keeps that edit.
- `command` slow: usually a large git repo or slow disk. Mention it, nothing to fix.
- Icons showing as boxes or `?`, or the user wants icons: run the glyph step of
  `/dashline:install`.
- API key, Bedrock, Vertex, Foundry or a gateway: no plan bars is expected, because
  those bill per use.

## 4. Nothing failed but it still looks wrong

Ask what they see, and compare it with
`! python3 -I -S "${CLAUDE_PLUGIN_ROOT}/statusline.py" --preview` (write in the real
path), which shows how each plan should look. Things to know:
- The `·12m` style tag after the plan bars means the numbers are that old: fetches are
  failing, and the `usage` line says why.
- Bars are hidden when the terminal is too narrow and turn into short text instead.
- A project's `.claude/settings.json` or `settings.local.json` can set its own
  statusLine that wins over the user's; the `settings` line names the file in use.
