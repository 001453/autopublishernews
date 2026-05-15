#!/usr/bin/env bash
# Bot X profili — Chromium + CDP (Linux / Docker). Windows: start_bot_chrome.ps1
set -euo pipefail

URL="${1:-https://x.com/login}"
FORCE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -Url) URL="$2"; shift 2 ;;
    -ForceRestart) FORCE=1; shift ;;
    *) shift ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="${X_PROFILE_DIR:-$ROOT/data/x_profile}"
PORT="${BOT_CDP_PORT:-9333}"
CDP="http://127.0.0.1:${PORT}"

mkdir -p "$PROFILE"

test_cdp() {
  curl -sf "${CDP}/json/version" >/dev/null 2>&1
}

open_cdp_tab() {
  local enc
  enc=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$URL'''))")
  curl -sf -X PUT "${CDP}/json/new?${enc}" >/dev/null 2>&1 \
    || curl -sf "${CDP}/json/new?${enc}" >/dev/null 2>&1
}

stop_profile_chrome() {
  pkill -f "user-data-dir=${PROFILE}" 2>/dev/null || true
  sleep 2
}

CHROME=""
for c in chromium chromium-browser google-chrome google-chrome-stable; do
  if command -v "$c" >/dev/null 2>&1; then
    CHROME="$c"
    break
  fi
done
if [[ -z "$CHROME" ]]; then
  PW="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
  CHROME="$(find "$PW" -name chrome -type f 2>/dev/null | head -1 || true)"
fi
if [[ -z "$CHROME" || ! -x "$CHROME" ]]; then
  echo "Chromium bulunamadi. Docker imajinda playwright kurulu olmali."
  exit 1
fi

if test_cdp; then
  echo "Bot Chrome CDP aktif (port $PORT)."
  open_cdp_tab && { echo "Yeni sekme: $URL"; exit 0; }
fi

if pgrep -f "user-data-dir=${PROFILE}" >/dev/null 2>&1 && ! test_cdp; then
  if [[ "$FORCE" -eq 1 ]]; then
    echo "Eski bot Chrome kapatiliyor..."
    stop_profile_chrome
  else
    echo "x_profile Chrome acik ama CDP kapali. Tekrar: $0 -ForceRestart"
    exit 1
  fi
fi

echo "Bot Chrome aciliyor: profil=$PROFILE port=$PORT"
export DISPLAY="${DISPLAY:-:99}"
nohup "$CHROME" \
  --remote-debugging-port="$PORT" \
  --user-data-dir="$PROFILE" \
  --disable-blink-features=AutomationControlled \
  --no-first-run \
  --no-default-browser-check \
  "$URL" >/dev/null 2>&1 &

for _ in $(seq 1 25); do
  sleep 1
  if test_cdp; then
    echo "Hazir. CDP port $PORT"
    exit 0
  fi
done
echo "Chrome basladi; CDP gecikebilir."
exit 0
