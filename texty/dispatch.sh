#!/usr/bin/env bash
# dispatch.sh — Send messages via Telegram Bot API on behalf of nexus Oracle
# Usage: dispatch --message "text" [--poll "question"]
# Reads bot_token + chat_id from ψ/credentials/telegram.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NEXUS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$NEXUS_ROOT/shared/vault-paths.sh"

MESSAGE=""
POLL_QUESTION=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --message) MESSAGE="$2"; shift 2 ;;
    --poll) POLL_QUESTION="$2"; shift 2 ;;
    *) shift ;;
  esac
done

if [[ -z "$MESSAGE" ]]; then
  echo "Usage: dispatch --message \"text\" [--poll \"question\"]"
  exit 1
fi

if [[ ! -f "$NEXUS_CREDENTIALS" ]]; then
  echo "Error: credentials/telegram.json not found"
  exit 1
fi

BOT_TOKEN=$(python3 -c "import json; print(json.load(open('$NEXUS_CREDENTIALS')).get('bot_token', ''))" 2>/dev/null || echo "")
CHAT_ID=$(python3 -c "import json; print(json.load(open('$NEXUS_CREDENTIALS')).get('chat_id', ''))" 2>/dev/null || echo "")

if [[ -z "$BOT_TOKEN" || -z "$CHAT_ID" ]]; then
  echo "Error: bot_token or chat_id not configured in credentials/telegram.json"
  exit 1
fi

API_URL="https://api.telegram.org/bot${BOT_TOKEN}"

# Log dispatch
DISPATCH_DIR="$NEXUS_DISPATCH/$(date +%Y-%m)"
mkdir -p "$DISPATCH_DIR"
COUNT=$(ls "$DISPATCH_DIR" 2>/dev/null | wc -l | tr -d ' ')
DISPATCH_ID="DSP-$(date +%Y%m%d)-$(printf '%03d' $((COUNT + 1)))"
DISPATCH_FILE="$DISPATCH_DIR/${DISPATCH_ID}.md"

MSG_TYPE=$([ -n "$POLL_QUESTION" ] && echo "task" || echo "info")

cat > "$DISPATCH_FILE" <<EOF
---
dispatch_id: ${DISPATCH_ID}
from: nexus
to: human (Telegram)
type: ${MSG_TYPE}
status: forwarded
sent: $(date -u +%Y-%m-%dT%H:%M:%SZ)
result: awaiting
---

${MESSAGE}
EOF

# Send via Telegram Bot API
if [[ -n "$POLL_QUESTION" ]]; then
  PAYLOAD=$(python3 -c "
import json
print(json.dumps({
    'chat_id': $CHAT_ID,
    'question': '$POLL_QUESTION',
    'options': json.dumps(['Approve', 'Reject', 'Need more info'])
}))")
  curl -s -X POST "${API_URL}/sendPoll" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" > /dev/null
  echo "Poll sent: $DISPATCH_ID"
else
  curl -s -X POST "${API_URL}/sendMessage" \
    -H "Content-Type: application/json" \
    -d "{\"chat_id\": $CHAT_ID, \"text\": \"$MESSAGE\"}" > /dev/null
  echo "Message sent: $DISPATCH_ID"
fi