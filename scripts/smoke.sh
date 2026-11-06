#!/usr/bin/env bash
# Run the shipped files on one Python the way Claude Code does, in a throwaway home with
# no login (so nothing reaches the network; a dead proxy is set in case).
#
#   scripts/smoke.sh /usr/bin/python3              # Apple's, on macOS
#   scripts/smoke.sh "$(uv python find 3.9)"       # the oldest supported Python
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

# Doctor's command check runs settings.json's `python3`: make that this Python.
mkdir -p "$tmp/bin" "$tmp/home"
ln -s "$py" "$tmp/bin/python3"
export HOME="$tmp/home" PATH="$tmp/bin:/usr/bin:/bin"
python3 -I -S statusline.py --install

# A render that fails still exits 0 with a one-line error, so read what it printed.
python3 -I -S "$HOME/.claude/scripts/statusline/statusline.py" \
  < tests/fixtures/stdin/after-first-response.json > "$tmp/out" 2> "$tmp/err"
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

# With no login every check is ok or info, so exit 1 is a real failure.
python3 -I -S statusline.py --doctor
