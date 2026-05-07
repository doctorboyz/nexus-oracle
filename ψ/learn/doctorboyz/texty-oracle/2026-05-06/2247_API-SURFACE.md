# texty-oracle API & Integration Surface

## 1. Telegram Bot API Integration

**Script**: `scripts/texty-daemon.py`
**Config**: `ψ/credentials/telegram.json`

Long-polling architecture (not webhooks). Polls `getUpdates` every 5s, filters for `"message"` type, tracks `OFFSET` for ack-based delivery.

### Slash Commands

| Command | Function | Implementation |
|---------|----------|---------------|
| `/wake <oracle>` | Start oracle session | `maw wake {oracle}` |
| `/sleep <oracle>` | Stop oracle session | `maw sleep {oracle}` |
| `/status` | Show fleet status | `maw fleet ls` |
| `/inbox <oracle>` | Check oracle inbox | `maw inbox ls` |
| `/send <oracle> <msg>` | Send message to oracle | `maw inbox send {oracle} "{msg}"` |
| `/help` | Show available commands | Static help text |

`/send` includes **busy/idle detection**: returns "⏳ busy" if oracle is processing.

### Non-Command Messages
Free-text from human → `MSG-HUMAN-{time}.md` in `ψ/inbox/` with type `query`.

### API Calls (all via curl)
- `sendMessage` — text with optional Markdown
- `sendPoll` — approval polls with options: Approve/Reject/Need more info
- `getUpdates` — long-polling for incoming messages
- `setMyCommands` — bot command registration

### Rate Limiting
Max 1 message per oracle per minute. Multiple escalations batched into single message.

## 2. MSG-ACK-RESULT Protocol

**Implementation**: `~/.maw/plugins/inbox/impl.ts`

### Message States
```
pending → acknowledged → completed
```

### Frontmatter Schema
```yaml
---
msg_id: MSG-{SENDER_UPPER}-{NNN}
from: {oracle_name}
to: {target_oracle}
type: task|query|escalation|info|ack|result
status: pending|acknowledged|completed
sent: {ISO timestamp}
ack_by: {ISO timestamp or "-"}
result: {result text or "-"}
reply_file: {path or "-"}
---
{message body}
```

### Filename Convention
`{YYYYMMDD}_{HH-MM}_{sender}_{MSG-{SENDER}-{NNN}}.md`

### Message Type Assessment

| Type | texty Action | Telegram Format |
|------|-------------|-----------------|
| `escalation` | Forward immediately | 🚨 `[texty] ESCALATION from {oracle}` |
| `query` | Forward with vault context | ❓ `[texty] QUERY from {oracle}` |
| `task` | Forward with approval poll | ✅ `[texty] TASK from {oracle}` |
| `info` | Auto-ACK, log only | — (no Telegram) |

### maw inbox Commands
```
maw inbox ls [--unread] [--from <oracle>] [--last N]
maw inbox send <oracle> <message> [--type task|query|escalation|info]
maw inbox ack <msg_id>
maw inbox result <msg_id> <result text>
maw inbox show <id>
maw inbox read <id>
```

## 3. Dispatch Logging System

**Directory**: `ψ/dispatch/YYYY-MM/`

Append-only records. Format: `DSP-{YYYYMMDD}-{NNN}.md`

```yaml
---
dispatch_id: DSP-20260506-001
from: pm
to: human (Telegram)
type: info
status: forwarded
sent: 2026-05-06T03:14:18Z
result: awaiting
---
[session-end] Session ended
```

## 4. Busy/Idle Oracle Detection API

### maw Level (`isOracleIdle()` in `~/.maw/plugins/inbox/impl.ts`)
- Captures last 50 lines of tmux pane via `tmux capture-pane`
- Strips ANSI escape codes
- Finds last `❯` prompt line
- Checks for processing indicators (`✻`, `⏺`, `·`, Julienning, etc.) below the prompt
- **BUSY**: Processing indicators found or no prompt → reject, no file written
- **IDLE**: Empty `❯` prompt, no processing → accept + tmux notification

### texty-daemon Level
```python
if "busy" in output.lower():
    return f"⏳ *{oracle}* is busy — try again when session ends"
```

### maw Trigger Engine (Idle Triggers)
- `markAgentActive(agent)` records timestamp, marks "busy"
- `checkIdleTriggers()` fires "agent-idle" trigger on busy→idle transition
- Configurable timeout per trigger

## 5. Hook System

**texty-oracle/.claude/settings.json**:
```json
{
  "hooks": {
    "Stop": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "bash .../session-summary-to-texty.sh texty"
      }]
    }]
  }
}
```

All sibling oracles have Stop hooks calling `session-summary-to-texty.sh` with their own name:
- emily: `session-summary-to-texty.sh emily`
- god-port: `session-summary-to-texty.sh god-port`
- pm: `session-summary-to-texty.sh pm`

## 6. Vault Access (Read-Only)

| Oracle | Vault Path |
|--------|-----------|
| emily | `/Users/doctorboyz/Code/github.com/doctorboyz/emily-oracle/ψ/` |
| god-port | `/Users/doctorboyz/Code/github.com/doctorboyz/god-port-oracle/ψ/` |
| pm | `/Users/doctorboyz/Code/github.com/doctorboyz/pm-oracle/ψ/` |

### Knowledge Query Protocol (3-tier)

```bash
query --scope vault --keyword "MT5"     # grep across oracle vaults
query --scope db --keyword "trades"       # sqlite3 search
query --scope web --keyword "latest API"  # delegates to Claude WebSearch
```

## 7. How Other Oracles Interact with texty

### notify-texty.sh (Event Notification)
```bash
notify-texty.sh <source_oracle> <event_type> "<message>"
# Event types: escalation, error, session-end, commit, info
```
Writes inbox + dispatch log + sends Telegram with emoji prefix.

### session-summary-to-texty.sh (Stop Hook)
```bash
session-summary-to-texty.sh <source_oracle>
```
Captures tmux output, extracts summary, sends to Telegram with "✅ Ready for new tasks" CTA.

### Direct maw inbox send
```bash
maw inbox send texty "message"
```
Writes directly to texty's `ψ/inbox/`.

## Key File Reference

| File | Purpose |
|------|---------|
| `scripts/texty-daemon.py` | Telegram bot daemon |
| `scripts/dispatch.sh` | Manual dispatch to Telegram |
| `scripts/notify-texty.sh` | Oracle→Telegram notification |
| `scripts/session-summary-to-texty.sh` | Stop hook handler |
| `scripts/query.sh` | Knowledge search (vault/DB/web) |
| `ψ/credentials/telegram.json` | Bot token & chat ID |
| `ψ/channels/telegram.md` | Telegram setup guide |
| `~/.maw/plugins/inbox/impl.ts` | MSG-ACK-RESULT protocol + busy detection |
| `~/.maw/plugins/inbox/index.ts` | maw inbox CLI command routing |
| `~/.maw-js/src/commands/shared/comm-send.ts` | maw send with idle check |