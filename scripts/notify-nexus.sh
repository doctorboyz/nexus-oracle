#!/usr/bin/env bash
# notify-nexus.sh — Send event notification from any oracle to nexus → Telegram
# Usage: notify-nexus.sh <source_oracle> <event_type> <message>
#   source_oracle: emily, god-port, nexus, etc.
#   event_type: session-end, escalation, commit, error, info
#   message: description text

set -uo pipefail

SOURCE_ORACLE="${1:-}"
EVENT_TYPE="${2:-}"
MESSAGE="${3:-}"

if [[ -z "$SOURCE_ORACLE" || -z "$EVENT_TYPE" || -z "$MESSAGE" ]]; then
  echo "Usage: notify-nexus.sh <source_oracle> <event_type> <message>"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NEXUS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$NEXUS_ROOT/shared/vault-paths.sh"

# Read credentials
if [[ ! -f "$NEXUS_CREDENTIALS" ]]; then
  echo "Error: nexus credentials not found at $NEXUS_CREDENTIALS"
  exit 1
fi

BOT_TOKEN=$(python3 -c "import json; print(json.load(open('$NEXUS_CREDENTIALS')).get('bot_token', ''))" 2>/dev/null || echo "")
CHAT_ID=$(python3 -c "import json; print(json.load(open('$NEXUS_CREDENTIALS')).get('chat_id', ''))" 2>/dev/null || echo "")

if [[ -z "$BOT_TOKEN" || -z "$CHAT_ID" ]]; then
  echo "Error: bot_token or chat_id not configured"
  exit 1
fi

# Generate message ID and timestamp
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
DATE_STR=$(date -u +%Y%m%d)
TIME_STR=$(date -u +%H-%M)
SOURCE_UPPER=$(echo "$SOURCE_ORACLE" | tr '[:lower:]' '[:upper:]')
MSG_COUNT=$(find "$NEXUS_INBOX" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
MSG_ID="MSG-${SOURCE_UPPER}-$(printf '%03d' $((MSG_COUNT + 1)))"
FILENAME="${DATE_STR}_${TIME_STR}_${SOURCE_ORACLE}_${MSG_ID}.md"

# Determine MSG type from event_type
case "$EVENT_TYPE" in
  escalation|error) MSG_TYPE="escalation" ;;
  session-end|commit) MSG_TYPE="info" ;;
  *) MSG_TYPE="info" ;;
esac

# Write to nexus inbox
mkdir -p "$NEXUS_INBOX"
cat > "${NEXUS_INBOX}/${FILENAME}" <<ENDOFFILE
---
msg_id: $MSG_ID
from: $SOURCE_ORACLE
to: nexus
type: $MSG_TYPE
status: pending
sent: $NOW
ack_by: "-"
result: "-"
reply_file: "-"
---

[$EVENT_TYPE] $MESSAGE
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
type: $MSG_TYPE
status: forwarded
sent: $NOW
result: awaiting
---

[$EVENT_TYPE] $MESSAGE
ENDOFFILE

# Send Telegram notification
API_URL="https://api.telegram.org/bot${BOT_TOKEN}"

case "$EVENT_TYPE" in
  escalation|error) EMOJI="🚨" ;;
  session-end) EMOJI="📋" ;;
  commit) EMOJI="📝" ;;
  *) EMOJI="ℹ️" ;;
esac

TG_MESSAGE="${EMOJI} [nexus] ${EVENT_TYPE} from ${SOURCE_ORACLE}: ${MESSAGE}"

ESCAPED_MESSAGE=$(python3 -c "import json; print(json.dumps('$TG_MESSAGE'))" 2>/dev/null || echo "\"$TG_MESSAGE\"")
curl -s -X POST "${API_URL}/sendMessage" \
  -H "Content-Type: application/json" \
  -d "{\"chat_id\": ${CHAT_ID}, \"text\": ${ESCAPED_MESSAGE}}" > /dev/null 2>&1 || echo "Warning: Telegram send failed"

echo "notify-nexus: $MSG_ID → Telegram ($EVENT_TYPE from $SOURCE_ORACLE)"