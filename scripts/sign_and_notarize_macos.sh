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

SIGN_ATTEMPTS=3
SIGN_BACKOFF_SECONDS=20
sign_ok=0
for attempt in $(seq 1 "$SIGN_ATTEMPTS"); do
  echo "Signing attempt ${attempt}/${SIGN_ATTEMPTS}..."
  if codesign \
    --force \
    --deep \
    --options runtime \
    --timestamp \
    --entitlements "$ENTITLEMENTS_PATH" \
    --sign "$APPLE_DEVELOPER_ID_APP" \
    "$APP_PATH"; then
    sign_ok=1
    break
  fi
  if [[ "$attempt" -lt "$SIGN_ATTEMPTS" ]]; then
    echo "codesign failed (likely transient timestamp outage). Retrying in ${SIGN_BACKOFF_SECONDS}s..." >&2
    sleep "$SIGN_BACKOFF_SECONDS"
  fi
done

if [[ "$sign_ok" -ne 1 ]]; then
  echo "codesign failed after ${SIGN_ATTEMPTS} attempts." >&2
  exit 1
fi

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
