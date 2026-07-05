$ErrorActionPreference = 'Stop'

$WorkspaceRoot = Split-Path -Parent $PSScriptRoot
$ManifestPath = Join-Path $WorkspaceRoot 'skills.manifest.json'
$CacheRoot = Join-Path $WorkspaceRoot '.skills-cache'

if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw "Manifest ikke fundet: $ManifestPath"
}

$Manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $CacheRoot | Out-Null

foreach ($Skill in $Manifest.skills) {
    $Name = [string]$Skill.name
    $Repo = [string]$Skill.repo
    $Ref = [string]$Skill.ref
    $ClonePath = Join-Path $CacheRoot $Name

    if (-not (Test-Path -LiteralPath (Join-Path $ClonePath '.git'))) {
        git clone $Repo $ClonePath
    } else {
        git -C $ClonePath fetch --all --tags --prune
    }

    git -C $ClonePath checkout $Ref
    git -C $ClonePath pull --ff-only 2>$null

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

        New-Item -ItemType Junction -Path $LinkPath -Target $ClonePath | Out-Null
        Write-Host "Synced $Name -> $LinkPath"
    }
}
