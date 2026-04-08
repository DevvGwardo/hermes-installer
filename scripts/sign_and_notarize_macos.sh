#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

APP_PATH="dist/Hermes Installer.app"
ZIP_PATH="dist/Hermes-Installer-macOS.zip"
ENTITLEMENTS_PATH="packaging/macos/entitlements.plist"

: "${APPLE_DEVELOPER_ID_APP:?APPLE_DEVELOPER_ID_APP is required}"
: "${APPLE_NOTARY_APPLE_ID:?APPLE_NOTARY_APPLE_ID is required}"
: "${APPLE_NOTARY_TEAM_ID:?APPLE_NOTARY_TEAM_ID is required}"
: "${APPLE_NOTARY_APP_PASSWORD:?APPLE_NOTARY_APP_PASSWORD is required}"

if [[ ! -d "$APP_PATH" ]]; then
  echo "Missing app bundle at $APP_PATH" >&2
  exit 1
fi

codesign \
  --force \
  --deep \
  --options runtime \
  --timestamp \
  --entitlements "$ENTITLEMENTS_PATH" \
  --sign "$APPLE_DEVELOPER_ID_APP" \
  "$APP_PATH"

codesign --verify --deep --strict --verbose=2 "$APP_PATH"
spctl --assess --type exec --verbose=2 "$APP_PATH" || true

rm -f "$ZIP_PATH"
ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"

xcrun notarytool submit "$ZIP_PATH" \
  --apple-id "$APPLE_NOTARY_APPLE_ID" \
  --password "$APPLE_NOTARY_APP_PASSWORD" \
  --team-id "$APPLE_NOTARY_TEAM_ID" \
  --wait

xcrun stapler staple "$APP_PATH"

rm -f "$ZIP_PATH"
ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"
echo "Created notarized artifact at $ZIP_PATH"

