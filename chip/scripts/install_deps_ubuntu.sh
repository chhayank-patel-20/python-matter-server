#!/usr/bin/env bash
set -euo pipefail

readonly DEPS=(
  build-essential
  git
  python3
  python3-venv
  python3-pip
  ninja-build
  cmake
  clang
  gcc
  g++
  pkg-config
  libssl-dev
  libdbus-1-dev
  libexpat1-dev
  libudev-dev
  libusb-1.0-0-dev
  libglib2.0-dev
  libavahi-client-dev
  libavahi-common-dev
  curl
  unzip
  openjdk-11-jdk
)

echo "This script installs common Ubuntu packages needed to build connectedhomeip (chip)."
echo "Run as a user with sudo privileges."

sudo apt-get update
sudo apt-get install -y "${DEPS[@]}"

echo "Upgrading pip and installing Python build helpers..."
python3 -m pip install --user --upgrade pip setuptools wheel

echo "Done. If additional dependencies are required by your platform, add them to this script."
