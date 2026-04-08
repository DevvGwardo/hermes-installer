# Hermes Installer

Desktop installer for [Hermes Agent](https://github.com/NousResearch/hermes-agent) on macOS and Windows.

This repo exists to give users a real click-install path:

- macOS: download `Hermes-Installer-macOS.zip`, open `Hermes Installer.app`, click `Install Hermes`
- Windows: download `Hermes-Installer-Windows.exe`, open it, click `Install Hermes`

Under the hood, the installer calls the official upstream install scripts from `NousResearch/hermes-agent`, then hands off to Hermes' own interactive setup commands so provider, OAuth, and model selection stay aligned with upstream behavior instead of being reimplemented here.

## What It Does

- Resolves the latest stable Hermes release from GitHub and installs that by default
- Downloads the official upstream installer script for the current platform
- Streams install logs into a desktop window
- Supports custom install directories and manual ref overrides
- Lets the user choose a post-install setup flow and opens Hermes into provider/model setup automatically
- Builds native desktop artifacts for macOS and Windows in GitHub Actions
- Publishes a simple GitHub Pages download site with OS-aware buttons

## Repo Layout

- `hermes_installer/` application code
- `tests/` unit tests for platform and command generation
- `scripts/` local build helpers
- `site/` static download page for GitHub Pages
- `.github/workflows/` CI, release, and Pages automation

## Local Development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
pytest
python -m hermes_installer.cli plan
python -m hermes_installer.app
```

## Build Locally

macOS:

```bash
./scripts/build_macos.sh
```

To sign and notarize a local macOS build, export these env vars first and then run:

```bash
./scripts/sign_and_notarize_macos.sh
```

Windows:

```powershell
./scripts/build_windows.ps1
```

## Release Artifacts

The release workflow produces these assets:

- `Hermes-Installer-macOS.zip`
- `Hermes-Installer-Windows.exe`
- `SHA256SUMS.txt`

The static download page expects those exact names.

## macOS Signing And Notarization

Unsigned macOS apps trigger the Gatekeeper warning:

> Apple could not verify "Hermes Installer" is free of malware that may harm your Mac or compromise your privacy.

To ship a Gatekeeper-clean macOS build, configure these GitHub Actions secrets:

- `APPLE_DEVELOPER_ID_APP`
  Example: `Developer ID Application: Your Name (TEAMID)`
- `APPLE_DEVELOPER_ID_APP_CERT_P12_BASE64`
  Base64-encoded `.p12` certificate export containing the Developer ID Application cert
- `APPLE_DEVELOPER_ID_APP_CERT_PASSWORD`
  Password for that `.p12`
- `APPLE_NOTARY_APPLE_ID`
  Apple ID email used for notarization
- `APPLE_NOTARY_TEAM_ID`
  Apple Developer Team ID
- `APPLE_NOTARY_APP_PASSWORD`
  App-specific password for notary submission

Once those are set, tagged releases sign the `.app`, notarize it with Apple, staple the ticket, and then upload the notarized zip.

## Publishing

1. Push the repo to GitHub.
2. Create a release tag such as `v0.1.0`.
3. Let the `release.yml` workflow build and attach artifacts.
4. Enable GitHub Pages for the repo using the Actions workflow.
5. For trusted macOS downloads, set the Apple signing/notarization secrets before tagging a release.

## Notes

- The installer is a UI wrapper around the upstream Hermes install scripts, not a fork of Hermes itself.
- The installer defaults to the latest stable upstream Hermes release tag. If GitHub API resolution fails, it falls back to `main`.
- Hermes itself remains upstream in `NousResearch/hermes-agent`.
- Without Apple signing credentials configured, macOS artifacts will build but will not pass Gatekeeper verification.
