# nexus-oracle — Quick Reference

## What It Does

nexus Oracle is the **central dispatcher and coordinator** for a fleet of AI oracle agents communicating via Telegram. Two roles, one agent:

1. **Dispatcher (texty)**: Routes messages between humans (via Telegram) and oracle agents
2. **Coordinator (pm)**: Tracks goals, monitors inbox activity, orchestrates cross-oracle tasks

It is an **agentic AI** system — no main loop. The agent wakes on session start, reads its vault (inbox, goals, dispatch), acts, writes results, and sleeps. The Python daemon (`nexus-daemon.py`) is the always-on Telegram bridge.

---

## Installation & Setup

### Prerequisites
- Python 3.13+ (macOS system python)
- `curl` (Telegram Bot API calls)
- `fswatch` (inbox watcher)
- `maw` CLI (fleet manager)
- PM2 (production daemon management)

### Credentials
`psi/credentials/telegram.json` (gitignored):
```json
{
  "bot_token": "BOT_TOKEN",
  "bot_id": 123456789,
  "chat_id": "HUMAN_PRIVATE_CHAT_ID",
  "channels": {
    "emily": "-100XXXXXXXXXX",
    "god-port": "-100YYYYYYYYYY",
    "fleet": "-100ZZZZZZZZZZ"
  }
}
```

### Fleet Config
`~/.config/maw/fleet/*.json` per oracle:
```json
{
  "name": "god-port",
  "windows": [{ "name": "god-port-oracle", "root": "/path/to/god-port-oracle" }],
  "routing": { "keywords": ["trade", "xau", "ทอง"], "domains": ["trading"] },
  "auto_wake": true
}
```

---

## Key Features

### Smart Routing (3-tier)

| Chat Context | Routing | Example |
|---|---|---|
| Oracle group (e.g., god-port) | Direct to that oracle | Message in god-port group → god-port |
| Fleet group | Keyword matching (Thai+English) | "ทองขึ้นไหม" → god-port via Thai keyword |
| Private chat | Falls back to nexus inbox | DM → manual handling |

Scoring: keyword match = `len(kw)/3 + 1.0`, domain = `+0.5`, confidence threshold = `0.5`, tie-break by total keyword length.

### Outbox Watcher (response delivery)

Every 3 seconds, scans all oracle `ψ/outbox/` directories:
1. Parse YAML frontmatter (`type`, `msg_id`, `from`, `respond_in`)
2. Resolve target chat: `respond_in` → `source_chat` from inbox → oracle group → private chat
3. Send to Telegram (plain text, no Markdown parse errors)
4. Archive to `ψ/outbox/archive/YYYY-MM/`

### Command Handlers

| Command | Function |
|---|---|
| `/wake <oracle>` | Start oracle session |
| `/sleep <oracle>` | Stop oracle session |
| `/status` | Fleet status |
| `/inbox <oracle>` | Check oracle inbox |
| `/send <oracle> <msg>` | Send message (smart: warns if already in that oracle's group) |
| `/broadcast <msg>` | Send to all oracle groups |
| `/goals` | List active goals |
| `/help` | Command reference + smart routing explanation |

### MSG-ACK-RESULT Protocol

File-based messaging between oracles with YAML frontmatter:
- **Send**: Write to target's `psi/inbox/` with `status: pending`
- **Ack**: Update status to `acknowledged`, write `ack_` file to outbox
- **Result**: Update status to `completed`, write `result_` file to outbox

Filename format: `{YYYYMMDD}_{HHMM}_{sender}_{msg_id}.md`

### Auto-Wake

When `deliver_to_oracle()` sends a message, if the oracle is not running and `auto_wake: true` in fleet config, it runs `maw wake {oracle}` automatically.

---

## Directory Structure

```
nexus-oracle/
├── texty/                          # Dispatcher role tools
│   ├── nexus-daemon.py             # Core daemon (polling + commands + outbox watcher)
│   ├── dispatch.sh                 # Send messages/polls via Telegram Bot API
│   ├── notify-nexus.sh             # Other oracles → nexus → Telegram
│   └── query.sh                    # Cross-vault knowledge search
├── pm/                             # Coordinator role tools
│   ├── inbox-watcher.sh            # fswatch inbox monitor + macOS notifications
│   └── inject-hook.sh              # Inject Stop hooks into other oracle repos
├── shared/                         # Shared utilities
│   ├── vault-paths.sh              # Central vault path resolution
│   ├── msg-protocol.sh             # MSG-ACK-RESULT helpers
│   ├── outbox-write.sh             # Write responses to outbox for auto-delivery
│   └── session-summary.sh          # Session end summary + Telegram notification
├── psi/ (ψ/)                       # Agent vault (the brain)
│   ├── identity.md
│   ├── credentials/telegram.json   # Bot token, chat_id, channels
│   ├── inbox/                      # Incoming messages
│   ├── outbox/                     # Outgoing responses (watched by daemon)
│   │   └── archive/YYYY-MM/       # Processed outbox files
│   ├── dispatch/YYYY-MM/           # Append-only dispatch log
│   ├── goals/active/              # Current goals
│   └── memory/learnings/           # Knowledge docs
└── logs/                           # Daemon logs
```

---

## Common Operations

### Daemon Management
```bash
# Polling mode (recommended)
pm2 start texty/nexus-daemon.py --interpreter python3
pm2 restart nexus-daemon
pm2 logs nexus-daemon

# Webhook mode (with cloudflared tunnel)
bash texty/nexus-daemon.sh start|stop|status
```

### Testing Routing
```bash
# In god-port group: "ราคาทองวันนี้" → routes to god-port
# In fleet group: "schedule a meeting" → routes to fammee
# In fleet group: "hello?" → no match, asks human to clarify
# In private chat: "anything" → falls to nexus inbox
```

### Sending Messages Manually
```bash
bash texty/dispatch.sh --message "Hello"              # To private chat
bash texty/dispatch.sh --message "Check" --oracle infra  # To oracle group
bash texty/dispatch.sh --message "Vote?" --poll "Yes or No?"  # Poll
```

### Outbox Response (from oracle session)
```bash
# Option 1: Write file directly
cat > ψ/outbox/result_MSG-HUMAN-1434.md << 'EOF'
---
msg_id: MSG-HUMAN-1434
from: infra
type: result
respond_in: -1003732972862
---
Docker is running fine. All containers healthy.
EOF

# Option 2: Use helper script
bash shared/outbox-write.sh --msg-id MSG-HUMAN-1434 --content "Docker is running fine."
```

---

## Key Design Principles

1. **Nothing is Deleted** — All dispatch logs, goals, status reports preserved
2. **Patterns Over Intentions** — Dispatch patterns reveal priorities; vault evidence reveals progress
3. **Two Roles, One Mission** — Dispatcher sends signals, Coordinator guides goals
4. **Transparency** — Every message has `[nexus]` attribution, no human impersonation
5. **Drive to Completion** — nexus doesn't just send and wait, it drives tasks to completion

## Communication Protocol

Every message follows: **ทำอะไร** → **เพื่ออะไร** → **แล้วไง** (What → Why → So what). Thai preferred, technical terms in English.