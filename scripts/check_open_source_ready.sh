#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

failures=0

section() {
  printf '\n== %s ==\n' "$1"
}

ok() {
  printf 'OK   %s\n' "$1"
}

fail() {
  printf 'FAIL %s\n' "$1" >&2
  failures=$((failures + 1))
}

run_check() {
  local label="$1"
  shift
  if "$@"; then
    ok "$label"
  else
    fail "$label"
  fi
}

section "Shell"
run_check "install.sh syntax" bash -n install.sh
run_check "customization installer syntax" bash -n scripts/install_birddog_customizations.sh

section "PHP"
if command -v php >/dev/null 2>&1; then
  for file in scripts/collage.php scripts/collage_index.php scripts/collage_regen.php; do
    run_check "$file syntax" php -l "$file"
  done
else
  fail "php is not installed"
fi

section "Python"
python_bin="birdnet/bin/python3"
if [ ! -x "$python_bin" ]; then
  python_bin="$(command -v python3 || true)"
fi
if [ -n "$python_bin" ] && [ -x "$python_bin" ]; then
  run_check "scripts/bird_collage.py compiles" "$python_bin" -m py_compile scripts/bird_collage.py
else
  fail "python3 is not installed"
fi

section "Installer"
run_check "install.sh help" sh -c './install.sh --help >/dev/null'
run_check "customization installer help" sh -c 'scripts/install_birddog_customizations.sh --help >/dev/null'
run_check "install.sh preflight" ./install.sh --check --skip-birdnet --skip-python-deps
run_check "customization installer preflight" scripts/install_birddog_customizations.sh --check
run_check "install.sh accepts GEMINI_API_KEY env" sh -c \
  'GEMINI_API_KEY=test-key ./install.sh --check --skip-birdnet --skip-python-deps | grep -q "Gemini key provided by GEMINI_API_KEY"'
run_check "customization installer accepts GEMINI_API_KEY env" sh -c \
  'GEMINI_API_KEY=test-key scripts/install_birddog_customizations.sh --check | grep -q "Gemini key provided by GEMINI_API_KEY"'
if ./install.sh --gemini-key >/tmp/birddog-install-argcheck.out 2>&1; then
  fail "install.sh rejects missing --gemini-key value"
else
  if grep -q -- "--gemini-key requires a value" /tmp/birddog-install-argcheck.out; then
    ok "install.sh rejects missing --gemini-key value"
  else
    cat /tmp/birddog-install-argcheck.out >&2
    fail "install.sh rejects missing --gemini-key value"
  fi
fi
rm -f /tmp/birddog-install-argcheck.out

section "Git Hygiene"
if git diff --check; then
  ok "no whitespace errors"
else
  fail "no whitespace errors"
fi

for pattern in ".env" "gemini_api_key" "gemini_api_key.backup" "birddog-collage-cache.tgz" "birddog-birds.db"; do
  if grep -Fxq "$pattern" .gitignore; then
    ok ".gitignore includes $pattern"
  else
    fail ".gitignore includes $pattern"
  fi
done

tracked_sensitive="$(git ls-files | grep -E '(gemini_api_key|birds\.db|installation-[0-9]|\.whl$|^birdnet/)' || true)"
if [ -z "$tracked_sensitive" ]; then
  ok "no tracked runtime/secrets artifacts"
else
  printf '%s\n' "$tracked_sensitive" >&2
  fail "no tracked runtime/secrets artifacts"
fi

section "Docs"
for file in README.md CONTRIBUTING.md docs/hardware.md SECURITY.md config/birddog.env.example; do
  if [ -f "$file" ]; then
    ok "$file exists"
  else
    fail "$file exists"
  fi
done

if [ ! -f .github/FUNDING.yml ]; then
  ok "no placeholder funding metadata"
else
  fail "no placeholder funding metadata"
fi

if grep -RIn "monalisa\|birddog.local\|git@github.com\|/home/admin" \
    --exclude-dir=.git --exclude-dir=birdnet \
    README.md docs install.sh scripts/install_birddog_customizations.sh \
    templates config SECURITY.md .github/ISSUE_TEMPLATE >/tmp/birddog-doc-scan.out 2>&1; then
  cat /tmp/birddog-doc-scan.out >&2
  fail "public setup files do not contain private/local leftovers"
else
  ok "public setup files do not contain private/local leftovers"
fi
rm -f /tmp/birddog-doc-scan.out

if [ "$failures" -eq 0 ]; then
  printf '\nOpen-source readiness checks passed.\n'
  exit 0
fi

printf '\nOpen-source readiness checks failed: %s\n' "$failures" >&2
exit 1
