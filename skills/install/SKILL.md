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
for `PYTHON -I -S "${CLAUDE_PLUGIN_ROOT}/statusline.py"`, where `PYTHON` is `python3`,
or on Windows the name step 1 found.

## 1. Python

dashline needs Python 3.9 or newer, by a name settings.json's command can run.

- **macOS, Linux and WSL:** run `python3 -c 'import sys; print(sys.version)'`. It must
  work as `python3`, because that is what settings.json runs.
- **Windows** (not WSL): try `py -3`, then `python`, then `python3`, each with
  `-c "import sys; print(sys.version)"`, and use the first that prints 3.9 or newer as
  `PYTHON`. `--install` picks the same way and writes that name into settings.json. A
  `python3` that prints "Python was not found" (the Microsoft Store's stand-in) doesn't
  count.

To tell Windows from WSL: in Claude's shell `uname -s` prints `MINGW…` or `MSYS…` on
Windows (Git Bash) and `Linux` in WSL. Where `uname` isn't found, the shell is
PowerShell: that's Windows too.

If none works, stop and tell the user how to get it:
- **macOS:** `brew install python` if `brew` exists; otherwise `xcode-select --install`,
  whose command-line tools include Python 3.9.
- **Linux:** the distro's package, e.g. `sudo apt install python3`.
- **Windows:** `winget install Python.Python.3.13`, or the installer from python.org;
  then restart Claude Code so it sees the new PATH.

Don't install it yourself.

## 2. Copy and point settings at it

Run `DASHLINE --install`. The glyph set already installed is kept; a first install
uses `unicode`.

- **Exit 0:** done. The output says where it copied the files and what settings.json
  now runs. Pass on any `note:` line: a project's own settings override the user
  entry there; files from an interrupted install were kept in
  `scripts/statusline.kept`; the command was rewritten for Windows. A note that
  `--glyphs <x> isn't a glyph set` means the command keeps a typo (like `Nerd`) and
  the statusline shows an error until it names a set: ask the glyph question (step 4).
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
  read-only (the file or its folder), or whose statusLine changed while installing
  (run it once more). On Windows it can also say no Python 3.9 or newer
  runs as `py -3`, `python` or `python3` (give step 1's Windows advice, and the
  message's note on a `py` that picks an older Python), or that the install path has a
  `$` or `` ` `` (relay its advice). Don't fix settings.json
  yourself unless the user asks. If `--replace` had moved another tool's files aside, the output says they were
  moved back. With `--glyphs`, it can also say it can't change `--glyphs` in this
  command automatically (a hand-edited command like `bash -lc '…'`): nothing was
  changed, and its message gives the edit to make; show it to the user.
- **Exit 2:** a usage error (a mistyped flag or glyph set). Relay the message; nothing
  was changed.

An update keeps files the user added to `scripts/statusline/` (notes, a wrapper script).
A `note:` line names any it couldn't move, and where they are now (usually
`scripts/statusline.kept`); pass it on.

An entry that is already dashline's keeps its command as written (for example a full
path to Python); only the `--glyphs` flag changes. One exception, on Windows: the
command older versions wrote (`python3 … "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/…"`, with
any Python in place of `python3`) is Bash only, so `--install` rewrites it in the
Windows form and a `note:` line says so; pass it on. So is the Windows command install
wrote, once the Python it names no longer runs (another that does takes its place).
Any other edit is kept, even one that PowerShell can't run (`$`-variables, `~`) or
whose Python is gone; `--install --replace` rewrites it in the Windows form, keeping the
glyph set (doctor says when; ask first, as for exit 3).

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
question marks, or when step 2's note or doctor's `settings` line says the command's
`--glyphs` isn't a glyph set. On a plain update, keep the set in use and don't ask; if doctor's `font` line ends
`(/dashline:install can switch to nerd)`, mention in one line that icons are available.
If the user already named a set (e.g. "install with nerd fonts"), skip the question and
pass `--glyphs` in step 2.

1. **Recommend `nerd`** every time: its icons are the best statusline. Doctor's `font`
   line (step 3; don't run doctor again for it) only changes what you say about it:
   whether this terminal has a Nerd Font already (`bundles Nerd Font symbols` or
   `found …`) or probably needs one (`no Nerd Font …`). It's a guess either way: a font
   can be installed but not picked in the terminal, or picked but not seen from here.
2. **Ask** (AskUserQuestion, header "Glyphs"), with `nerd` first and marked
   "(Recommended)". Describe the sets in words; don't print sample icons, since the
   reply may not be drawn in the terminal's font:
   - `nerd`: icons for git, branches, tags and fast mode. Needs a Nerd Font: say
     whether this terminal seems to have one; if not, that you'll say how to add one.
   - `unicode`: simple symbols such as ⎇ for the branch and ✎ for changes, which any
     modern font draws.
   - `ascii`: plain text only, such as `(main)` and `* +12`. Works in any terminal.
   - "Compare them first": ask the user to run this themselves, with the real path in
     place of `${CLAUDE_PLUGIN_ROOT}`, then end your turn and wait for their pick:

     ```
     ! python3 -I -S "${CLAUDE_PLUGIN_ROOT}/statusline.py" --preview ultra-fable --glyphs all
     ```

     (on Windows, with step 1's `PYTHON` in place of `python3`)
3. **Install the pick:** `DASHLINE --install --glyphs <set>`, unless that set is already
   in use.
4. **Tell the user what to check**, since the statusline itself is the real test (a font
   can be installed but not picked in the terminal). It changes within a minute, or
   after their next message.
   - `nerd`: line 3 starts with a git logo (in a repo) or a folder icon before the
     project name. Every icon comes from the same font, so if that one draws, they all
     do. If it's an empty box or `?`, the terminal needs a Nerd Font (step 5), or
     `/dashline:install` again can switch to `unicode`. When doctor's `font` line said
     `no Nerd Font …`, give step 5's install line now, with this check.
   - `unicode`: in a git repo the branch shows as `⎇ main`. If that's a box, choose
     `ascii`.
5. **Getting a Nerd Font:** when `nerd` was picked without one, or the user chose
   `unicode` or `ascii` but wants icons, explain briefly that a Nerd Font adds icons for
   the branch, commits, tags and fast mode. Only the "Symbols Only" font is needed:
   <https://github.com/ryanoasis/nerd-fonts/releases/latest> (`NerdFontsSymbolsOnly`).
   Give the one-line install for where the terminal runs:
   - Linux: `mkdir -p ~/.local/share/fonts && curl -fsSL https://github.com/ryanoasis/nerd-fonts/releases/latest/download/NerdFontsSymbolsOnly.tar.xz | tar -xJ -C ~/.local/share/fonts && fc-cache -f`
   - macOS: `brew install --cask font-symbols-only-nerd-font`
   - Windows, including WSL (doctor's `font` line mentions `Windows' fonts`): the
     terminal is a Windows program, so the font goes on Windows, not in Linux. Suggest
     Cascadia Code NF, the Nerd Font version of Windows Terminal's own Cascadia (Cascadia
     Mono NF is the same without ligatures): download the zip from
     <https://github.com/microsoft/cascadia-code/releases/latest>, open
     `ttf\CascadiaCodeNF.ttf` and click Install. Then in Windows Terminal: Settings → the
     profile → Appearance → Font face → `Cascadia Code NF`, and restart the terminal if
     it isn't listed yet. Ask first whether that list already has `Cascadia Code NF` or
     `Cascadia Mono NF`: newer Windows Terminals bring their own copy, which doctor
     can't see, so only picking it is needed.

   Some terminals need the font picked in their settings, or a restart. Afterwards,
   `/dashline:install` can switch to `nerd`. Never install fonts or edit terminal
   settings yourself.

Switching the glyph set needs no second doctor run: `--install` prints what
settings.json now runs.

The plan bars appear after the first background fetch, within a minute. Never print the
user's token or credentials.
