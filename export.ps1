# export.ps1 - export source text from a CODESYS project (codesys-sync)
# Usage:
#   interactive menu (pick a number):
#     powershell -NoProfile -ExecutionPolicy Bypass -File <codesys-sync>\export.ps1 -Root <repo>
#   non-interactive (pick by number):
#     powershell -NoProfile -ExecutionPolicy Bypass -File <codesys-sync>\export.ps1 -Root <repo> -Select 1
# Exports a COPY of the project file from projects/ - safe to run while the IDE has it open.
# CODESYS installation is auto-detected (override with -CodesysExe/-Profile or CODESYS_SYNC_EXE/CODESYS_SYNC_PROFILE).
[CmdletBinding()]
param(
    [string]$Root = "",
    [int]$Select = 0,
    [string]$SrcRoot = "src/plc",
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

$files = @(Get-ChildItem $projDir -File -Recurse | Where-Object { $_.Extension -in ".project", ".library" } | Sort-Object FullName)
if ($files.Count -eq 0) { Write-Host "No .project/.library files under projects/"; exit 1 }

Write-Host "Exportable projects:"
for ($i = 0; $i -lt $files.Count; $i++) {
    $out = Get-OutDir $files[$i]
    Write-Host ("  {0}. {1}  ->  {2}" -f ($i + 1), $files[$i].FullName.Substring($projDir.Length + 1), $out.Substring($root.Length + 1))
}

if ($Select -lt 1 -or $Select -gt $files.Count) {
    $Select = [int](Read-Host "Enter number")
}
if ($Select -lt 1 -or $Select -gt $files.Count) { Write-Host "Invalid number"; exit 1 }

$file = $files[$Select - 1]
$outDir = Get-OutDir $file
$work = Join-Path $root ".codesys-sync"
New-Item -ItemType Directory -Force -Path $work, $outDir | Out-Null

# robocopy copies the project (plain copy silently truncates files locked by the IDE)
robocopy $file.DirectoryName $work $file.Name | Out-Null
if ($LASTEXITCODE -ge 8) { Write-Host "robocopy failed (exit $LASTEXITCODE)"; exit 1 }
$copy = Join-Path $work $file.Name

# target file for the IronPython script (path passed via CODESYS_SYNC_TARGET; the .py falls back to target.txt next to itself)
$utf8 = New-Object System.Text.UTF8Encoding $false
$targetFile = Join-Path $work "target.txt"
$env:CODESYS_SYNC_TARGET = $targetFile
[System.IO.File]::WriteAllLines($targetFile, @(
    "project=$copy",
    "outdir=$outDir",
    "log=$(Join-Path $work ((Get-ExportName $file.BaseName) + '_export_log.txt'))"
), $utf8)

Write-Host "Exporting $($file.Name) ... (headless CODESYS startup is slow, about 1-2 minutes)"
# PS 5.1 quotes whole arguments containing spaces and CODESYS then mis-parses --profile;
# instead generate a pure-ASCII temp bat and call it via cmd (same shape as the verified run_export.bat).
$bat = Join-Path $work "run_codesys.bat"
[System.IO.File]::WriteAllLines($bat, @(
    "@echo off",
    "`"$codesys`" --noUI --profile=`"$profile`" --runscript=`"$(Join-Path $PSScriptRoot 'export_pous.py')`"",
    "exit /b %ERRORLEVEL%"
), [System.Text.Encoding]::ASCII)
cmd /c $bat
$code = $LASTEXITCODE

$logPath = Join-Path $work ((Get-ExportName $file.BaseName) + '_export_log.txt')
if (Test-Path $logPath) {
    Write-Host "---- export log ----"
    Get-Content $logPath -Encoding UTF8
}
if ($code -ne 0) { Write-Host "CODESYS exit code: $code"; exit $code }

# stamp on success: the import side uses it to detect "project newer than last export"
$stamp = Join-Path $work ((Get-ExportName $file.BaseName) + '_lastexport.txt')
[System.IO.File]::WriteAllText($stamp, "stamped=$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')`nsource=$($file.FullName)`n")
Write-Host "Export done: $outDir"
