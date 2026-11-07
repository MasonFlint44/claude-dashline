# Windows without Git Bash: install and doctor run from Windows PowerShell (as Claude's
# own PowerShell tool would), and doctor runs the statusLine command in PowerShell, as
# Claude Code then does. Git for Windows and PowerShell 7 are hidden from both: off PATH,
# and Program Files pointed at an empty folder.
#
#   powershell -NoProfile -File scripts/smoke.ps1 C:\path\to\python.exe
#
# A throwaway home with no login, and a dead proxy, so nothing reaches the network.
# Exits 1 on any failure.
param([Parameter(Mandatory = $true)][string]$Python)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("dashline-" + [guid]::NewGuid())
$profileDir = Join-Path $tmp "home"
$empty = Join-Path $tmp "empty"
New-Item -ItemType Directory -Path $profileDir, $empty | Out-Null
try {
    $env:HOME = $profileDir
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
    $env:PATH = "$(Split-Path -Parent $Python);$sys32;$sys32\WindowsPowerShell\v1.0"

    & $Python -I -S statusline.py --install
    if ($LASTEXITCODE -ne 0) { throw "install exited $LASTEXITCODE" }
    $settings = Get-Content (Join-Path $profileDir ".claude\settings.json") -Raw | ConvertFrom-Json
    $command = $settings.statusLine.command
    Write-Output "statusLine command: $command"
    if ($command -notmatch '^python -I -S "[A-Za-z]:/[^"]*/statusline\.py"$') {
        throw "not the Windows command"
    }

    # Doctor runs that command in PowerShell on a sample session, and checks its output
    # (lines, symbols, time). With no login every check is ok, info or a git warning;
    # a cold PowerShell start on a busy runner may warn (slow).
    $doctor = & $Python -I -S statusline.py --doctor
    $code = $LASTEXITCODE
    $doctor | Write-Output
    if ($code -ne 0) { throw "doctor exited $code" }
    $ran = '^\s*(ok|warn)\s+command\s+printed \d+ lines in \d+ ms \(PowerShell\)( \(slow\))?$'
    if (-not ($doctor | Select-String -Pattern $ran)) {
        throw "doctor didn't run the command in PowerShell, or it wasn't ok"
    }
}
catch {
    Write-Output "::error::$_"
    exit 1
}
finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
