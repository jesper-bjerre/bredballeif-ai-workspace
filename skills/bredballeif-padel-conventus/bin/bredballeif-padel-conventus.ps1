$ErrorActionPreference = 'Stop'

$SkillDir = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $SkillDir 'scripts') + [IO.Path]::PathSeparator + $env:PYTHONPATH

$AllowedActions = @('-h', '--help', 'search', 'list', 'stats', 'compare', 'budget-report')
if ($args.Count -lt 1 -or $args[0] -notin $AllowedActions) {
    Write-Error 'Afvist: standard-wrapperen tillader kun read-only Conventus-actions.'
}

$WorkspaceDir = Split-Path -Parent (Split-Path -Parent $SkillDir)
$VenvPython = Join-Path $WorkspaceDir '.venv/Scripts/python.exe'
if ($env:BIF_PYTHON_BIN) {
    $PythonBin = $env:BIF_PYTHON_BIN
} elseif (Test-Path -LiteralPath $VenvPython) {
    $PythonBin = $VenvPython
} else {
    $PythonBin = 'python'
}
& $PythonBin -m agent @args
exit $LASTEXITCODE
