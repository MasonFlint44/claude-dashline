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
| `cache` | `<config>/cache/statusline/`: writable, private, when last fetched, fetch lock |
| `command` | runs the exact settings command on a sample session, like Claude Code does |
| `git` | git for the directory row (2.11 or newer) |
| `theme` | the Claude Code theme whose colors the statusline uses |
| `font` | whether Nerd Font icons are likely to render, and the glyph set in use |

## 3. Fix what's safe

Do these without asking, then run doctor again:
- `install` warns that the copy is old or differs: run `DASHLINE --install`. It keeps
  the glyph set and only rewrites settings.json when the entry is already dashline's.

Ask first (AskUserQuestion), and act only on a yes:
- `settings` says no statusLine, or one that runs another statusline: run
  `DASHLINE --install`. If it exits 3, show the existing entry from its output and ask
  before `DASHLINE --install --replace`.
- `cache` says other users can read it: `chmod 700` on the folder it names.

Explain, and leave to the user:
- `disableAllHooks`: it turns off hooks too, so removing it is the user's decision.
- `login` / `usage` asking for `/login`: only the user can sign in. A 403 with
  `CLAUDE_CODE_OAUTH_TOKEN` set means a `claude setup-token` token, which can't read
  plan usage. The statusline still works; only the plan bars are missing.
- `usage` network failures: the statusline keeps the last numbers (marked with their
  age) and retries on its own. Point at proxy settings (`HTTPS_PROXY`) only if the user
  is behind one.
- An expired token (`warn`): Claude Code renews it on its next request. No action
  needed.
- `command` failing with `python3` not found: Claude Code's PATH lacks `python3`. The
  user can install Python (see `/dashline:install` step 1) or edit the command to use
  a full path to Python 3.9+.
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
