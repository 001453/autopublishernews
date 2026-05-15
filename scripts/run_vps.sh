#!/usr/bin/env bash
# Sunucu / Docker giris noktasi: Chromium CDP + panel + otomatik zamanlayici
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export DATA_DIR="${DATA_DIR:-$ROOT/data}"
export X_PROFILE_DIR="${X_PROFILE_DIR:-$DATA_DIR/x_profile}"
export PANEL_CONFIG_PATH="${PANEL_CONFIG_PATH:-$DATA_DIR/panel_config.json}"
export AUTO_START_SCHEDULER="${AUTO_START_SCHEDULER:-1}"
export PANEL_HOST="${PANEL_HOST:-0.0.0.0}"
export PANEL_PORT="${PANEL_PORT:-8765}"
export USE_EXISTING_CHROME="${USE_EXISTING_CHROME:-0}"
export BROWSER_CHANNEL="${BROWSER_CHANNEL:-chromium}"
export HEADLESS="${HEADLESS:-0}"
export BOT_CDP_PORT="${BOT_CDP_PORT:-9333}"

mkdir -p "$DATA_DIR"
if [[ ! -f "$PANEL_CONFIG_PATH" ]] && [[ -f "$ROOT/panel_config.json" ]]; then
  cp "$ROOT/panel_config.json" "$PANEL_CONFIG_PATH"
  echo "panel_config kopyalandi: $PANEL_CONFIG_PATH"
fi

# Sanal ekran (headless sunucu)
if [[ -z "${DISPLAY:-}" ]] || ! xdpyinfo >/dev/null 2>&1; then
  if command -v Xvfb >/dev/null 2>&1; then
    Xvfb :99 -screen 0 1920x1080x24 >/dev/null 2>&1 &
    export DISPLAY=:99
    sleep 1
  fi
fi

bash "$ROOT/scripts/start_bot_chrome.sh" -ForceRestart -Url "https://x.com/login" || true
sleep 3

echo "Panel: http://${PANEL_HOST}:${PANEL_PORT}"
echo "Ilk kurulum: tarayicidan panele girin; X oturumu Chromium penceresinde acik olmali."
echo "VNC/RDP yoksa: sunucuda bir kez manuel X girisi icin xvfb + screenshot veya Windows VPS onerilir."

exec python dashboard.py
