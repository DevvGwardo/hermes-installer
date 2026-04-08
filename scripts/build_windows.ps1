$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

pyinstaller `
  --noconfirm `
  --clean `
  --windowed `
  --onefile `
  --name "Hermes Installer" `
  hermes_installer/app.py

Copy-Item "dist/Hermes Installer.exe" "dist/Hermes-Installer-Windows.exe" -Force
Write-Host "Created dist/Hermes-Installer-Windows.exe"

