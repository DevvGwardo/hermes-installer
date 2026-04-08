$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pip install pyte

$ManifestPath = Join-Path $Root "packaging\windows\hermes-installer.manifest"
$VersionFile  = Join-Path $Root "packaging\windows\version_info.txt"

pyinstaller `
  --noconfirm `
  --clean `
  --windowed `
  --onefile `
  --name "Hermes Installer" `
  --add-data "hermes_installer\assets\banner.png;hermes_installer\assets" `
  --hidden-import pyte `
  --hidden-import wcwidth `
  --manifest $ManifestPath `
  --version-file $VersionFile `
  hermes_installer/app.py

Copy-Item "dist/Hermes Installer.exe" "dist/Hermes-Installer-Windows.exe" -Force

# Code-sign the executable if a certificate is available.
# This is the most effective way to prevent SmartScreen warnings.
# To sign, set SIGNING_CERT to the sha1 thumbprint or subject name of your code-signing cert:
#   $env:SIGNING_CERT = "thumbprint"
#   .\scripts\build_windows.ps1
if (Test-Path env:SIGNING_CERT) {
    $Cert = $env:SIGNING_CERT
    Write-Host "Signing dist/Hermes-Installer-Windows.exe with certificate $Cert ..."
    signtool sign /sha1 $Cert /tr http://timestamp.digicert.com /td sha256 /fd sha256 "dist/Hermes-Installer-Windows.exe"
    signtool verify /pa "dist/Hermes-Installer-Windows.exe"
    Write-Host "Code signing succeeded."
} else {
    Write-Host "SIGNING_CERT not set — skipping code signing."
    Write-Host "To eliminate SmartScreen warnings, sign the executable with an EV code-signing certificate."
    Write-Host "  1. Obtain an EV code-signing certificate from a trusted CA (DigiCert, Sectigo, etc.)"
    Write-Host "  2. Set `$env:SIGNING_CERT to the certificate thumbprint or subject name"
    Write-Host "  3. Re-run this script"
}

Write-Host "Created dist/Hermes-Installer-Windows.exe"