#!/usr/bin/env bash
# nexus-daemon.sh — Start nexus Telegram webhook daemon with cloudflared tunnel
# Usage: ./nexus-daemon.sh [start|stop|status]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NEXUS_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$NEXUS_ROOT/logs"
TUNNEL_URL_FILE="$LOG_DIR/tunnel_url.txt"
PID_DIR="$LOG_DIR"
DAEMON_PID_FILE="$PID_DIR/nexus-daemon.pid"
TUNNEL_PID_FILE="$PID_DIR/cloudflared.pid"
PORT=8443

mkdir -p "$LOG_DIR"

cmd="${1:-start}"

case "$cmd" in
  start)
    echo "Starting nexus daemon..."

    # Stop existing processes
    "$0" stop 2>/dev/null || true
    sleep 1

    # Start cloudflared tunnel
    cloudflared tunnel --url "http://localhost:$PORT" --no-autoupdate \
      > "$LOG_DIR/cloudflared.log" 2>&1 &
    CF_PID=$!
    echo "$CF_PID" > "$TUNNEL_PID_FILE"
    echo "Cloudflared started (PID: $CF_PID)"

    # Wait for tunnel URL
    TUNNEL_URL=""
    for i in $(seq 1 20); do
      sleep 2
      TUNNEL_URL=$(grep -oE 'https://[a-zA-Z0-9\-]+\.trycloudflare\.com' "$LOG_DIR/cloudflared.log" 2>/dev/null | tail -1)
      if [ -n "$TUNNEL_URL" ]; then
        break
      fi
      echo "Waiting for tunnel... ($i)"
    done

    if [ -z "$TUNNEL_URL" ]; then
      echo "ERROR: Could not get tunnel URL from cloudflared"
      cat "$LOG_DIR/cloudflared.log"
      kill "$CF_PID" 2>/dev/null || true
      exit 1
    fi

    echo "$TUNNEL_URL" > "$TUNNEL_URL_FILE"
    echo "Tunnel URL: $TUNNEL_URL"

    # Wait for DNS propagation
    sleep 3

    # Start the Python daemon (reads TUNNEL_URL_FILE for webhook setup)
    python3 "$SCRIPT_DIR/nexus-daemon.py" \
      >> "$LOG_DIR/nexus-daemon.log" 2>> "$LOG_DIR/nexus-daemon.err" &
    DAEMON_PID=$!
    echo "$DAEMON_PID" > "$DAEMON_PID_FILE"
    echo "Daemon started (PID: $DAEMON_PID)"

    sleep 2
    if kill -0 "$DAEMON_PID" 2>/dev/null; then
      echo "✅ nexus daemon is running"
      echo "   Tunnel: $TUNNEL_URL"
      echo "   Webhook: $TUNNEL_URL/webhook"
    else
      echo "❌ daemon crashed, check $LOG_DIR/nexus-daemon.err"
      cat "$LOG_DIR/nexus-daemon.err"
    fi
    ;;

  stop)
    echo "Stopping nexus daemon..."
    if [ -f "$DAEMON_PID_FILE" ]; then
      DAEMON_PID=$(cat "$DAEMON_PID_FILE")
      kill "$DAEMON_PID" 2>/dev/null || true
      rm -f "$DAEMON_PID_FILE"
    fi
    if [ -f "$TUNNEL_PID_FILE" ]; then
      CF_PID=$(cat "$TUNNEL_PID_FILE")
      kill "$CF_PID" 2>/dev/null || true
      rm -f "$TUNNEL_PID_FILE"
    fi
    # Also kill any stray processes
    pkill -f "nexus-daemon.py" 2>/dev/null || true
    pkill -f "cloudflared.*8443" 2>/dev/null || true

    # Remove webhook from Telegram
    python3 -c "
import json, subprocess
try:
    with open('$NEXUS_ROOT/ψ/credentials/telegram.json') as f:
        creds = json.load(f)
    url = f'https://api.telegram.org/bot{creds[\"bot_token\"]}/deleteWebhook'
    subprocess.run(['curl', '-s', '-X', 'POST', url, '-d', '{"drop_pending_updates": false}'], timeout=10)
except: pass
" 2>/dev/null || true

    rm -f "$TUNNEL_URL_FILE"
    echo "✅ Stopped"
    ;;

  status)
    DAEMON_RUNNING=false
    TUNNEL_RUNNING=false
    if [ -f "$DAEMON_PID_FILE" ]; then
      DAEMON_PID=$(cat "$DAEMON_PID_FILE")
      if kill -0 "$DAEMON_PID" 2>/dev/null; then
        DAEMON_RUNNING=true
      fi
    fi
    if [ -f "$TUNNEL_PID_FILE" ]; then
      CF_PID=$(cat "$TUNNEL_PID_FILE")
      if kill -0 "$CF_PID" 2>/dev/null; then
        TUNNEL_RUNNING=true
      fi
    fi
    echo "Daemon: $DAEMON_RUNNING"
    echo "Tunnel: $TUNNEL_RUNNING"
    if [ -f "$TUNNEL_URL_FILE" ]; then
      echo "URL: $(cat $TUNNEL_URL_FILE)"
    fi
    ;;

  *)
    echo "Usage: $0 {start|stop|status}"
    ;;
esac