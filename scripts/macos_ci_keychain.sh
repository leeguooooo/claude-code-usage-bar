#!/usr/bin/env bash
# Import only this job's encrypted signing material into a disposable keychain.
set -euo pipefail
umask 077

case "${1:-}" in
  prepare)
    for name in MACOS_CERTIFICATE_BASE64 MACOS_CERTIFICATE_PASSWORD ASC_KEY_P8_BASE64 ASC_KEY_ID; do
      [ -n "${!name:-}" ] || { echo "Missing signing secret: $name" >&2; exit 1; }
    done
    keychain="$RUNNER_TEMP/cs-signing.keychain-db"
    certificate="$RUNNER_TEMP/cs-signing.p12"
    api_key="$RUNNER_TEMP/cs-notary.p8"
    password="$(openssl rand -hex 24)"
    printf '::add-mask::%s\n' "$password"
    printf '%s' "$MACOS_CERTIFICATE_BASE64" | base64 --decode > "$certificate"
    printf '%s' "$ASC_KEY_P8_BASE64" | base64 --decode > "$api_key"
    security create-keychain -p "$password" "$keychain"
    security set-keychain-settings -lut 21600 "$keychain"
    security unlock-keychain -p "$password" "$keychain"
    security import "$certificate" -P "$MACOS_CERTIFICATE_PASSWORD" -T /usr/bin/codesign -k "$keychain" >/dev/null
    security set-key-partition-list -S apple-tool:,apple: -s -k "$password" "$keychain" >/dev/null
    security list-keychains -d user -s "$keychain" "$HOME/Library/Keychains/login.keychain-db"
    rm -f "$certificate"
    printf 'SIGNING_KEYCHAIN=%s\nASC_KEY_PATH=%s\n' "$keychain" "$api_key" >> "$GITHUB_ENV"
    ;;
  cleanup)
    security delete-keychain "$RUNNER_TEMP/cs-signing.keychain-db" >/dev/null 2>&1 || true
    rm -f "$RUNNER_TEMP/cs-signing.p12" "$RUNNER_TEMP/cs-notary.p8"
    ;;
  *) echo "Usage: $0 prepare|cleanup" >&2; exit 2 ;;
esac
