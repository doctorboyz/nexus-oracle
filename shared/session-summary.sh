#!/usr/bin/env bash
# session-summary.sh — Capture oracle session summary and send to nexus → Telegram
# Usage: session-summary.sh <source_oracle>
# Called from each oracle's Stop hook.
# Merges the functionality of session-summary-to-texty.sh and session-report-to-pm.sh

set -uo pipefail

SOURCE_ORACLE="${1:-}"

if [[ -z "$SOURCE_ORACLE" ]]; then
  echo "Usage: session-summary.sh <source_oracle>"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NEXUS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$NEXUS_ROOT/shared/vault-paths.sh"

# Read credentials
if [[ ! -f "$NEXUS_CREDENTIALS" ]]; then
  echo "Error: nexus credentials not found"
  exit 1
fi

BOT_TOKEN=$(python3 -c "import json; print(json.load(open('$NEXUS_CREDENTIALS')).get('bot_token', ''))" 2>/dev/null || echo "")
CHAT_ID=$(python3 -c "import json; print(json.load(open('$NEXUS_CREDENTIALS')).get('chat_id', ''))" 2>/dev/null || echo "")

if [[ -z "$BOT_TOKEN" || -z "$CHAT_ID" ]]; then
  echo "Error: bot_token or chat_id not configured"
  exit 1
fi

# ── Capture session output ──────────────────────────────────────────

# Find the oracle's tmux pane
SESSION_NAME="$SOURCE_ORACLE"
PANE_TARGET=""

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
  FIRST_PANE=$(tmux list-panes -t "$SESSION_NAME" -F '#{window_index}.#{pane_index}' 2>/dev/null | head -1 | tr -d ' ')
  if [[ -n "$FIRST_PANE" ]]; then
    PANE_TARGET="${SESSION_NAME}:${FIRST_PANE}"
  fi
fi

# Capture last 80 lines of output
CAPTURED=""
if [[ -n "$PANE_TARGET" ]]; then
  CAPTURED=$(tmux capture-pane -t "$PANE_TARGET" -p -S -80 2>/dev/null | grep -v '^$' | grep -v '^[─═━]' | grep -v '⏵⏵' | grep -v '✻' | grep -v '❯' | tail -10)
fi

# Build summary message
if [[ -n "$CAPTURED" ]]; then
  SUMMARY=$(echo "$CAPTURED" | tail -5 | sed 's/^/  /')
  MESSAGE="📋 ${SOURCE_ORACLE} session ended
${SUMMARY}
✅ Ready for new tasks — /send ${SOURCE_ORACLE} <msg>"
else
  MESSAGE="📋 ${SOURCE_ORACLE} session ended
✅ Ready for new tasks — /send ${SOURCE_ORACLE} <msg>"
fi

# ── Write to nexus inbox ─────────────────────────────────────────────

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
DATE_STR=$(date -u +%Y%m%d)
TIME_STR=$(date -u +%H-%M)
SOURCE_UPPER=$(echo "$SOURCE_ORACLE" | tr '[:lower:]' '[:upper:]')
MSG_COUNT=$(find "$NEXUS_INBOX" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
MSG_ID="MSG-${SOURCE_UPPER}-$(printf '%03d' $((MSG_COUNT + 1)))"
FILENAME="${DATE_STR}_${TIME_STR}_${SOURCE_ORACLE}_${MSG_ID}.md"

mkdir -p "$NEXUS_INBOX"
cat > "${NEXUS_INBOX}/${FILENAME}" <<ENDOFFILE
---
msg_id: $MSG_ID
from: $SOURCE_ORACLE
to: nexus
type: info
status: pending
sent: $NOW
ack_by: "-"
result: "-"
reply_file: "-"
---

[session-end] ${SOURCE_ORACLE} session ended
ENDOFFILE

# Log dispatch
DISPATCH_DIR="$NEXUS_DISPATCH/$(date +%Y-%m)"
mkdir -p "$DISPATCH_DIR"
COUNT=$(find "$DISPATCH_DIR" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
DISPATCH_ID="DSP-$(date +%Y%m%d)-$(printf '%03d' $((COUNT + 1)))"
cat > "${DISPATCH_DIR}/${DISPATCH_ID}.md" <<ENDOFFILE
---
dispatch_id: $DISPATCH_ID
from: $SOURCE_ORACLE
to: human (Telegram)
type: info
status: forwarded
sent: $NOW
result: awaiting
---

$MESSAGE
ENDOFFILE

# ── Send Telegram ────────────────────────────────────────────────────

API_URL="https://api.telegram.org/bot${BOT_TOKEN}"
ESCAPED_MESSAGE=$(python3 -c "import json; print(json.dumps('''$MESSAGE'''))" 2>/dev/null || echo "\"$MESSAGE\"")
curl -s -X POST "${API_URL}/sendMessage" \
  -H "Content-Type: application/json" \
  -d "{\"chat_id\": ${CHAT_ID}, \"text\": ${ESCAPED_MESSAGE}}" > /dev/null 2>&1 || echo "Warning: Telegram send failed"

echo "session-summary: $MSG_ID → Telegram ($SOURCE_ORACLE)"