#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 -m pip install -r requirements-dev.txt

pyinstaller \
  --clean \
  --onefile \
  --name diskman \
  --paths src \
  --collect-all rich \
  src/diskman/cli.py

echo "Binary created at: $ROOT_DIR/dist/diskman"
