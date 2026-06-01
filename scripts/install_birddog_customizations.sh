#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="${HOME:-/home/admin}"
PYTHON_BIN="$REPO_DIR/birdnet/bin/python3"
COLLAGE_DIR="$HOME_DIR/BirdSongs/Extracted/collage"
STYLE_SRC="$REPO_DIR/config/bird_collage_style.txt"
STYLE_DST="/etc/birdnet/bird_collage_style.txt"
MOUNT_SRC="$REPO_DIR/templates/home-admin-BirdSongs-StreamData.mount"
MOUNT_DST="/etc/systemd/system/home-admin-BirdSongs-StreamData.mount"
COLLAGE_SERVICE_SRC="$REPO_DIR/templates/birdnet_collage.service"
COLLAGE_TIMER_SRC="$REPO_DIR/templates/birdnet_collage.timer"
COLLAGE_SERVICE_DST="/etc/systemd/system/birdnet_collage.service"
COLLAGE_TIMER_DST="/etc/systemd/system/birdnet_collage.timer"

usage() {
  cat <<'EOF'
Usage: scripts/install_birddog_customizations.sh [--install-python-deps] [--restore-cache PATH]

Applies the custom BirdNET-Pi collage/dashboard files after a fresh BirdNET-Pi
install or after cloning this repo on a rebuilt Raspberry Pi.

Options:
  --install-python-deps   pip install requirements_custom.txt into birdnet venv
  --restore-cache PATH    restore a tar.gz made from BirdSongs/Extracted/collage
EOF
}

INSTALL_DEPS=0
RESTORE_CACHE=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --install-python-deps) INSTALL_DEPS=1 ;;
    --restore-cache) shift; RESTORE_CACHE="${1:-}" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

mkdir -p "$COLLAGE_DIR/images" /etc/birdnet

if [ -f "$STYLE_SRC" ]; then
  sudo install -m 0644 "$STYLE_SRC" "$STYLE_DST"
fi

if [ -f "$MOUNT_SRC" ]; then
  sudo install -m 0644 "$MOUNT_SRC" "$MOUNT_DST"
  sudo systemctl daemon-reload
  sudo systemctl enable home-admin-BirdSongs-StreamData.mount >/dev/null 2>&1 || true
fi

if [ -f "$COLLAGE_SERVICE_SRC" ] && [ -f "$COLLAGE_TIMER_SRC" ]; then
  sudo install -m 0644 "$COLLAGE_SERVICE_SRC" "$COLLAGE_SERVICE_DST"
  sudo install -m 0644 "$COLLAGE_TIMER_SRC" "$COLLAGE_TIMER_DST"
  sudo systemctl daemon-reload
  sudo systemctl enable --now birdnet_collage.timer >/dev/null 2>&1 || true
fi

if [ "$INSTALL_DEPS" -eq 1 ]; then
  if [ ! -x "$PYTHON_BIN" ]; then
    echo "Missing BirdNET virtualenv python at $PYTHON_BIN" >&2
    exit 1
  fi
  "$PYTHON_BIN" -m pip install -r "$REPO_DIR/requirements_custom.txt"
fi

if [ -n "$RESTORE_CACHE" ]; then
  mkdir -p "$COLLAGE_DIR"
  tar -xzf "$RESTORE_CACHE" -C "$COLLAGE_DIR"
fi

if [ -x "$PYTHON_BIN" ]; then
  "$PYTHON_BIN" -m py_compile "$REPO_DIR/scripts/bird_collage.py"
  "$PYTHON_BIN" "$REPO_DIR/scripts/bird_collage.py" --all-ranges --limit 28 || true
else
  echo "Skipped collage index build; $PYTHON_BIN is not present yet."
fi

echo "Birddog customizations installed."
