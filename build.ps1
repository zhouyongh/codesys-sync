# build.ps1 - headless build of a CODESYS project, structured report out (codesys-sync)
# Usage:
#   interactive menu (pick a number):
#     powershell -NoProfile -ExecutionPolicy Bypass -File <codesys-sync>\build.ps1 -Root <repo>
#   non-interactive (pick by number):
#     powershell -NoProfile -ExecutionPolicy Bypass -File <codesys-sync>\build.ps1 -Root <repo> -Select 1
#   write the report to a specific file (default <repo>\.codesys-sync\build_report.txt):
#     ... -Out <report path>
# Builds a COPY of the project file from projects/ - safe to run while the IDE has it open.
# Exit codes: 0 = no errors, 1 = compile errors, anything else = tool failure.
# CODESYS installation is auto-detected (override with -CodesysExe/-Profile or CODESYS_SYNC_EXE/CODESYS_SYNC_PROFILE).
[CmdletBinding()]
param(
    [string]$Root = "",
    [int]$Select = 0,
    [string]$Out = "",
    [string]$CodesysExe = "",
    [string]$Profile = ""
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
. (Join-Path $PSScriptRoot "common.ps1")

if (-not $Root) { Write-Host "-Root is required (target repo root, must contain projects\)"; exit 1 }
$root    = (Resolve-Path -LiteralPath $Root).Path
$projDir = Join-Path $root "projects"
$install = Resolve-CodesysInstall -Exe $CodesysExe -ProfileName $Profile
$codesys = $install.Exe
$profile = $install.Profile
Write-Host "CODESYS: $codesys"
Write-Host "Profile: $profile"

# list .project only (.library cannot be built)
$files = @(Get-ChildItem $projDir -File -Recurse | Where-Object { $_.Extension -eq ".project" } | Sort-Object FullName)
if ($files.Count -eq 0) { Write-Host "No .project files under projects/"; exit 1 }

Write-Host "Buildable projects:"
for ($i = 0; $i -lt $files.Count; $i++) {
    Write-Host ("  {0}. {1}" -f ($i + 1), $files[$i].FullName.Substring($projDir.Length + 1))
}

if ($Select -lt 1 -or $Select -gt $files.Count) {
    $Select = [int](Read-Host "Enter number")
}
if ($Select -lt 1 -or $Select -gt $files.Count) { Write-Host "Invalid number"; exit 1 }

$file = $files[$Select - 1]
$work = Join-Path $root ".codesys-sync"
New-Item -ItemType Directory -Force -Path $work | Out-Null

# report path
if ($Out -ne "") {
    if (-not [IO.Path]::IsPathRooted($Out)) { $Out = Join-Path (Get-Location) $Out }
    $report = $Out
} else {
    $report = Join-Path $work "build_report.txt"
}
$reportDir = Split-Path -Parent $report
if ($reportDir) { New-Item -ItemType Directory -Force -Path $reportDir | Out-Null }

# robocopy copies the project (plain copy silently truncates files locked by the IDE)
robocopy $file.DirectoryName $work $file.Name | Out-Null
if ($LASTEXITCODE -ge 8) { Write-Host "robocopy failed (exit $LASTEXITCODE)"; exit 1 }
$copy = Join-Path $work $file.Name

# target file for the IronPython script (path passed via CODESYS_SYNC_TARGET)
$utf8 = New-Object System.Text.UTF8Encoding $false
$targetFile = Join-Path $work "target.txt"
$env:CODESYS_SYNC_TARGET = $targetFile
[System.IO.File]::WriteAllLines($targetFile, @(
    "source=$($file.FullName)",
    "project=$copy",
    "report=$report"
), $utf8)

Write-Host "Building $($file.Name) ... (headless CODESYS startup is slow, about 1-2 minutes)"
# same as export.ps1: call a temp ASCII bat via cmd to dodge the PS 5.1 quoting problem
$bat = Join-Path $work "run_codesys.bat"
[System.IO.File]::WriteAllLines($bat, @(
    "@echo off",
    "`"$codesys`" --noUI --profile=`"$profile`" --runscript=`"$(Join-Path $PSScriptRoot 'build_project.py')`"",
    "exit /b %ERRORLEVEL%"
), [System.Text.Encoding]::ASCII)
cmd /c $bat
$code = $LASTEXITCODE
if ($code -ne 0) { Write-Host "CODESYS exit code: $code"; exit $code }

if (-not (Test-Path $report)) { Write-Host "Report not generated: $report"; exit 2 }
Write-Host "---- build_report.txt ----"
Get-Content $report -Encoding UTF8

$m = Select-String -Path $report -Pattern '^errors=(\d+)$'
if ($m) {
    $n = [int]$m.Matches[0].Groups[1].Value
    if ($n -gt 0) { Write-Host "Build FAILED: $n error(s) (see $report)"; exit 1 }
    Write-Host "Build passed (0 errors), report: $report"
    exit 0
}
Write-Host "No errors= line found in report: $report"; exit 2
