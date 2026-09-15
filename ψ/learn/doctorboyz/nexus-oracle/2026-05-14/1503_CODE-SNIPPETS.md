# nexus-oracle Code Snippets Analysis

Generated: 2026-05-14

---

## 1. Main Entry Point — `nexus-daemon.py` main() and Polling Loop

**File**: `/Users/doctorboyz/Code/github.com/doctorboyz/nexus-oracle/texty/nexus-daemon.py`

### main() — Lines 844-878

```python
def main():
    print("=" * 50)
    print("nexus Oracle daemon starting (polling mode)...")
    print(f"Bot: @texty_oracle_bot")
    print(f"Chat ID: {CHAT_ID}")
    print(f"Oracles: {', '.join(sorted(ORACLES))}")
    print(f"Channels: {', '.join(f'{k}={v}' for k, v in sorted(CHANNELS.items()))}")
    print(f"Authorized chats: {len(AUTHORIZED_CHATS)}")
    print(f"Routing table: {len(ROUTING_TABLE)} oracles")
    print(f"Outbox watching: {len(ORACLE_DIRS)} oracles")
    print("=" * 50)

    # Make sure no webhook is set (conflicts with polling)
    curl_api("deleteWebhook", {"drop_pending_updates": True})

    register_commands()
    send_message("📡 [nexus] Daemon started — smart routing active\nIn oracle groups: just type • In Fleet: auto-route • /help for commands")

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"Polling every {POLL_INTERVAL}s (long polling with 10s timeout)")
    while True:
        try:
            poll_updates()
            poll_outboxes()
        except KeyboardInterrupt:
            shutdown()
        except Exception as e:
            print(f"Poll error: {e}")
        time.sleep(POLL_INTERVAL)
```

**Key pattern**: The main loop does two things each tick: (1) polls Telegram for incoming updates, and (2) scans all oracle outboxes for outgoing responses. This makes the daemon bidirectional — it both receives and sends. Error handling catches `KeyboardInterrupt` separately for graceful shutdown; all other exceptions are logged and the loop continues (resilient to transient failures).

### poll_updates() — Lines 744-816

```python
def poll_updates():
    """Poll Telegram for new updates (long polling)"""
    global OFFSET
    result = curl_api("getUpdates", {
        "offset": OFFSET,
        "timeout": 10,
        "allowed_updates": ["message"]
    })
    if not result or not result.get("ok"):
        return

    for update in result.get("result", []):
        OFFSET = update["update_id"] + 1

        if "message" not in update:
            continue

        msg = update["message"]
        from_id = msg.get("from", {}).get("id")
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "")
        msg_id = msg.get("message_id")

        # Only process from authorized senders (human + bot/MCP)
        if from_id not in ALLOWED_SENDERS:
            continue

        # Only process from authorized chats (private + oracle groups)
        if chat_id not in AUTHORIZED_CHATS:
            continue

        if not text:
            continue

        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] msg from chat {chat_id}: {text[:50]}")

        if text.startswith("/"):
            response = handle_command(text, chat_id, msg_id)
            if response:
                send_message(response, chat_id=chat_id, reply_to=msg_id)
        else:
            # Smart routing for non-command messages
            oracle = get_oracle_by_chat(chat_id)

            if oracle and oracle != "fleet":
                # CASE 1: Message in an oracle-specific group
                deliver_to_oracle(oracle, text, chat_id, from_id)

            elif chat_id == CHANNELS.get("fleet"):
                # CASE 2: Message in the fleet group
                routing = get_routing_table()
                target_oracle, confidence = route_by_intent(text, routing)

                if target_oracle and confidence >= 0.5:
                    deliver_to_oracle(target_oracle, text, chat_id, from_id)
                else:
                    oracle_list = ", ".join(sorted(ORACLES - {"nexus"}))
                    send_message(
                        f"🤔 *Not sure which oracle should handle this.*\n\n"
                        f"_{text[:100]}_\n\n"
                        f"Reply `/send <oracle> <msg>` or:\n"
                        f"Oracles: {oracle_list}",
                        chat_id=chat_id
                    )
                    forward_to_nexus(text, from_id, chat_id)

            else:
                # CASE 3: Private chat or unknown — fallback to nexus inbox
                forward_to_nexus(text, from_id, chat_id)
```

**Key pattern**: Three-tier smart routing: (1) direct delivery in oracle-specific groups, (2) keyword-based intent routing in the fleet group, (3) fallback to nexus inbox for everything else. The `ALLOWED_SENDERS` and `AUTHORIZED_CHATS` sets provide security boundaries.

---

## 2. Core Implementations

### Smart Routing — `route_by_intent()` — Lines 363-408

```python
def route_by_intent(text, routing_table):
    """Score message text against oracle routing keywords/domains.
    Returns (oracle_name, confidence) or (None, 0.0) if no clear match.
    Uses weighted keyword matching — no NLP, no external deps.
    """
    text_lower = text.lower()
    scores = {}
    match_details = {}

    for oracle_name, routing in routing_table.items():
        if oracle_name == "nexus":
            continue  # nexus is the router, not a destination
        score = 0.0
        matched = []
        keywords = routing.get("keywords", [])
        domains = routing.get("domains", [])

        for kw in keywords:
            if kw in text_lower:
                score += len(kw) / 3.0 + 1.0
                matched.append(kw)

        for domain in domains:
            if domain in text_lower:
                score += 0.5
                matched.append(domain)

        if score > 0:
            scores[oracle_name] = score
            match_details[oracle_name] = matched

    if not scores:
        return (None, 0.0)

    best_oracle = max(scores, key=lambda k: scores[k])
    best_score = scores[best_oracle]
    confidence = min(best_score / 3.0, 1.0) if best_score > 1.0 else 0.0

    # Tie-break by total matched keyword length (more specific wins)
    tied = [o for o, s in scores.items() if abs(s - best_score) < 0.01]
    if len(tied) > 1:
        best_oracle = max(tied, key=lambda o: sum(len(kw) for kw in match_details.get(o, [])))
        best_score = scores[best_oracle]
        confidence = min(best_score / 3.0, 1.0) if best_score > 1.0 else 0.0

    return (best_oracle, confidence) if confidence > 0 else (None, 0.0)
```

**Key pattern**: Weighted keyword scoring without NLP dependencies. Keywords score `len(kw)/3.0 + 1.0` (longer keywords score higher), domains score a flat 0.5. Confidence is normalized to [0, 1] with a threshold of 0.5 for fleet routing. Tie-breaking uses total matched keyword length to favor more specific matches.

### Message Delivery — `deliver_to_oracle()` — Lines 417-500

```python
def deliver_to_oracle(oracle, text, respond_chat_id, from_user_id):
    """Deliver a message directly to an oracle's inbox and post confirmation.
    respond_chat_id: the chat where the human sent the message.
    Returns a status string for logging.
    """
    # 1. Deliver via maw inbox send
    escaped_text = text.replace('"', '\\"').replace('`', '\\`')
    output = run_cmd(f'maw inbox send {oracle} "{escaped_text}"')

    maw_ok = True
    if "Cannot resolve" in output or "not found" in output or "Error" in output:
        result = write_to_inbox(oracle, text)
        maw_ok = False

    # 2. Auto-wake if not running
    cfg = load_fleet_config(oracle)
    auto_wake = cfg.get("auto_wake", True)
    wake_msg = ""
    if not is_oracle_running(oracle) and auto_wake:
        wake_output = run_cmd(f"maw wake {oracle}")
        if "running" in wake_output.lower() or "started" in wake_output.lower():
            wake_msg = f"\n⚡ Auto-woke {oracle}"

    # 3. Post confirmation in source chat
    oracle_chat = get_oracle_chat(oracle)
    delivery_method = "inbox + maw" if maw_ok else "inbox (direct)"

    if respond_chat_id == CHAT_ID:
        # Private chat
        send_message(f"📨 *Delivered to {oracle}* ({delivery_method}){wake_msg}\n\n_{text[:100]}_")
    elif respond_chat_id == oracle_chat:
        # Already in the oracle's group
        send_message(f"📨 *Message received for {oracle}*\n\n_{text[:200]}_{wake_msg}", chat_id=oracle_chat)
    else:
        # Fleet group or other
        send_message(f"📨 *Routed to {oracle}* ({delivery_method}){wake_msg}\n\n_{text[:200]}_", chat_id=respond_chat_id)
        if oracle_chat:
            send_message(f"📨 *Message from Fleet* \\(auto-routed\\)\n\n_{text[:200]}_{wake_msg}", chat_id=oracle_chat)

    # 4. Write audit trail to nexus inbox
    now = datetime.datetime.now(timezone.utc)
    filename = f"{now.strftime('%Y%m%d')}_{now.strftime('%H-%M')}_human_MSG-HUMAN-{now.strftime('%H%M')}.md"
    filepath = os.path.join(PSI_DIR, "inbox", filename)
    routing_method = "intent" if respond_chat_id == CHANNELS.get("fleet") else "direct"
    chat_type = "group" if respond_chat_id != CHAT_ID else "private"
    content = f"""---
msg_id: MSG-HUMAN-{now.strftime('%H%M')}
from: human
to: {oracle}
type: query
status: routed
sent: {now.isoformat()}Z
source_chat: {respond_chat_id}
routed_to: {oracle}
routing_method: {routing_method}
respond_in: {respond_chat_id}
respond_chat_type: {chat_type}
ack_by: "-"
result: "-"
reply_file: "-"
---

{text}

---

**How to respond**: Write your answer to `ψ/outbox/` with this frontmatter:
```
---
msg_id: MSG-HUMAN-{now.strftime('%H%M')}
from: {oracle}
type: result
respond_in: {respond_chat_id}
---
<your answer here>
```
Or use: `bash shared/outbox-write.sh --msg-id MSG-HUMAN-{now.strftime('%H%M')} --content "your answer"`
The nexus outbox watcher will send it to Telegram automatically.
"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)

    return f"delivered to {oracle}"
```

**Key pattern**: Four-step delivery pipeline: (1) try `maw inbox send`, fall back to direct file write, (2) auto-wake the oracle session if not running, (3) post contextual confirmation to the originating chat (different message depending on chat type), (4) write a complete audit trail file to the nexus inbox with full frontmatter including `source_chat`, `routing_method`, and `respond_in` fields that enable the return path.

### Outbox Watcher — `poll_outboxes()` and `process_outbox_file()` — Lines 224-348

```python
def process_outbox_file(oracle_name, filepath, oracle_dirs):
    """Process a single outbox file: parse frontmatter, determine target chat, send to Telegram.
    Returns True if file was processed (sent or skipped), False on error.
    """
    try:
        with open(filepath) as f:
            content = f.read()

        # Parse YAML frontmatter
        if not content.startswith("---"):
            body = content.strip()
            metadata = {}
        else:
            end = content.find("---", 3)
            if end < 0:
                body = content[3:].strip()
                metadata = {}
            else:
                frontmatter = content[3:end].strip()
                body = content[end + 3:].strip()
                metadata = {}
                for line in frontmatter.split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        metadata[key.strip()] = value.strip().strip('"').strip("'")

        msg_type = metadata.get("type", "result")
        msg_id = metadata.get("msg_id", "")
        from_oracle = metadata.get("from", oracle_name)

        # Skip ack type — deliver_to_oracle already confirms receipt
        if msg_type == "ack":
            return True

        # Only send result, reply, response types (or files without type)
        if msg_type not in ("result", "reply", "response", ""):
            return True  # Archive unknown types silently

        if not body:
            return True  # Empty body, archive silently

        # Determine target chat (priority order)
        target_chat = None

        # 1. respond_in field from frontmatter
        respond_in = metadata.get("respond_in")
        if respond_in:
            try:
                target_chat = int(respond_in)
            except ValueError:
                pass

        # 2. Cross-reference source_chat from original inbox message
        if target_chat is None and msg_id:
            target_chat = find_source_chat(oracle_dirs, msg_id)

        # 3. Oracle's dedicated Telegram group
        if target_chat is None:
            target_chat = get_oracle_chat(oracle_name)

        # 4. Fallback to private chat with human
        if target_chat is None:
            target_chat = CHAT_ID

        prefix = f"💬 [{from_oracle}]"
        max_body = 3900 - len(prefix)
        truncated_body = body[:max_body] + "..." if len(body) > max_body else body
        response_text = f"{prefix}\n\n{truncated_body}"
        payload = {"chat_id": target_chat, "text": response_text}
        result = curl_api("sendMessage", payload)

        sent_ok = result and result.get("ok", False)
        if not sent_ok:
            print(f"[outbox] Failed to send {os.path.basename(filepath)} to chat {target_chat}: {result}")
        return sent_ok

    except Exception as e:
        print(f"[outbox] Error processing {filepath}: {e}")
        return False


def poll_outboxes():
    """Scan all oracle outboxes for new response files and send them to Telegram."""
    oracle_dirs = get_oracle_dirs()
    if not oracle_dirs:
        return

    for oracle_name, dirs in oracle_dirs.items():
        outbox_dir = dirs.get("outbox")
        if not outbox_dir or not os.path.isdir(outbox_dir):
            continue

        for f in os.listdir(outbox_dir):
            # Skip archive, dotfiles, non-markdown
            if f.startswith(".") or f == "archive" or not f.endswith(".md"):
                continue

            filepath = os.path.join(outbox_dir, f)
            if not os.path.isfile(filepath):
                continue

            success = process_outbox_file(oracle_name, filepath, oracle_dirs)
            if success:
                archive_outbox_file(filepath)
                print(f"[outbox] {oracle_name}: sent and archived {f}")
            else:
                print(f"[outbox] {oracle_name}: will retry {f}")
```

**Key pattern**: Four-level target chat resolution for return messages: (1) explicit `respond_in` frontmatter field, (2) cross-referencing `source_chat` from the original inbox message by `msg_id`, (3) oracle's dedicated group chat, (4) fallback to private chat. Failed sends are NOT archived — they remain in the outbox for retry on the next poll cycle.

### `find_source_chat()` — Cross-Referencing Inbox/Outbox — Lines 191-221

```python
def find_source_chat(oracle_dirs, msg_id):
    """Find the source_chat for a message by scanning oracle inboxes.
    Returns the Telegram chat ID (int) or None.
    """
    if not msg_id:
        return None
    for oracle_name, dirs in oracle_dirs.items():
        inbox_dir = dirs.get("inbox")
        if not inbox_dir or not os.path.isdir(inbox_dir):
            continue
        for f in os.listdir(inbox_dir):
            if msg_id not in f or not f.endswith(".md"):
                continue
            filepath = os.path.join(inbox_dir, f)
            try:
                with open(filepath) as fh:
                    content = fh.read()
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end > 0:
                        frontmatter = content[3:end].strip()
                        for line in frontmatter.split("\n"):
                            if line.startswith("source_chat:"):
                                val = line.split(":", 1)[1].strip()
                                try:
                                    return int(val)
                                except ValueError:
                                    return None
            except Exception:
                continue
    return None
```

**Key pattern**: Scans ALL oracle inbox directories for a file whose name contains the `msg_id`, then parses its frontmatter to extract the `source_chat` field. This creates a return-path mechanism: inbox messages carry `source_chat` and `respond_in` metadata, so outbox responses can find their way back to the correct Telegram chat even when routed through multiple hops.

### Command Handlers — `handle_command()` — Lines 562-665

```python
def handle_command(text, from_chat_id, message_id):
    """Parse and execute slash commands"""
    parts = text.strip().split()
    cmd = parts[0].lower().split("@")[0]  # Strip @bot_name suffix
    args = parts[1:]

    if cmd == "/help":
        return (
            "*nexus Oracle Commands*\n"
            "/wake \\<oracle\\> — Start oracle session\n"
            "/sleep \\<oracle\\> — Stop oracle session\n"
            "/status — Show fleet status\n"
            "/inbox \\<oracle\\> — Check oracle inbox\n"
            "/send \\<oracle\\> \\<msg\\> — Send message to specific oracle\n"
            "/broadcast \\<msg\\> — Send message to all oracle groups\n"
            "/goals — Show active goals\n"
            "/help — This message\n\n"
            "*Smart Routing*\n"
            "In an oracle group: just type — your message goes to that oracle directly\n"
            "In Fleet group: type naturally — nexus routes to the right oracle by keywords\n\n"
            f"Oracles: {', '.join(sorted(ORACLES))}"
        )

    elif cmd == "/wake":
        if not args or args[0].lower() not in ORACLES:
            return f"Usage: /wake <oracle>\nOracles: {', '.join(sorted(ORACLES))}"
        oracle = args[0].lower()
        output = run_cmd(f"maw wake {oracle}")
        oracle_chat = get_oracle_chat(oracle)
        if oracle_chat:
            send_message(f"⚡ *{oracle}* session started", chat_id=oracle_chat)
        return f"*wake {oracle}:*\n```\n{output}\n```"

    # ... /sleep, /status, /inbox, /send, /broadcast, /goals handlers ...

    elif cmd == "/broadcast":
        if not args:
            return "Usage: /broadcast <message>\nSends to all oracle groups."
        msg = " ".join(args)
        results = {}
        for name, cid in CHANNELS.items():
            if name == "fleet":
                continue
            result = send_message(f"📢 *Broadcast:*\n\n{msg}", chat_id=cid)
            results[name] = "✅" if result and result.get("ok") else "❌"
        summary = "\n".join(f"• {n}: {s}" for n, s in sorted(results.items()))
        return f"*Broadcast sent:*\n{summary}\n\n📝 {msg[:100]}"
```

**Key pattern**: Commands delegate to shell tools (`maw wake`, `maw sleep`, `maw fleet ls`, `maw inbox send`) and translate output to Markdown-formatted Telegram messages. The `@bot_name` suffix stripping on line 566 handles the Telegram convention where group commands can include the bot username.

---

## 3. Interesting Patterns

### Fleet Config Loading with Cache TTL — Lines 76-93, 350-360, 182-188

```python
# Load once at startup
ORACLES = load_oracles_from_fleet()
ROUTING_TABLE = load_routing_table()
_routing_loaded_at = time.time()
ORACLE_DIRS = find_oracle_dirs()
_oracle_dirs_loaded_at = time.time()

# Cache with TTL refresh
def get_routing_table():
    """Return cached routing table, refreshing every ROUTING_CACHE_TTL seconds."""
    global ROUTING_TABLE, _routing_loaded_at
    if time.time() - _routing_loaded_at > ROUTING_CACHE_TTL:
        ROUTING_TABLE = load_routing_table()
        _routing_loaded_at = time.time()
    return ROUTING_TABLE

def get_oracle_dirs():
    """Return cached oracle dirs, refreshing every ORACLE_DIRS_CACHE_TTL seconds."""
    global ORACLE_DIRS, _oracle_dirs_loaded_at
    if time.time() - _oracle_dirs_loaded_at > ORACLE_DIRS_CACHE_TTL:
        ORACLE_DIRS = find_oracle_dirs()
        _oracle_dirs_loaded_at = time.time()
    return ORACLE_DIRS
```

**Cache TTL constants**: `ROUTING_CACHE_TTL = 300` and `ORACLE_DIRS_CACHE_TTL = 300` (both 5 minutes). Fleet configs are loaded from `~/.config/maw/fleet/*.json` at startup, then refreshed on demand every 5 minutes. This balances freshness with filesystem I/O.

### Keyword Scoring — Lines 363-408 (shown above in section 2)

Scoring formula: `score += len(kw) / 3.0 + 1.0` for keywords, `score += 0.5` for domain matches. Confidence = `min(score / 3.0, 1.0)` with a minimum score of 1.0 required. The threshold for fleet routing is `confidence >= 0.5`.

### Cross-Referencing Inbox/Outbox — `find_source_chat()` (shown above in section 2)

The `msg_id` field is the join key: when `deliver_to_oracle()` writes an inbox file, it embeds `msg_id: MSG-HUMAN-{HHMM}` and `source_chat: {chat_id}`. When an oracle writes an outbox response with the same `msg_id`, `process_outbox_file()` uses `find_source_chat()` to scan all inboxes for that `msg_id` and recover the `source_chat` field. This enables responses to find their way back to the correct Telegram chat.

### Archive Pattern — `archive_outbox_file()` — Lines 308-319

```python
def archive_outbox_file(filepath):
    """Move a processed outbox file to archive/YYYY-MM/ subdirectory."""
    outbox_dir = os.path.dirname(filepath)
    now = datetime.datetime.now(timezone.utc)
    month_dir = os.path.join(outbox_dir, "archive", now.strftime("%Y-%m"))
    os.makedirs(month_dir, exist_ok=True)
    dest = os.path.join(month_dir, os.path.basename(filepath))
    try:
        os.rename(filepath, dest)
    except OSError:
        import shutil
        shutil.move(filepath, dest)
```

**Key pattern**: Processed outbox files are moved to `archive/YYYY-MM/` subdirectories (monthly buckets). The `os.rename` with `shutil.move` fallback handles cross-filesystem moves. Files that fail to send are NOT archived — they stay in the outbox for retry.

---

## 4. Error Handling Examples

### API Error Handling — `curl_api()` — Lines 503-524

```python
def curl_api(method, params=None):
    """Call Telegram Bot API via curl"""
    url = f"{API_URL}/{method}"
    try:
        if params:
            result = subprocess.run(
                ["curl", "-s", "-X", "POST", url,
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps(params)],
                capture_output=True, text=True, timeout=30
            )
        else:
            result = subprocess.run(
                ["curl", "-s", url],
                capture_output=True, text=True, timeout=30
            )
        if result.stdout:
            return json.loads(result.stdout)
        return None
    except Exception as e:
        print(f"API error ({method}): {e}")
        return None
```

**Pattern**: Returns `None` on any failure (network error, timeout, JSON parse error). Callers check `result and result.get("ok", False)` — the `send_message()` and `process_outbox_file()` functions handle `None` gracefully. The 30-second curl timeout prevents hangs.

### maw Command Failure — `deliver_to_oracle()` — Lines 423-428

```python
    escaped_text = text.replace('"', '\\"').replace('`', '\\`')
    output = run_cmd(f'maw inbox send {oracle} "{escaped_text}"')

    maw_ok = True
    if "Cannot resolve" in output or "not found" in output or "Error" in output:
        result = write_to_inbox(oracle, text)
        maw_ok = False
```

**Pattern**: Falls back to direct file write (`write_to_inbox()`) if `maw` command fails. The fallback writes a properly formatted inbox file directly to the oracle's `ψ/inbox/` directory. This makes the system resilient to `maw` being unavailable.

### Shell Command Timeout — `run_cmd()` — Lines 548-559

```python
def run_cmd(cmd):
    """Run shell command and return output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        output = result.stdout.strip()
        if result.stderr and not output:
            output = result.stderr.strip()
        return output[:4000] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out (15s)"
    except Exception as e:
        return f"Error: {e}"
```

**Pattern**: 15-second timeout on all shell commands. Output is truncated to 4000 characters (well under Telegram's 4096 message limit). stderr is used as fallback if stdout is empty.

### Outbox Processing Failure — `poll_outboxes()` — Lines 342-347

```python
            success = process_outbox_file(oracle_name, filepath, oracle_dirs)
            if success:
                archive_outbox_file(filepath)
                print(f"[outbox] {oracle_name}: sent and archived {f}")
            else:
                print(f"[outbox] {oracle_name}: will retry {f}")
```

**Pattern**: Failed outbox files are simply left in place. The next polling cycle will attempt them again. This is a simple but effective retry mechanism — no exponential backoff, but also no lost messages.

### Missing File Handling — `write_to_inbox()` — Lines 668-709

The entire function is wrapped in `try/except` blocks at the per-config level:

```python
    for f in os.listdir(fleet_dir):
        if f.endswith(".json"):
            try:
                with open(os.path.join(fleet_dir, f)) as fh:
                    cfg = json.load(fh)
                    # ... find oracle, write file ...
            except Exception:
                continue
    return False
```

**Pattern**: Each fleet config file is tried independently. A corrupt or missing config for one oracle does not prevent delivery to others. The function returns `True` on success, `False` if no oracle was found.

---

## 5. Shell Scripts

### `dispatch.sh` — `/Users/doctorboyz/Code/github.com/doctorboyz/nexus-oracle/texty/dispatch.sh`

Key patterns:
- **Oracle targeting** (lines 44-63): If `--oracle` flag is provided, reads `channels` mapping from credentials JSON to find the group chat ID; falls back to private `chat_id` for direct messages.
- **Dispatch audit log** (lines 73-93): Every dispatch creates a timestamped markdown file in `ψ/dispatch/YYYY-MM/` with frontmatter tracking `dispatch_id`, `from`, `to`, `type`, `status`, and `sent` timestamp. This satisfies the "Never auto-delete" golden rule.
- **Poll support** (lines 96-107): Can send Telegram polls (with pre-set options "Approve", "Reject", "Need more info") alongside plain messages.

```bash
# Dispatch log frontmatter pattern (lines 81-93)
cat > "$DISPATCH_FILE" <<EOF
---
dispatch_id: ${DISPATCH_ID}
from: nexus
to: ${DEST_LABEL}
type: ${MSG_TYPE}
status: forwarded
sent: $(date -u +%Y-%m-%dT%H:%M:%SZ)
result: awaiting
---

${MESSAGE}
EOF
```

### `outbox-write.sh` — `/Users/doctorboyz/Code/github.com/doctorboyz/nexus-oracle/shared/outbox-write.sh`

Key patterns:
- **Dual input mode** (lines 73-80): Accepts either `--file` (extracts `msg_id` and `respond_in` from an inbox file's frontmatter via grep/sed) or direct `--msg-id` and `--respond-in` flags.
- **Stdin fallback** (lines 89-95): If `--content` is not provided and stdin is piped, reads content from stdin.
- **Unicode psi directory resolution** (lines 22-27): Checks both `ψ` and `psi` directory names to handle filesystem encoding differences.

```bash
# Stdin fallback pattern (lines 89-95)
if [ -z "$CONTENT" ]; then
    if [ ! -t 0 ]; then
        CONTENT="$(cat)"
    else
        echo "Error: --content is required (or pipe content via stdin)" >&2
        exit 1
    fi
fi
```

```bash
# Frontmatter extraction from inbox file (lines 75-79)
if [ -z "$MSG_ID" ]; then
    MSG_ID="$(grep '^msg_id:' "$INBOX_FILE" | head -1 | sed 's/msg_id:[[:space:]]*//' | tr -d '"')"
fi
if [ -z "$RESPOND_IN" ]; then
    RESPOND_IN="$(grep '^respond_in:' "$INBOX_FILE" | head -1 | sed 's/respond_in:[[:space:]]*//' | tr -d '"')"
fi
```

### `msg-protocol.sh` — `/Users/doctorboyz/Code/github.com/doctorboyz/nexus-oracle/shared/msg-protocol.sh`

Key patterns:
- **Sequential ID generation** (lines 6-12): `msg_generate_id()` scans existing outbox files to find the next available `MSG-NEXUS-NNN` sequence number, ensuring uniqueness without a central counter.
- **Hardcoded vault paths** (lines 42-49): Maps oracle names to their vault inbox paths using the variables from `vault-paths.sh`. This creates a static routing table in shell.
- **In-place status updates** (lines 73-87): `msg_ack()` and `msg_result()` use `sed -i ''` (macOS syntax) to update frontmatter fields (`status:`, `ack_by:`, `result:`) in-place, then write a separate ack/result file to the outbox.

```bash
# Sequential ID generation (lines 6-12)
msg_generate_id() {
    local counter=1
    while [ -f "$NEXUS_OUTBOX/MSG-NEXUS-$(printf '%03d' $counter)"* ] 2>/dev/null; do
        counter=$((counter + 1))
    done
    echo "MSG-NEXUS-$(printf '%03d' $counter)"
}

# In-place frontmatter update (lines 86-87)
sed -i '' "s/status: pending/status: acknowledged/" "$msg_file"
sed -i '' "s/ack_by: \"-\"/ack_by: $timestamp/" "$msg_file"
```

### `inbox-watcher.sh` — `/Users/doctorboyz/Code/github.com/doctorboyz/nexus-oracle/pm/inbox-watcher.sh`

Key patterns:
- **fswatch-based file monitoring** (line 49): Uses `fswatch` with `Created` and `Updated` event filters, piped through `while IFS= read -r -d '' file` for null-delimited filenames (handles spaces in paths).
- **Filter logic** (lines 53-55): Skips non-markdown files and files prefixed with `ack_` or `result_` (which are self-generated, not incoming messages).
- **macOS notifications** (line 69): Uses `osascript -e "display notification ..."` to show native macOS notifications, with `2>/dev/null || true` to silently fail on non-macOS or when notifications are disabled.

```bash
# fswatch monitoring loop (lines 49-89)
fswatch -0 --event Created --event Updated "$NEXUS_INBOX" | while IFS= read -r -d '' file; do
  filename=$(basename "$file")

  # Skip non-md files and ack/result files (those are from nexus itself)
  if [[ ! "$filename" == *.md ]] || [[ "$filename" == ack_* ]] || [[ "$filename" == result_* ]]; then
    continue
  fi

  # Extract sender and type from filename
  sender=$(echo "$filename" | sed -E 's/^[0-9_-]+_([a-z]+)_MSG.*/\1/' | head -1)
  msg_id=$(echo "$filename" | sed -E 's/.*_(MSG-[A-Z]+-[0-9]+).*/\1/' | head -1)

  # macOS notification
  osascript -e "display notification \"From: ${sender:-unknown}\" with title \"nexus Oracle Inbox\" subtitle \"${msg_id:-$filename}\"" 2>/dev/null || true

  # Write receipt to outbox
  # ...
done &
```

### `vault-paths.sh` — `/Users/doctorboyz/Code/github.com/doctorboyz/nexus-oracle/shared/vault-paths.sh`

Key pattern: Central path resolution. Every shell script sources this file to get consistent paths. The psi directory is resolved at source time with a fallback:

```bash
# Unicode-aware psi resolution (lines 8-14)
if [ -d "$NEXUS_ROOT/ψ" ]; then
    PSI_DIR="$NEXUS_ROOT/ψ"
elif [ -d "$NEXUS_ROOT/psi" ]; then
    PSI_DIR="$NEXUS_ROOT/psi"
else
    PSI_DIR="$NEXUS_ROOT/ψ"  # Default even if missing (will fail later)
fi
```

### `nexus-daemon-launcher.sh` — `/Users/doctorboyz/Code/github.com/doctorboyz/nexus-oracle/texty/nexus-daemon-launcher.sh`

Key pattern: macOS `launchd` wrapper that resolves the Python interpreter and ensures unbuffered output (`python3 -u`):

```bash
# Interpreter detection (lines 10-13)
PYTHON3="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
if [ ! -f "$PYTHON3" ]; then
    PYTHON3=$(which python3 2>/dev/null || echo "python3")
fi

exec "$PYTHON3" -u "$SCRIPT_DIR/nexus-daemon.py" \
  >> "$LOG_DIR/nexus-daemon.log" 2>> "$LOG_DIR/nexus-daemon.err"
```

### `nexus-daemon.sh` — `/Users/doctorboyz/Code/github.com/doctorboyz/nexus-oracle/texty/nexus-daemon.sh`

Key pattern: Webhook-mode startup script (alternative to polling mode). Starts a `cloudflared` tunnel, waits up to 40 seconds for the tunnel URL, then starts the Python daemon. On stop, it also calls `deleteWebhook` via inline Python:

```bash
# Tunnel URL polling (lines 37-44)
for i in $(seq 1 20); do
  sleep 2
  TUNNEL_URL=$(grep -oE 'https://[a-zA-Z0-9\-]+\.trycloudflare\.com' "$LOG_DIR/cloudflared.log" 2>/dev/null | tail -1)
  if [ -n "$TUNNEL_URL" ]; then
    break
  fi
  echo "Waiting for tunnel... ($i)"
done
```

### `inject-hook.sh` — `/Users/doctorboyz/Code/github.com/doctorboyz/nexus-oracle/pm/inject-hook.sh`

Key pattern: Programmatically modifies another oracle's `.claude/settings.json` to add a Stop hook. Uses Python's `json` module for safe JSON merging, checks for duplicate hooks, and creates settings.json from scratch if it does not exist:

```python
# Python inline JSON merge (lines 107-133)
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
```

### `.claude/settings.json` — `/Users/doctorboyz/Code/github.com/doctorboyz/nexus-oracle/.claude/settings.json`

Nexus's own hooks configuration:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash /Users/doctorboyz/Code/github.com/doctorboyz/nexus-oracle/shared/session-summary.sh nexus"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "bash -c 'INBOX=\"/Users/doctorboyz/Code/github.com/doctorboyz/nexus-oracle/ψ/inbox\"; COUNT=$(ls \"$INBOX\"/*.md 2>/dev/null | grep -L \"status: completed\" | wc -l | tr -d \" \"); if [ \"$COUNT\" -gt 0 ]; then echo \"📬 nexus: $COUNT unprocessed inbox message(s) pending — check ψ/inbox/\"; fi'"
          }
        ]
      }
    ]
  }
}
```

**PostToolUse hook**: After every `Write` or `Edit` tool call, checks for unprocessed inbox messages and prints a reminder. This creates a gentle nudge for the agent to process pending messages.

---

## Summary of Key Architectural Patterns

| Pattern | Where | Purpose |
|---------|-------|---------|
| Vault-driven state | `ψ/inbox/`, `ψ/outbox/`, `ψ/dispatch/`, `ψ/goals/` | All communication and state flows through filesystem markdown files with YAML frontmatter |
| MSG-ACK-RESULT protocol | `msg-protocol.sh`, inbox/outbox frontmatter | Three-phase message lifecycle: receive -> acknowledge -> result |
| Cache TTL | `ROUTING_CACHE_TTL=300`, `ORACLE_DIRS_CACHE_TTL=300` | Fleet configs refreshed every 5 minutes, not on every poll |
| Four-level return-path resolution | `process_outbox_file()` lines 268-287 | `respond_in` > cross-ref `source_chat` > oracle group > private chat |
| Graceful degradation | `deliver_to_oracle()` maw fallback, `process_outbox_file()` retry-on-fail | System continues working even when maw is down or Telegram API errors |
| Audit trail | `ψ/dispatch/` monthly logs, `ψ/inbox/` frontmatter | Every message is tracked with dispatch_id, timestamps, and routing metadata |
| Unicode-safe psi resolution | `find_psi_dir()`, `vault-paths.sh` | Handles both `ψ` and `psi` directory names across platforms |
