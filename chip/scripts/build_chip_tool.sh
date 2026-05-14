#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 [--out OUT_DIR] [--python-out PY_OUT] [--install-venv VENV_PATH]

Build chip-tool and attempt to produce the controller Python wheel.

Options:
  --out OUT_DIR        Build output directory for host artifacts (default: out/host)
  --python-out DIR     Output directory for Python wheel (default: out/python_lib)
  --install-venv PATH  If provided, install the built wheel into this virtualenv
EOF
}

OUT=out/host
PY_OUT=out/python_lib
INSTALL_VENV=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2;;
    --python-out) PY_OUT="$2"; shift 2;;
    --install-venv) INSTALL_VENV="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 1;;
  esac
done

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CHIP_DIR="$ROOT_DIR/connectedhomeip"

echo "Using repo root: $ROOT_DIR"
echo "Building outputs: host=$OUT python=$PY_OUT"

mkdir -p "$CHIP_DIR/$OUT" "$CHIP_DIR/$PY_OUT"

pushd "$CHIP_DIR" >/dev/null

if ! command -v gn >/dev/null 2>&1; then
  echo "gn not found in PATH. If gn is not installed, run gn from depot_tools or install gn." >&2
fi

echo "Generating build files (gn gen $OUT)"
gn gen "$OUT" || true

echo "Building chip-tool (ninja -C $OUT chip-tool)"
if ninja -C "$OUT" chip-tool; then
  echo "chip-tool built: $CHIP_DIR/$OUT/chip-tool"
else
  echo "Warning: building chip-tool failed via ninja. Check build output." >&2
fi

# Try building the controller Python package via a ninja target, fallback to Python packaging
echo "Attempting to build Python wheel via ninja target 'controller_python_package'"
if ninja -C "$OUT" controller_python_package; then
  echo "ninja built the Python package into $OUT"
else
  echo "ninja target unavailable or failed. Falling back to Python packaging in src/controller/python if present."
  if [ -d src/controller/python ] && [ -f src/controller/python/setup.py ]; then
    pushd src/controller/python >/dev/null
    python3 -m pip install --user --upgrade pip setuptools wheel
    mkdir -p "$CHIP_DIR/$PY_OUT/controller/python"
    python3 setup.py bdist_wheel --dist-dir "$CHIP_DIR/$PY_OUT/controller/python"
    popd >/dev/null
  else
    echo "No setup.py found; cannot build wheel automatically. Check your repo build rules." >&2
  fi
fi

# If requested, install the built wheel into a venv
if [ -n "$INSTALL_VENV" ]; then
  if [ ! -d "$INSTALL_VENV" ]; then
    echo "Virtualenv not found at $INSTALL_VENV; creating one."
    python3 -m venv "$INSTALL_VENV"
  fi
  WHEEL_GLOB="$CHIP_DIR/$PY_OUT/controller/python/matter*.whl"
  WHEEL_PATH=$(ls $WHEEL_GLOB 2>/dev/null | head -n1 || true)
  if [ -z "$WHEEL_PATH" ]; then
    echo "No wheel found at $WHEEL_GLOB; nothing to install." >&2
  else
    echo "Installing wheel $WHEEL_PATH into venv $INSTALL_VENV"
    "$INSTALL_VENV/bin/pip" install "$WHEEL_PATH"
  fi
fi

popd >/dev/null

echo "Build script finished."
