#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

APP_BUNDLE_ID="${APP_BUNDLE_ID:-io.github.devvgwardo.hermes-installer}"
VENV_DIR="${ROOT_DIR}/.venv"

python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pip install pyte

pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "Hermes Installer" \
  --osx-bundle-identifier "$APP_BUNDLE_ID" \
  --add-data "hermes_installer/assets/banner.png:hermes_installer/assets" \
  --hidden-import pyte \
  --hidden-import wcwidth \
  hermes_installer/app.py

ditto -c -k --keepParent "dist/Hermes Installer.app" "dist/Hermes-Installer-macOS.zip"
echo "Created dist/Hermes-Installer-macOS.zip"
