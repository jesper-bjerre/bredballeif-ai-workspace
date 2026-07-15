$ErrorActionPreference = 'Stop'

$SkillDir = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $SkillDir 'scripts') + [IO.Path]::PathSeparator + $env:PYTHONPATH

if ($args.Count -ge 1 -and ($args[0] -eq '-h' -or $args[0] -eq '--help')) {
    python -m agent --help
    exit $LASTEXITCODE
}

if ($args.Count -lt 1) {
    Write-Error "Brug: bredballeif-padel-baner.ps1 DD-MM-YYYY [HH:MM-fra] [HH:MM-til]"
}

$Date = $args[0]
$From = if ($args.Count -ge 2) { $args[1] } else { $null }
$To = if ($args.Count -ge 3) { $args[2] } else { $null }

if ($Date -notmatch '^\d{2}-\d{2}-\d{4}$') {
    Write-Error "Fejl: dato skal være DD-MM-YYYY (fik: '$Date')"
}

$AgentArgs = @('availability', '--date', $Date)
if ($From) { $AgentArgs += @('--time-from', $From) }
if ($To) { $AgentArgs += @('--time-to', $To) }

python -m agent @AgentArgs
