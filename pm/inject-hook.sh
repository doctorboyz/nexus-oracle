#!/usr/bin/env bash
# nexus Oracle — Inject Stop hook into another oracle project
# Usage: ./pm/inject-hook.sh <oracle-name>
# Example: $0 god-port
#
# This adds a Stop hook to the target oracle's .claude/settings.json
# that sends a session-end report to nexus's inbox.

set -e

ORACLE_NAME="${1:-}"
if [ -z "$ORACLE_NAME" ]; then
  echo "Usage: $0 <oracle-name>"
  echo "Example: $0 god-port"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NEXUS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$NEXUS_ROOT/shared/vault-paths.sh"

# Resolve oracle root from fleet config
FLEET_DIR="$HOME/.config/maw/fleet"
ORACLE_ROOT=""

for f in "$FLEET_DIR"/*.json; do
  name=$(python3 -c "import json; print(json.load(open('$f'))['name'])" 2>/dev/null)
  if [ "$name" = "$ORACLE_NAME" ]; then
    ORACLE_ROOT=$(python3 -c "import json; print(json.load(open('$f'))['windows'][0]['root'])" 2>/dev/null)
    break
  fi
done

if [ -z "$ORACLE_ROOT" ]; then
  echo "ERROR: Oracle '$ORACLE_NAME' not found in fleet configs"
  echo "Available oracles:"
  for f in "$FLEET_DIR"/*.json; do
    name=$(python3 -c "import json; print(json.load(open('$f'))['name'])" 2>/dev/null)
    echo "  - $name"
  done
  exit 1
fi

SETTINGS="$ORACLE_ROOT/.claude/settings.json"
SCRIPTS_DIR="$ORACLE_ROOT/scripts"

# Create scripts directory if needed
mkdir -p "$SCRIPTS_DIR"

# Create the session-report-to-nexus script for this oracle
cat > "$SCRIPTS_DIR/session-report-to-nexus.sh" << 'SCRIPT'
#!/bin/bash
# Oracle Session End Report to nexus
# Automatically called by Stop hook
DATE=$(date +%Y-%m-%d)
TIME=$(date +%H%M)
ORACLE_ROOT="__ORACLE_ROOT__"
ORACLE_NAME="__ORACLE_NAME__"
NEXUS_INBOX="__NEXUS_INBOX__"
OUTBOX="$ORACLE_ROOT/ψ/outbox"

mkdir -p "$NEXUS_INBOX"

# Collect latest outbox activity
latest_outbox=$(ls -t "$OUTBOX"/*.md 2>/dev/null | head -3 | xargs -I{} basename {} | tr '\n' ',' | sed 's/,$//')

# Write session end report
cat > "$NEXUS_INBOX/${DATE}_${TIME}_${ORACLE_NAME}_MSG-${ORACLE_NAME:0:2}-AUTO-${TIME}.md" << EOF
---
msg_id: MSG-${ORACLE_NAME:0:2}-AUTO-${TIME}
from: $ORACLE_NAME
to: nexus
type: info
status: pending
sent: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
ack_by: -
result: -
reply_file: -
---

# $ORACLE_NAME — Session End Report

**Session ended**: $(date "+%Y-%m-%d %H:%M:%S %Z")

## Outbox Activity (latest)
$latest_outbox

## Auto-generated
This message was automatically created by $ORACLE_NAME's Stop hook.
nexus: please review and update goals if needed.
EOF

echo "$ORACLE_NAME session report sent to nexus inbox"
SCRIPT

# Replace placeholders
sed -i '' "s|__ORACLE_ROOT__|$ORACLE_ROOT|g" "$SCRIPTS_DIR/session-report-to-nexus.sh"
sed -i '' "s|__ORACLE_NAME__|$ORACLE_NAME|g" "$SCRIPTS_DIR/session-report-to-nexus.sh"
sed -i '' "s|__NEXUS_INBOX__|$NEXUS_INBOX|g" "$SCRIPTS_DIR/session-report-to-nexus.sh"
chmod +x "$SCRIPTS_DIR/session-report-to-nexus.sh"

# Create or update .claude/settings.json
mkdir -p "$ORACLE_ROOT/.claude"

if [ -f "$SETTINGS" ]; then
  # Merge hook into existing settings
  python3 -c "
import json, sys

with open('$SETTINGS') as f:
    settings = json.load(f)

hooks = settings.get('hooks', {})
stop_hooks = hooks.get('Stop', [])

# Check if our hook already exists
hook_cmd = 'bash $SCRIPTS_DIR/session-report-to-nexus.sh'
existing = any(h.get('command', '') == hook_cmd for h in stop_hooks)

if not existing:
    stop_hooks.append({
        'matcher': '',
        'command': hook_cmd,
        'description': 'Send session end report to nexus inbox'
    })
    hooks['Stop'] = stop_hooks
    settings['hooks'] = hooks

    with open('$SETTINGS', 'w') as f:
        json.dump(settings, f, indent=2)
    print('Hook added to existing settings')
else:
    print('Hook already exists in settings')
"
else
  # Create new settings.json with hook
  cat > "$SETTINGS" << SETTINGS
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "command": "bash $SCRIPTS_DIR/session-report-to-nexus.sh",
        "description": "Send session end report to nexus inbox"
      }
    ]
  }
}
SETTINGS
  echo "Created new settings.json with hook"
fi

echo ""
echo "✅ Injected Stop hook into $ORACLE_NAME"
echo "   Script: $SCRIPTS_DIR/session-report-to-nexus.sh"
echo "   Settings: $SETTINGS"
echo ""
echo "When $ORACLE_NAME's session ends, it will automatically"
echo "send a report to nexus's inbox at:"
echo "   $NEXUS_INBOX"