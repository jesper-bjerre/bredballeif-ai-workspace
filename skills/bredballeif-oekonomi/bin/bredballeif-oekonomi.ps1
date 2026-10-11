$ErrorActionPreference = 'Stop'
$SkillsDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$AllowedActions = @('budget-report', 'board-report', '-h', '--help')
if ($args.Count -lt 1 -or $args[0] -notin $AllowedActions) {
    Write-Error 'Afvist: økonomi-wrapperen tillader kun budget-report og board-report.'
}
if ($args[0] -in @('-h', '--help')) {
    Write-Output 'Brug: bredballeif-oekonomi.ps1 budget-report --department <afdeling> [--year YYYY] [--years 1..3]'
    Write-Output '     bredballeif-oekonomi.ps1 board-report [--year YYYY] --output <privat-fil.pdf>'
    exit 0
}
if ($args[0] -eq 'board-report') {
    $env:PYTHONPATH = (Join-Path $PSScriptRoot '../scripts') + [IO.Path]::PathSeparator + $env:PYTHONPATH
    $WorkspaceDir = Split-Path -Parent $SkillsDir
    $VenvPython = Join-Path $WorkspaceDir '.venv/Scripts/python.exe'
    if ($env:BIF_PYTHON_BIN) {
        $PythonBin = $env:BIF_PYTHON_BIN
    } elseif (Test-Path -LiteralPath $VenvPython) {
        $PythonBin = $VenvPython
    } else {
        $PythonBin = 'python'
    }
    & $PythonBin -m bif_economy @args
    exit $LASTEXITCODE
}
& (Join-Path $SkillsDir 'bredballeif-padel-conventus/bin/bredballeif-padel-conventus.ps1') @args
exit $LASTEXITCODE
