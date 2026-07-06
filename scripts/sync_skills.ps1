$ErrorActionPreference = 'Stop'

$WorkspaceRoot = Split-Path -Parent $PSScriptRoot
$ManifestPath = Join-Path $WorkspaceRoot 'skills.manifest.json'

if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw "Manifest ikke fundet: $ManifestPath"
}

$Manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json

foreach ($Skill in $Manifest.skills) {
    $Name = [string]$Skill.name
    $Source = [string]$Skill.source
    if ([string]::IsNullOrWhiteSpace($Source)) {
        $Source = "skills/$Name"
    }

    $SourcePath = Join-Path $WorkspaceRoot $Source
    if (-not (Test-Path -LiteralPath $SourcePath)) {
        throw "Skill-kilde ikke fundet for ${Name}: $SourcePath"
    }

    foreach ($Target in $Skill.targets) {
        $TargetDir = Join-Path $WorkspaceRoot ([string]$Target)
        $LinkPath = Join-Path $TargetDir $Name
        New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

        if (Test-Path -LiteralPath $LinkPath) {
            $Existing = Get-Item -LiteralPath $LinkPath -Force
            if ($Existing.LinkType -eq 'Junction' -or $Existing.LinkType -eq 'SymbolicLink') {
                Remove-Item -LiteralPath $LinkPath -Force
            } else {
                Write-Warning "Springer over $LinkPath fordi den findes og ikke er et link."
                continue
            }
        }

        New-Item -ItemType Junction -Path $LinkPath -Target $SourcePath | Out-Null
        Write-Host "Synced $Name -> $LinkPath"
    }
}
