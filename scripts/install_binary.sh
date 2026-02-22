#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-}"
REPO="${2:-gaffer/disk-manager}"
TARGET="${TARGET:-/usr/local/bin/diskman}"
TMP="$(mktemp)"

if [[ -z "$VERSION" ]]; then
  echo "Usage: ./scripts/install_binary.sh <version> [owner/repo]"
  echo "Example: ./scripts/install_binary.sh 0.2.1 gaffer/disk-manager"
  exit 1
fi

URL="https://github.com/${REPO}/releases/download/v${VERSION}/diskman-linux-x86_64"
echo "Downloading: $URL"
curl -fL "$URL" -o "$TMP"
chmod +x "$TMP"

if [[ "$EUID" -ne 0 ]]; then
  echo "Installing with sudo to: $TARGET"
  sudo install -m 0755 "$TMP" "$TARGET"
else
  install -m 0755 "$TMP" "$TARGET"
fi

rm -f "$TMP"
echo "Installed: $TARGET"
"$TARGET" --help | sed -n '1,8p'
