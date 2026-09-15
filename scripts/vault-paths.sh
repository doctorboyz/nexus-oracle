#!/usr/bin/env bash
# nexus-oracle shared vault path resolution
# Source this file in other scripts: source "$(dirname "$0")/vault-paths.sh"

NEXUS_ROOT="/Users/doctorboyz/Code/github.com/doctorboyz/nexus-oracle"

# Resolve psi directory (handles both ψ and psi)
if [ -d "$NEXUS_ROOT/ψ" ]; then
    PSI_DIR="$NEXUS_ROOT/ψ"
elif [ -d "$NEXUS_ROOT/psi" ]; then
    PSI_DIR="$NEXUS_ROOT/psi"
else
    PSI_DIR="$NEXUS_ROOT/ψ"
fi

# Nexus vault paths
NEXUS_INBOX="$PSI_DIR/inbox"
NEXUS_OUTBOX="$PSI_DIR/outbox"
NEXUS_DISPATCH="$PSI_DIR/dispatch"
NEXUS_CREDENTIALS="$PSI_DIR/credentials/telegram.json"
NEXUS_GOALS="$PSI_DIR/goals"
NEXUS_CHANNELS="$PSI_DIR/channels"
NEXUS_MEMORY="$PSI_DIR/memory"
NEXUS_LEARNINGS="$PSI_DIR/memory/learnings"

# Other Oracle vault paths (read-only)
EMILY_ROOT="/Users/doctorboyz/Code/github.com/doctorboyz/emily-oracle"
GODPORT_ROOT="/Users/doctorboyz/Code/github.com/doctorboyz/god-port-oracle"
MKT_ROOT="/Users/doctorboyz/Code/github.com/doctorboyz/mkt-oracle"
DEV_ROOT="/Users/doctorboyz/Code/github.com/doctorboyz/dev-oracle"
KAPPY_ROOT="/Users/doctorboyz/Code/github.com/doctorboyz/kappy-oracle"

EMILY_VAULT="$EMILY_ROOT/ψ"
GODPORT_VAULT="$GODPORT_ROOT/ψ"
MKT_VAULT="$MKT_ROOT/ψ"
DEV_VAULT="$DEV_ROOT/ψ"
KAPPY_VAULT="$KAPPY_ROOT/ψ"

# Message ID format: MSG-NEXUS-NNN
NEXUS_MSG_PREFIX="MSG-NEXUS"