#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="${HOME:-/home/admin}"
PYTHON_BIN="$REPO_DIR/birdnet/bin/python3"
COLLAGE_DIR="$HOME_DIR/BirdSongs/Extracted/collage"
STREAM_DIR="$HOME_DIR/BirdSongs/StreamData"
STYLE_SRC="$REPO_DIR/config/bird_collage_style.txt"
STYLE_DST="/etc/birdnet/bird_collage_style.txt"
COLLAGE_TIMER_SRC="$REPO_DIR/templates/birdnet_collage.timer"
COLLAGE_SERVICE_DST="/etc/systemd/system/birdnet_collage.service"
COLLAGE_TIMER_DST="/etc/systemd/system/birdnet_collage.timer"
INSTALL_USER="$(id -un)"
INSTALL_GROUP="$(id -gn)"

usage() {
  cat <<'EOF'
Usage: scripts/install_birddog_customizations.sh [options]

Applies the custom BirdNET-Pi collage/dashboard files after a fresh BirdNET-Pi
install or after cloning this repo on a rebuilt Raspberry Pi.

Options:
  --check                 run preflight checks without installing anything
  --install-python-deps   pip install requirements_custom.txt into birdnet venv
  --restore-cache PATH    restore a tar.gz made from BirdSongs/Extracted/collage
  --gemini-key KEY        install a Gemini API key for image generation
  --gemini-key-file PATH  install a Gemini API key from a local file
EOF
}

INSTALL_DEPS=0
RESTORE_CACHE=""
GEMINI_KEY=""
GEMINI_KEY_FILE=""
CHECK_ONLY=0

need_arg() {
  local opt="$1"
  local value="${2:-}"
  if [ -z "$value" ] || [[ "$value" == --* ]]; then
    echo "$opt requires a value." >&2
    usage
    exit 2
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --check) CHECK_ONLY=1 ;;
    --install-python-deps) INSTALL_DEPS=1 ;;
    --restore-cache) shift; need_arg "--restore-cache" "${1:-}"; RESTORE_CACHE="$1" ;;
    --gemini-key) shift; need_arg "--gemini-key" "${1:-}"; GEMINI_KEY="$1" ;;
    --gemini-key-file) shift; need_arg "--gemini-key-file" "${1:-}"; GEMINI_KEY_FILE="$1" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

if [ -n "$GEMINI_KEY" ] && [ -n "$GEMINI_KEY_FILE" ]; then
  echo "Use either --gemini-key or --gemini-key-file, not both." >&2
  exit 2
fi

preflight() {
  local ok=1
  local stream_unit="unknown"

  if [ "$EUID" = 0 ]; then
    echo "FAIL non-root user: run as the Pi user, not root."
    ok=0
  else
    echo "OK   non-root user"
  fi

  for cmd in sudo systemctl; do
    if command -v "$cmd" >/dev/null 2>&1; then
      echo "OK   command available: $cmd"
    else
      echo "FAIL missing command: $cmd"
      ok=0
    fi
  done

  if command -v systemd-escape >/dev/null 2>&1; then
    stream_unit="$(systemd-escape -p --suffix=mount "$STREAM_DIR")"
    echo "OK   command available: systemd-escape"
  else
    echo "WARN missing command: systemd-escape; StreamData tmpfs mount will be skipped"
  fi

  for path in "$STYLE_SRC" "$COLLAGE_TIMER_SRC" "$REPO_DIR/scripts/bird_collage.py" "$REPO_DIR/requirements_custom.txt"; do
    if [ -e "$path" ]; then
      echo "OK   found ${path#$REPO_DIR/}"
    else
      echo "FAIL missing ${path#$REPO_DIR/}"
      ok=0
    fi
  done

  if [ "$INSTALL_DEPS" -eq 1 ]; then
    if [ -x "$PYTHON_BIN" ]; then
      echo "OK   BirdNET virtualenv python exists"
    else
      echo "FAIL missing BirdNET virtualenv python at $PYTHON_BIN"
      ok=0
    fi
  elif [ -x "$PYTHON_BIN" ]; then
    echo "OK   BirdNET virtualenv python exists"
  else
    echo "INFO BirdNET virtualenv python not present yet"
  fi

  if [ "$GEMINI_KEY_FILE" ]; then
    if [ -f "$GEMINI_KEY_FILE" ]; then
      echo "OK   Gemini key file exists"
    else
      echo "FAIL Gemini key file not found: $GEMINI_KEY_FILE"
      ok=0
    fi
  elif [ "$GEMINI_KEY" ]; then
    echo "OK   Gemini key provided as argument"
  elif [ -s /etc/birdnet/gemini_api_key ]; then
    echo "OK   existing /etc/birdnet/gemini_api_key"
  else
    echo "WARN no Gemini key provided; image generation will be skipped until one is installed"
  fi

  if [ "$RESTORE_CACHE" ]; then
    if [ -f "$RESTORE_CACHE" ]; then
      echo "OK   restore cache archive exists"
    else
      echo "FAIL restore cache archive not found: $RESTORE_CACHE"
      ok=0
    fi
  fi

  echo "INFO collage cache directory: $COLLAGE_DIR"
  echo "INFO stream data directory: $STREAM_DIR"
  echo "INFO stream mount unit: $stream_unit"
  echo "INFO collage timer unit: birdnet_collage.timer"
  echo "INFO install user/group: $INSTALL_USER:$INSTALL_GROUP"

  if [ "$ok" -eq 1 ]; then
    echo "Customization preflight passed."
    return 0
  fi
  echo "Customization preflight failed."
  return 1
}

ensure_sudo() {
  if ! sudo -v; then
    echo "Could not validate sudo credentials." >&2
    exit 1
  fi
}

if [ "$CHECK_ONLY" -eq 1 ]; then
  preflight
  exit $?
fi

preflight
ensure_sudo

mkdir -p "$COLLAGE_DIR/images"
mkdir -p "$STREAM_DIR"
sudo mkdir -p /etc/birdnet

if [ -n "$GEMINI_KEY" ]; then
  tmp_key="$(mktemp)"
  trap 'rm -f "$tmp_key"' EXIT
  printf '%s\n' "$GEMINI_KEY" > "$tmp_key"
  chmod 600 "$tmp_key"
  sudo install -m 0600 "$tmp_key" /etc/birdnet/gemini_api_key
elif [ -n "$GEMINI_KEY_FILE" ]; then
  if [ ! -f "$GEMINI_KEY_FILE" ]; then
    echo "Gemini key file not found: $GEMINI_KEY_FILE" >&2
    exit 1
  fi
  sudo install -m 0600 "$GEMINI_KEY_FILE" /etc/birdnet/gemini_api_key
fi

if [ -f "$STYLE_SRC" ]; then
  sudo install -m 0644 "$STYLE_SRC" "$STYLE_DST"
fi

install_stream_mount() {
  if ! command -v systemd-escape >/dev/null 2>&1; then
    echo "systemd-escape not found; skipping StreamData tmpfs mount." >&2
    return 0
  fi
  local mount_unit
  local mount_dst
  local tmp_unit
  mount_unit="$(systemd-escape -p --suffix=mount "$STREAM_DIR")"
  mount_dst="/etc/systemd/system/$mount_unit"
  tmp_unit="$(mktemp)"
  cat > "$tmp_unit" <<EOF
[Unit]
Description=BirdNET tmpfs for transient stream files
ConditionPathExists=$STREAM_DIR

[Mount]
What=tmpfs
Where=$STREAM_DIR
Type=tmpfs
Options=mode=1777,nosuid,nodev

[Install]
WantedBy=multi-user.target
EOF
  sudo install -m 0644 "$tmp_unit" "$mount_dst"
  rm -f "$tmp_unit"
  sudo systemctl daemon-reload
  sudo systemctl enable "$mount_unit" >/dev/null 2>&1 || true
}

install_collage_timer() {
  if [ ! -f "$COLLAGE_TIMER_SRC" ]; then
    echo "Missing $COLLAGE_TIMER_SRC; skipping collage timer install." >&2
    return 0
  fi
  local tmp_service
  tmp_service="$(mktemp)"
  cat > "$tmp_service" <<EOF
[Unit]
Description=Birddog collage index and image refresh
After=birdnet_analysis.service

[Service]
Type=oneshot
User=$INSTALL_USER
Group=$INSTALL_GROUP
Environment=HOME=$HOME_DIR
WorkingDirectory=$REPO_DIR
ExecStart=$PYTHON_BIN $REPO_DIR/scripts/bird_collage.py --all-ranges --limit 28 --generate --variant both --max-new 2
EOF
  sudo install -m 0644 "$tmp_service" "$COLLAGE_SERVICE_DST"
  rm -f "$tmp_service"
  sudo install -m 0644 "$COLLAGE_TIMER_SRC" "$COLLAGE_TIMER_DST"
  sudo systemctl daemon-reload
  sudo systemctl enable --now birdnet_collage.timer >/dev/null 2>&1 || true
}

install_stream_mount
install_collage_timer

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
