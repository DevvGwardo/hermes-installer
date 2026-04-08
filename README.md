# Hermes Installer

Desktop installer for [Hermes Agent](https://github.com/NousResearch/hermes-agent) on macOS and Windows.

This repo exists to give users a real click-install path:

- macOS: download `Hermes-Installer-macOS.zip`, open `Hermes Installer.app`, click `Install Hermes`
- Windows: download `Hermes-Installer-Windows.exe`, open it, click `Install Hermes`

Under the hood, the installer calls the official upstream install scripts from `NousResearch/hermes-agent`, so the desktop UI stays aligned with the actual Hermes install flow instead of forking that logic.

## What It Does

- Resolves the latest stable Hermes release from GitHub and installs that by default
- Downloads the official upstream installer script for the current platform
- Streams install logs into a desktop window
- Supports custom install directories and manual ref overrides
- Opens a terminal window to run `hermes setup` or `hermes` after install
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

## Publishing

1. Push the repo to GitHub.
2. Create a release tag such as `v0.1.0`.
3. Let the `release.yml` workflow build and attach artifacts.
4. Enable GitHub Pages for the repo using the Actions workflow.

## Notes

- The installer is a UI wrapper around the upstream Hermes install scripts, not a fork of Hermes itself.
- The installer defaults to the latest stable upstream Hermes release tag. If GitHub API resolution fails, it falls back to `main`.
- Hermes itself remains upstream in `NousResearch/hermes-agent`.

