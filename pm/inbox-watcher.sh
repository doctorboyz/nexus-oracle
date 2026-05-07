#!/usr/bin/env bash
# nexus Oracle — Inbox Watcher
# Watches nexus's inbox directory and sends notifications when new messages arrive
# Usage: ./pm/inbox-watcher.sh [--daemon] [--stop]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NEXUS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$NEXUS_ROOT/shared/vault-paths.sh"

NEXUS_INBOX="$NEXUS_INBOX"
NEXUS_OUTBOX="$NEXUS_OUTBOX"
PID_FILE="/tmp/nexus-inbox-watcher.pid"
LOG_FILE="/tmp/nexus-inbox-watcher.log"

case "${1:-}" in
  --stop)
    if [ -f "$PID_FILE" ]; then
      kill "$(cat "$PID_FILE")" 2>/dev/null
      rm "$PID_FILE"
      echo "Inbox watcher stopped."
    else
      echo "No watcher running."
    fi
    exit 0
    ;;
  --status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "Inbox watcher running (PID: $(cat "$PID_FILE"))"
    else
      echo "Inbox watcher not running."
    fi
    exit 0
    ;;
esac

# Check for existing watcher
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Inbox watcher already running (PID: $(cat "$PID_FILE")). Use --stop to stop."
  exit 1
fi

echo "nexus Inbox Watcher starting..."
echo "Watching: $NEXUS_INBOX"

# Create inbox if it doesn't exist
mkdir -p "$NEXUS_INBOX"

# Watch for new files in inbox
fswatch -0 --event Created --event Updated "$NEXUS_INBOX" | while IFS= read -r -d '' file; do
  filename=$(basename "$file")

  # Skip non-md files and ack/result files (those are from nexus itself)
  if [[ ! "$filename" == *.md ]] || [[ "$filename" == ack_* ]] || [[ "$filename" == result_* ]]; then
    continue
  fi

  # Extract sender and type from filename
  # Format: {date}_{time}_{sender}_{msg_id}.md
  sender=$(echo "$filename" | sed -E 's/^[0-9_-]+_([a-z]+)_MSG.*/\1/' | head -1)
  msg_id=$(echo "$filename" | sed -E 's/.*_(MSG-[A-Z]+-[0-9]+).*/\1/' | head -1)

  # Create notification
  timestamp=$(date "+%H:%M:%S")
  notification="📬 nexus Inbox: New message from ${sender:-unknown} (${msg_id:-$filename}) at ${timestamp}"

  echo "$notification" >> "$LOG_FILE"

  # macOS notification
  osascript -e "display notification \"From: ${sender:-unknown}\" with title \"nexus Oracle Inbox\" subtitle \"${msg_id:-$filename}\"" 2>/dev/null || true

  # Write receipt to outbox
  receipt_file="$NEXUS_OUTBOX/inbox_receipt_$(date +%Y%m%d_%H%M%S).md"
  cat > "$receipt_file" << RECEIPT
---
type: inbox_receipt
date: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
from: inbox-watcher
---

# Inbox Receipt

New message detected: $filename
Source: ${sender:-unknown}
Time: $timestamp

nexus should process this inbox message and respond according to goals.
RECEIPT

done &

echo $! > "$PID_FILE"
echo "Inbox watcher started (PID: $(cat "$PID_FILE"))"
echo "Log: $LOG_FILE"