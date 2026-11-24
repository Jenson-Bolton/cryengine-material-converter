param([switch]$SkipInstall, [string]$PythonExecutable = '')

$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $pythonPath = if ($PythonExecutable) {
        (Resolve-Path -LiteralPath $PythonExecutable -ErrorAction Stop).Path
    } else {
        Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    }
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        & python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Creating the Python environment failed.' }
    }
    if (-not $SkipInstall) {
        & $pythonPath -m pip install -r requirements-dev.txt
        if ($LASTEXITCODE -ne 0) { throw 'Installing build dependencies failed.' }
    }
    & $pythonPath tests\test_converter.py
    if ($LASTEXITCODE -ne 0) { throw 'Regression checks failed.' }
    & $pythonPath -m PyInstaller --noconfirm --onefile --windowed --name MaterialConverter --collect-all OpenImageIO --exclude-module numpy.f2py --exclude-module numpy.testing --distpath dist --workpath build --specpath build src\converter.py
    if ($LASTEXITCODE -ne 0) { throw 'Building MaterialConverter.exe failed.' }
    & $pythonPath scripts\collect_licenses.py dist\licenses
    if ($LASTEXITCODE -ne 0) { throw 'Collecting dependency notices failed.' }
    Copy-Item -LiteralPath README.md,LICENSE,THIRD_PARTY_NOTICES.md -Destination dist -Force
    Write-Output 'Built dist\MaterialConverter.exe and its documentation/licence notices.'
}
finally {
    Pop-Location
}
