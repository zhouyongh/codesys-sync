# common.ps1 - shared helpers for codesys-sync scripts (dot-source this file)
# Resolves the CODESYS installation without hardcoding any machine path:
#   1) explicit -CodesysExe / -Profile parameters
#   2) environment variables CODESYS_SYNC_EXE / CODESYS_SYNC_PROFILE
#   3) auto-detect: match the project's LAST-SAVED compiler version
#      (project_settings.get_compilerversion) to the installed "CODESYS 3.5*"
#      whose version equals that compiler version. Falls back to a one-shot
#      probe that opens the project WITHOUT saving to read the version.
#      Profile taken from <install>\CODESYS\Profiles\*.profile.xml

function Get-CodesysInstalls {
    $bases = @()
    foreach ($v in @(
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)},
        $(if ($env:SystemDrive) { Join-Path $env:SystemDrive 'Program Files' }),
        $(if ($env:SystemDrive) { Join-Path $env:SystemDrive 'Program Files (x86)' }),
        'C:\Program Files',
        'C:\Program Files (x86)'
    )) {
        if ($v -and (Test-Path $v) -and ($bases -notcontains $v)) { $bases += $v }
    }
    $found = @()
    foreach ($base in $bases) {
        Get-ChildItem $base -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "CODESYS 3.5*" } | ForEach-Object {
                $exeCandidate = Join-Path $_.FullName "CODESYS\Common\CODESYS.exe"
                if (Test-Path $exeCandidate) {
                    $m = [regex]::Match($_.Name, 'CODESYS\s+(3\.5\.\d+\.\d+)')
                    $ver = if ($m.Success) { $m.Groups[1].Value } else { "0.0.0" }
                    $found += [pscustomobject]@{
                        Exe = $exeCandidate
                        Version = $ver
                        InstallName = $_.Name
                    }
                }
            }
    }
    # oldest first — probe order / stable listing
    $found | Sort-Object {
        $p = @($_.Version -split '\.') | ForEach-Object { [int]$_ }
        while ($p.Count -lt 4) { $p += 0 }
        ($p[0] * 1000000) + ($p[1] * 10000) + ($p[2] * 100) + $p[3]
    }
}

function Get-ProjectSavedVersion {
    # Return the project's last-saved compiler version (e.g. "3.5.22.40")
    # Sources (first hit wins):
    #   1) sidecar written by export: _project_info.txt  "compiler_version: ..."
    #   2) work-dir stamp <name>_lastexport.txt "compiler=..."
    #   3) one-shot probe via CODESYS --runscript (opens, reads, no save)
    param(
        [string]$ProjectFile,
        [string]$ExportInfo = "",
        [string]$StampFile = "",
        [string]$ProbeExe = "",
        [string]$ProbeProfile = ""
    )
    if (-not $ProjectFile -or -not (Test-Path $ProjectFile)) { return $null }

    # 1) export sidecar
    if ($ExportInfo -and (Test-Path $ExportInfo)) {
        $line = Select-String -Path $ExportInfo -Pattern '^\s*compiler_version\s*:\s*([0-9.]+)' |
                Select-Object -First 1
        if ($line) { return $line.Matches[0].Groups[1].Value }
    }
    # 2) work stamp
    if ($StampFile -and (Test-Path $StampFile)) {
        $line = Select-String -Path $StampFile -Pattern '^\s*compiler\s*=\s*([0-9.]+)' |
                Select-Object -First 1
        if ($line) { return $line.Matches[0].Groups[1].Value }
    }

    # 3) probe: open without saving, print get_compilerversion()
    if (-not $ProbeExe) {
        $installs = @(Get-CodesysInstalls)
        if ($installs.Count -eq 0) { return $null }
        # newest first — it can open older projects (upgrade-in-memory, no save)
        $probeInst = $installs | Sort-Object {
            $p = @($_.Version -split '\.') | ForEach-Object { [int]$_ }
            while ($p.Count -lt 4) { $p += 0 }
            ($p[0] * 1000000) + ($p[1] * 10000) + ($p[2] * 100) + $p[3]
        } -Descending | Select-Object -First 1
        $ProbeExe = $probeInst.Exe
        if (-not $ProbeProfile) {
            $ProbeProfile = Get-ProfileForExe $ProbeExe
        }
    }

    $skillDir = $PSScriptRoot
    $work = Join-Path (Split-Path -Parent $ProjectFile) ".codesys-sync-probe"
    if (-not (Test-Path $work)) { New-Item -ItemType Directory -Path $work | Out-Null }
    $target = Join-Path $work "probe_target.txt"
    $result = Join-Path $work "probe_result.txt"
    @(
        "project=$ProjectFile",
        "result=$result"
    ) | Set-Content -Path $target -Encoding UTF8

    $bat = Join-Path $work "run_probe.bat"
    @(
        "@echo off",
        "set CODESYS_SYNC_TARGET=$target",
        "`"$ProbeExe`" --noUI --profile=`"$ProbeProfile`" --runscript=`"$(Join-Path $skillDir 'probe_version.py')`"",
        "exit /b %ERRORLEVEL%"
    ) | Set-Content -Path $bat -Encoding ASCII

    $null = & cmd /c "`"$bat`"" 2>&1
    if (Test-Path $result) {
        $line = Select-String -Path $result -Pattern '^\s*compiler_version\s*=\s*([0-9.]+)' |
                Select-Object -First 1
        if ($line) { return $line.Matches[0].Groups[1].Value }
    }
    return $null
}

function Get-ProfileForExe {
    param([string]$Exe)
    $commonDir = Split-Path -Parent $Exe            # ...\CODESYS\Common
    $csDir     = Split-Path -Parent $commonDir       # ...\CODESYS
    $profDir   = Join-Path $csDir "Profiles"
    $pf = Get-ChildItem $profDir -Filter "*.profile.xml" -File -ErrorAction SilentlyContinue |
          Sort-Object Name | Select-Object -First 1
    if (-not $pf) {
        throw "No profile found in $profDir. Pass -Profile (name = the .profile.xml file name), or set CODESYS_SYNC_PROFILE."
    }
    $pf.Name -replace '\.profile\.xml$', ''
}

function Resolve-CodesysInstall {
    param(
        [string]$Exe = "",
        [string]$ProfileName = "",
        # when set, auto-detect picks the install matching this project's last-saved version
        [string]$ProjectFile = "",
        [string]$ExportInfo = "",
        [string]$StampFile = ""
    )
    if (-not $Exe)    { $Exe = $env:CODESYS_SYNC_EXE }
    if (-not $ProfileName) { $ProfileName = $env:CODESYS_SYNC_PROFILE }

    if (-not $Exe) {
        $installs = @(Get-CodesysInstalls)
        if ($installs.Count -eq 0) {
            throw "No CODESYS 3.5 installation found. Pass -CodesysExe with the CODESYS.exe path, or set CODESYS_SYNC_EXE."
        }

        $want = $null
        if ($ProjectFile) {
            $want = Get-ProjectSavedVersion -ProjectFile $ProjectFile `
                -ExportInfo $ExportInfo -StampFile $StampFile
        }

        if ($want) {
            # pick the install whose version equals the project's last-saved version
            $match = $installs | Where-Object { $_.Version -eq $want } | Select-Object -First 1
            if (-not $match) {
                # allow same major.minor.patch prefix (e.g. 3.5.22.40 vs 3.5.22.30)
                $prefix = ($want -split '\.')[0..2] -join '.'
                $match = $installs | Where-Object { $_.Version -like "$prefix*" } | Select-Object -First 1
            }
            if (-not $match) {
                $avail = ($installs | ForEach-Object { $_.Version }) -join ', '
                throw "No CODESYS install matches the project's last-saved version $want (installed: $avail). Pass -CodesysExe to pin an install."
            }
            $Exe = $match.Exe
            Write-Host "CODESYS install matched project version $want -> $($match.InstallName)"
        } else {
            # version unknown: fall back to the newest install and say so
            $newest = $installs | Select-Object -Last 1
            $Exe = $newest.Exe
            Write-Host "WARN: project version unknown; using newest install $($newest.InstallName) ($($newest.Version)). Pass -CodesysExe to pin."
        }
    }
    if (-not (Test-Path $Exe)) { throw "CODESYS.exe not found: $Exe" }

    if (-not $ProfileName) {
        $ProfileName = Get-ProfileForExe $Exe
    }

    [pscustomobject]@{ Exe = $Exe; Profile = $ProfileName }
}
