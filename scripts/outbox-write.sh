#!/usr/bin/env bash
# outbox-write.sh — Write a response to oracle's outbox
# nexus outbox watcher picks it up and sends to Telegram automatically
#
# Usage:
#   bash shared/outbox-write.sh --msg-id MSG-HUMAN-1434 --content "Your response"
#   bash shared/outbox-write.sh --msg-id MSG-HUMAN-1434 --respond-in -100xxx --content "Your response"
#   bash shared/outbox-write.sh --file inbox_file.md --content "Your response"
#
# If --respond-in is not provided, it reads from the inbox message's frontmatter.
# If --file is provided, it extracts msg_id and respond_in from that inbox file.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Find this oracle's root directory (where shared/ lives)
ORACLE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Find psi directory
PSI_DIR=""
for entry in "$ORACLE_ROOT/ψ" "$ORACLE_ROOT/psi"; do
    if [ -d "$entry" ]; then
        PSI_DIR="$entry"
        break
    fi
done

if [ -z "$PSI_DIR" ]; then
    echo "Error: psi directory not found in $ORACLE_ROOT" >&2
    exit 1
fi

OUTBOX_DIR="$PSI_DIR/outbox"
INBOX_DIR="$PSI_DIR/inbox"
ARCHIVE_DIR="$OUTBOX_DIR/archive"

# Get oracle name from root directory name
ORACLE_NAME="$(basename "$ORACLE_ROOT" | sed 's/-oracle$//')"

MSG_ID=""
RESPOND_IN=""
CONTENT=""
INBOX_FILE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --msg-id)
            MSG_ID="$2"
            shift 2
            ;;
        --respond-in)
            RESPOND_IN="$2"
            shift 2
            ;;
        --content)
            CONTENT="$2"
            shift 2
            ;;
        --file)
            INBOX_FILE="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

# If inbox file provided, extract msg_id and respond_in from it
if [ -n "$INBOX_FILE" ] && [ -f "$INBOX_FILE" ]; then
    if [ -z "$MSG_ID" ]; then
        MSG_ID="$(grep '^msg_id:' "$INBOX_FILE" | head -1 | sed 's/msg_id:[[:space:]]*//' | tr -d '"')"
    fi
    if [ -z "$RESPOND_IN" ]; then
        RESPOND_IN="$(grep '^respond_in:' "$INBOX_FILE" | head -1 | sed 's/respond_in:[[:space:]]*//' | tr -d '"')"
    fi
fi

# Validate required fields
if [ -z "$MSG_ID" ]; then
    echo "Error: --msg-id is required (or use --file to extract from inbox)" >&2
    exit 1
fi

if [ -z "$CONTENT" ]; then
    # Read content from stdin if not provided
    if [ ! -t 0 ]; then
        CONTENT="$(cat)"
    else
        echo "Error: --content is required (or pipe content via stdin)" >&2
        exit 1
    fi
fi

# Ensure outbox directory exists
mkdir -p "$OUTBOX_DIR"

# Generate filename with timestamp
NOW="$(date -u +"%Y%m%d_%H%M")"
RESULT_TYPE="result"
FILENAME="${NOW}_${ORACLE_NAME}_${MSG_ID}.md"
FILEPATH="$OUTBOX_DIR/$FILENAME"

# Write outbox file with YAML frontmatter
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

cat > "$FILEPATH" <<EOF
---
msg_id: $MSG_ID
from: $ORACLE_NAME
type: $RESULT_TYPE
timestamp: $TIMESTAMP
respond_in: ${RESPOND_IN:-""}
---

$CONTENT
EOF

echo "Written: $FILEPATH"
echo "nexus outbox watcher will send this to Telegram within ~3-6 seconds."