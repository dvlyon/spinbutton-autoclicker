#!/usr/bin/env bash
set -euo pipefail

PORT="${CDP_PORT:-9222}"
PROFILE_DIR="${CHROME_PROFILE_DIR:-$HOME/.chrome-spinbot-profile}"
START_URL="${1:-https://staging.playin.com/playin/tournaments/zwm3s2x5ss1x/play}"
CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if [[ ! -x "$CHROME_BIN" ]]; then
  echo "Google Chrome not found at: $CHROME_BIN" >&2
  exit 1
fi

echo "Launching Chrome with CDP on port $PORT (profile: $PROFILE_DIR)..."
exec "$CHROME_BIN" \
  --remote-debugging-port="$PORT" \
  --user-data-dir="$PROFILE_DIR" \
  --no-first-run \
  --no-default-browser-check \
  "$START_URL"
