#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
  echo "Creating virtual environment at .venv"
  python3 -m venv "$ROOT_DIR/.venv"
fi

PYTHON="$ROOT_DIR/.venv/bin/python"
"$PYTHON" -m pip install --upgrade pip setuptools wheel
"$PYTHON" -m pip install -r requirements-dev.txt

"$PYTHON" -m PyInstaller \
  --clean \
  --onefile \
  --name diskman \
  --distpath bin \
  --paths src \
  --collect-all rich \
  src/diskman/cli.py

echo "Binary created at: $ROOT_DIR/bin/diskman"
