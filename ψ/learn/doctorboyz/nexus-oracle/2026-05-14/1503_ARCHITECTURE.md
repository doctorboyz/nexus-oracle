# nexus-oracle Architecture Analysis

> Generated 2026-05-14 by learn agent

---

## 1. Directory Structure and Organization Philosophy

nexus-oracle follows a **role-based** directory layout where code tools and agent vault are cleanly separated:

```
nexus-oracle/
├── texty/              # Dispatcher role tools (Telegram-facing)
├── pm/                 # Coordinator role tools (fleet management)
├── shared/             # Cross-role utility library
├── scripts/            # (empty) CLI entry points placeholder
├── ψ/                  # Agent vault — the persistent brain
│   ├── identity.md       # Oracle identity document
│   ├── inbox/            # Incoming messages (MSG-ACK-RESULT protocol)
│   ├── outbox/           # Outgoing responses (archive/ subfolder)
│   ├── dispatch/         # Append-only dispatch log (monthly folders)
│   ├── channels/         # Channel config docs (telegram.md)
│   ├── credentials/      # API keys (gitignored)
│   ├── goals/            # Goal tracking (active/completed/archived)
│   ├── memory/           # Persistent knowledge
│   │   ├── learnings/      # Protocol docs, guides, operational learnings
│   │   └── retrospectives/ # Session retrospectives
│   ├── texty/            # Dispatcher sub-vault
│   └── pm/               # Coordinator sub-vault
└── logs/               # Runtime logs (daemon, cloudflared)
```

**Philosophy**: The `texty/` and `pm/` directories hold **executable tools** (shell scripts, Python daemon). The `ψ/` directory holds **persistent state** — messages, goals, dispatch logs, memory. Code is ephemeral; the vault is permanent. The `shared/` directory provides common utilities (path resolution, message protocol, outbox writing) that both roles use. This mirrors the project's founding principle: "Nothing is Deleted" — vault files are append-only, goal files are superseded rather than removed.

The `ψ/` directory uses a Unicode character (Greek psi) as its name. Both the Python daemon and shell scripts contain fallback logic to find either `ψ/` or `psi/` (see `nexus-daemon.py` lines 36-46 `find_psi_dir()` and `shared/vault-paths.sh` lines 8-14).

---

## 2. Entry Points

### 2.1 nexus-daemon.py (`texty/nexus-daemon.py`)

**Primary daemon** — a long-running Python process that:
- Polls Telegram Bot API every 3 seconds via `getUpdates` (long polling with 10s timeout) (lines 747-875)
- Polls all oracle outboxes every cycle for response delivery (lines 322-348)
- Provides slash commands: `/wake`, `/sleep`, `/status`, `/inbox`, `/send`, `/broadcast`, `/goals`, `/help` (lines 562-665)
- Implements smart routing for non-command messages (lines 784-816)
- Registers bot commands on startup via `setMyCommands` (lines 818-834)

Key configuration:
- `POLL_INTERVAL = 3` seconds between cycles
- `ROUTING_CACHE_TTL = 300` seconds for routing table refresh
- `ORACLE_DIRS_CACHE_TTL = 300` seconds for fleet directory refresh
- Credentials loaded from `ψ/credentials/telegram.json` (bot_token, bot_id, chat_id, channels)

### 2.2 nexus-daemon.sh (`texty/nexus-daemon.sh`)

**Webhook-mode launcher** — starts the daemon behind a cloudflared tunnel:
- Starts `cloudflared tunnel --url http://localhost:8443` (line 29)
- Waits up to 40 seconds for the tunnel URL (lines 36-44)
- Launches `nexus-daemon.py` with stdout/stderr redirected to logs (line 60-61)
- Manages PID files for both cloudflared and the Python process
- On stop, kills both processes and calls `deleteWebhook` on the Telegram API (lines 94-102)

### 2.3 nexus-daemon-launcher.sh (`texty/nexus-daemon-launcher.sh`)

**launchd-compatible wrapper** — used when running the daemon as a macOS service:
- Resolves Python 3.13 path (lines 10-13)
- Runs with `-u` flag for unbuffered output
- Redirects all output to `logs/nexus-daemon.log` and `logs/nexus-daemon.err`

### 2.4 dispatch.sh (`texty/dispatch.sh`)

**One-shot message sender** — a bash script for sending Telegram messages or polls:
- Reads `ψ/credentials/telegram.json` for bot token and chat IDs (lines 37-42)
- Routes to oracle-specific group chat (`--oracle` flag) or default private chat (lines 44-63)
- Logs every dispatch to `ψ/dispatch/YYYY-MM/DSP-YYYYMMDD-NNN.md` (lines 73-93)
- Uses `curl` to call the Telegram Bot API directly (lines 96-112)

### 2.5 inbox-watcher.sh (`pm/inbox-watcher.sh`)

**Filesystem event monitor** — watches `ψ/inbox/` using `fswatch`:
- Detects new/updated `.md` files (line 49)
- Skips `ack_*` and `result_*` files (nexus-generated) (line 53)
- Sends macOS notifications via `osascript` (line 69)
- Writes receipt files to `ψ/outbox/` (lines 72-87)
- Runs as a background process with PID tracking

### 2.6 inject-hook.sh (`pm/inject-hook.sh`)

**Claude Code hook injector** — adds Stop hooks to other oracle repos:
- Reads fleet config from `~/.config/maw/fleet/*.json` to find oracle root directories (lines 26-32)
- Creates a `scripts/session-report-to-nexus.sh` in the target oracle (lines 51-94)
- Writes/merges a Stop hook into the target's `.claude/settings.json` (lines 103-149)
- When a target oracle's Claude Code session ends, it auto-sends a session-end report to nexus's inbox

---

## 3. Core Abstractions and Their Relationships

### 3.1 The Daemon Polling Loop

The central abstraction is the `main()` loop in `nexus-daemon.py` (lines 844-874):

```
while True:
    poll_updates()      # Read Telegram messages
    poll_outboxes()      # Scan oracle outboxes for responses
    time.sleep(3)        # Wait before next cycle
```

Each cycle performs two operations:
1. **Inbound**: Read Telegram updates via Bot API `getUpdates` (long-polling with 10s timeout), then route messages
2. **Outbound**: Scan all oracle outbox directories for new `.md` files, parse frontmatter, determine target chat, send via Telegram API, then archive

This dual-direction polling makes nexus a **bidirectional bridge** between Telegram and the oracle fleet.

### 3.2 Smart Routing System

Defined in `nexus-daemon.py` lines 363-408 (`route_by_intent()`). Three routing tiers:

**Tier 1 — Oracle Group (direct)**: When a message arrives in an oracle-specific Telegram group, it goes directly to that oracle. Context is unambiguous. (lines 788-789)

**Tier 2 — Fleet Group (keyword-based)**: Messages in the "fleet" group are scored against routing keywords/domains from fleet configs. Each keyword match adds `len(keyword)/3 + 1.0` points; domain matches add 0.5. Confidence is `min(score/3.0, 1.0)`. Requires confidence >= 0.5 to auto-route; otherwise asks the human. (lines 793-811)

**Tier 3 — Private/Unknown (fallback)**: Messages in private chat or unrecognized groups are forwarded to nexus's own inbox for manual triage. (lines 813-815)

Routing keywords per oracle (from fleet config, documented in `ψ/memory/learnings/2026-05-14_smart-routing.md`):
- emily: buddy, spawn, oracle, create, meta, framework, architecture, design
- god-port: trade, trading, backtest, signal, position, profit, pnl, portfolio, market, forex, xau, gold, chart, indicator, ea, strategy
- kappy: knowledge, line, bot, search, learn, remember, wiki, note, document
- fammee: fam, family, schedule, calendar, reminder, meal, grocery, todo, personal, home
- infra: deploy, docker, container, server, infra, tunnel, cloudflare, ci, release, build, logs, nginx, ssl, domain, dns, pm2, daemon

### 3.3 Outbox Watcher

`poll_outboxes()` (lines 322-348) scans all oracle outbox directories every cycle. For each `.md` file found:
1. Parse YAML frontmatter for `type`, `msg_id`, `from`, `respond_in`
2. Skip `ack` type messages (already confirmed via `deliver_to_oracle`)
3. Determine target chat via priority: `respond_in` field > source_chat cross-reference > oracle's Telegram group > private chat (lines 266-288)
4. Send via Telegram Bot API with `[oracle]` attribution prefix (lines 291-296)
5. Archive to `outbox/archive/YYYY-MM/` (lines 308-319)

### 3.4 MSG-ACK-RESULT Protocol

Formally defined in `ψ/memory/learnings/message-protocol.md` and implemented by `shared/msg-protocol.sh`.

**State machine**: `pending -> acknowledged -> completed`

**Send phase**: Sender writes a `.md` file to the receiver's `ψ/inbox/` with frontmatter containing `msg_id`, `from`, `to`, `type`, `status: pending`.

**Ack phase**: Receiver reads the inbox file, updates `status: acknowledged` and `ack_by: <timestamp>`, then writes `ack_{msg_id}_{date}.md` to their own `ψ/outbox/`.

**Result phase**: Receiver updates `status: completed` and writes `result_{msg_id}_{date}.md` to their outbox, which the outbox watcher picks up and delivers to Telegram.

**Timeout rules** (from protocol docs):
- < 1 session pending: wait
- > 1 session pending: `maw peek` or send reminder
- > 2 sessions pending: log timeout in goal file
- > 3 sessions pending: escalate to emily

Shell helpers in `shared/msg-protocol.sh`:
- `msg_generate_id()`: Auto-increment MSG-NEXUS-NNN IDs
- `msg_send()`: Write to target oracle's inbox with correct frontmatter
- `msg_ack()`: Acknowledge a message, update status, write ack file
- `msg_result()`: Mark completed, write result file
- `msg_status()`: Query current status of a message

### 3.5 Delivery Pipeline (`deliver_to_oracle()`)

`nexus-daemon.py` lines 417-500 implement the full delivery pipeline:
1. **Try `maw inbox send`**: Primary delivery via the maw orchestration tool (line 424)
2. **Fallback direct write**: If maw fails, write directly to the oracle's `ψ/inbox/` (lines 427-428, `write_to_inbox()` lines 668-709)
3. **Auto-wake**: If oracle is not running and `auto_wake: true` in fleet config, call `maw wake` (lines 432-437)
4. **Confirm in source chat**: Send delivery confirmation to the Telegram chat where the message originated (lines 440-454)
5. **Audit trail**: Write to nexus's own `ψ/inbox/` with `routing_method` and `respond_in` metadata (lines 457-495)

---

## 4. Dependencies

### 4.1 External Tools

| Dependency | Purpose | Used In |
|---|---|---|
| **Telegram Bot API** | Bidirectional messaging (long-polling getUpdates, sendMessage, sendPoll) | `nexus-daemon.py`, `dispatch.sh`, `session-summary.sh`, `notify-nexus.sh` |
| **maw** | Oracle fleet orchestration CLI (wake, sleep, peek, inbox send, fleet ls) | `nexus-daemon.py` (commands + delivery) |
| **cloudflared** | TLS tunnel for webhook mode | `nexus-daemon.sh` |
| **fswatch** | Filesystem event monitoring for inbox | `pm/inbox-watcher.sh` |
| **PM2** | Process management (mentioned in CLAUDE.md) | Production deployment |
| **Python 3** | Runtime for daemon | `nexus-daemon.py`, `nexus-daemon-launcher.sh` |
| **curl** | HTTP client for Telegram API calls | All shell scripts, Python daemon |
| **osascript** | macOS native notifications | `pm/inbox-watcher.sh` |

### 4.2 Configuration Dependencies

| Config | Location | Purpose |
|---|---|---|
| **Telegram credentials** | `ψ/credentials/telegram.json` | bot_token, bot_id, chat_id, channels map |
| **Fleet configs** | `~/.config/maw/fleet/*.json` | Oracle names, roots, routing keywords, auto_wake flags |
| **Vault paths** | `shared/vault-paths.sh` | Hard-coded paths to all oracle vault directories |
| **Claude Code hooks** | `.claude/settings.json` | Stop hook for session summary, PostToolUse hook for inbox reminders |

### 4.3 Internal Dependencies (Cross-Oracle)

The `shared/vault-paths.sh` file hard-codes paths to sibling oracle repos:
- `/Users/doctorboyz/Code/github.com/doctorboyz/emily-oracle/ψ`
- `/Users/doctorboyz/Code/github.com/doctorboyz/god-port-oracle/ψ`
- `/Users/doctorboyz/Code/github.com/doctorboyz/mkt-oracle/ψ`
- `/Users/doctorboyz/Code/github.com/doctorboyz/dev-oracle/ψ`
- `/Users/doctorboyz/Code/github.com/doctorboyz/kappy-oracle/ψ`

The Python daemon reads fleet configs from `~/.config/maw/fleet/` at runtime for the same information, making the shell paths a secondary fallback.

---

## 5. Data Flow: Telegram -> Daemon -> Oracle -> Outbox -> Telegram

### Complete Message Lifecycle

```
[1] HUMAN sends message in Telegram
        |
        v
[2] nexus-daemon.py polls Telegram (getUpdates every 3s)
        |
        v
[3] Message classified:
    a) Slash command -> handle_command() -> direct response
    b) Oracle group message -> deliver_to_oracle(oracle_name, text, chat_id, from_id)
    c) Fleet group message -> route_by_intent() -> deliver_to_oracle() or ask human
    d) Private/unknown -> forward_to_nexus() -> write to ψ/inbox/
        |
        v
[4] deliver_to_oracle():
    a) Try: maw inbox send {oracle} "{text}"
    b) Fallback: write_to_inbox() -> direct file write to {oracle}/ψ/inbox/
    c) If not running: maw wake {oracle} (auto-wake)
    d) Confirm: send Telegram confirmation in source chat
    e) Audit: write to nexus ψ/inbox/ with routing metadata
        |
        v
[5] Target oracle's Claude Code session wakes, reads inbox
        |
        v
[6] Oracle processes message, writes response to own ψ/outbox/
    (with frontmatter: msg_id, from, type: result, respond_in: <chat_id>)
        |
        v
[7] nexus-daemon.py polls outboxes (poll_outboxes() every 3s)
        |
        v
[8] For each outbox .md file:
    a) Parse frontmatter (type, msg_id, from, respond_in)
    b) Determine target chat (respond_in > source_chat lookup > oracle group > private)
    c) Send via Telegram API: "💬 [{from_oracle}]\n\n{body}"
    d) Archive file to outbox/archive/YYYY-MM/
        |
        v
[9] HUMAN receives oracle response in Telegram
```

### Dispatch Path (Agent-Initiated)

When nexus agent itself wants to send a message (e.g., session summary, escalation):

```
[1] Agent calls bash texty/dispatch.sh --message "..." [--oracle <name>]
        |
        v
[2] dispatch.sh:
    a) Read bot_token and chat_id from ψ/credentials/telegram.json
    b) Resolve target: --oracle flag -> channel map, else private chat
    c) Log dispatch to ψ/dispatch/YYYY-MM/DSP-YYYYMMDD-NNN.md
    d) Send via curl to Telegram Bot API (sendMessage or sendPoll)
        |
        v
[3] Telegram delivers message to human or oracle group
```

### Notification Path (Other Oracle -> Nexus)

When another oracle needs to notify nexus (e.g., session end, error):

```
[1] Other oracle's Stop hook calls bash shared/session-summary.sh <oracle>
    -or- bash texty/notify-nexus.sh <source> <type> "<message>"
        |
        v
[2] Script:
    a) Write to nexus ψ/inbox/ with MSG-ACK-RESULT frontmatter
    b) Log dispatch to ψ/dispatch/YYYY-MM/
    c) Send Telegram notification with emoji prefix (🚨/📋/📝/ℹ️)
        |
        v
[3] nexus agent reads inbox on next session wake
```

### Outbox Write Path (Oracle Response)

When an oracle agent wants to respond to a message:

```
[1] Agent calls: bash shared/outbox-write.sh --msg-id MSG-HUMAN-1434 --content "response"
        |
        v
[2] outbox-write.sh:
    a) Resolve ψ/ directory
    b) Write to ψ/outbox/{timestamp}_{oracle}_{msg_id}.md
    c) Include frontmatter: msg_id, from, type, timestamp, respond_in
        |
        v
[3] nexus-daemon.py polls outboxes every 3s
        |
        v
[4] process_outbox_file():
    a) Parse frontmatter
    b) Determine target chat
    c) Send "💬 [{from_oracle}]\n\n{body}" to Telegram
    d) Archive file
```

---

## Key Architectural Observations

1. **Vault-as-database pattern**: The `ψ/` directory is the oracle's persistent memory. Messages, goals, dispatch logs, and learnings are all markdown files with YAML frontmatter. There is no traditional database — the filesystem IS the database.

2. **Polling over webhooks (current default)**: The daemon uses `getUpdates` long-polling, not webhooks. The webhook infrastructure (`nexus-daemon.sh` with cloudflared) exists but the daemon's main loop calls `poll_updates()` which uses polling. This is simpler to operate but has 3-6 second latency.

3. **Dual identity — Dispatcher + Coordinator**: The two roles (texty and pm) share one daemon. The Dispatcher role handles Telegram messaging; the Coordinator role handles goal tracking and fleet orchestration. They share the same vault but use different tool directories.

4. **Graceful degradation**: The daemon has fallbacks at every layer: `maw inbox send` falls back to direct file write; direct file write falls back to forwarding to nexus inbox; webhook mode falls back to polling mode.

5. **Audit trail by design**: Every dispatch is logged to `ψ/dispatch/YYYY-MM/DSP-*.md`. Every inbox message has a full lifecycle tracked in its frontmatter (status, ack_by, result, reply_file). The "Nothing is Deleted" principle means this data is append-only.

6. **Fleet config as source of truth**: Oracle discovery (names, roots, routing keywords) is loaded from `~/.config/maw/fleet/*.json` with a 5-minute cache TTL. This means fleet membership changes propagate within 5 minutes without daemon restart.

7. **Session-aware hooks**: The `.claude/settings.json` PostToolUse hook checks for unprocessed inbox messages after every file write, and the Stop hook sends a session summary to Telegram. The `pm/inject-hook.sh` tool propagates these hooks to other oracle repos.
