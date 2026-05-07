#!/usr/bin/env bash
# nexus-daemon-launcher.sh — Wrapper for launchd with proper logging
# Flushes output to log files immediately

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/../../logs"
mkdir -p "$LOG_DIR"

# Detect python3 path (prefer system python for macOS compatibility)
PYTHON3="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
if [ ! -f "$PYTHON3" ]; then
    PYTHON3=$(which python3 2>/dev/null || echo "python3")
fi

exec "$PYTHON3" -u "$SCRIPT_DIR/nexus-daemon.py" \
  >> "$LOG_DIR/nexus-daemon.log" 2>> "$LOG_DIR/nexus-daemon.err"