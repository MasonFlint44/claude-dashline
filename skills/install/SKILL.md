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
- **Exit 3:** settings.json already runs a different statusline, and the output shows
  that entry. Show it to the user and ask (AskUserQuestion) whether to replace it.
  Only if they say yes, run `DASHLINE --install --replace`. If they say no, stop:
  dashline is copied but not active.
- **Exit 1:** relay the error, which is usually settings.json that isn't valid JSON.
  Don't fix settings.json yourself unless the user asks.

## 3. Glyph set

A terminal can't be asked which fonts it draws, so the user has to look.

1. Run `DASHLINE --doctor` and read its `font` line. It says whether this terminal
   probably shows Nerd Font icons (Ghostty and WezTerm bundle them; otherwise it
   looks for an installed Nerd Font) and which set is in use.
2. Ask the user to run this themselves, because only output from their own `!` command
   is certain to show in their terminal's font. Write it with the real path in place of
   `${CLAUDE_PLUGIN_ROOT}`:

   ```
   ! python3 -I -S "${CLAUDE_PLUGIN_ROOT}/statusline.py" --preview ultra-fable --glyphs all
   ```

   It prints the same statusline in `nerd`, `unicode` and `ascii`. Ask them to reply
   with the first set whose icons all look right (no empty boxes, question marks or
   overlapping characters). Say which one you expect, based on the `font` line. End
   your turn here and wait for their answer.
3. Once they pick:
   - Run `DASHLINE --install --glyphs <set>`, unless that set is already in use.
   - If they chose `unicode` or `ascii` and want icons, explain briefly that a Nerd
     Font adds icons for the branch, commits, tags and fast mode. Only the "Symbols
     Only" font is needed: <https://github.com/ryanoasis/nerd-fonts/releases/latest>
     (`NerdFontsSymbolsOnly`). Give the one-line install for their OS:
     - Linux: `mkdir -p ~/.local/share/fonts && curl -fsSL https://github.com/ryanoasis/nerd-fonts/releases/latest/download/NerdFontsSymbolsOnly.tar.xz | tar -xJ -C ~/.local/share/fonts && fc-cache -f`
     - macOS: `brew install --cask font-symbols-only-nerd-font`
     - Windows Terminal: install any Nerd Font and choose it as the profile's font face.

     Some terminals need the font picked in their settings, or a restart. Afterwards,
     running `/dashline:install` again re-checks and switches to `nerd`. Never install
     fonts or edit terminal settings yourself.

If the user already named a set (e.g. "install with nerd fonts"), skip the preview and
pass `--glyphs` in step 2.

## 4. Check

Run `DASHLINE --doctor` and tell the user the result in a sentence or two. If it isn't
`All good.`, explain each `warn` and `fail` line and its `fix:`, using the doctor
skill's guidance (`/dashline:doctor`).

The plan bars appear after the first background fetch, within a minute. Never print the
user's token or credentials.
