# texty-oracle Architecture

## Directory Structure and Organization Philosophy

The project follows the Oracle family pattern: a `ψ/` (psi) vault directory holds all runtime state, while code lives in `scripts/` at the top level.

**Top-level layout:**
- `CLAUDE.md` — identity charter and operating rules (Thai + English)
- `README.md` — public-facing summary
- `.claude/settings.json` — hook configuration (Stop hook triggers session-summary-to-texty)
- `scripts/` — five executable files (1 Python daemon, 4 shell scripts)
- `ψ/` — the vault, containing all mutable state
- `logs/` — daemon output (gitignored)

**Vault (`ψ/`) layout:**
- `inbox/` — incoming MSG-ACK-RESULT messages from other oracles and the human
- `inbox/handoff/` — reserved for oracle-to-oracle handoff
- `outbox/` — messages sent by texty
- `credentials/telegram.json` — bot_token and chat_id (gitignored)
- `channels/telegram.md` — Telegram setup guide
- `memory/resonance/` — awakening record
- `memory/learnings/` — operational guides (dispatch-guide, channel-ops, knowledge-access)
- `dispatch/` — append-only dispatch log, organized by month (e.g., `2026-05/`)
- `identity.md` — oracle identity YAML
- `learn/` — knowledge-capture directory for `/learn` skill

**Philosophy: append-only, never delete** (Principle 1). Every message, dispatch, and state change is recorded as a new file.

## Entry Points (All of Them)

| Entry Point | Type | Purpose |
|-------------|------|---------|
| `texty-daemon.py` | Python daemon | Telegram bot polling (5s interval), slash commands, message routing |
| `dispatch.sh` | Shell script | Manual dispatch to Telegram (text or polls) |
| `notify-texty.sh` | Shell script | Cross-oracle event notification → inbox + dispatch + Telegram |
| `session-summary-to-texty.sh` | Shell script | Stop hook: captures tmux summary, sends to Telegram |
| `query.sh` | Shell script | Knowledge search across vaults/DBs/web |
| `maw inbox` | CLI (maw plugin) | Inter-oracle MSG-ACK-RESULT protocol |

## Core Abstractions and Relationships

### MSG-ACK-RESULT Protocol

```
pending → acknowledged → completed
```

Message frontmatter:
```yaml
msg_id: MSG-{ORACLE}-{NNN}
from: {source_oracle}
to: {target_oracle}
type: task | query | escalation | info | ack | result
status: pending | acknowledged | completed
sent: {ISO timestamp}
ack_by: "-"
result: "-"
reply_file: "-"
```

### Dispatch Assessment (texty's role)

| MSG Type | Action | Telegram Format |
|----------|--------|-----------------|
| `escalation` | Forward immediately | 🚨 `[texty] ESCALATION from {oracle}` |
| `query` | Forward with vault context | ❓ `[texty] QUERY from {oracle}` |
| `task` | Forward with approval poll | ✅ `[texty] TASK from {oracle}` + poll |
| `info` | Auto-ACK, log only | — (no Telegram) |

### Communication Flow

```
Oracle A → maw inbox send texty "message"
    ↓
texty assesses type
    ├── escalation/query/task → Telegram → human
    ├── info → auto-ACK
    ↓
human responds via Telegram
    ↓
texty → maw inbox result → Oracle A's inbox
```

### Oracle Family Topology

```
emily (root)
  ├── god-port (trading)
  ├── pm (coordinator)
  └── texty (dispatcher)
```

## Dependencies

| Dependency | Purpose | Notes |
|-----------|---------|-------|
| Python 3.13 | daemon runtime | Standard library only, no pip packages |
| curl | Telegram API calls | Used in both Python and shell scripts |
| tmux | session management, pane capture, busy detection | Core to oracle lifecycle |
| Bun/maw | CLI orchestration | 70+ plugins, inbox protocol, fleet management |
| sqlite3 | knowledge search | Used by query.sh |

No package.json or requirements.txt — zero external Python dependencies.

## Busy/Idle Detection System

Implemented in `~/.maw/plugins/inbox/impl.ts`:

1. **`isOracleIdle(target)`**: Scans tmux pane for Claude Code's `❯` prompt and processing indicators
2. **Busy**: No `❯` found, or processing indicators (`✻`, `⏺`, `·`) below the prompt → reject message
3. **Idle**: Empty `❯` prompt with no processing below → accept + inject tmux notification
4. **No session**: Message delivered to inbox only (no rejection, no notification)

When `/send <oracle> <msg>` is used via Telegram:
- **BUSY**: `maw inbox send` throws error → daemon replies "⏳ oracle is busy"
- **IDLE**: Message written to inbox + `tmux send-keys` injects prompt → daemon replies "✅ delivered"

## Session Summary on End

`session-summary-to-texty.sh` fires from each oracle's Stop hook:
1. Captures last 80 lines of tmux output
2. Filters noise (empty lines, separators, spinners)
3. Takes last 5 meaningful lines as summary
4. Writes to texty inbox + dispatch log
5. Sends Telegram: `📋 {oracle} session ended + summary + ✅ Ready for new tasks — /send {oracle} <msg>`