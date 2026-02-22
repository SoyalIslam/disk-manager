#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REPOSITORY_URL="${REPOSITORY_URL:-https://upload.pypi.org/legacy/}"

if [[ -z "${TWINE_USERNAME:-}" || -z "${TWINE_PASSWORD:-}" ]]; then
  echo "TWINE_USERNAME and TWINE_PASSWORD must be set."
  echo "Example: TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-... ./scripts/publish_pypi.sh"
  exit 1
fi

if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
  echo "Creating virtual environment at .venv"
  python3 -m venv "$ROOT_DIR/.venv"
fi

PYTHON="$ROOT_DIR/.venv/bin/python"
"$PYTHON" -m pip install --upgrade pip setuptools wheel
"$PYTHON" -m pip install --upgrade build twine

OUT_DIR="$ROOT_DIR/packages"
rm -rf "$OUT_DIR" build/*
mkdir -p "$OUT_DIR"

"$PYTHON" -m build --outdir "$OUT_DIR"
"$PYTHON" -m twine check "$OUT_DIR"/*
"$PYTHON" -m twine upload --repository-url "$REPOSITORY_URL" "$OUT_DIR"/*

echo "Published successfully: $REPOSITORY_URL"
