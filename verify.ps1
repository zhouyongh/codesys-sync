# verify.ps1 - compare the export tree against the project WITHOUT modifying either
# (codesys-sync). Reports missing objects, content drift, rename candidates.
# Usage:
#   interactive menu:
#     powershell -NoProfile -ExecutionPolicy Bypass -File <codesys-sync>\verify.ps1 -Root <repo>
#   non-interactive:
#     powershell -NoProfile -ExecutionPolicy Bypass -File <codesys-sync>\verify.ps1 -Root <repo> -Select 1
#   report path (default <repo>\.codesys-sync\<project>_verify_report.txt): ... -Out <path>
# Exit codes: 0 = in sync, 1 = differences found, anything else = tool failure.
[CmdletBinding()]
param(
    [string]$Root = "",
    [int]$Select = 0,
    [string]$SrcRoot = "src/plc",
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

function Get-ExportName([string]$base) {
    # full-width parens included on purpose: CJK project names may contain them
    return ($base -replace '[\\/:*?"<>|\s\(\)（）]+', '-').Trim('-')
}

function Get-OutDir([System.IO.FileInfo]$file) {
    $name = Get-ExportName $file.BaseName
    $base = Join-Path $root ($SrcRoot -replace '/', '\')
    if ($file.Extension -eq ".library") {
        $base = Join-Path $base "reference"
    }
    $rel = $file.DirectoryName.Substring($projDir.Length).TrimStart('\')
    if ($rel) { $base = Join-Path $base $rel }
    return (Join-Path $base $name)
}

$files = @(Get-ChildItem $projDir -File -Recurse | Where-Object { $_.Extension -in ".project", ".library" } | Sort-Object FullName |
    Where-Object { Test-Path (Join-Path (Get-OutDir $_) "_index.txt") })
if ($files.Count -eq 0) { Write-Host "No verifiable projects (run export.ps1 first)"; exit 1 }

Write-Host "Verifiable projects (text tree vs project, read-only):"
for ($i = 0; $i -lt $files.Count; $i++) {
    $outDisp = Get-OutDir $files[$i]
    Write-Host ("  {0}. {1}  <->  {2}" -f ($i + 1), $files[$i].FullName.Substring($projDir.Length + 1), $outDisp.Substring($root.Length + 1))
}

if ($Select -lt 1 -or $Select -gt $files.Count) {
    $Select = [int](Read-Host "Enter number")
}
if ($Select -lt 1 -or $Select -gt $files.Count) { Write-Host "Invalid number"; exit 1 }

$file = $files[$Select - 1]
$outDir = Get-OutDir $file

# resolve CODESYS install AFTER project selection: match the project's last-saved version
$ename = Get-ExportName $file.BaseName
$work0 = Join-Path $root ".codesys-sync"
$exportInfo = Join-Path $outDir "_project_info.txt"
$stamp0 = Join-Path $work0 ($ename + '_lastexport.txt')
$install = Resolve-CodesysInstall -Exe $CodesysExe -ProfileName $Profile `
    -ProjectFile $file.FullName -ExportInfo $exportInfo -StampFile $stamp0
$codesys = $install.Exe
$profile = $install.Profile
Write-Host "CODESYS: $codesys"
Write-Host "Profile: $profile"

$work = Join-Path $root ".codesys-sync"
New-Item -ItemType Directory -Force -Path $work | Out-Null

if ($Out -ne "") {
    if (-not [IO.Path]::IsPathRooted($Out)) { $Out = Join-Path (Get-Location) $Out }
    $report = $Out
} else {
    $report = Join-Path $work ($ename + "_verify_report.txt")
}
$reportDir = Split-Path -Parent $report
if ($reportDir) { New-Item -ItemType Directory -Force -Path $reportDir | Out-Null }

$utf8 = New-Object System.Text.UTF8Encoding $false
$targetFile = Join-Path $work "target_verify.txt"
$env:CODESYS_SYNC_TARGET = $targetFile
[System.IO.File]::WriteAllLines($targetFile, @(
    "project=$($file.FullName)",
    "indir=$outDir",
    "report=$report"
), $utf8)

Write-Host "Verifying $($file.Name) ... (about 1 minute)"
$bat = Join-Path $work "run_verify.bat"
[System.IO.File]::WriteAllLines($bat, @(
    "@echo off",
    "set CODESYS_SYNC_TARGET=$targetFile",
    "`"$codesys`" --noUI --profile=`"$profile`" --runscript=`"$(Join-Path $PSScriptRoot 'verify_export.py')`"",
    "exit /b %ERRORLEVEL%"
), [System.Text.Encoding]::ASCII)
cmd /c $bat | Out-Null

if (-not (Test-Path $report)) { Write-Host "Report not generated: $report"; exit 2 }
Write-Host "---- verify report ----"
Get-Content $report -Encoding UTF8

$m = Select-String -Path $report -Pattern '^errors=(\d+)$'
if ($m) {
    $n = [int]$m.Matches[0].Groups[1].Value
    if ($n -gt 0) { Write-Host "Out of sync: $n difference(s) (see $report)"; exit 1 }
    Write-Host "In sync (no differences between project and text tree), report: $report"
    exit 0
}
Write-Host "No errors= line found in report: $report"; exit 2
