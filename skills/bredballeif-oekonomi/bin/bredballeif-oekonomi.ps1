$ErrorActionPreference = 'Stop'
$SkillsDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$AllowedActions = @('budget-report', '-h', '--help')
if ($args.Count -lt 1 -or $args[0] -notin $AllowedActions) {
    Write-Error 'Afvist: økonomi-wrapperen tillader kun read-only budget-report.'
}
if ($args[0] -in @('-h', '--help')) {
    Write-Output 'Brug: bredballeif-oekonomi.ps1 budget-report --department <afdeling> [--year YYYY] [--years 1..3]'
    exit 0
}
& (Join-Path $SkillsDir 'bredballeif-padel-conventus/bin/bredballeif-padel-conventus.ps1') @args
exit $LASTEXITCODE
