# texty-oracle Quick Reference

## What texty-oracle Does

texty-oracle is a **communication dispatcher** that bridges the Oracle family (a multi-agent system orchestrated by `maw`) and a human operator via Telegram. Its core identity: "The voice line, not the voice owner — every message passes through us, every answer comes from the person."

**Core responsibilities:**

- **Relay messages**: Receives MSG-ACK-RESULT protocol messages from other oracles and forwards them to the human via Telegram, then returns the human's response back.
- **Slash-command daemon**: A persistent Python daemon (`texty-daemon.py`) polls the Telegram Bot API for commands and executes them locally via the `maw` CLI.
- **Knowledge query**: When the human asks questions, texty searches across all oracle vaults and the web, then responds with sourced answers.
- **Session-end summaries**: Captures tmux output and sends summaries to Telegram when oracle sessions end.
- **Event notification**: Allows any oracle to push events through texty to Telegram with emoji prefixes.

**What texty never does:**

- Never auto-approves decisions — everything goes through the human
- Never modifies other oracles' vaults — read-only access, communication via MSG-ACK-RESULT only
- Never impersonates the human — all outbound messages carry the `[texty]` prefix

## Installation and Setup

### 1. Telegram Bot Token

Create a Telegram bot via `@BotFather` on Telegram.

### 2. Chat ID Discovery

Send any message to the bot, then use `telegram-get-unread` to discover your `chat_id`.

### 3. Configure Credentials

Create `ψ/credentials/telegram.json`:

```json
{
  "bot_token": "<YOUR_BOT_TOKEN>",
  "bot_id": "<YOUR_BOT_ID>",
  "chat_id": "<YOUR_CHAT_ID>",
  "note": "Bot: @texty_oracle_bot via BotFather",
  "created": "2026-04-29"
}
```

This file is gitignored (via `ψ/.gitignore`).

### 4. Start the Daemon

```bash
# Direct launch (foreground, for testing)
python3 scripts/texty-daemon.py

# Via launcher (background, with logging)
bash scripts/texty-daemon-launcher.sh
```

The daemon polls Telegram every 5 seconds using long polling.

### 5. Configure Claude Code Hook

`.claude/settings.json` configures a Stop hook that runs `session-summary-to-texty.sh` when a session ends.

## Telegram Slash Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/wake <oracle>` | Start an oracle session | `/wake emily` |
| `/sleep <oracle>` | Stop an oracle session | `/sleep god-port` |
| `/status` | Show fleet status | `/status` |
| `/inbox <oracle>` | Check an oracle's inbox | `/inbox pm` |
| `/send <oracle> <msg>` | Send message to oracle | `/send emily hello` |
| `/help` | Show available commands | `/help` |

Valid oracle names: `emily`, `god-port`, `pm`, `texty`.

Non-command messages are treated as human queries and written to `ψ/inbox/`.

## Dispatch Script

```bash
# Send a text message
bash scripts/dispatch.sh --message "[texty] ESCALATION from god-port: MT5 connection lost"

# Send a poll for approval
bash scripts/dispatch.sh --message "Deploy v2.1?" --poll "Should we deploy v2.1?"
```

## Notify Script (from other oracles)

```bash
bash scripts/notify-texty.sh <oracle> <event_type> "<message>"
# Event types: escalation, error, session-end, commit, info
```

Emoji prefixes: `escalation/error` → 🚨, `session-end` → 📋, `commit` → 📝, `info` → ℹ️

## MSG-ACK-RESULT Protocol

### Message Assessment

| MSG Type | Action | Telegram Format |
|----------|--------|-----------------|
| `escalation` | Forward immediately | 🚨 `[texty] ESCALATION from {oracle}` |
| `query` | Forward with vault context | ❓ `[texty] QUERY from {oracle}` + context |
| `task` | Forward with approval poll | ✅ `[texty] TASK from {oracle}` + poll |
| `info` | ACK automatically, log only | — (no Telegram) |

### Dispatch Log Format

Every dispatch creates an append-only file in `ψ/dispatch/YYYY-MM/DSP-YYYYMMDD-NNN.md`.

## Busy/Idle Oracle Detection

When `/send <oracle> <msg>` is used, `maw inbox send` checks if the target oracle is busy:

- **BUSY**: Message is rejected, no file written. Telegram replies: `⏳ {oracle} is busy — try again when session ends`
- **IDLE**: Message written to inbox + injected into tmux via `tmux send-keys` + Enter. Telegram replies: `✅ Delivered to {oracle}`

Detection works by scanning the tmux pane for Claude Code's `❯` prompt and processing indicators (`✻`, `⏺`, `·`).

## Session Summary on Session End

`session-summary-to-texty.sh` captures last 5 meaningful lines from tmux and sends to Telegram:

```
📋 {oracle} session ended
  {summary lines}
✅ Ready for new tasks — /send {oracle} <msg>
```

## File Locations

| Path | Purpose |
|------|---------|
| `scripts/texty-daemon.py` | Telegram bot daemon |
| `scripts/dispatch.sh` | Manual dispatch to Telegram |
| `scripts/notify-texty.sh` | Oracle-to-Telegram notification |
| `scripts/session-summary-to-texty.sh` | Session end summary |
| `scripts/query.sh` | Knowledge query script |
| `ψ/credentials/telegram.json` | Bot token & chat ID (gitignored) |
| `ψ/dispatch/YYYY-MM/` | Append-only dispatch logs |
| `ψ/inbox/` | Incoming messages |
| `ψ/channels/telegram.md` | Telegram setup guide |