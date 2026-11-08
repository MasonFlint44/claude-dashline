#!/usr/bin/env bash
# Run the shipped files on one Python the way Claude Code does, in a throwaway home with
# no login (so nothing reaches the network; a dead proxy is set in case).
#
#   scripts/smoke.sh /usr/bin/python3              # Apple's, on macOS
#   scripts/smoke.sh "$(uv python find 3.9)"       # the oldest supported Python
#
# On Windows it runs in Git Bash: the install there names Python by `python` (this one,
# first on PATH) and the doctor runs the command in Git Bash, as Claude Code would. With
# Program Files hidden from it, doctor has to find Git Bash from git on PATH (Git Bash's
# own, in ucrt64\bin or mingw64\bin), the way Claude Code finds a Git installed elsewhere.
#
# The home folder has a space and accented letters (`José Müller`), as many profile
# folders do, and so does the project the sample session is in: its name must reach the
# statusline intact.
#
# The test suite runs on 3.10 and newer (its tools have dropped 3.9), so this is what
# keeps dashline itself working on 3.9. Exits 1 on any failure.
set -euo pipefail

py=${1:?usage: scripts/smoke.sh PYTHON}
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export NO_COLOR=1 HTTPS_PROXY=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9
unset CLAUDE_CONFIG_DIR CLAUDE_CODE_OAUTH_TOKEN

"$py" --version
"$py" -I -S -c 'import sys; assert sys.version_info >= (3, 9), sys.version'

# Every module imports: catches syntax or library use newer than this Python.
"$py" -I -S -c '
import importlib, pkgutil, sys
sys.path.append("src")
import dashline
for m in pkgutil.iter_modules(dashline.__path__):
    importlib.import_module("dashline." + m.name)
print("imported", len(list(pkgutil.iter_modules(dashline.__path__))), "modules")
'
"$py" -I -S statusline.py --version
"$py" -I -S statusline.py --preview all > /dev/null

# Doctor's command check runs the Python settings.json names: make that this one.
home_dir="$tmp/José Müller"
mkdir -p "$home_dir/projé"
case "$(uname -s)" in
  MINGW* | MSYS* | CYGWIN*)
    # No symlinks to lean on: this Python's own folder goes first, and the PATH leaves
    # out C:\Windows, so `py` (the launcher, which would pick another Python) isn't
    # found and `python` is this one. System32 stays for taskkill and PowerShell.
    # git stays too, from wherever Git Bash has it (ucrt64\bin, mingw64\bin or cmd).
    home=$(cygpath -w "$home_dir")
    sys32=$(cygpath -u "$SYSTEMROOT")/System32
    git_dir=$(dirname "$(command -v git)")
    echo "git: $(cygpath -w "$git_dir")"
    export HOME="$home" USERPROFILE="$home"
    export PATH="$(dirname "$(cygpath -u "$py")"):$git_dir:/usr/bin:/bin:$sys32:$sys32/WindowsPowerShell/v1.0"
    unset CLAUDE_CODE_GIT_BASH_PATH
    mkdir -p "$tmp/empty"
    empty=$(cygpath -w "$tmp/empty")
    # Names with parentheses can't be exported from Bash; env sets them for one command.
    hide=(env "ProgramFiles=$empty" "ProgramW6432=$empty" "ProgramFiles(x86)=$empty")
    shell="(Git Bash)"
    run=("$py" -I -S)
    installed="$home_dir/.claude/scripts/statusline/statusline.py"
    ;;
  *)
    mkdir -p "$tmp/bin"
    ln -s "$py" "$tmp/bin/python3"
    export HOME="$home_dir" PATH="$tmp/bin:/usr/bin:/bin"
    run=(python3 -I -S)
    installed="$HOME/.claude/scripts/statusline/statusline.py"
    hide=(env)
    shell=""
    ;;
esac
"${run[@]}" statusline.py --install

# The sample session, in the project folder.
"$py" -I -S - "$home_dir/projé" > "$tmp/session.json" <<'PY'
import json, sys
with open("tests/fixtures/stdin/after-first-response.json", encoding="utf-8") as f:
    session = json.load(f)
session["cwd"] = sys.argv[1]
session["workspace"] = {"current_dir": sys.argv[1], "project_dir": sys.argv[1]}
# As Claude Code (Node) sends it: UTF-8, the accented letters not escaped.
sys.stdout.buffer.write(json.dumps(session, ensure_ascii=False).encode())
PY

# A render that fails still exits 0 with a one-line error, so read what it printed.
"${run[@]}" "$installed" < "$tmp/session.json" > "$tmp/out" 2> "$tmp/err"
cat "$tmp/out"
if [ -s "$tmp/err" ]; then
  echo "::error::the render wrote to stderr"; cat "$tmp/err"; exit 1
fi
if grep -q "internal error" "$tmp/out"; then
  echo "::error::the render failed"; exit 1
fi
if [ "$(wc -l < "$tmp/out")" -lt 2 ]; then
  echo "::error::the render printed fewer than 2 lines"; exit 1
fi
if ! grep -q "projé" "$tmp/out"; then
  echo "::error::the project's name didn't reach the statusline intact"; exit 1
fi

# The same, as Claude Code runs it: settings.json's command, through the shell (Git
# Bash on Windows), with the accented session on stdin.
"$py" -I -S - "$home_dir/.claude/settings.json" > "$tmp/command" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    sys.stdout.buffer.write(json.load(f)["statusLine"]["command"].encode())
PY
bash -c "$(cat "$tmp/command")" < "$tmp/session.json" > "$tmp/out" 2> "$tmp/err"
if [ -s "$tmp/err" ] || ! grep -q "projé" "$tmp/out"; then
  echo "::error::the command through bash -c didn't render the project intact"
  cat "$tmp/out" "$tmp/err"; exit 1
fi

# With no login every check is ok or info, so exit 1 is a real failure.
"${hide[@]}" "${run[@]}" statusline.py --doctor | tee "$tmp/doctor"
if ! grep -q "command  *printed .*${shell:+ $shell}" "$tmp/doctor"; then
  echo "::error::doctor didn't run the command${shell:+ in $shell}"; exit 1
fi
