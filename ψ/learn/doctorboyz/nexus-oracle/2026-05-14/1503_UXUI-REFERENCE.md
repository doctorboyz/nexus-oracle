# nexus-oracle Telegram Bot UX Reference

**Generated**: 2026-05-14  
**Source**: `/Users/doctorboyz/Code/github.com/doctorboyz/nexus-oracle`  
**Primary Code**: `texty/nexus-daemon.py` (878 lines), `texty/dispatch.sh`, `texty/notify-nexus.sh`

---

## 1. Command Inventory

### 1.1 Slash Commands

All commands are registered with Telegram via `setMyCommands` (line 818-834) and handled in `handle_command()` (line 562-665).

| Command | Arguments | Output Format | Error Messages | File:Line |
|---------|-----------|---------------|----------------|-----------|
| `/wake` | `<oracle>` | Markdown code block with maw output | `"Usage: /wake <oracle>\nOracles: {list}"` | daemon.py:586-594 |
| `/sleep` | `<oracle>` | Markdown code block with maw output | `"Usage: /sleep <oracle>\nOracles: {list}"` | daemon.py:596-603 |
| `/status` | (none) | `*Fleet Status:*\n```{maw output}```` | (delegates to maw, errors shown raw) | daemon.py:606-607 |
| `/inbox` | `<oracle>` | `*inbox ({oracle}):*\n```{maw output}```` | `"Usage: /inbox <oracle>\nOracles: {list}"` | daemon.py:610-615 |
| `/send` | `<oracle> <msg>` | Delivery confirmation with emoji | `"Usage: /send <oracle> <message>\nOracles: {list}"` or "already in group" hint | daemon.py:617-637 |
| `/broadcast` | `<msg>` | Per-oracle delivery status list | `"Usage: /broadcast <message>\nSends to all oracle groups."` | daemon.py:639-651 |
| `/goals` | (none) | Bulleted list of `.md` filenames, or "No active goals" | `"*Goals directory not found*"` | daemon.py:653-663 |
| `/help` | (none) | Markdown-formatted command list + smart routing explanation | N/A | daemon.py:569-584 |

**Intuitiveness Assessment**: Commands are reasonably intuitive for a power-user audience. The `/inbox` command is misleading -- it claims to check a specific oracle's inbox but actually runs `maw inbox ls` which lists ALL inboxes, not the specified one (the oracle argument is parsed but the maw command ignores it at line 614). The `/broadcast` command skips the "fleet" channel (line 647), which is correct behavior but undocumented from the user's perspective.

**Consistency Issues**:
- `/wake` and `/sleep` also post a message to the oracle's group (lines 592-593, 601-602), but `/status` and `/inbox` do not.
- Error messages use different formats: some use plain text, some use Markdown, some use emoji.
- The `/send` hint for "already in group" uses escaped Markdown (`\\!`) while other messages use unescaped.

---

## 2. Message UX

### 2.1 Markdown Formatting

**Parse mode**: All bot-sent messages use `parse_mode: "Markdown"` (line 529).

**Markdown patterns used**:
- Bold: `*wake {oracle}:*`, `*Fleet Status:*`, `*Delivered to {oracle}*`
- Italic: `_text[:100]_`, `_text[:200]_` (message previews)
- Code blocks: `````{maw output}```` (for /wake, /sleep, /status, /inbox)
- Escaped characters: `\\!` in the `/send` same-group hint (line 625)

**Defect - Telegram Markdown v1 fragility** (Severity: HIGH):
The daemon uses Markdown v1 (`parse_mode: "Markdown"`) which is extremely fragile. Characters like `_`, `*`, `[`, `` ` `` in user-generated content will cause parse failures. The outbox response handler explicitly avoids Markdown for this reason (lines 289-290):

```python
# Send response as plain text (oracle responses often have markdown
# tables/special chars that break Telegram's Markdown parser)
```

But the command handler still uses Markdown for all its output. This inconsistency means:
- Oracle responses are sent as plain text (no formatting)
- Command responses are sent as Markdown (risking parse errors on special characters in maw output)
- The `/help` message uses bold/italic but could break if oracle names contain special chars

### 2.2 Emoji Usage

Emoji is used consistently as status indicators:

| Emoji | Meaning | Location |
|-------|---------|----------|
| 📨 | Delivery confirmation | daemon.py:446,449,452,454 |
| ⚡ | Auto-wake notification | daemon.py:438 |
| 💤 | Sleep/oracle stopped | daemon.py:602 |
| 💡 | Hint/suggestion | daemon.py:625 |
| 📡 | Daemon status | daemon.py:840,860 |
| 🤔 | Routing uncertainty | daemon.py:805 |
| ✅ | Success | daemon.py:636 |
| ❌ | Failure | daemon.py:630 |
| ⏳ | Busy/oracle occupied | daemon.py:632 |
| 📢 | Broadcast | daemon.py:648 |
| 📝 | Received/note | daemon.py:741 |
| 🚨 | Escalation (in notify-nexus.sh) | notify-nexus.sh:94 |
| 📋 | Session end / info | notify-nexus.sh:95, session-summary.sh:56 |

### 2.3 Message Length and Truncation

**Human-facing previews**:
- Private chat delivery: `text[:100]` (line 446)
- Group/fleet delivery: `text[:200]` (lines 449, 452, 454)

**Outbox response truncation**:
- Max body: 3900 chars minus prefix length (line 292)
- Truncation marker: `...` appended (line 293)
- Telegram's actual limit is 4096 chars; the 3900 buffer accounts for prefix but not Markdown formatting overhead

**Defect - No multi-message splitting** (Severity: MEDIUM):
When an oracle response exceeds ~3900 chars, it is silently truncated with `...`. There is no mechanism to split long responses across multiple messages. Oracle output (backtest results, code, etc.) could easily exceed this.

### 2.4 Attribution

All messages include `[nexus]` or `[oracle_name]` prefix per the Golden Rule "Never impersonate human" (CLAUDE.md line 128). Outbox responses use `f"💬 [{from_oracle}]"` (line 291). This is consistent and clear.

---

## 3. Error and Feedback UX

### 3.1 Command Errors

| Error Condition | User Sees | Helpful? | File:Line |
|-----------------|-----------|----------|-----------|
| Unknown oracle name | `"Usage: /{cmd} <oracle>\nOracles: {list}"` | Partially -- lists valid oracles but no explanation of what they do | daemon.py:588,598,611,619 |
| Missing argument | Same as unknown oracle | No -- same generic usage message | daemon.py:588,619 |
| `/send` to same oracle group | `"You're already in the {oracle} group! Just type directly..."` | Yes -- helpful contextual hint | daemon.py:624-625 |
| Unknown command | `"Unknown command: {cmd}\nType /help for available commands"` | Yes | daemon.py:665 |
| `/broadcast` with no message | `"Usage: /broadcast <message>\nSends to all oracle groups."` | Yes | daemon.py:641 |
| `/goals` with no goals dir | `"*Goals directory not found*"` | Marginal -- no guidance on what to do | daemon.py:663 |

### 3.2 Delivery Errors

| Error Condition | User Sees | Helpful? | File:Line |
|-----------------|-----------|----------|-----------|
| `maw inbox send` fails (Cannot resolve / not found) | Falls back to `write_to_inbox()`. If that also fails: `"Cannot deliver to {oracle}\n\nmaw: {output[:200]}"` | Partially -- shows raw maw error | daemon.py:428,627-630 |
| Oracle busy | `"{oracle} is busy -- try again when session ends\n\nReply /send {oracle} <msg> later"` | Yes -- actionable suggestion | daemon.py:632 |
| Telegram API send fails | Silent failure (logged to stdout only) | NO -- user gets no feedback | daemon.py:297-301,523-524 |

**Defect - Silent Telegram API failures** (Severity: CRITICAL):
When `curl_api("sendMessage", ...)` fails, the error is only printed to stdout (line 300: `print(f"[outbox] Failed to send...")`). The user in Telegram receives NO feedback. This affects:
- Outbox responses (line 296-301)
- `deliver_to_oracle` confirmations (lines 446-454)
- `/wake` and `/sleep` group notifications (lines 592-593, 601-602)
- `/broadcast` messages (line 648)

For `deliver_to_oracle()`, the function returns a status string regardless of whether the Telegram send succeeded (line 500), meaning the audit trail records "delivered" even if the message never reached Telegram.

### 3.3 Oracle Offline / Unreachable

When an oracle is not running:
1. The daemon checks `is_oracle_running()` via `maw peek {oracle}` (line 412)
2. If `auto_wake` is true in fleet config, it auto-wakes (lines 435-438)
3. If auto-wake fails or is disabled, the user sees the delivery confirmation but the message sits unprocessed

**Defect - No explicit "oracle offline" feedback** (Severity: HIGH):
If auto-wake fails (e.g., maw not responding), the user still sees `📨 *Delivered to {oracle}*`. The `wake_msg` is only appended on success. There is no message for "oracle is offline and could not be woken". The `is_oracle_running()` check uses string matching on maw output (`"running" in output.lower() or "active" in output.lower()`) which is fragile (line 414).

### 3.4 Daemon Startup/Shutdown

- Startup: `📡 [nexus] Daemon started — smart routing active\nIn oracle groups: just type * In Fleet: auto-route * /help for commands` (line 860)
- Shutdown: `📡 [nexus] Daemon stopped` (line 840)
- These are sent to the private chat ID only.

---

## 4. Smart Routing UX

### 4.1 Oracle Group (Direct Routing)

**When user sends a plain message in an oracle-specific group** (e.g., `📊 God-Port`):
- Daemon identifies the group-to-oracle mapping via `get_oracle_by_chat()` (line 542)
- Message is delivered directly to that oracle via `deliver_to_oracle()` (line 791)
- User sees: `📨 *Message received for {oracle}*\n\n_{text[:200]}_` in the same group (line 449)
- If oracle not running and auto_wake succeeds: `⚡ Auto-woke {oracle}` appended (line 438)

**UX Quality**: Good. Context is clear, user knows the message went to the right place.

### 4.2 Fleet Group (Auto-Routing)

**When user sends a plain message in the Fleet group**:
- Daemon runs `route_by_intent()` against keyword/domain matching (lines 363-408)
- **High confidence (>= 0.5)**: Routes to matched oracle automatically (line 800)
  - User sees: `📨 *Routed to {oracle}* (intent)\n\n_{text[:200]}_` in fleet group (line 452)
  - Oracle's group also gets: `📨 *Message from Fleet* \\(auto-routed\\)\n\n_{text[:200]}_` (line 454)
- **Low confidence (< 0.5)**: Asks user which oracle (lines 803-811)
  - User sees: `🤔 *Not sure which oracle should handle this.*\n\n_{text[:100]}_\n\nReply /send <oracle> <msg> or:\nOracles: {list}`
  - Message is also forwarded to nexus inbox as fallback (line 811)

**Routing algorithm details** (lines 363-408):
- Keywords: weighted by `len(kw)/3 + 1` (longer matches score higher)
- Domains: fixed 0.5 weight
- Confidence: `min(best_score / 3.0, 1.0)` only if `best_score > 1.0`
- Tie-breaking: prefer oracle with longer total matched keyword length
- Nexus excluded as a destination (line 374)

**Defect - Fleet routing message cross-posts with escaped Markdown** (Severity: MEDIUM):
The cross-post to the oracle's group uses `\\(auto-routed\\)` with escaped parentheses (line 454). In Telegram Markdown v1, this renders as `\(auto-routed\)` instead of `(auto-routed)`, creating visual noise.

**Defect - Ambiguous routing feedback** (Severity: LOW):
The delivery method label alternates between "inbox + maw" and "inbox (direct)" but the user has no context for what this distinction means. This is an internal implementation detail leaked into the UX (lines 442-452).

### 4.3 Private Chat (Fallback)

**When user sends a plain message in private chat**:
- Message is forwarded to nexus inbox via `forward_to_nexus()` (line 815)
- User sees: `📝 [nexus] Received (from private chat): {text[:80]}` (line 741)
- Source label varies: "from {oracle}" if from a group, "from private chat" otherwise (line 719)

**Defect - Private chat is a dead end** (Severity: HIGH):
Messages to nexus inbox are stored but there is no mechanism to:
1. Notify the nexus agent that a new inbox message arrived (inbox watcher only creates a macOS notification, line 69 of inbox-watcher.sh)
2. Automatically route the message to the appropriate oracle
3. Provide the user with a timely response

The user receives a "Received" confirmation but may never get a response. The inbox watcher (`pm/inbox-watcher.sh`) uses `fswatch` and `osascript` for local notifications only -- it does not trigger any agent action.

### 4.4 "Not Sure" Routing Message

When routing confidence is below 0.5, the user sees:

```
🤔 *Not sure which oracle should handle this.*

_{text[:100]}_

Reply `/send <oracle> <msg>` or:
Oracles: emily, fammee, god-port, infra, kappy
```

**Defect - Oracle list excludes nexus but includes no descriptions** (Severity: MEDIUM):
The oracle list is bare names with no indication of what each oracle does. The routing keywords ARE available in fleet configs but are not shown. A user unfamiliar with the fleet would need to guess.

**Defect - `/send` in fleet group requires retyping the message** (Severity: MEDIUM):
The prompt says "Reply `/send <oracle> <msg>`" but the user already typed their message. They must retype it, which is friction. There is no button/callback mechanism to streamline this.

---

## 5. Response Flow UX

### 5.1 End-to-End Flow

```
User sends message in Telegram
        |
        v
[nexus-daemon.py poll_updates()] -- every 3 seconds
        |
        v
Is it a slash command?
   YES --> handle_command() --> send_message() to Telegram
   NO  --> Smart routing:
        |
        +-- Oracle group --> deliver_to_oracle()
        |       |
        |       +-- maw inbox send OR write_to_inbox() fallback
        |       +-- Auto-wake if needed
        |       +-- Confirmation message in source chat
        |       +-- Cross-post to oracle's group (if from fleet)
        |
        +-- Fleet group --> route_by_intent()
        |       |
        |       +-- High confidence --> deliver_to_oracle()
        |       +-- Low confidence --> "Not sure" + forward_to_nexus()
        |
        +-- Private chat --> forward_to_nexus()
                |
                +-- "Received" confirmation
                +-- Written to ψ/inbox/

Oracle processes and writes response to ψ/outbox/
        |
        v
[nexus-daemon.py poll_outboxes()] -- every 3 seconds (same loop)
        |
        v
process_outbox_file()
        |
        +-- Parse YAML frontmatter
        +-- Determine target chat (respond_in > source_chat cross-ref > oracle's group > private)
        +-- Send as plain text: "💬 [{from_oracle}]\n\n{body}"
        +-- Archive to outbox/archive/YYYY-MM/
```

### 5.2 Timing and Latency

- **Poll interval**: 3 seconds (line 71, `POLL_INTERVAL = 3`)
- **Long polling timeout**: 10 seconds (line 749)
- **Effective worst-case latency**: 3-6 seconds for command responses + 3-6 seconds for outbox delivery = **6-12 seconds total round-trip**
- **Auto-wake latency**: Additional `maw wake` execution time (15s timeout, line 557) on top of delivery

**Defect - No "thinking" feedback** (Severity: MEDIUM):
Commands like `/wake`, `/sleep`, `/status` that shell out to `maw` have a 15-second timeout (line 557). During this time, the user sees no feedback. Telegram shows "typing..." indicators would help but are not implemented.

### 5.3 Outbox Response Flow

The outbox watcher (`poll_outboxes()`, lines 322-348) scans ALL oracle outboxes every polling cycle. Target chat determination has a 4-level priority (lines 267-287):

1. `respond_in` field in frontmatter (explicit routing)
2. Cross-reference `source_chat` from original inbox message (bidirectional)
3. Oracle's dedicated Telegram group (default)
4. Private chat with human (ultimate fallback)

**Strength**: The `respond_in` and `source_chat` mechanisms allow responses to route back to the exact chat where the question originated, including fleet and cross-oracle routing.

**Defect - Source chat cross-reference is fragile** (Severity: MEDIUM):
`find_source_chat()` (lines 191-221) scans ALL oracle inbox directories looking for a file whose name contains the `msg_id`. This is:
- O(N*M) where N = number of oracles and M = number of inbox files
- Relies on filename format matching: `msg_id not in f` (line 202) which is a substring match on filenames, potentially matching wrong messages
- No caching -- called for every outbox file on every poll cycle

---

## 6. UX Defects Summary

### CRITICAL

| # | Defect | Location | Impact |
|---|--------|----------|--------|
| C1 | **Silent Telegram API failures** | daemon.py:296-301, 523-524 | User sends a command or message, API call fails silently. No retry, no user-visible error. Only logged to stdout. Particularly dangerous for `deliver_to_oracle()` which returns "delivered" status regardless of send success. |
| C2 | **Private chat is a dead end** | daemon.py:712-741, inbox-watcher.sh | User messages in private chat get a "Received" confirmation but no guarantee of response. The inbox watcher only creates local macOS notifications -- it does not trigger agent wake or any automated processing. |

### HIGH

| # | Defect | Location | Impact |
|---|--------|----------|--------|
| H1 | **No "oracle offline" feedback** | daemon.py:412-438 | If auto-wake fails, user still sees "Delivered" but the oracle won't process the message until manually woken. No "oracle is asleep" or "wake failed" message. |
| H2 | **Markdown v1 fragility** | daemon.py:529, 289-290 | Markdown v1 breaks on underscores, asterisks, and backticks in maw output and oracle names. The outbox handler already avoids Markdown for this reason but command handlers still use it. |
| H3 | **`/inbox` ignores oracle argument** | daemon.py:614 | The command parses `<oracle>` but `maw inbox ls` shows ALL inboxes. User expects oracle-specific inbox. |
| H4 | **No typing/thinking indicator** | daemon.py:548-559 | Commands that shell out to `maw` (up to 15s timeout) show no feedback during execution. User may resend or assume the bot is broken. |

### MEDIUM

| # | Defect | Location | Impact |
|---|--------|----------|--------|
| M1 | **No message splitting for long responses** | daemon.py:292-294 | Oracle responses >3900 chars are truncated with `...`. No continuation mechanism. |
| M2 | **Routing "not sure" lists bare oracle names** | daemon.py:803-811 | Oracle names shown without descriptions. Fleet configs have routing keywords that could be displayed. |
| M3 | **Fleet cross-post has escaped parentheses** | daemon.py:454 | `\\(auto-routed\\)` renders as `\(auto-routed\)` in Telegram. |
| M4 | **Internal implementation detail leaked to UX** | daemon.py:442 | "inbox + maw" vs "inbox (direct)" delivery method labels are confusing to end users. |
| M5 | **Source chat cross-reference is O(N*M)** | daemon.py:191-221 | Performance degrades with more inbox files. Substring match on msg_id can cause false positives. |
| M6 | **`/send` in fleet group requires retyping message** | daemon.py:809 | After routing fails, user must retype their entire message with `/send`. No callback button mechanism. |
| M7 | **Broadcast skips fleet group without documenting** | daemon.py:647 | `/broadcast` silently skips the "fleet" channel. Users may not understand why fleet doesn't receive broadcasts. |
| M8 | **Inconsistent error message formatting** | daemon.py:588,619,641,665 | Some errors use plain text, some use Markdown, some use emoji. No unified style. |

### LOW

| # | Defect | Location | Impact |
|---|--------|----------|--------|
| L1 | **`/goals` shows filenames, not goal titles** | daemon.py:656 | Returns `.md` filenames like `mt5-trading.md` instead of parsed titles. |
| L2 | **`/status` shows raw maw output** | daemon.py:607 | Raw CLI output in a code block. Could be formatted as a table. |
| L3 | **No `/cancel` or `/stop` command** | None | No way for users to abort a long-running operation or cancel a pending delivery. |
| L4 | **`ORACLES` set may be stale** | daemon.py:76-93 | Loaded once at startup with 5-minute cache. New oracles added to fleet configs may take up to 5 minutes to be recognized. |
| L5 | **`is_oracle_running()` string matching** | daemon.py:412-414 | Checks for "running" or "active" in maw output, which could match unrelated text. |
| L6 | **Poll interval fixed at 3 seconds** | daemon.py:71 | No adaptive backoff or exponential retry on API failures. |

---

## 7. Recommendations (Prioritized)

### P0 -- Fix Now

1. **Handle Telegram API failures visibly** (C1)
   - File: `texty/nexus-daemon.py`, lines 296-301, 523-524
   - Check `curl_api()` return value in `deliver_to_oracle()`. If `send_message()` fails, send a follow-up error message or retry. For outbox failures, implement retry logic instead of silently skipping.
   - Add a simple retry mechanism: 3 attempts with 1-second backoff.

2. **Fix private chat dead end** (C2)
   - File: `texty/nexus-daemon.py`, line 815; `pm/inbox-watcher.sh`
   - Instead of just writing to inbox, attempt routing via `route_by_intent()` for private chat messages too. If confidence >= 0.5, auto-route (same as fleet). If low confidence, ask the user which oracle they want.
   - Optionally: have the inbox watcher trigger agent wake.

### P1 -- Fix Soon

3. **Add "oracle offline / wake failed" feedback** (H1)
   - File: `texty/nexus-daemon.py`, lines 435-438
   - After `is_oracle_running()` and auto-wake attempt, if oracle is still not running, append a warning: `" ⚠️ {oracle} may not be active -- message delivered to inbox"`

4. **Switch to MarkdownV2 or HTML parse mode** (H2)
   - File: `texty/nexus-daemon.py`, line 529
   - Change `parse_mode: "Markdown"` to `parse_mode: "HTML"` which is more forgiving with special characters. Update all message formatting to use HTML tags.
   - Alternatively, use MarkdownV2 with proper escaping.

5. **Fix `/inbox` to be oracle-specific** (H3)
   - File: `texty/nexus-daemon.py`, line 614
   - Replace `maw inbox ls` with `maw inbox ls {oracle}` or scan only that oracle's inbox directory.

6. **Add typing indicator before shell commands** (H4)
   - File: `texty/nexus-daemon.py`
   - Call `curl_api("sendChatAction", {"chat_id": chat_id, "action": "typing"})` before shelling out to `maw` commands.

### P2 -- Improve When Convenient

7. **Implement message splitting for long responses** (M1)
   - File: `texty/nexus-daemon.py`, lines 292-294
   - Split responses >4000 chars into multiple messages with `(1/N)` numbering.

8. **Add oracle descriptions to "not sure" routing message** (M2)
   - File: `texty/nexus-daemon.py`, lines 803-811
   - Include one-line descriptions from fleet configs alongside oracle names.

9. **Fix Markdown escaping in fleet cross-post** (M3)
   - File: `texty/nexus-daemon.py`, line 454
   - Change `\\(auto-routed\\)` to just `(auto-routed)` or use HTML mode.

10. **Replace implementation-detail labels in delivery confirmations** (M4)
    - File: `texty/nexus-daemon.py`, lines 442-452
    - Replace "inbox + maw" / "inbox (direct)" with user-facing labels like "delivered" / "delivered (direct to inbox)".

11. **Add InlineKeyboardMarkup callback buttons for routing** (M6)
    - File: `texty/nexus-daemon.py`, lines 803-811
    - When routing confidence is low, present inline buttons for each oracle instead of requiring `/send` retyping. This requires adding callback query handling to `poll_updates()`.

12. **Document that `/broadcast` skips fleet** (M7)
    - File: `texty/nexus-daemon.py`, line 641
    - Add to help text: "Sends to all oracle groups (excluding Fleet)."

### P3 -- Nice to Have

13. **Parse goal titles from frontmatter** (L1)
    - Read first line or YAML `title` field from goal files instead of showing filenames.

14. **Format `/status` output as table** (L2)
    - Parse `maw fleet ls` output and format as a Markdown table.

15. **Add `/cancel` command** (L3)
    - Allow users to cancel pending deliveries or stop wake attempts.

16. **Implement exponential backoff for polling** (L6)
    - On API errors, increase `POLL_INTERVAL` temporarily instead of hammering the API.

17. **Cache source_chat mapping** (M5)
    - Build a simple dict mapping `msg_id -> source_chat` from inbox scans to avoid O(N*M) lookups.

---

## Appendix A: Message Format Examples

### Startup Message
```
📡 [nexus] Daemon started — smart routing active
In oracle groups: just type * In Fleet: auto-route * /help for commands
```

### /help Response
```
*nexus Oracle Commands*
/wake \<oracle\> — Start oracle session
/sleep \<oracle\> — Stop oracle session
/status — Show fleet status
/inbox \<oracle\> — Check oracle inbox
/send \<oracle\> \<msg\> — Send message to specific oracle
/broadcast \<msg\> — Send message to all oracle groups
/goals — Show active goals
/help — This message

*Smart Routing*
In an oracle group: just type — your message goes to that oracle directly
In Fleet group: type naturally — nexus routes to the right oracle by keywords

Oracles: emily, fammee, god-port, infra, kappy
```

### Delivery Confirmation (Private Chat)
```
📨 *Delivered to god-port* (inbox + maw)
⚡ Auto-woke god-port

_backtest results on XAUUSD_
```

### Delivery Confirmation (Fleet Group, Auto-Routed)
```
📨 *Routed to god-port* (intent)
⚡ Auto-woke god-port

_check docker again_
```

### Oracle Response (from Outbox)
```
💬 [god-port]

Backtest results for XAUUSD H1:
- PF: 1.63
- MaxDD: 18.2%
- WR: 52.1%
...
```

### Routing Uncertainty
```
🤔 *Not sure which oracle should handle this.*

_ให้ทุกคนอธิบาย ตัวตนของตัวเอง_

Reply `/send <oracle> <msg>` or:
Oracles: emily, fammee, god-port, infra, kappy
```

### Private Chat Fallback
```
📝 [nexus] Received (from private chat): ตอนนี้เก่งแค่ไหนแล้ว เล่ามาซิ
```

### Session End Notification
```
📋 god-port session ended
  (last 5 lines of session output)
✅ Ready for new tasks — /send god-port <msg>
```

---

## Appendix B: Architecture Diagram

```
Telegram User
     |
     | (HTTP long-poll, 10s timeout)
     v
[nexus-daemon.py]  <-- polls every 3s -->
     |
     +-- /commands --> handle_command() --> maw CLI --> send_message()
     |
     +-- plain text --> smart routing:
     |       |
     |       +-- Oracle group --> deliver_to_oracle()
     |       +-- Fleet group --> route_by_intent()
     |       |       +-- confidence >= 0.5 --> deliver_to_oracle()
     |       |       +-- confidence < 0.5 --> ask user + forward_to_nexus()
     |       |
     |       +-- Private chat --> forward_to_nexus()
     |
     +-- poll_outboxes() --> for each oracle:
             |
             +-- process_outbox_file()
                     |
                     +-- Parse frontmatter
                     +-- Find target chat (4-level priority)
                     +-- send_message() as plain text
                     +-- Archive file

Other scripts:
  dispatch.sh        -- Direct message send (CLI)
  notify-nexus.sh    -- Other oracles --> nexus inbox --> Telegram
  session-summary.sh -- Oracle session end --> Telegram
  outbox-write.sh    -- Oracle writes response for auto-delivery
```
