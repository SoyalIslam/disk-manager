#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: ./scripts/package_release_binary.sh <version>"
  echo "Example: ./scripts/package_release_binary.sh 0.2.1"
  exit 1
fi

./scripts/build_binary.sh

OUT_DIR="$ROOT_DIR/release"
BIN_SRC="$ROOT_DIR/bin/diskman"
mkdir -p "$OUT_DIR"
BIN_NAME="diskman-linux-x86_64"
cp "$BIN_SRC" "$OUT_DIR/$BIN_NAME"
chmod +x "$OUT_DIR/$BIN_NAME"

tar -C "$OUT_DIR" -czf "$OUT_DIR/${BIN_NAME}-v${VERSION}.tar.gz" "$BIN_NAME"
sha256sum "$OUT_DIR/$BIN_NAME" > "$OUT_DIR/${BIN_NAME}.sha256"
sha256sum "$OUT_DIR/${BIN_NAME}-v${VERSION}.tar.gz" > "$OUT_DIR/${BIN_NAME}-v${VERSION}.tar.gz.sha256"

echo "Release binary: $OUT_DIR/$BIN_NAME"
echo "Release tar.gz: $OUT_DIR/${BIN_NAME}-v${VERSION}.tar.gz"
