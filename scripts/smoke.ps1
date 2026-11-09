# Windows without Git Bash: install and doctor run from Windows PowerShell (as Claude's
# own PowerShell tool would), and doctor runs the statusLine command in PowerShell, as
# Claude Code then does. Git for Windows and PowerShell 7 are hidden from both: off PATH,
# and Program Files pointed at an empty folder. HOME isn't set, as in a real session.
#
#   powershell -NoProfile -File scripts/smoke.ps1 C:\path\to\python.exe
#
# The profile folder has a space and accented letters (`José Müller`), as many do, and
# so does the project the sample session is in: its name must reach the statusline
# intact through PowerShell. Then, in turn:
#   - with the python.org launcher on PATH, so the command is `py -3 …`, what most
#     python.org installs get;
#   - without it again: that command's Python is gone, and install rewrites it;
#   - the command older versions wrote (Bash only): install rewrites it;
#   - with PowerShell 7 in Program Files, which Claude Code then runs the command in.
#
# A throwaway home with no login, and a dead proxy, so nothing reaches the network.
# Exits 1 on any failure.
param([Parameter(Mandatory = $true)][string]$Python)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

# Windows PowerShell reads this file as ANSI: the accented letters are built, not typed.
$e = [char]0x00E9
$u = [char]0x00FC
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("dashline-" + [guid]::NewGuid())
$profileDir = Join-Path $tmp "Jos$e M${u}ller"
$project = Join-Path $profileDir "proj$e"
$empty = Join-Path $tmp "empty"
$settingsFile = Join-Path $profileDir ".claude\settings.json"
New-Item -ItemType Directory -Path $project, $empty | Out-Null

# The installed command, run in a PowerShell (argv[2]) on a real session's input (in the
# project folder), as Claude Code runs it: a render that works prints its lines, the
# project's name and `│` among them, and nothing on stderr. Python runs it, reading the
# command from settings.json (PowerShell 5.1 would mangle its quotes in an argument).
$render = Join-Path $tmp "render.py"
Set-Content -Path $render -Encoding ASCII -Value @'
import json, os, subprocess, sys
project, powershell = sys.argv[1], sys.argv[2]
settings = os.path.join(os.environ['USERPROFILE'], '.claude', 'settings.json')
with open(settings, encoding='utf-8') as f:
    command = json.load(f)['statusLine']['command']
print('statusLine command: ' + command.encode('ascii', 'backslashreplace').decode())
with open(os.path.join('tests', 'fixtures', 'stdin', 'after-first-response.json'), encoding='utf-8') as f:
    session = json.load(f)
session['cwd'] = project
session['workspace'] = {'current_dir': project, 'project_dir': project}
shell = [powershell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command']
# As Claude Code (Node) sends it: UTF-8, the accented letters not escaped.
stdin = json.dumps(session, ensure_ascii=False).encode()
r = subprocess.run(shell + [command], input=stdin, capture_output=True, timeout=60)
out = r.stdout.decode('utf-8', 'replace')
sys.stdout.buffer.write(r.stdout)  # as bytes: this stdout is in the ANSI code page
sys.stdout.flush()
err = r.stderr.decode('utf-8', 'replace').strip()
if err:
    sys.exit('the render wrote to stderr:\n' + err)
if r.returncode != 0 or 'internal error' in out or len(out.splitlines()) < 2:
    sys.exit('the render failed (exit %d)' % r.returncode)
if os.path.basename(project) not in out or '\u2502' not in out:
    sys.exit("the project's name or the separators didn't reach the statusline intact")
'@

$windowsPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

# Install (exit 0, the Windows command with $Expected, and the $Note if given), render it
# in $Shell, and have doctor run it there too.
function Check-Install([string]$Expected, [string]$Note = "", [string]$Shell = $windowsPowerShell,
                       [string]$ShellName = "PowerShell") {
    $out = & $Python -I -S statusline.py --install
    $code = $LASTEXITCODE
    $out | Write-Output
    if ($code -ne 0) { throw "install exited $code" }
    if ($Note -and -not ($out | Select-String -SimpleMatch $Note)) { throw "no note: $Note" }
    $settings = Get-Content $settingsFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $command = $settings.statusLine.command
    if ($command -notmatch "^$Expected -I -S `"[A-Za-z]:/[^`"]*/dashline\.py`"$") {
        throw "not the Windows command with $Expected"
    }

    & $Python -I -S $render $project $Shell
    if ($LASTEXITCODE -ne 0) { throw "the render in $ShellName failed" }

    # Doctor runs that command in the same shell on a sample session, and checks its
    # output (lines, symbols, time). With no login every check is ok, info or a git
    # warning; a cold PowerShell start on a busy runner may warn (slow).
    $doctor = & $Python -I -S statusline.py --doctor
    $code = $LASTEXITCODE
    $doctor | Write-Output
    if ($code -ne 0) { throw "doctor exited $code" }
    $ran = "^\s*(ok|warn)\s+command\s+printed \d+ lines in \d+ ms \($ShellName\)( \(slow\))?$"
    if (-not ($doctor | Select-String -Pattern $ran)) {
        throw "doctor didn't run the command in $ShellName, or it wasn't ok"
    }
}

try {
    # Program Files as it really is, for PowerShell 7 at the end.
    $realPwsh = Join-Path $env:ProgramFiles "PowerShell\7"
    Remove-Item Env:HOME -ErrorAction SilentlyContinue
    $env:USERPROFILE = $profileDir
    $env:NO_COLOR = "1"
    $env:HTTPS_PROXY = "http://127.0.0.1:9"
    foreach ($name in "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_GIT_BASH_PATH") {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
    $env:ProgramFiles = $empty
    $env:ProgramW6432 = $empty
    ${env:ProgramFiles(x86)} = $empty
    # This Python's folder, so `python` is this one; not C:\Windows, whose `py` launcher
    # would pick another; System32 for taskkill and Windows PowerShell.
    $sys32 = Join-Path $env:SystemRoot "System32"
    $path = "$(Split-Path -Parent $Python);$sys32;$sys32\WindowsPowerShell\v1.0"
    $env:PATH = $path
    Check-Install "python"

    # The python.org launcher, in C:\Windows: install looks for it first. A command
    # written fresh names it.
    $launcher = Join-Path $env:SystemRoot "py.exe"
    if (-not (Test-Path $launcher)) { throw "no py launcher in $env:SystemRoot on this runner" }
    $env:PATH = "$path;$env:SystemRoot"
    & py -3 -c "import sys; print(sys.version)"
    if ($LASTEXITCODE -ne 0) { throw "py -3 doesn't run a Python on this runner" }
    Remove-Item $settingsFile
    Check-Install "py -3"

    # py gone again: a plain install rewrites the command with a Python that runs.
    $env:PATH = $path
    Check-Install "python" "doesn't run here any more"

    # The command older versions wrote, Bash only: install rewrites it too.
    $old = 'python3 -I -S "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/scripts/dashline/statusline.py"'
    $json = @{ statusLine = @{ type = "command"; command = $old } } | ConvertTo-Json
    [IO.File]::WriteAllText($settingsFile, $json)
    Check-Install "python" "was Bash only"

    # PowerShell 7 in Program Files (Git still hidden): Claude Code runs the command there.
    if (-not (Test-Path (Join-Path $realPwsh "pwsh.exe"))) { throw "no PowerShell 7 on this runner" }
    $programFiles = Join-Path $tmp "Program Files"
    New-Item -ItemType Directory -Path (Join-Path $programFiles "PowerShell") | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $programFiles "PowerShell\7") -Target $realPwsh | Out-Null
    $env:ProgramFiles = $programFiles
    $env:ProgramW6432 = $programFiles
    Check-Install "python" "" (Join-Path $programFiles "PowerShell\7\pwsh.exe") "PowerShell 7"
}
catch {
    Write-Output "::error::$_"
    exit 1
}
finally {
    # The junction first, so removing the folder never reaches the real PowerShell 7.
    $junction = Join-Path $tmp "Program Files\PowerShell\7"
    if (Test-Path $junction) { [IO.Directory]::Delete($junction) }
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
