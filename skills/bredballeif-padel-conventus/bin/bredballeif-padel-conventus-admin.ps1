$ErrorActionPreference = 'Stop'

$SkillDir = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $SkillDir 'scripts') + [IO.Path]::PathSeparator + $env:PYTHONPATH

$AllowedActions = @('-h', '--help', 'create-americano', 'create-mexicano', 'create-group')
if ($args.Count -lt 1 -or $args[0] -notin $AllowedActions) {
    Write-Error 'Afvist: admin-wrapperen tillader kun Conventus write-actions og kræver gatewayapproval.'
}

python -m agent @args
