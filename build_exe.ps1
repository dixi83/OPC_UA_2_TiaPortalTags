$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$portablePython = Join-Path $root ".python\python.exe"
$buildWork = Join-Path $env:TEMP ("opc-ua-export-" + [guid]::NewGuid().ToString("N"))

if (Test-Path $portablePython) {
    $python = $portablePython
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python was not found. Install Python 3.10 or later and install requirements-build.txt."
    }
    $python = $pythonCommand.Source
}

& $python -m PyInstaller `
    --clean `
    --noconfirm `
    --onefile `
    --windowed `
    --icon (Join-Path $root "assets\branding\icon.ico") `
    --add-data ("$(Join-Path $root 'assets\branding\icon.ico');assets\branding") `
    --name OPC_UA_TIA_Export `
    --distpath (Join-Path $root "dist") `
    --workpath $buildWork `
    --specpath (Join-Path $root ".tmp\pyinstaller") `
    (Join-Path $root "opc_ua_export_app.py")

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

Copy-Item -LiteralPath (Join-Path $root "generic_tia_hmi_template.xlsx") -Destination (Join-Path $root "dist\generic_tia_hmi_template.xlsx") -Force
Copy-Item -LiteralPath (Join-Path $root "LICENSE.md") -Destination (Join-Path $root "dist\LICENSE.md") -Force
Write-Host "GUI executable and license created in dist"
