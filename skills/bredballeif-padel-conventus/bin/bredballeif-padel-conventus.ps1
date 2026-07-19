$ErrorActionPreference = 'Stop'

$SkillDir = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $SkillDir 'scripts') + [IO.Path]::PathSeparator + $env:PYTHONPATH

$AllowedActions = @('-h', '--help', 'search', 'list', 'stats', 'compare', 'budget-report')
if ($args.Count -lt 1 -or $args[0] -notin $AllowedActions) {
    Write-Error 'Afvist: standard-wrapperen tillader kun read-only Conventus-actions.'
}

python -m agent @args
