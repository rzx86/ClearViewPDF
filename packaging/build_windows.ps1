param([string]$DistPath = "dist")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Assert-NativeSuccess([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed with exit code $LASTEXITCODE" }
}

if (-not (Test-Path ".venv-win\Scripts\python.exe")) {
    py -3.10 -m venv .venv-win
    Assert-NativeSuccess "Virtual environment creation"
}
$python = Join-Path $root ".venv-win\Scripts\python.exe"
& $python -m pip install --upgrade pip
Assert-NativeSuccess "pip upgrade"
& $python -m pip install -e ".[build]"
Assert-NativeSuccess "Dependency installation"
& $python packaging\make_icon.py
Assert-NativeSuccess "Icon generation"
& $python -m PyInstaller --noconfirm --clean --windowed `
    --name ClearViewPDF `
    --distpath $DistPath `
    --icon packaging\clearview.ico `
    --add-data "clearview_pdf\assets;clearview_pdf\assets" `
    --collect-all fastembed `
    --collect-all onnxruntime `
    --collect-all tokenizers `
    launcher.py
Assert-NativeSuccess "PyInstaller build"

$exe = Join-Path $root (Join-Path $DistPath "ClearViewPDF\ClearViewPDF.exe")
if (-not (Test-Path $exe)) { throw "Expected executable was not created: $exe" }
Write-Host ""
Write-Host "Built: $exe"
