#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$REPO_DIR/birdnet/bin/python3"

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Installs BirdNET-Pi from this checkout, then applies the Birddog collage
dashboard customizations.

Options:
  --gemini-key KEY        install a Gemini API key for image generation
  --gemini-key-file PATH  install a Gemini API key from a local file
  --check                 run preflight checks without installing anything
  --skip-birdnet          skip the base BirdNET-Pi install step
  --skip-python-deps      skip the extra Birddog Python dependency pass
  -h, --help              show this help

Typical fresh Pi setup:
  cd ~
  git clone https://github.com/dlbone/birddog.git BirdNET-Pi
  cd BirdNET-Pi
  ./install.sh --gemini-key-file ~/gemini_api_key

You can also export GEMINI_API_KEY before running ./install.sh.
EOF
}

need_arg() {
  local opt="$1"
  local value="${2:-}"
  if [ -z "$value" ] || [[ "$value" == --* ]]; then
    echo "$opt requires a value." >&2
    usage
    exit 2
  fi
}

GEMINI_KEY=""
GEMINI_KEY_FILE=""
SKIP_BIRDNET=0
SKIP_DEPS=0
CHECK_ONLY=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --gemini-key) shift; need_arg "--gemini-key" "${1:-}"; GEMINI_KEY="$1" ;;
    --gemini-key-file) shift; need_arg "--gemini-key-file" "${1:-}"; GEMINI_KEY_FILE="$1" ;;
    --check) CHECK_ONLY=1 ;;
    --skip-birdnet) SKIP_BIRDNET=1 ;;
    --skip-python-deps) SKIP_DEPS=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

if [ "$GEMINI_KEY" ] && [ "$GEMINI_KEY_FILE" ]; then
  echo "Use either --gemini-key or --gemini-key-file, not both." >&2
  exit 2
fi

preflight() {
  local ok=1
  local arch
  arch="$(uname -m)"

  if [ "$EUID" = 0 ]; then
    echo "FAIL non-root user: run as the Pi user, not root."
    ok=0
  else
    echo "OK   non-root user"
  fi

  if [ "$arch" = "aarch64" ] || [ "$arch" = "x86_64" ]; then
    echo "OK   64-bit architecture: $arch"
  else
    echo "FAIL 64-bit architecture required; found $arch"
    ok=0
  fi

  for cmd in git python3 sudo; do
    if command -v "$cmd" >/dev/null 2>&1; then
      echo "OK   command available: $cmd"
    else
      echo "FAIL missing command: $cmd"
      ok=0
    fi
  done

  if command -v sudo >/dev/null 2>&1; then
    if sudo -n true 2>/dev/null; then
      echo "OK   sudo credentials available"
    else
      echo "WARN sudo is installed but credentials are not cached; install will prompt"
    fi
  fi

  if command -v arecord >/dev/null 2>&1; then
    if arecord -l 2>/dev/null | grep -qiE 'card [0-9]'; then
      echo "OK   ALSA recording device visible"
    else
      echo "WARN no ALSA recording device visible; plug in a USB mic before expecting detections"
    fi
  else
    echo "WARN arecord is not installed yet; microphone check skipped"
  fi

  if [ -r /proc/meminfo ]; then
    local mem_kb
    mem_kb="$(awk '/^MemTotal:/ { print $2 }' /proc/meminfo)"
    if [ -n "$mem_kb" ] && [ "$mem_kb" -ge 900000 ]; then
      echo "OK   memory available: $((mem_kb / 1024)) MB"
    else
      echo "WARN low memory detected; Raspberry Pi 4/5 with at least 1 GB is recommended"
    fi
  fi

  if command -v df >/dev/null 2>&1; then
    local free_kb
    free_kb="$(df -Pk "$REPO_DIR" | awk 'NR == 2 { print $4 }')"
    if [ -n "$free_kb" ] && [ "$free_kb" -ge 4194304 ]; then
      echo "OK   disk space available: $((free_kb / 1024)) MB"
    else
      echo "WARN low disk space detected; keep at least 4 GB free for install and recordings"
    fi
  fi

  for path in \
    "$REPO_DIR/scripts/install_birdnet.sh" \
    "$REPO_DIR/scripts/install_birddog_customizations.sh" \
    "$REPO_DIR/scripts/bird_collage.py" \
    "$REPO_DIR/requirements_custom.txt" \
    "$REPO_DIR/config/bird_collage_style.txt"
  do
    if [ -e "$path" ]; then
      echo "OK   found ${path#$REPO_DIR/}"
    else
      echo "FAIL missing ${path#$REPO_DIR/}"
      ok=0
    fi
  done

  if [ "$GEMINI_KEY_FILE" ]; then
    if [ -f "$GEMINI_KEY_FILE" ]; then
      echo "OK   Gemini key file exists"
    else
      echo "FAIL Gemini key file not found: $GEMINI_KEY_FILE"
      ok=0
    fi
  elif [ "$GEMINI_KEY" ]; then
    echo "OK   Gemini key provided as argument"
  elif [ "${GEMINI_API_KEY:-}" ]; then
    echo "OK   Gemini key provided by GEMINI_API_KEY"
  elif [ -s /etc/birdnet/gemini_api_key ]; then
    echo "OK   existing /etc/birdnet/gemini_api_key"
  else
    echo "WARN no Gemini key provided; detection works, new image generation will be skipped"
  fi

  if [ -x "$PYTHON_BIN" ]; then
    echo "OK   existing BirdNET virtualenv"
  else
    echo "INFO BirdNET virtualenv not found; base install will create it"
  fi

  if [ "$ok" -eq 1 ]; then
    echo "Preflight passed."
    return 0
  fi
  echo "Preflight failed."
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

if [ "$SKIP_BIRDNET" -eq 0 ]; then
  if [ -x "$PYTHON_BIN" ]; then
    echo "BirdNET virtualenv already exists; skipping base install."
  else
    echo "Installing base BirdNET-Pi from this checkout..."
    "$REPO_DIR/scripts/install_birdnet.sh"
  fi
else
  echo "Skipping base BirdNET-Pi install."
fi

custom_args=()
if [ "$SKIP_DEPS" -eq 0 ]; then
  custom_args+=(--install-python-deps)
fi
if [ "$GEMINI_KEY" ]; then
  custom_args+=(--gemini-key "$GEMINI_KEY")
fi
if [ "$GEMINI_KEY_FILE" ]; then
  custom_args+=(--gemini-key-file "$GEMINI_KEY_FILE")
fi

"$REPO_DIR/scripts/install_birddog_customizations.sh" "${custom_args[@]}"

echo "Birddog install complete."
echo "Open http://birddog.local or the Pi's IP address from your browser."
