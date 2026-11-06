---
name: install
description: Install or update the dashline statusline — copy it into the Claude config folder, point settings.json's statusLine at it, and pick the glyph set (nerd, unicode or ascii) that renders in this terminal. Use when the user runs /dashline:install, asks to set up, enable or update dashline or "the statusline", has just updated the plugin, wants Nerd Font icons (or wants them gone), or says the statusline shows boxes or question marks.
---

# Install dashline

dashline is a Python script. This skill copies it to
`${CLAUDE_CONFIG_DIR:-~/.claude}/scripts/statusline/`, writes the `statusLine` entry in
user settings, and picks the glyph set. `statusline.py --install` does the copying and
the settings edit. Don't edit settings.json by hand.

The plugin copy is at `${CLAUDE_PLUGIN_ROOT}/statusline.py`. Below, `DASHLINE` stands
for `python3 -I -S "${CLAUDE_PLUGIN_ROOT}/statusline.py"`.

## 1. Python

Run `python3 -c 'import sys; print(sys.version)'`. dashline needs Python 3.9 or newer,
reachable as `python3`, because that is the command settings.json runs.

If it's missing or older, stop and tell the user how to get it:
- **macOS:** `brew install python` if `brew` exists; otherwise `xcode-select --install`,
  whose command-line tools include Python 3.9.
- **Linux:** the distro's package, e.g. `sudo apt install python3`.

Don't install it yourself.

## 2. Copy and point settings at it

Run `DASHLINE --install`. The glyph set already installed is kept; a first install
uses `unicode`.

- **Exit 0:** done. The output says where it copied the files and what settings.json
  now runs. Pass on any `note:` line: a project's own settings override the user
  entry there.
- **Exit 3:** nothing was changed, because something else is there. The output says
  what: settings.json runs a different statusline (the entry is shown), or
  `scripts/statusline/` holds another tool's files. Show it to the user and ask
  (AskUserQuestion) whether to replace it. Only if they say yes, run
  `DASHLINE --install --replace`; it moves another tool's files to
  `scripts/statusline.backup` rather than deleting them. If they say no, stop.
- **Exit 4:** nothing was changed, because the installed copy is newer than this
  plugin's (the output gives both versions). This plugin is probably out of date. Ask
  (AskUserQuestion) with updating the plugin as the recommended choice: `/plugin`,
  then `/dashline:install` again. Only if the user wants the older version anyway,
  run `DASHLINE --install --downgrade` (add `--replace` if exit 3 asked for it too).
- **Exit 1:** relay the error: usually settings.json that isn't valid JSON, or is
  read-only (the file or its folder). Don't fix settings.json yourself unless the user
  asks. If `--replace` had moved another tool's files aside, the output says they were
  moved back. With `--glyphs`, it can also say it can't change `--glyphs` in this
  command automatically (a hand-edited command like `bash -lc '…'`): nothing was
  changed, and its message gives the edit to make; show it to the user.
- **Exit 2:** a usage error (a mistyped flag or glyph set). Relay the message; nothing
  was changed.

An update keeps files the user added to `scripts/statusline/` (notes, a wrapper script).
A `note:` line names any it couldn't move, and where they are now
(`scripts/statusline.kept`); pass it on.

An entry that is already dashline's keeps its command as written (for example a full
path to Python); only the `--glyphs` flag changes.

## 3. Check

Run `DASHLINE --doctor` and tell the user the result in a sentence or two. If it isn't
`All good.`, explain each `warn` and `fail` line and its `fix:`, using the doctor
skill's guidance (`/dashline:doctor`). Each doctor run fetches plan usage live, so the
doctor skill's limit applies: one more run only to confirm fixes you applied from it.
Keep its `font` line for the next step: it says whether this terminal probably shows
Nerd Font icons (Ghostty and WezTerm bundle them; otherwise it looks for an installed
Nerd Font) and which set is in use.

## 4. Glyph set

Ask which glyph set to use when this was a first install (step 2's output said
`installed`, not `updated` or `already has`), when the user asked about icons, boxes or
question marks, or when doctor's `settings` line says the command names an unknown glyph
set. On a plain update, keep the set in use and don't ask; if doctor's `font` line ends
`(/dashline:install can switch to nerd)`, mention in one line that icons are available.
If the user already named a set (e.g. "install with nerd fonts"), skip the question and
pass `--glyphs` in step 2.

1. **Recommend from doctor's `font` line** (step 3; don't run doctor again for it):
   `nerd` when it says a terminal bundles Nerd Font symbols or `found …` a Nerd Font,
   otherwise `unicode`.
2. **Ask** (AskUserQuestion, header "Glyphs"), with the recommended set first and marked
   "(Recommended)". Describe the sets in words; don't print sample icons, since the
   reply may not be drawn in the terminal's font:
   - `nerd`: icons for git, branches, tags and fast mode. Needs a Nerd Font; Ghostty
     and WezTerm include one.
   - `unicode`: simple symbols such as ⎇ for the branch and ✎ for changes, which any
     modern font draws.
   - `ascii`: plain text only, such as `(main)` and `* +12`. Works in any terminal.
   - "Compare them first": ask the user to run this themselves, with the real path in
     place of `${CLAUDE_PLUGIN_ROOT}`, then end your turn and wait for their pick:

     ```
     ! python3 -I -S "${CLAUDE_PLUGIN_ROOT}/statusline.py" --preview ultra-fable --glyphs all
     ```
3. **Install the pick:** `DASHLINE --install --glyphs <set>`, unless that set is already
   in use.
4. **Tell the user what to check**, since the statusline itself is the real test (a font
   can be installed but not picked in the terminal). It changes within a minute, or
   after their next message.
   - `nerd`: line 3 starts with a git logo (in a repo) or a folder icon before the
     project name. Every icon comes from the same font, so if that one draws, they all
     do. If it's an empty box or `?`, run `/dashline:install` again and choose
     `unicode`.
   - `unicode`: in a git repo the branch shows as `⎇ main`. If that's a box, choose
     `ascii`.
5. **Icons wanted without a Nerd Font:** if the user chose `unicode` or `ascii` but
   wants icons, explain briefly that a Nerd Font adds icons for the branch, commits,
   tags and fast mode. Only the "Symbols Only" font is needed:
   <https://github.com/ryanoasis/nerd-fonts/releases/latest> (`NerdFontsSymbolsOnly`).
   Give the one-line install for their OS:
   - Linux: `mkdir -p ~/.local/share/fonts && curl -fsSL https://github.com/ryanoasis/nerd-fonts/releases/latest/download/NerdFontsSymbolsOnly.tar.xz | tar -xJ -C ~/.local/share/fonts && fc-cache -f`
   - macOS: `brew install --cask font-symbols-only-nerd-font`
   - Windows Terminal: install any Nerd Font and choose it as the profile's font face.

   Some terminals need the font picked in their settings, or a restart. Afterwards,
   `/dashline:install` can switch to `nerd`. Never install fonts or edit terminal
   settings yourself.

Switching the glyph set needs no second doctor run: `--install` prints what
settings.json now runs.

The plan bars appear after the first background fetch, within a minute. Never print the
user's token or credentials.
