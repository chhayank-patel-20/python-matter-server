#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WHEELS_DIR="$ROOT/wheels"
VENV="$ROOT/.venv"
if [ ! -d "$WHEELS_DIR" ]; then
  echo "No wheels directory: $WHEELS_DIR"
  exit 1
fi
if [ ! -d "$VENV" ]; then
  echo "No venv found at $VENV. Create one with: python3 -m venv .venv"
  exit 1
fi
echo "Installing wheels from $WHEELS_DIR into venv $VENV"
"$VENV/bin/pip" install --force-reinstall --no-deps "$WHEELS_DIR"/*.whl
echo "Done."