$ErrorActionPreference = 'Stop'

$SkillDir = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $SkillDir 'scripts') + [IO.Path]::PathSeparator + $env:PYTHONPATH

$AllowedActions = @('-h', '--help', 'discover', 'create', 'onboard', 'export', 'welcome-email', 'process-emails', 'book-court')
if ($args.Count -lt 1 -or $args[0] -notin $AllowedActions) {
    Write-Error 'Afvist: admin-wrapperen tillader kun godkendelsespligtige onboarding-actions.'
}

python -m agent @args
