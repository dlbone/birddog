#!/usr/bin/env bash
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="${HOME:-$(dirname "$REPO_DIR")}"
failures=0
warnings=0

section() {
  printf '\n== %s ==\n' "$1"
}

ok() {
  printf 'OK   %s\n' "$1"
}

warn() {
  printf 'WARN %s\n' "$1"
  warnings=$((warnings + 1))
}

fail() {
  printf 'FAIL %s\n' "$1"
  failures=$((failures + 1))
}

have() {
  command -v "$1" >/dev/null 2>&1
}

check_file() {
  if [ -e "$1" ]; then
    ok "$2"
  else
    fail "$2 ($1 missing)"
  fi
}

check_optional_file() {
  if [ -e "$1" ]; then
    ok "$2"
  else
    warn "$2 ($1 missing)"
  fi
}

check_service() {
  local unit="$1"
  if ! have systemctl; then
    warn "systemctl not available; skipped $unit"
    return
  fi
  if systemctl list-unit-files "$unit" >/dev/null 2>&1; then
    if systemctl is-active --quiet "$unit"; then
      ok "$unit active"
    else
      warn "$unit installed but not active"
    fi
  else
    warn "$unit not installed"
  fi
}

check_http() {
  local label="$1"
  local url="$2"
  if ! have curl; then
    warn "curl not available; skipped $label"
    return
  fi
  local code
  code="$(curl -fsS -o /dev/null -m 3 -w '%{http_code}' "$url" 2>/dev/null || true)"
  case "$code" in
    200|204|301|302|401|403) ok "$label reachable ($code)" ;;
    ""|000) warn "$label not reachable" ;;
    *) warn "$label returned HTTP $code" ;;
  esac
}

section "Repo"
if [ -d "$REPO_DIR/.git" ]; then
  ok "git checkout present"
  if git -C "$REPO_DIR" rev-parse --short HEAD >/dev/null 2>&1; then
    ok "commit $(git -C "$REPO_DIR" rev-parse --short HEAD)"
  fi
else
  warn "not a git checkout"
fi
check_file "$REPO_DIR/install.sh" "top-level installer"
check_file "$REPO_DIR/scripts/install_birddog_customizations.sh" "Birddog customization installer"
check_file "$REPO_DIR/scripts/bird_collage.py" "collage generator"
check_file "$REPO_DIR/config/bird_collage_style.txt" "collage image prompt"

section "Python"
if [ -x "$REPO_DIR/birdnet/bin/python3" ]; then
  ok "BirdNET virtualenv python"
  "$REPO_DIR/birdnet/bin/python3" -m py_compile "$REPO_DIR/scripts/bird_collage.py" \
    && ok "collage generator compiles" \
    || fail "collage generator compiles"
else
  fail "BirdNET virtualenv python ($REPO_DIR/birdnet/bin/python3 missing)"
fi

section "Gemini"
if [ -s /etc/birdnet/gemini_api_key ]; then
  ok "Gemini key installed at /etc/birdnet/gemini_api_key"
elif [ -n "${GEMINI_API_KEY:-}" ]; then
  ok "Gemini key available in GEMINI_API_KEY"
else
  warn "no Gemini key found; detections work, new image generation is skipped"
fi
check_optional_file /etc/birdnet/bird_collage_style.txt "installed collage prompt"

section "Runtime Data"
check_optional_file "$HOME_DIR/BirdSongs/Extracted/collage" "collage cache directory"
check_optional_file "$REPO_DIR/scripts/birds.db" "BirdNET detection database"
check_optional_file "$HOME_DIR/BirdSongs/StreamData" "stream data directory"

section "Microphone"
if have arecord; then
  if arecord -l 2>/dev/null | grep -qiE 'card [0-9]'; then
    ok "ALSA recording device visible"
    arecord -l 2>/dev/null | sed 's/^/     /'
  else
    fail "no ALSA recording device visible"
  fi
else
  warn "arecord not installed; cannot check microphone"
fi

section "Services"
for unit in \
  caddy.service \
  birdnet_recording.service \
  birdnet_analysis.service \
  birdnet_log.service \
  birdnet_collage.timer
do
  check_service "$unit"
done

section "Web"
check_http "local homepage" "http://127.0.0.1/"
check_http "collage API" "http://127.0.0.1/scripts/collage_index.php?hours=24"

section "Summary"
printf '%s failure(s), %s warning(s)\n' "$failures" "$warnings"
if [ "$failures" -gt 0 ]; then
  exit 1
fi
exit 0
