#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

APP_BUNDLE_ID="${APP_BUNDLE_ID:-io.github.devvgwardo.hermes-installer}"

python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"

pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "Hermes Installer" \
  --osx-bundle-identifier "$APP_BUNDLE_ID" \
  hermes_installer/app.py

ditto -c -k --keepParent "dist/Hermes Installer.app" "dist/Hermes-Installer-macOS.zip"
echo "Created dist/Hermes-Installer-macOS.zip"
