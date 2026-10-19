# import.ps1 - write exported text back into a CODESYS project (codesys-sync)
# Usage:
#   interactive menu (pick a number):
#     powershell -NoProfile -ExecutionPolicy Bypass -File <codesys-sync>\import.ps1 -Root <repo>
#   only list projects under a directory/keyword (e.g. T2):
#     powershell -NoProfile -ExecutionPolicy Bypass -File <codesys-sync>\import.ps1 -Root <repo> -Dir T2
#   non-interactive:
#     powershell -NoProfile -ExecutionPolicy Bypass -File <codesys-sync>\import.ps1 -Root <repo> -Select 1 [-Yes] [-Sync] [-Force] [-VerifyBuild]
# NOTE: this writes the REAL project file under projects/ - close that project in the CODESYS IDE first!
# The script backs up the project file automatically; it only saves when actual changes passed
# the per-object write-back verification.
# CODESYS installation is auto-detected (override with -CodesysExe/-Profile or CODESYS_SYNC_EXE/CODESYS_SYNC_PROFILE).
[CmdletBinding()]
param(
    [string]$Root = "",
    [int]$Select = 0,
    [switch]$Yes,
    [string]$Dir = "",
    [string]$SrcRoot = "src/plc",
    [switch]$Sync,
    [switch]$Force,
    [switch]$VerifyBuild,
    [switch]$VerifyQuick,
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

# only list projects that already have an export directory (v2 layout is marked by _index.txt); -Dir filters by path keyword
$files = @(Get-ChildItem $projDir -File -Recurse | Where-Object { $_.Extension -in ".project", ".library" } | Sort-Object FullName |
    Where-Object { Test-Path (Join-Path (Get-OutDir $_) "_index.txt") })
if ($Dir -ne "") {
    $files = @($files | Where-Object { $_.FullName -like "*$Dir*" })
}
if ($files.Count -eq 0) { Write-Host "No importable projects (run export.ps1 first; old flat-layout exports must be re-exported)"; exit 1 }

Write-Host "Importable projects (writes the real project file - make sure the IDE has it closed):"
for ($i = 0; $i -lt $files.Count; $i++) {
    $out = Get-OutDir $files[$i]
    Write-Host ("  {0}. {1}  <-  {2}" -f ($i + 1), $files[$i].FullName.Substring($projDir.Length + 1), $out.Substring($root.Length + 1))
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

$opsFile = Join-Path $outDir "structure_ops.txt"
if (Test-Path $opsFile) {
    Write-Host "---- structure_ops.txt (these structure ops will run first) ----"
    Get-Content $opsFile -Encoding UTF8 | Where-Object { $_.Trim() -ne "" -and -not $_.Trim().StartsWith("#") } | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Host "(no structure_ops.txt - text write-back only)"
}

if (-not $Yes) {
    $ans = Read-Host "Import $($outDir.Substring($root.Length + 1)) into $($file.Name)? (y/N)"
    if ($ans -ne "y" -and $ans -ne "Y") { Write-Host "Cancelled"; exit 0 }
}

# target file for the IronPython script (path passed via CODESYS_SYNC_TARGET; the .py falls back to target.txt next to itself)
$utf8 = New-Object System.Text.UTF8Encoding $false
$work = Join-Path $root ".codesys-sync"
New-Item -ItemType Directory -Force -Path $work | Out-Null
$ename = Get-ExportName $file.BaseName
$logPath = Join-Path $work ($ename + '_import_log.txt')
$stampPath = Join-Path $work ($ename + '_lastexport.txt')
$targetFile = Join-Path $work "target.txt"
$env:CODESYS_SYNC_TARGET = $targetFile
$targetLines = @(
    "project=$($file.FullName)",
    "indir=$outDir",
    "log=$logPath",
    "lastexport=$stampPath"
)
if ($Sync)  { $targetLines += "sync=1" }
if ($Force) { $targetLines += "force=1" }
[System.IO.File]::WriteAllLines($targetFile, $targetLines, $utf8)

Write-Host "Importing $($file.Name) ... (about 1-2 minutes)"
# same as export.ps1: call a temp ASCII bat via cmd to dodge the PS 5.1 quoting problem
$bat = Join-Path $work "run_codesys.bat"
[System.IO.File]::WriteAllLines($bat, @(
    "@echo off",
    "`"$codesys`" --noUI --profile=`"$profile`" --runscript=`"$(Join-Path $PSScriptRoot 'import_pous.py')`"",
    "exit /b %ERRORLEVEL%"
), [System.Text.Encoding]::ASCII)
cmd /c $bat
$code = $LASTEXITCODE

if (Test-Path $logPath) {
    Write-Host "---- import log ----"
    Get-Content $logPath -Encoding UTF8
}
# CODESYS --runscript often exits 0 even when the script hit FATAL - trust the log, not the exit code
if (Test-Path $logPath) {
    $fatal = Select-String -Path $logPath -Pattern '^FATAL|^ABORTED' | Select-Object -First 1
    if ($fatal) { Write-Host "Import FAILED (log contains FATAL/ABORTED)"; exit 1 }
}
if ($code -ne 0) { Write-Host "CODESYS exit code: $code"; exit $code }
Write-Host "Import done, see $logPath"

if ($VerifyBuild -or $VerifyQuick) {
    $quick = $VerifyQuick -and -not $VerifyBuild
    if ($quick) {
        Write-Host "Running precompile quick check (-VerifyQuick) ... (about 30 seconds)"
        $scriptName = "check_project.py"
        $rname = $ename + '_check_report.txt'
    } else {
        Write-Host "Running full build check (-VerifyBuild) ... (about 1 minute)"
        $scriptName = "build_project.py"
        $rname = $ename + '_build_report.txt'
    }
    $buildReport = Join-Path $work $rname
    $buildTarget = Join-Path $work "target_build.txt"
    [System.IO.File]::WriteAllLines($buildTarget, @(
        "source=$($file.FullName)",
        "project=$($file.FullName)",
        "report=$buildReport"
    ), $utf8)
    $batB = Join-Path $work "run_build.bat"
    [System.IO.File]::WriteAllLines($batB, @(
        "@echo off",
        "set CODESYS_SYNC_TARGET=$buildTarget",
        "`"$codesys`" --noUI --profile=`"$profile`" --runscript=`"$(Join-Path $PSScriptRoot $scriptName)`"",
        "exit /b %ERRORLEVEL%"
    ), [System.Text.Encoding]::ASCII)
    cmd /c $batB | Out-Null
    if (-not (Test-Path $buildReport)) { Write-Host "Check report not generated"; exit 2 }
    $head = Get-Content $buildReport -Encoding UTF8 | Select-Object -First 6
    Write-Host "---- check report ----"
    $head | ForEach-Object { Write-Host $_ }
    $errLine = Get-Content $buildReport -Encoding UTF8 | Where-Object { $_ -like 'errors=*' } | Select-Object -First 1
    if ($errLine -eq 'errors=0') { Write-Host "Check passed"; exit 0 }
    Write-Host "Check FAILED (see $buildReport)"; exit 3
}
