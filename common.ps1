# common.ps1 - shared helpers for codesys-sync scripts (dot-source this file)
# Resolves the CODESYS installation without hardcoding any machine path:
#   1) explicit -CodesysExe / -Profile parameters
#   2) environment variables CODESYS_SYNC_EXE / CODESYS_SYNC_PROFILE
#   3) auto-detect: newest "CODESYS 3.5*" install under Program Files,
#      profile taken from <install>\CODESYS\Profiles\*.profile.xml

function Resolve-CodesysInstall {
    param(
        [string]$Exe = "",
        [string]$ProfileName = ""
    )
    if (-not $Exe)    { $Exe = $env:CODESYS_SYNC_EXE }
    if (-not $ProfileName) { $ProfileName = $env:CODESYS_SYNC_PROFILE }

    if (-not $Exe) {
        # some hosts (elevated/restricted shells) do not inject $env:ProgramFiles
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
                    if (Test-Path $exeCandidate) { $found += Get-Item $exeCandidate }
                }
        }
        if ($found.Count -eq 0) {
            throw "No CODESYS 3.5 installation found. Pass -CodesysExe with the CODESYS.exe path, or set CODESYS_SYNC_EXE."
        }
        $sorted = $found | Sort-Object {
            $m = [regex]::Match($_.FullName, 'CODESYS 3\.5\.(\d+)')
            if ($m.Success) { [int]$m.Groups[1].Value } else { 0 }
        } -Descending
        $Exe = $sorted[0].FullName
    }
    if (-not (Test-Path $Exe)) { throw "CODESYS.exe not found: $Exe" }

    if (-not $ProfileName) {
        $commonDir = Split-Path -Parent $Exe            # ...\CODESYS\Common
        $csDir     = Split-Path -Parent $commonDir       # ...\CODESYS
        $profDir   = Join-Path $csDir "Profiles"
        $pf = Get-ChildItem $profDir -Filter "*.profile.xml" -File -ErrorAction SilentlyContinue |
              Sort-Object Name -Descending | Select-Object -First 1
        if (-not $pf) {
            throw "No profile found in $profDir. Pass -Profile (name = the .profile.xml file name), or set CODESYS_SYNC_PROFILE."
        }
        # "NAME.profile.xml" -> "NAME"
        $ProfileName = $pf.Name -replace '\.profile\.xml$', ''
    }

    [pscustomobject]@{ Exe = $Exe; Profile = $ProfileName }
}
