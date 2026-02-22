#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_SRC="$ROOT_DIR/bin/diskman"
TARGET="${1:-/usr/local/bin/diskman}"

if [[ ! -x "$BIN_SRC" ]]; then
  echo "Binary not found at $BIN_SRC"
  echo "Build it first: ./scripts/build_binary.sh"
  exit 1
fi

if [[ "$EUID" -ne 0 ]]; then
  echo "Installing to $TARGET with sudo"
  sudo install -m 0755 "$BIN_SRC" "$TARGET"
else
  install -m 0755 "$BIN_SRC" "$TARGET"
fi

echo "Installed: $TARGET"
"$TARGET" --help | sed -n '1,8p'
