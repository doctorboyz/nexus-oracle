# nexus-oracle API Surface

> Generated 2026-05-14 from source analysis

---

## 1. Public API -- Telegram Bot API Integration

### 1.1 Core API Client (`curl_api`)

**File**: `texty/nexus-daemon.py` lines 503-524

The single function `curl_api(method, params)` wraps every Telegram Bot API call. It uses `subprocess.run` with `curl` and 30s timeout.

```python
def curl_api(method, params=None):
    url = f"{API_URL}/{method}"   # API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
    # POST with JSON params, or GET with no params
    # Returns parsed JSON or None on error
```

Methods called:
| Method | Used In | Purpose |
|--------|---------|---------|
| `getUpdates` | `poll_updates()` L747-751 | Long-poll with 10s timeout, `allowed_updates: ["message"]` |
| `sendMessage` | `send_message()` L527-532, `process_outbox_file()` L296, `deliver_to_oracle()` L444-454, `notify-nexus.sh` L103, `dispatch.sh` L109, `session-summary.sh` L114 | Primary output channel |
| `sendPoll` | `dispatch.sh` L97-106 | Approval polls (Approve/Reject/Need more info) |
| `setMyCommands` | `register_commands()` L818-834 | Register `/wake`, `/sleep`, `/status`, `/inbox`, `/send`, `/broadcast`, `/goals`, `/help` |
| `deleteWebhook` | `nexus-daemon.sh` L94-101 (stop), `nexus-daemon.py` `main()` L857 | Switch from webhook to polling mode |

### 1.2 `send_message(text, chat_id=None, reply_to=None)`

**File**: `texty/nexus-daemon.py` lines 527-532

```python
def send_message(text, chat_id=None, reply_to=None):
    payload = {"chat_id": chat_id or CHAT_ID, "text": text, "parse_mode": "Markdown"}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    return curl_api("sendMessage", payload)
```

Used throughout daemon for command responses, delivery confirmations, auto-wake notifications, and broadcast messages. Supports Markdown parse mode and optional reply threading.

### 1.3 Polling Loop (`poll_updates`)

**File**: `texty/nexus-daemon.py` lines 744-815

Long-polls Telegram at `POLL_INTERVAL=3s` with `timeout=10`. Processes only `message` updates. Authorization enforced:
- **Allowed senders** (`ALLOWED_SENDERS`): `CHAT_ID` (human) + `BOT_ID` (for MCP-sent messages) -- L68
- **Allowed chats** (`AUTHORIZED_CHATS`): private chat + all channel group chats -- L66

Unrecognized senders or chats are silently dropped.

### 1.4 Outbox Watcher (`poll_outboxes`)

**File**: `texty/nexus-daemon.py` lines 322-348

Scans all oracle outbox directories every poll cycle. For each `.md` file (excluding `archive/`, dotfiles):
1. Parse YAML frontmatter
2. Determine target chat via `respond_in` field, `source_chat` cross-reference, oracle group, or private chat fallback (priority order, L266-287)
3. Send message prefixed with `[oracle_name]`
4. Archive successful sends to `outbox/archive/YYYY-MM/`

Ack-type messages are silently archived without sending (L256-257). Types sent: `result`, `reply`, `response`, or empty type (L260).

---

## 2. Extension Points

### 2.1 Adding New Slash Commands

**File**: `texty/nexus-daemon.py` function `handle_command()` L562-665

To add a new command:
1. Add entry to `commands` list in `register_commands()` (L818-834) for Telegram command menu
2. Add `elif cmd == "/newcmd":` branch in `handle_command()` (L562+)
3. Commands automatically strip `@bot_name` suffix (L566): `/send@texty_oracle_bot` becomes `/send`

Current commands:
| Command | Handler | maw Integration |
|---------|---------|-----------------|
| `/wake <oracle>` | `maw wake {oracle}` L590 | Yes |
| `/sleep <oracle>` | `maw sleep {oracle}` L599 | Yes |
| `/status` | `maw fleet ls` L607 | Yes |
| `/inbox <oracle>` | `maw inbox ls` L613 | Yes |
| `/send <oracle> <msg>` | `maw inbox send` or `write_to_inbox()` L618-637 | Yes + fallback |
| `/broadcast <msg>` | Direct API call to all channels L639-651 | No (direct) |
| `/goals` | Reads `ψ/goals/active/` L653-663 | No (filesystem) |
| `/help` | Static help text L569-584 | No |

### 2.2 Adding New Oracles to the Fleet

Three places must be updated:

1. **Fleet config** (`~/.config/maw/fleet/NN-name.json`): Add new JSON file with `name`, `windows[].root`, `routing.keywords`, `routing.domains`, `auto_wake`, `sync_peers`
2. **Telegram channels** (`ψ/credentials/telegram.json`): Add `"oracle_name": -100xxxxxxxxxx` to `channels` dict
3. **Oracle vault path** (`shared/vault-paths.sh` L27-37): Add `ORACLE_ROOT` and `ORACLE_VAULT` variables; add case in `msg_send()` (L42-48)

The daemon auto-loads oracle names from fleet config (L76-93) and oracle directories (L138-178) with 5-minute cache TTLs (`ORACLE_DIRS_CACHE_TTL`, `ROUTING_CACHE_TTL`).

### 2.3 Adding New Routing Keywords

**File**: `~/.config/maw/fleet/NN-name.json` under `routing` key

The `route_by_intent()` function (L363-408) matches message text against:
- `keywords`: Weighted by `(len(kw) / 3.0) + 1.0` per match (L383-385)
- `domains`: Fixed `+0.5` per match (L387-389)
- Confidence threshold: `>= 0.5` required for auto-routing in fleet group (L799)
- Tie-breaking: longer total keyword length wins (L403-404)

To add routing for a new oracle, add keywords and domains to its fleet config JSON. The daemon reloads routing every 5 minutes automatically.

### 2.4 Adding New Message Types

**File**: `shared/msg-protocol.sh` L31-32, L50

Current types: `escalation|query|task|info` (L32). To add a new type:
1. Add to the type comment/documentation
2. Handle in `process_outbox_file()` if the type requires special delivery logic (currently only `ack` is skipped, `result/reply/response/""` are sent -- L256-261)
3. Update `notify-nexus.sh` case statement (L47-51) if the type needs a special emoji

---

## 3. Integration Patterns

### 3.1 maw CLI Integration

The daemon shells out to `maw` for fleet management. All maw commands run via `run_cmd()` (L548-559) with 15s timeout.

| maw Command | Daemon Usage | Shell Script Usage |
|-------------|-------------|-------------------|
| `maw wake <oracle>` | `/wake` command L590 | Not used in shell scripts |
| `maw sleep <oracle>` | `/sleep` command L599 | Not used in shell scripts |
| `maw fleet ls` | `/status` command L607 | Not used in shell scripts |
| `maw inbox ls` | `/inbox` command L613 | Not used in shell scripts |
| `maw inbox send <oracle> "<msg>"` | `/send` command L624, `deliver_to_oracle()` L424 | Not used in shell scripts |
| `maw peek <oracle>` | `is_oracle_running()` L412 | Not used in shell scripts |

Fallback when maw cannot resolve an oracle: `write_to_inbox()` (L668-709) directly writes to the oracle's `ψ/inbox/` filesystem.

### 3.2 PM2 Process Management

**File**: `texty/nexus-daemon-launcher.sh`

The daemon is designed to run under PM2. The launcher:
- Resolves python3 path (prefers `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, falls back to `which python3`)
- Runs `nexus-daemon.py` with `-u` (unbuffered output)
- Logs to `logs/nexus-daemon.log` and `logs/nexus-daemon.err`

**File**: `texty/nexus-daemon.sh` -- alternative start/stop/status wrapper that also manages a `cloudflared` tunnel (port 8443). This script is for webhook mode (currently unused; daemon uses polling mode instead).

### 3.3 Telegram Channels

**File**: `ψ/credentials/telegram.json`

The `channels` dict maps oracle names to Telegram group chat IDs (negative integers). The daemon uses these for:
- Smart routing: messages in an oracle's group go directly to that oracle
- `/broadcast`: sends to all channels except "fleet"
- Outbox delivery: each oracle's responses go to their group by default

Channel configuration:
```json
{
  "channels": {
    "fleet": -1003530083227,
    "emily": -1003935822927,
    "god-port": -1003980671935,
    "nexus": -1003869399481,
    "fammee": -1003966517375,
    "kappy": -1003574843613,
    "infra": -1003732972862
  }
}
```

---

## 4. Shell API

### 4.1 `texty/dispatch.sh` -- Send Telegram Messages

**File**: `texty/dispatch.sh`

```
Usage: dispatch --message "text" [--oracle <name>] [--poll "question"]
```

| Flag | Required | Description |
|------|----------|-------------|
| `--message` | Yes | Text content to send |
| `--oracle` | No | Target oracle name; sends to that oracle's group chat. Without it, sends to private chat |
| `--poll` | No | Question text; sends a Telegram poll with fixed options (Approve/Reject/Need more info) |

Behavior:
- Reads `ψ/credentials/telegram.json` for `bot_token`, `chat_id`, and `channels`
- Creates dispatch log in `ψ/dispatch/YYYY-MM/DSP-YYYYMMDD-NNN.md`
- Uses curl to call `sendMessage` or `sendPoll` directly

### 4.2 `shared/outbox-write.sh` -- Write Outbox Responses

**File**: `shared/outbox-write.sh`

```
Usage:
  bash shared/outbox-write.sh --msg-id MSG-HUMAN-1434 --content "Your response"
  bash shared/outbox-write.sh --msg-id MSG-HUMAN-1434 --respond-in -100xxx --content "Your response"
  bash shared/outbox-write.sh --file inbox_file.md --content "Your response"
```

| Flag | Required | Description |
|------|----------|-------------|
| `--msg-id` | Yes (or `--file`) | Message ID to respond to |
| `--respond-in` | No | Telegram chat ID for delivery. Falls back to inbox message's `respond_in` field |
| `--content` | Yes (or stdin) | Response text. Can be piped via stdin |
| `--file` | No | Inbox file to extract `msg_id` and `respond_in` from |

Output: Writes to `ψ/outbox/YYYYMMDD_HHMM_{oracle_name}_{msg_id}.md` with YAML frontmatter. The nexus outbox watcher picks it up within 3-6 seconds.

### 4.3 `shared/msg-protocol.sh` -- MSG-ACK-RESULT Helpers

**File**: `shared/msg-protocol.sh`

Source this file: `source "$(dirname "$0")/../shared/vault-paths.sh" && source "$(dirname "$0")/msg-protocol.sh"`

| Function | Signature | Returns |
|----------|-----------|---------|
| `msg_generate_id` | () | Next sequential `MSG-NEXUS-NNN` ID |
| `msg_timestamp` | () | ISO 8601 UTC timestamp |
| `msg_date` | () | `YYYYMMDD` date string |
| `msg_time` | () | `HHMM` time string |
| `msg_send` | `<target_oracle> <type> <message>` | Writes to target inbox, prints `msg_id` |
| `msg_ack` | `<msg_id>` | Updates status to `acknowledged`, writes ack file |
| `msg_result` | `<msg_id> <result_summary>` | Updates status to `completed`, writes result file |
| `msg_status` | `<msg_id>` | Prints status: `pending`/`acknowledged`/`completed`/`not_found` |

`msg_send` targets: `emily`, `god-port`, `mkt`, `dev`, `kappy`, `nexus`. Adding a new oracle requires updating the case statement (L42-48).

### 4.4 `texty/notify-nexus.sh` -- External Oracle Notifications

**File**: `texty/notify-nexus.sh`

```
Usage: notify-nexus.sh <source_oracle> <event_type> <message>
```

| Argument | Description |
|----------|-------------|
| `source_oracle` | Name of the calling oracle (e.g. `emily`, `god-port`) |
| `event_type` | `escalation`, `error`, `session-end`, `commit`, `info` |
| `message` | Free-text description |

Behavior:
- Maps event types to emojis: escalation/error = siren, session-end = clipboard, commit = memo, info = info
- Writes to `ψ/inbox/` with proper frontmatter
- Creates dispatch log in `ψ/dispatch/`
- Sends Telegram notification via `sendMessage` API

### 4.5 `texty/query.sh` -- Cross-Vault Knowledge Search

**File**: `texty/query.sh`

```
Usage: query --scope vault|db|web --keyword "search term"
```

| Scope | Searches |
|-------|----------|
| `vault` | All oracle vaults: `*/ψ/memory/`, `ψ/goals/`, `*/ψ/inbox/`, `ψ/dispatch/` |
| `db` | All `.db` and `.sqlite` files under oracle base dir |
| `web` | Prints instruction to use Claude Code's `WebSearch` tool |

### 4.6 `pm/inbox-watcher.sh` -- fswatch Inbox Monitor

**File**: `pm/inbox-watcher.sh`

```
Usage:
  bash pm/inbox-watcher.sh          # Start (foreground, uses fswatch)
  bash pm/inbox-watcher.sh --stop   # Stop the watcher
  bash pm/inbox-watcher.sh --status # Check if running
```

Behavior:
- Uses `fswatch` to monitor `ψ/inbox/` for `Created` and `Updated` events
- Ignores `ack_*` and `result_*` files (those are from nexus itself)
- Extracts sender and `msg_id` from filename pattern `{date}_{time}_{sender}_{msg_id}.md`
- Sends macOS notification via `osascript`
- Writes receipt to `ψ/outbox/inbox_receipt_YYYYMMDD_HHMMSS.md`
- PID tracked at `/tmp/nexus-inbox-watcher.pid`

### 4.7 `pm/inject-hook.sh` -- Inject Stop Hooks

**File**: `pm/inject-hook.sh`

```
Usage: inject-hook.sh <oracle-name>
```

Behavior:
- Reads oracle root from `~/.config/maw/fleet/*.json`
- Creates `scripts/session-report-to-nexus.sh` in the target oracle repo
- Injects a `Stop` hook into `<oracle>/.claude/settings.json` that calls the script
- The script writes a session-end report to nexus's inbox

### 4.8 `shared/session-summary.sh` -- Session End Summary

**File**: `shared/session-summary.sh`

```
Usage: session-summary.sh <source_oracle>
```

Behavior:
- Captures last 10 lines from the oracle's tmux pane (filters out borders/prompts)
- Writes to `ψ/inbox/` with `type: info` and `from: <source_oracle>`
- Creates dispatch log
- Sends Telegram notification with session summary

### 4.9 `shared/vault-paths.sh` -- Path Resolution

**File**: `shared/vault-paths.sh`

Exports these variables (source before use):

| Variable | Path |
|----------|------|
| `NEXUS_ROOT` | `/Users/doctorboyz/Code/github.com/doctorboyz/nexus-oracle` |
| `PSI_DIR` | `$NEXUS_ROOT/ψ` (or `$NEXUS_ROOT/psi`) |
| `NEXUS_INBOX` | `$PSI_DIR/inbox` |
| `NEXUS_OUTBOX` | `$PSI_DIR/outbox` |
| `NEXUS_DISPATCH` | `$PSI_DIR/dispatch` |
| `NEXUS_CREDENTIALS` | `$PSI_DIR/credentials/telegram.json` |
| `NEXUS_GOALS` | `$PSI_DIR/goals` |
| `NEXUS_CHANNELS` | `$PSI_DIR/channels` |
| `NEXUS_MEMORY` | `$PSI_DIR/memory` |
| `NEXUS_LEARNINGS` | `$PSI_DIR/memory/learnings` |
| `EMILY_ROOT` | `/Users/doctorboyz/Code/github.com/doctorboyz/emily-oracle` |
| `GODPORT_ROOT` | `/Users/doctorboyz/Code/github.com/doctorboyz/god-port-oracle` |
| `MKT_ROOT` | `/Users/doctorboyz/Code/github.com/doctorboyz/mkt-oracle` |
| `DEV_ROOT` | `/Users/doctorboyz/Code/github.com/doctorboyz/dev-oracle` |
| `KAPPY_ROOT` | `/Users/doctorboyz/Code/github.com/doctorboyz/kappy-oracle` |
| `EMILY_VAULT` | `$EMILY_ROOT/ψ` (and similar for other oracles) |
| `NEXUS_MSG_PREFIX` | `MSG-NEXUS` |

---

## 5. Configuration Surface

### 5.1 `ψ/credentials/telegram.json` Schema

```json
{
  "bot_token": "string (Telegram bot API token)",
  "bot_id": "string (numeric bot user ID, optional, derived from token)",
  "chat_id": "string (human's private Telegram chat ID)",
  "note": "string (description)",
  "created": "string (ISO date)",
  "channels": {
    "fleet": "integer (Telegram group chat ID)",
    "emily": "integer",
    "god-port": "integer",
    "nexus": "integer",
    "fammee": "integer",
    "kappy": "integer",
    "infra": "integer"
  }
}
```

This file is gitignored (`.gitignore` L5: `ψ/credentials/`).

### 5.2 Fleet Config Schema (`~/.config/maw/fleet/NN-name.json`)

```json
{
  "name": "string (oracle name, matches channels key)",
  "windows": [
    {
      "name": "string (tmux window name)",
      "repo": "string (GitHub repo path: user/repo)",
      "root": "string (absolute path to oracle repo root)"
    }
  ],
  "sync_peers": ["string (oracle names to sync with)"],
  "budded_from": "string|null (parent oracle name)",
  "budded_at": "string (ISO 8601 timestamp)",
  "note": "string (optional description)",
  "routing": {
    "keywords": ["string (Thai + English keywords for intent matching)"],
    "domains": ["string (topic domains for lower-weight matching)"]
  },
  "auto_wake": "boolean (true = daemon wakes oracle on message delivery)"
}
```

Key routing fields:
- `keywords`: High-weight matches (weight = `len(kw)/3 + 1`). Thai and English terms.
- `domains`: Low-weight matches (weight = `0.5`). Broad topic categories.
- `auto_wake`: When `true`, `deliver_to_oracle()` calls `maw wake` if oracle not running.

---

## 6. Data Formats

### 6.1 Inbox/Outbox Message YAML Frontmatter

**File**: `shared/msg-protocol.sh` L53-67, `texty/nexus-daemon.py` L462-495

```yaml
---
msg_id: MSG-NEXUS-001        # or MSG-HUMAN-HHMM, MSG-GP-NNN, MSG-{PREFIX}-AUTO-HHMM
from: nexus                    # sender oracle or "human"
to: god-port                   # target oracle or "nexus" or "human (Telegram)"
type: query                    # escalation | query | task | info | reply | result
status: pending                # pending | acknowledged | completed | processed | routed
sent: 2026-05-14T15:03:00Z    # ISO 8601 UTC
source_chat: -1003980671935   # Telegram chat ID (optional, for routing responses)
source_oracle: god-port        # originating oracle group (optional)
routed_to: god-port            # auto-routing destination (optional)
routing_method: intent          # "intent" (fleet group) or "direct" (oracle group/private)
respond_in: -1003530083227     # Telegram chat ID for response delivery (optional)
respond_chat_type: group        # "group" or "private" (optional)
ack_by: "-"                     # timestamp or "-" if not acked
result: "-"                     # timestamp or "-" if not resolved
reply_file: "-"                 # path to reply file or "-"
---

Message body text here.
```

### 6.2 Dispatch Log Format

**File**: `texty/dispatch.sh` L81-93, `texty/notify-nexus.sh` L76-88

Path pattern: `ψ/dispatch/YYYY-MM/DSP-YYYYMMDD-NNN.md`

```yaml
---
dispatch_id: DSP-20260503-017
from: emily
to: human (Telegram)           # or oracle group name
type: info                      # info | task | escalation
status: forwarded               # forwarded | delivered
sent: 2026-05-03T07:23:42Z
result: awaiting                # awaiting | confirmed
---

Message content here.
```

### 6.3 Outbox Response Format

**File**: `shared/outbox-write.sh` L107-121

```yaml
---
msg_id: MSG-HUMAN-1434
from: nexus
type: result                    # result | reply | response | ack (ack is silently archived)
timestamp: 2026-05-14T15:03:00Z
respond_in: -1003530083227      # Telegram chat ID for delivery target
---

Response body text here.
```

### 6.4 Archive Directory Structure

```
ψ/
  inbox/
    2026-04-29_11.15_god-port_MSG-GP-002.md
    {date}_{time}_{sender}_{msg_id}.md
  outbox/
    archive/
      2026-05/                  # monthly archive of processed outbox files
  dispatch/
    2026-04/                    # monthly dispatch logs
    2026-05/
      DSP-20260503-017.md
  goals/
    active/                     # current goal files (.md)
    completed/                  # achieved goals
    archived/                   # superseded goals
    handoff/                    # goals handed between oracles
  credentials/
    telegram.json               # gitignored
  channels/
    telegram.md                 # setup guide
  memory/
    learnings/
    retrospectives/
  texty/                        # dispatcher sub-vault
  pm/                           # coordinator sub-vault
```

### 6.5 Inbox Receipt Format

**File**: `pm/inbox-watcher.sh` L72-87

```yaml
---
type: inbox_receipt
date: 2026-05-14T15:03:00Z
from: inbox-watcher
---

# Inbox Receipt
New message detected: {filename}
Source: {sender}
Time: {timestamp}
```

### 6.6 Message ID Conventions

| Prefix | Origin | Example |
|--------|--------|---------|
| `MSG-NEXUS-NNN` | nexus-initiated messages | `MSG-NEXUS-001` |
| `MSG-HUMAN-HHMM` | Human-initiated via Telegram | `MSG-HUMAN-1434` |
| `MSG-GP-NNN` | god-port initiated | `MSG-GP-002` |
| `MSG-{PREFIX}-AUTO-HHMM` | Auto-generated (Stop hooks, session reports) | `MSG-go-AUTO-1516` |
| `MSG-EM-NNN` | emily initiated | `MSG-EM-001` |
| `DSP-YYYYMMDD-NNN` | Dispatch log IDs | `DSP-20260503-017` |

---

## 7. Daemon Smart Routing Logic

**File**: `texty/nexus-daemon.py` L786-815

Three routing cases for non-command messages:

| Case | Condition | Behavior |
|------|-----------|----------|
| **Oracle group** | `chat_id` matches a channel group | Direct delivery to that oracle via `deliver_to_oracle()` |
| **Fleet group** | `chat_id` matches `channels.fleet` | Intent routing via `route_by_intent()`. If confidence >= 0.5, auto-delivers. Otherwise, asks human which oracle. |
| **Private/unknown** | `chat_id` matches `CHAT_ID` or unknown | Forwarded to nexus inbox via `forward_to_nexus()` |

`deliver_to_oracle()` flow (L417-500):
1. Try `maw inbox send {oracle} "{text}"` -- falls back to direct filesystem write
2. If oracle not running and `auto_wake=true`, run `maw wake {oracle}`
3. Post confirmation in source chat
4. Write audit trail to nexus inbox with routing metadata

---

*End of API Surface document.*
