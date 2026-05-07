#!/usr/bin/env bash
# nexus-oracle MSG-ACK-RESULT protocol helpers
# Source this file: source "$(dirname "$0")/../shared/vault-paths.sh" && source "$(dirname "$0")/msg-protocol.sh"

# Generate a new message ID: MSG-NEXUS-NNN
msg_generate_id() {
    local counter=1
    while [ -f "$NEXUS_OUTBOX/MSG-NEXUS-$(printf '%03d' $counter)"* ] 2>/dev/null; do
        counter=$((counter + 1))
    done
    echo "MSG-NEXUS-$(printf '%03d' $counter)"
}

# Get current timestamp in ISO format
msg_timestamp() {
    date -u +"%Y-%m-%dT%H:%M:%SZ"
}

# Get current date for filenames
msg_date() {
    date +"%Y%m%d"
}

# Get current time for filenames
msg_time() {
    date +"%H%M"
}

# Write a message to target oracle's inbox
# Usage: msg_send <target_oracle> <type> <message_content>
# type: escalation|query|task|info
msg_send() {
    local target_oracle="$1"
    local msg_type="$2"
    local message="$3"
    local timestamp=$(msg_timestamp)
    local date=$(msg_date)
    local time=$(msg_time)
    local msg_id=$(msg_generate_id)

    local target_inbox
    case "$target_oracle" in
        emily)   target_inbox="$EMILY_VAULT/inbox" ;;
        god-port) target_inbox="$GODPORT_VAULT/inbox" ;;
        mkt)    target_inbox="$MKT_VAULT/inbox" ;;
        dev)    target_inbox="$DEV_VAULT/inbox" ;;
        kappy)  target_inbox="$KAPPY_VAULT/inbox" ;;
        nexus)  target_inbox="$NEXUS_INBOX" ;;
        *)      echo "Unknown oracle: $target_oracle"; return 1 ;;
    esac

    local filename="${date}_${time}_nexus_${msg_id}.md"
    cat > "$target_inbox/$filename" <<EOF
---
msg_id: $msg_id
from: nexus
to: $target_oracle
type: $msg_type
status: pending
sent: $timestamp
ack_by: "-"
result: "-"
reply_file: "-"
---

$message
EOF
    echo "$msg_id"
}

# Acknowledge a message in own inbox
# Usage: msg_ack <msg_id>
msg_ack() {
    local msg_id="$1"
    local timestamp=$(msg_timestamp)
    local date=$(msg_date)

    # Find the message file
    local msg_file=$(ls "$NEXUS_INBOX"/*"${msg_id}"*.md 2>/dev/null | head -1)
    if [ -z "$msg_file" ]; then
        echo "Message $msg_id not found in inbox"
        return 1
    fi

    # Update status in the message file
    sed -i '' "s/status: pending/status: acknowledged/" "$msg_file"
    sed -i '' "s/ack_by: \"-\"/ack_by: $timestamp/" "$msg_file"

    # Write ack file to outbox
    local ack_file="$NEXUS_OUTBOX/ack_${msg_id}_${date}.md"
    cat > "$ack_file" <<EOF
---
msg_id: $msg_id
from: nexus
type: ack
timestamp: $timestamp
---

Acknowledged message $msg_id
EOF
    echo "Acknowledged $msg_id"
}

# Write result for a message
# Usage: msg_result <msg_id> <result_summary>
msg_result() {
    local msg_id="$1"
    local result_summary="$2"
    local timestamp=$(msg_timestamp)
    local date=$(msg_date)

    # Find the message file
    local msg_file=$(ls "$NEXUS_INBOX"/*"${msg_id}"*.md 2>/dev/null | head -1)
    if [ -z "$msg_file" ]; then
        echo "Message $msg_id not found in inbox"
        return 1
    fi

    # Update status in the message file
    sed -i '' "s/status: acknowledged/status: completed/" "$msg_file"
    sed -i '' "s/result: \"-\"/result: $timestamp/" "$msg_file"

    # Write result file to outbox
    local result_file="$NEXUS_OUTBOX/result_${msg_id}_${date}.md"
    cat > "$result_file" <<EOF
---
msg_id: $msg_id
from: nexus
type: result
timestamp: $timestamp
---

$result_summary
EOF
    echo "Result written for $msg_id"
}

# Check message status
# Usage: msg_status <msg_id>
msg_status() {
    local msg_id="$1"
    local msg_file=$(ls "$NEXUS_INBOX"/*"${msg_id}"*.md 2>/dev/null | head -1)
    if [ -z "$msg_file" ]; then
        echo "not_found"
        return
    fi
    grep "^status:" "$msg_file" | awk '{print $2}'
}