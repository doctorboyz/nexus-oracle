#!/usr/bin/env python3
"""
nexus-daemon.py — Telegram bot daemon for nexus Oracle
Polls Telegram for slash commands and group messages.
Managed by PM2: pm2 start nexus-daemon.py --interpreter python3

Commands:
  /wake <oracle>       — Start oracle session (maw wake <oracle>)
  /sleep <oracle>      — Stop oracle session (maw sleep <oracle>)
  /status              — Show fleet status (maw fleet ls + fleetdb)
  /inbox <oracle>      — Check oracle inbox (maw inbox ls + fleetdb)
  /send <oracle> <msg> — Send message to specific oracle
  /broadcast <msg>     — Send message to all oracle groups
  /goals               — Show active goals (fleetdb)
  /help                — Show available commands

Smart routing:
  - In an oracle group: plain text goes directly to that oracle
  - In Fleet group: auto-route by keyword matching
  - In private chat: falls back to nexus inbox

Event-driven (Phase B):
  - Messages stored in PostgreSQL via fleetdb
  - LISTEN/NOTIFY for real-time oracle state changes
  - File-based inbox/outbox still supported as fallback
"""

import asyncio
import json
import logging
import shutil
import subprocess
import sys
import os
import time
import datetime
from datetime import timezone
import signal
import threading

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("nexus")

# --- Async fleetdb infrastructure (Phase B) ---
# Runs an asyncio event loop in a daemon thread for database operations.
_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_fleetdb_available = False


def _run_async(coro):
    """Run an async coroutine from sync code and return result."""
    if _loop is None:
        return None
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    try:
        return future.result(timeout=10)
    except Exception:
        return None


def _start_event_loop():
    """Start the asyncio event loop in a background daemon thread."""
    global _loop, _loop_thread
    _loop = asyncio.new_event_loop()
    _loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
    _loop_thread.start()


def _init_fleetdb():
    """Initialize fleetdb (tables, registry sync) — called once at startup."""
    global _fleetdb_available
    try:
        from daemon import fleetdb

        _run_async(fleetdb.init_fleet_db())
        _fleetdb_available = True
        logger.info("[fleetdb] Database initialized — event-driven mode active")
        return fleetdb
    except Exception as e:
        logger.warning(f"[fleetdb] Unavailable — falling back to file-based mode: {e}")
        _fleetdb_available = False
        return None


def _db_create_message(from_oracle, to_oracle, msg_type, content, **kwargs):
    """Sync wrapper for fleetdb.create_message()."""
    fleetdb = _init_fleetdb() if not _fleetdb_available else None
    if not _fleetdb_available and fleetdb is None:
        return None
    # Re-import from module-level if already initialized
    try:
        from daemon import fleetdb as fdb
    except ImportError:
        return None
    try:
        return _run_async(fdb.create_message(from_oracle, to_oracle, msg_type, content, **kwargs))
    except Exception as e:
        logger.error(f"[fleetdb] create_message failed: {e}")
        return None


def _db_get_pending_messages(oracle_name):
    """Sync wrapper for fleetdb.get_pending_messages_for()."""
    if not _fleetdb_available:
        return []
    try:
        from daemon import fleetdb as fdb
        return _run_async(fdb.get_pending_messages_for(oracle_name)) or []
    except Exception:
        return []


def _db_get_fleet_status():
    """Sync wrapper for fleetdb.get_fleet_status()."""
    if not _fleetdb_available:
        return []
    try:
        from daemon import fleetdb as fdb
        return _run_async(fdb.get_fleet_status()) or []
    except Exception:
        return []


def _db_get_active_goals(oracle_name=None):
    """Sync wrapper for fleetdb.get_active_goals()."""
    if not _fleetdb_available:
        return []
    try:
        from daemon import fleetdb as fdb
        return _run_async(fdb.get_active_goals(oracle_name)) or []
    except Exception:
        return []


def _db_update_oracle_state(oracle_name, state):
    """Sync wrapper for fleetdb.update_oracle_state()."""
    if not _fleetdb_available:
        return
    try:
        from daemon import fleetdb as fdb
        _run_async(fdb.update_oracle_state(oracle_name, state))
    except Exception:
        pass


def _db_log_activity(activity_type, oracle_name, **kwargs):
    """Sync wrapper for fleetdb.log_activity()."""
    if not _fleetdb_available:
        return
    try:
        from daemon import fleetdb as fdb
        _run_async(fdb.log_activity(activity_type, oracle_name, **kwargs))
    except Exception:
        pass


# --- Constants ---
MAX_OUTBOX_RETRIES = 3
MAX_API_RETRIES = 1  # 1 retry after initial attempt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NEXUS_ROOT = os.path.dirname(SCRIPT_DIR)


def find_psi_dir():
    """Find the psi directory (handles unicode psi character)"""
    for entry in os.listdir(NEXUS_ROOT):
        full_path = os.path.join(NEXUS_ROOT, entry)
        if os.path.isdir(full_path) and entry in ("psi", "ψ"):
            return full_path
    for entry in os.listdir(NEXUS_ROOT):
        full_path = os.path.join(NEXUS_ROOT, entry)
        if os.path.isdir(full_path) and len(entry) <= 2 and not entry.startswith("."):
            return full_path
    return None


PSI_DIR = find_psi_dir()
if not PSI_DIR:
    logger.error("psi directory not found")
    sys.exit(1)

CREDENTIALS_FILE = os.path.join(PSI_DIR, "credentials", "telegram.json")

with open(CREDENTIALS_FILE) as f:
    CREDS = json.load(f)

BOT_TOKEN = CREDS["bot_token"]
BOT_ID = int(CREDS.get("bot_id", BOT_TOKEN.split(":")[0]))
CHAT_ID = int(CREDS["chat_id"])
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
CHANNELS = {k: int(v) for k, v in CREDS.get("channels", {}).items()}
AUTHORIZED_CHATS = {CHAT_ID} | set(CHANNELS.values())
ALLOWED_SENDERS = {CHAT_ID, BOT_ID}

OFFSET = 0
POLL_INTERVAL = 3
ROUTING_CACHE_TTL = 300  # 5 minutes
ORACLE_DIRS_CACHE_TTL = 300  # 5 minutes

# Outbox retry tracking: filepath -> attempt count
_outbox_retry_count: dict[str, int] = {}


def load_oracles_from_fleet():
    """Load oracle names from maw fleet config."""
    fleet_dir = os.path.expanduser("~/.config/maw/fleet")
    if os.path.isdir(fleet_dir):
        names = set()
        for f in os.listdir(fleet_dir):
            if f.endswith(".json"):
                try:
                    with open(os.path.join(fleet_dir, f)) as fh:
                        cfg = json.load(fh)
                        if "name" in cfg:
                            names.add(cfg["name"])
                except Exception:
                    continue
        if names:
            return names
    return {"emily", "god-port", "nexus", "kappy", "fammee", "infra"}


ORACLES = load_oracles_from_fleet()


def load_routing_table():
    """Load routing metadata from fleet configs.
    Returns dict mapping oracle name -> {"keywords": [...], "domains": [...]}.
    """
    fleet_dir = os.path.expanduser("~/.config/maw/fleet")
    if not os.path.isdir(fleet_dir):
        return {}
    routing = {}
    for f in os.listdir(fleet_dir):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(fleet_dir, f)) as fh:
                cfg = json.load(fh)
                name = cfg.get("name")
                if name:
                    routing[name] = cfg.get("routing", {})
        except Exception:
            continue
    return routing


def load_fleet_config(oracle):
    """Load a single oracle's fleet config."""
    fleet_dir = os.path.expanduser("~/.config/maw/fleet")
    if not os.path.isdir(fleet_dir):
        return {}
    for f in os.listdir(fleet_dir):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(fleet_dir, f)) as fh:
                cfg = json.load(fh)
                if cfg.get("name") == oracle:
                    return cfg
        except Exception:
            continue
    return {}


def find_oracle_dirs():
    """Find oracle directories (psi, inbox, outbox) from fleet configs.
    Returns dict mapping oracle name -> {root, psi, inbox, outbox}.
    """
    fleet_dir = os.path.expanduser("~/.config/maw/fleet")
    if not os.path.isdir(fleet_dir):
        return {}
    dirs = {}
    for f in os.listdir(fleet_dir):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(fleet_dir, f)) as fh:
                cfg = json.load(fh)
                name = cfg.get("name")
                windows = cfg.get("windows", [])
                if not name or not windows:
                    continue
                root = windows[0].get("root")
                if not root or not os.path.isdir(root):
                    continue
                # Find psi/ψ directory
                psi_dir = None
                for entry in os.listdir(root):
                    full = os.path.join(root, entry)
                    if os.path.isdir(full) and entry in ("psi", "ψ"):
                        psi_dir = full
                        break
                if psi_dir:
                    dirs[name] = {
                        "root": root,
                        "psi": psi_dir,
                        "inbox": os.path.join(psi_dir, "inbox"),
                        "outbox": os.path.join(psi_dir, "outbox"),
                    }
        except Exception:
            continue
    return dirs


ORACLE_DIRS = find_oracle_dirs()
_oracle_dirs_loaded_at = time.time()


def get_oracle_dirs():
    """Return cached oracle dirs, refreshing every ORACLE_DIRS_CACHE_TTL seconds."""
    global ORACLE_DIRS, _oracle_dirs_loaded_at
    if time.time() - _oracle_dirs_loaded_at > ORACLE_DIRS_CACHE_TTL:
        ORACLE_DIRS = find_oracle_dirs()
        _oracle_dirs_loaded_at = time.time()
    return ORACLE_DIRS


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


def process_outbox_file(oracle_name, filepath, oracle_dirs):
    """Process a single outbox file: parse frontmatter, determine target chat, send to Telegram.
    Returns True if file was processed (sent or skipped), False on error.
    """
    try:
        with open(filepath) as f:
            content = f.read()

        # Parse YAML frontmatter
        if not content.startswith("---"):
            # No frontmatter — treat entire content as response body
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
            logger.info(f"[outbox] {oracle_name}: skipping ack {os.path.basename(filepath)}")
            return True

        # Only send result, reply, response types (or files without type)
        if msg_type not in ("result", "reply", "response", ""):
            logger.info(f"[outbox] {oracle_name}: skipping unknown type '{msg_type}' {os.path.basename(filepath)}")
            return True

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

        # Send response as plain text (oracle responses often have markdown
        # tables/special chars that break Telegram's Markdown parser)
        prefix = f"💬 [{from_oracle}]"
        max_body = 3900 - len(prefix)
        truncated_body = body[:max_body] + "..." if len(body) > max_body else body
        response_text = f"{prefix}\n\n{truncated_body}"
        payload = {"chat_id": target_chat, "text": response_text}
        result = curl_api("sendMessage", payload)

        sent_ok = result and result.get("ok", False)
        if not sent_ok:
            error_desc = result.get("description", "unknown error") if result else "no response"
            logger.warning(f"[outbox] Failed to send {os.path.basename(filepath)} to chat {target_chat}: {error_desc}")
            # Notify human that delivery failed
            send_message(f"⚠️ [nexus] Failed to deliver {escape_html(from_oracle)} response to chat {target_chat}: {escape_html(error_desc[:200])}")
        return sent_ok

    except Exception as e:
        logger.error(f"[outbox] Error processing {filepath}: {e}")
        return False


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
        shutil.move(filepath, dest)


def move_to_dead_letter(filepath, oracle_name, reason):
    """Move an outbox file to dead/YYYY-MM/ after exceeding max retries."""
    outbox_dir = os.path.dirname(filepath)
    now = datetime.datetime.now(timezone.utc)
    dead_dir = os.path.join(outbox_dir, "dead", now.strftime("%Y-%m"))
    os.makedirs(dead_dir, exist_ok=True)
    dest = os.path.join(dead_dir, os.path.basename(filepath))
    try:
        os.rename(filepath, dest)
    except OSError:
        shutil.move(filepath, dest)
    logger.error(
        f"[outbox] {oracle_name}: moved to dead letter after {MAX_OUTBOX_RETRIES} retries: "
        f"{os.path.basename(filepath)} — {reason}"
    )
    send_message(
        f"☠️ [nexus] Dead letter: {escape_html(oracle_name)} outbox file "
        f"{escape_html(os.path.basename(filepath))} failed {MAX_OUTBOX_RETRIES}x\n"
        f"Reason: {escape_html(reason[:200])}"
    )


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
            # Skip archive, dead, dotfiles, non-markdown
            if f.startswith(".") or f in ("archive", "dead") or not f.endswith(".md"):
                continue

            filepath = os.path.join(outbox_dir, f)
            if not os.path.isfile(filepath):
                continue

            success = process_outbox_file(oracle_name, filepath, oracle_dirs)
            if success:
                archive_outbox_file(filepath)
                # Clear retry count on success
                _outbox_retry_count.pop(filepath, None)
            else:
                # Track retry count; move to dead letter after MAX_OUTBOX_RETRIES
                _outbox_retry_count[filepath] = _outbox_retry_count.get(filepath, 0) + 1
                if _outbox_retry_count[filepath] >= MAX_OUTBOX_RETRIES:
                    move_to_dead_letter(filepath, oracle_name, f"send failed after {_outbox_retry_count[filepath]} attempts")
                    _outbox_retry_count.pop(filepath, None)
                else:
                    logger.warning(
                        f"[outbox] {oracle_name}: will retry {f} "
                        f"(attempt {_outbox_retry_count[filepath]}/{MAX_OUTBOX_RETRIES})"
                    )


ROUTING_TABLE = load_routing_table()
_routing_loaded_at = time.time()


def get_routing_table():
    """Return cached routing table, refreshing every ROUTING_CACHE_TTL seconds."""
    global ROUTING_TABLE, _routing_loaded_at
    if time.time() - _routing_loaded_at > ROUTING_CACHE_TTL:
        ROUTING_TABLE = load_routing_table()
        _routing_loaded_at = time.time()
    return ROUTING_TABLE


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


def is_oracle_running(oracle):
    """Check if an oracle session is currently running via maw peek."""
    output = run_cmd(["maw", "peek", oracle])
    return "running" in output.lower() or "active" in output.lower()


def deliver_to_oracle(oracle, text, respond_chat_id, from_user_id):
    """Deliver a message directly to an oracle's inbox and post confirmation.
    respond_chat_id: the chat where the human sent the message.
    Returns a status string for logging.
    """
    # 1. Deliver via maw inbox send (no shell escaping needed — list args)
    output = run_cmd(["maw", "inbox", "send", oracle, text])

    maw_ok = True
    if "Cannot resolve" in output or "not found" in output or "Error" in output:
        result = write_to_inbox(oracle, text)
        maw_ok = False

    # 2. Auto-wake if not running, or notify running session via maw hey
    cfg = load_fleet_config(oracle)
    auto_wake = cfg.get("auto_wake", True)
    wake_msg = ""
    if is_oracle_running(oracle):
        # Oracle is running — inject message directly into its tmux pane
        # This is the key step that makes oracle sessions respond in real-time
        hey_summary = f"New message from Telegram: {text[:80]}"
        hey_output = run_cmd(["maw", "hey", oracle, hey_summary])
        if "sent" in hey_output.lower() or "delivered" in hey_output.lower() or hey_output:
            wake_msg = f"\n⚡ Notified {oracle} (session running)"
        else:
            wake_msg = f"\n📥 Delivered to {oracle} inbox (session may need refresh)"
    elif auto_wake:
        wake_output = run_cmd(["maw", "wake", oracle])
        if "running" in wake_output.lower() or "started" in wake_output.lower():
            wake_msg = f"\n⚡ Auto-woke {oracle}"
        else:
            wake_msg = f"\n⚠️ Could not auto-wake {oracle} — message delivered to inbox but oracle is offline"

    # 3. Post confirmation in source chat
    oracle_chat = get_oracle_chat(oracle)
    delivery_method = "inbox + maw" if maw_ok else "inbox (direct)"

    if respond_chat_id == CHAT_ID:
        # Private chat
        result = send_message(f"📨 <b>Delivered to {escape_html(oracle)}</b> ({delivery_method}){escape_html(wake_msg)}\n\n<i>{escape_html(text[:100])}</i>")
        if not result or not result.get("ok"):
            logger.warning(f"[deliver] Failed to send confirmation to private chat: {result}")
    elif respond_chat_id == oracle_chat:
        # Already in the oracle's group
        result = send_message(f"📨 <b>Message received for {escape_html(oracle)}</b>\n\n<i>{escape_html(text[:200])}</i>{escape_html(wake_msg)}", chat_id=oracle_chat)
        if not result or not result.get("ok"):
            logger.warning(f"[deliver] Failed to send confirmation to {oracle} group: {result}")
    else:
        # Fleet group or other
        result = send_message(f"📨 <b>Routed to {escape_html(oracle)}</b> ({delivery_method}){escape_html(wake_msg)}\n\n<i>{escape_html(text[:200])}</i>", chat_id=respond_chat_id)
        if not result or not result.get("ok"):
            logger.warning(f"[deliver] Failed to send confirmation to fleet group: {result}")
        if oracle_chat:
            result2 = send_message(f"📨 <b>Message from Fleet</b> (auto-routed)\n\n<i>{escape_html(text[:200])}</i>{escape_html(wake_msg)}", chat_id=oracle_chat)
            if not result2 or not result2.get("ok"):
                logger.warning(f"[deliver] Failed to send cross-post to {oracle} group: {result2}")

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
sent: {now.isoformat()}z
source_chat: {respond_chat_id}
routed_to: {oracle}
routing_method: {routing_method}
respond_in: {respond_chat_id}
respond_chat_type: {chat_type}
ack_by: "-"
result: "-"
reply_file: ""
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

    # Also write to fleetdb (Phase B)
    _db_create_message("human", oracle, "query", text,
                       respond_in=str(respond_chat_id))

    return f"delivered to {oracle}"


def curl_api(method, params=None, max_retries=MAX_API_RETRIES):
    """Call Telegram Bot API via curl with retry on timeout."""
    url = f"{API_URL}/{method}"
    for attempt in range(max_retries + 1):
        try:
            if params:
                result = subprocess.run(
                    ["curl", "-s", "-X", "POST", url,
                     "-H", "Content-Type: application/json",
                     "-d", json.dumps(params)],
                    capture_output=True, text=True, timeout=30,
                )
            else:
                result = subprocess.run(
                    ["curl", "-s", url],
                    capture_output=True, text=True, timeout=30,
                )
            if result.stdout:
                return json.loads(result.stdout)
            return None
        except subprocess.TimeoutExpired:
            if attempt < max_retries:
                logger.warning(f"[api] Timeout on {method}, retry {attempt + 1}/{max_retries}")
                time.sleep(2)
                continue
            logger.error(f"[api] Timeout on {method} after {max_retries + 1} attempts")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"[api] Parse error on {method}: {e}")
            return None
        except Exception as e:
            logger.error(f"[api] Error on {method}: {e}")
            return None
    return None


def escape_html(text):
    """Escape HTML special characters for safe Telegram rendering."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_message(text, chat_id=None, reply_to=None):
    """Send message via Telegram bot using HTML parse mode (more robust than Markdown v1)."""
    payload = {"chat_id": chat_id or CHAT_ID, "text": text, "parse_mode": "HTML"}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    return curl_api("sendMessage", payload)


def get_oracle_chat(oracle):
    """Get the group chat ID for an oracle, or None if not found."""
    return CHANNELS.get(oracle)


def get_oracle_by_chat(chat_id):
    """Find which oracle a group chat belongs to, or None."""
    for name, cid in CHANNELS.items():
        if cid == chat_id:
            return name
    return None


def run_cmd(args):
    """Run command and return output. Args is a list of strings (no shell injection risk)."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        output = result.stdout.strip()
        if result.stderr and not output:
            output = result.stderr.strip()
        return output[:4000] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out (15s)"
    except Exception as e:
        return f"Error: {e}"


def handle_command(text, from_chat_id, message_id):
    """Parse and execute slash commands"""
    parts = text.strip().split()
    # Handle @bot_name suffix in commands: /send@texty_oracle_bot -> /send
    cmd = parts[0].lower().split("@")[0]
    args = parts[1:]

    if cmd == "/help":
        return (
            "<b>nexus Oracle Commands</b>\n"
            "/wake &lt;oracle&gt; — Start oracle session\n"
            "/sleep &lt;oracle&gt; — Stop oracle session\n"
            "/status — Show fleet status\n"
            "/inbox &lt;oracle&gt; — Check oracle inbox\n"
            "/send &lt;oracle&gt; &lt;msg&gt; — Send message to specific oracle\n"
            "/broadcast &lt;msg&gt; — Send message to all oracle groups\n"
            "/goals — Show active goals\n"
            "/help — This message\n\n"
            "<b>Smart Routing</b>\n"
            "In an oracle group: just type — your message goes to that oracle directly\n"
            "In Fleet group: type naturally — nexus routes to the right oracle by keywords\n\n"
            f"Oracles: {', '.join(sorted(ORACLES))}"
        )

    elif cmd == "/wake":
        if not args or args[0].lower() not in ORACLES:
            return f"Usage: /wake &lt;oracle&gt;\nOracles: {', '.join(sorted(ORACLES))}"
        oracle = args[0].lower()
        output = run_cmd(["maw", "wake", oracle])
        oracle_chat = get_oracle_chat(oracle)
        if oracle_chat:
            send_message(f"⚡ <b>{escape_html(oracle)}</b> session started", chat_id=oracle_chat)
        return f"<b>wake {escape_html(oracle)}:</b>\n<pre>{escape_html(output)}</pre>"

    elif cmd == "/sleep":
        if not args or args[0].lower() not in ORACLES:
            return f"Usage: /sleep &lt;oracle&gt;\nOracles: {', '.join(sorted(ORACLES))}"
        oracle = args[0].lower()
        output = run_cmd(["maw", "sleep", oracle])
        oracle_chat = get_oracle_chat(oracle)
        if oracle_chat:
            send_message(f"💤 <b>{escape_html(oracle)}</b> session stopped", chat_id=oracle_chat)
        return f"<b>sleep {escape_html(oracle)}:</b>\n<pre>{escape_html(output)}</pre>"

    elif cmd == "/status":
        output = run_cmd(["maw", "fleet", "ls"])
        # Enrich with fleetdb data if available
        fleet_rows = _db_get_fleet_status()
        if fleet_rows:
            db_lines = []
            for r in fleet_rows:
                name = r.get("name", "?")
                state = r.get("state", "?")
                workload = r.get("workload_pct", 0)
                goals = r.get("active_goals", 0)
                tasks = r.get("active_tasks", 0)
                db_lines.append(f"  {name:10s} [{state:7s}] g={goals} t={tasks} w={workload}%")
            db_summary = "\n".join(db_lines)
            return f"<b>Fleet Status (DB):</b>\n<pre>{escape_html(db_summary)}</pre>\n\n<b>maw:</b>\n<pre>{escape_html(output)}</pre>"
        return f"<b>Fleet Status:</b>\n<pre>{escape_html(output)}</pre>"

    elif cmd == "/inbox":
        if not args or args[0].lower() not in ORACLES:
            return f"Usage: /inbox &lt;oracle&gt;\nOracles: {', '.join(sorted(ORACLES))}"
        oracle = args[0].lower()
        # Show inbox for the specified oracle specifically
        oracle_dirs = get_oracle_dirs()
        oracle_dir = oracle_dirs.get(oracle, {})
        inbox_path = oracle_dir.get("inbox")
        if inbox_path and os.path.isdir(inbox_path):
            files = sorted(os.listdir(inbox_path))
            md_files = [f for f in files if f.endswith(".md")]
            if md_files:
                listing = "\n".join(md_files[-10:])
                return f"<b>inbox ({escape_html(oracle)}):</b> {len(md_files)} messages\n<pre>{escape_html(listing)}</pre>"
            else:
                return f"<b>inbox ({escape_html(oracle)}):</b> Empty"
        # Fallback to maw inbox ls if we can't find the oracle's inbox dir
        output = run_cmd(["maw", "inbox", "ls"])
        return f"<b>inbox ({escape_html(oracle)}):</b>\n<pre>{escape_html(output)}</pre>"

    elif cmd == "/send":
        if len(args) < 2 or args[0].lower() not in ORACLES:
            return f"Usage: /send &lt;oracle&gt; &lt;message&gt;\nOracles: {', '.join(sorted(ORACLES))}"
        oracle = args[0].lower()
        msg = " ".join(args[1:])
        # If sending to the oracle whose group you're already in, hint about smart routing
        current_oracle = get_oracle_by_chat(from_chat_id)
        if current_oracle == oracle:
            return f"💡 You're already in the {escape_html(oracle)} group! Just type your message directly — no /send needed."
        output = run_cmd(["maw", "inbox", "send", oracle, msg])
        if "Cannot resolve" in output or "not found" in output:
            result = write_to_inbox(oracle, msg)
            if not result:
                return f"❌ <b>Cannot deliver to {escape_html(oracle)}</b>\n\n{escape_html(output[:200])}"
        if "busy" in output.lower():
            return f"⏳ <b>{escape_html(oracle)} is busy</b> — try again when session ends\n\nReply /send {escape_html(oracle)} &lt;msg&gt; later"
        oracle_chat = get_oracle_chat(oracle)
        if oracle_chat:
            send_message(f"📨 <b>Message from human:</b>\n\n{escape_html(msg)}", chat_id=oracle_chat)
            return f"✅ <b>Delivered to {escape_html(oracle)}</b>\n\nSent to group + inbox"
        return f"✅ <b>Delivered to {escape_html(oracle)}</b> (inbox only)\n\n<pre>{escape_html(output)}</pre>"

    elif cmd == "/broadcast":
        if not args:
            return "Usage: /broadcast &lt;message&gt;\nSends to all oracle groups."
        msg = " ".join(args)
        # Send to all oracle groups (skip fleet)
        results = {}
        for name, cid in CHANNELS.items():
            if name == "fleet":
                continue
            result = send_message(f"📢 <b>Broadcast:</b>\n\n{escape_html(msg)}", chat_id=cid)
            results[name] = "✅" if result and result.get("ok") else "❌"
        summary = "\n".join(f"• {n}: {s}" for n, s in sorted(results.items()))
        return f"<b>Broadcast sent:</b>\n{summary}\n\n📝 {escape_html(msg[:100])}"

    elif cmd == "/goals":
        # Use fleetdb for goals (Phase B)
        db_goals = _db_get_active_goals()
        if db_goals:
            lines = []
            for g in db_goals:
                goal_id = g.get("goal_id", "?")
                title = g.get("title", "?")
                progress = g.get("progress_pct", 0)
                owner = g.get("oracle_owner", "?")
                lines.append(f"• {goal_id}: {title} [{progress}%] ({owner})")
            return f"<b>Active Goals (DB):</b>\n" + "\n".join(lines)
        # Fallback to file-based
        goals_dir = os.path.join(PSI_DIR, "goals", "active")
        if os.path.isdir(goals_dir):
            goals = [f for f in os.listdir(goals_dir) if f.endswith(".md")]
            if goals:
                return f"<b>Active Goals:</b>\n" + "\n".join(f"• {escape_html(g.replace('.md', ''))}" for g in goals)
            else:
                return "<b>No active goals</b>"
        else:
            return "<b>Goals directory not found</b>"

    else:
        return f"Unknown command: {cmd}\nType /help for available commands"


def write_to_inbox(oracle, message):
    """Write message directly to oracle's inbox (file-based) + fleetdb (Phase B)."""
    fleet_dir = os.path.expanduser("~/.config/maw/fleet")
    if not os.path.isdir(fleet_dir):
        return False

    file_written = False
    for f in os.listdir(fleet_dir):
        if f.endswith(".json"):
            try:
                with open(os.path.join(fleet_dir, f)) as fh:
                    cfg = json.load(fh)
                    if cfg.get("name") == oracle:
                        root = cfg.get("windows", [{}])[0].get("root")
                        if root:
                            for entry in os.listdir(root):
                                if entry in ("psi", "ψ") and os.path.isdir(os.path.join(root, entry)):
                                    psi = os.path.join(root, entry)
                                    inbox_dir = os.path.join(psi, "inbox")
                                    os.makedirs(inbox_dir, exist_ok=True)
                                    now = datetime.datetime.now(timezone.utc)
                                    msg_id = f"MSG-NEXUS-{now.strftime('%H%M%S')}"
                                    filename = f"{now.strftime('%Y%m%d')}_{now.strftime('%H%M')}_nexus_{msg_id}.md"
                                    filepath = os.path.join(inbox_dir, filename)
                                    content = f"""---
msg_id: {msg_id}
from: nexus
to: {oracle}
type: query
status: pending
sent: {now.isoformat()}z
ack_by: "-"
result: "-"
reply_file: "-"
---

{message}
"""
                                    with open(filepath, "w") as wf:
                                        wf.write(content)
                                    file_written = True
            except Exception:
                continue

    return file_written


def forward_to_nexus(text, from_id, chat_id):
    """Forward unroutable messages to nexus inbox with helpful response."""
    now = datetime.datetime.now(timezone.utc)
    filename = f"{now.strftime('%Y%m%d')}_{now.strftime('%H-%M')}_human_MSG-HUMAN-{now.strftime('%H%M')}.md"
    filepath = os.path.join(PSI_DIR, "inbox", filename)

    oracle = get_oracle_by_chat(chat_id)
    source_label = f"from {oracle}" if oracle else "from private chat"

    content = f"""---
msg_id: MSG-HUMAN-{now.strftime('%H%M')}
from: human
to: nexus
type: query
status: pending
sent: {now.isoformat()}z
source_chat: {chat_id}
source_oracle: {oracle or 'none'}
ack_by: "-"
result: "-"
reply_file: "-"
---

{text}
"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)

    # Also write to fleetdb (Phase B)
    _db_create_message("human", "nexus", "query", text,
                       respond_in=str(chat_id),
                       content_json={"source_oracle": oracle or "none"})

    # Try to auto-route in private chat — suggest which oracle might handle this
    if chat_id == CHAT_ID:
        routing = get_routing_table()
        target_oracle, confidence = route_by_intent(text, routing)
        oracle_list = ", ".join(sorted(ORACLES - {"nexus"}))
        if target_oracle and confidence >= 0.5:
            hint = f"\n\n💡 This looks like it's for <b>{escape_html(target_oracle)}</b> — try: <code>/send {target_oracle} {escape_html(text[:50])}</code>"
        else:
            hint = f"\n\n💡 Try: <code>/send &lt;oracle&gt; &lt;message&gt;</code>\nOracles: {escape_html(oracle_list)}"
        send_message(f"📝 [nexus] Received ({source_label}): {escape_html(text[:80])}{hint}")
    else:
        send_message(f"📝 [nexus] Received ({source_label}): {escape_html(text[:80])}")


def poll_updates():
    """Poll Telegram for new updates (long polling)"""
    global OFFSET
    result = curl_api("getUpdates", {
        "offset": OFFSET,
        "timeout": 10,
        "allowed_updates": ["message"],
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

        logger.info(f"[msg] chat={chat_id} from={from_id}: {text[:50]}")

        if text.startswith("/"):
            response = handle_command(text, chat_id, msg_id)
            if response:
                send_message(response, chat_id=chat_id, reply_to=msg_id)
        else:
            # Smart routing for non-command messages
            oracle = get_oracle_by_chat(chat_id)

            if oracle and oracle != "fleet":
                # CASE 1: Message in an oracle-specific group
                # Route directly to that oracle — context is clear
                deliver_to_oracle(oracle, text, chat_id, from_id)

            elif chat_id == CHANNELS.get("fleet"):
                # CASE 2: Message in the fleet group
                # Auto-route by intent/keyword matching
                routing = get_routing_table()
                target_oracle, confidence = route_by_intent(text, routing)

                if target_oracle and confidence >= 0.5:
                    deliver_to_oracle(target_oracle, text, chat_id, from_id)
                else:
                    # No confident match — ask human which oracle should handle it
                    oracle_list = ", ".join(sorted(ORACLES - {"nexus"}))
                    send_message(
                        f"🤔 <b>Not sure which oracle should handle this.</b>\n\n"
                        f"<i>{escape_html(text[:100])}</i>\n\n"
                        f"Reply /send &lt;oracle&gt; &lt;msg&gt; or:\n"
                        f"Oracles: {oracle_list}",
                        chat_id=chat_id,
                    )
                    forward_to_nexus(text, from_id, chat_id)

            else:
                # CASE 3: Private chat or unknown — fallback to nexus inbox
                forward_to_nexus(text, from_id, chat_id)


def register_commands():
    """Register bot commands with Telegram"""
    commands = [
        {"command": "wake", "description": "Start oracle session (e.g., /wake emily)"},
        {"command": "sleep", "description": "Stop oracle session (e.g., /sleep emily)"},
        {"command": "status", "description": "Show fleet status"},
        {"command": "inbox", "description": "Check oracle inbox (e.g., /inbox emily)"},
        {"command": "send", "description": "Send message to oracle (e.g., /send emily hello)"},
        {"command": "broadcast", "description": "Send message to all oracle groups"},
        {"command": "goals", "description": "Show active goals"},
        {"command": "help", "description": "Show available commands"},
    ]
    result = curl_api("setMyCommands", {"commands": commands})
    if result and result.get("ok"):
        logger.info("Bot commands registered!")
    else:
        logger.error(f"Failed to register commands: {result}")


def shutdown(signum=None, frame=None):
    """Clean shutdown"""
    logger.info("Shutting down...")
    send_message("📡 [nexus] Daemon stopped")
    sys.exit(0)


def main():
    logger.info("=" * 50)
    logger.info("nexus Oracle daemon starting (Phase C: event-driven + 30s fallback)...")
    logger.info(f"Bot: @texty_oracle_bot")
    logger.info(f"Chat ID: {CHAT_ID}")
    logger.info(f"Oracles: {', '.join(sorted(ORACLES))}")
    logger.info(f"Channels: {', '.join(f'{k}={v}' for k, v in sorted(CHANNELS.items()))}")
    logger.info(f"Authorized chats: {len(AUTHORIZED_CHATS)}")
    logger.info(f"Routing table: {len(ROUTING_TABLE)} oracles")
    logger.info(f"Outbox watching: {len(ORACLE_DIRS)} oracles")
    logger.info("=" * 50)

    # Start async event loop for fleetdb (Phase C: event-driven)
    _start_event_loop()
    _init_fleetdb()

    # Start LISTEN/NOTIFY event consumers (Phase C)
    if _fleetdb_available:
        from daemon import event_consumer
        _run_async(event_consumer.start_event_consumers())
        logger.info("[event] LISTEN/NOTIFY consumers active — event-driven mode")
        _db_update_oracle_state("nexus", "online")

    # Make sure no webhook is set (conflicts with polling)
    curl_api("deleteWebhook", {"drop_pending_updates": True})

    register_commands()
    send_message("📡 [nexus] Daemon started — smart routing active\nIn oracle groups: just type • In Fleet: auto-route • /help for commands")

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info(f"Polling every {POLL_INTERVAL}s (event-driven + 30s fallback outbox scan)")
    _last_outbox_fallback = 0
    while True:
        try:
            poll_updates()
            # Fallback outbox scan every 30s (NOTIFY handles normal path)
            if time.time() - _last_outbox_fallback > 30:
                poll_outboxes()
                _last_outbox_fallback = time.time()
        except KeyboardInterrupt:
            shutdown()
        except Exception as e:
            logger.error(f"Poll error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()