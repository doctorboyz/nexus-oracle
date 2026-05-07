#!/usr/bin/env python3
"""
nexus-daemon.py — Telegram bot daemon for nexus Oracle
Polls Telegram for slash commands and executes them locally.
Uses curl for all API calls (avoids Python SSL issues on macOS).

Commands:
  /wake <oracle>   — Start oracle session (maw wake <oracle>)
  /sleep <oracle>  — Stop oracle session (maw sleep <oracle>)
  /status           — Show fleet status (maw fleet ls)
  /inbox <oracle>  — Check oracle inbox (maw inbox ls)
  /send <oracle> <msg> — Send message to oracle inbox
  /help             — Show available commands
"""

import json
import subprocess
import sys
import time
import os
import datetime

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
    print("Error: psi directory not found")
    sys.exit(1)

CREDENTIALS_FILE = os.path.join(PSI_DIR, "credentials", "telegram.json")

with open(CREDENTIALS_FILE) as f:
    CREDS = json.load(f)

BOT_TOKEN = CREDS["bot_token"]
CHAT_ID = int(CREDS["chat_id"])
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

ORACLES = {"emily", "god-port", "nexus", "mkt", "dev", "kappy"}
OFFSET = 0
POLL_INTERVAL = 5


def curl_api(method, params=None):
    """Call Telegram Bot API via curl (avoids Python SSL issues on macOS)"""
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


def send_message(text, chat_id=None, reply_to=None):
    """Send message via Telegram bot"""
    payload = {"chat_id": chat_id or CHAT_ID, "text": text, "parse_mode": "Markdown"}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    return curl_api("sendMessage", payload)


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


def handle_command(text, from_chat_id, message_id):
    """Parse and execute slash commands"""
    parts = text.strip().split()
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd == "/help":
        return (
            "*nexus Oracle Commands*\n"
            "/wake \\<oracle\\> — Start oracle session\n"
            "/sleep \\<oracle\\> — Stop oracle session\n"
            "/status — Show fleet status\n"
            "/inbox \\<oracle\\> — Check oracle inbox\n"
            "/send \\<oracle\\> \\<msg\\> — Send message to oracle\n"
            "/goals — Show active goals\n"
            "/help — This message\n\n"
            f"Oracles: {', '.join(sorted(ORACLES))}"
        )

    elif cmd == "/wake":
        if not args or args[0].lower() not in ORACLES:
            return f"Usage: /wake <oracle>\nOracles: {', '.join(sorted(ORACLES))}"
        oracle = args[0].lower()
        output = run_cmd(f"maw wake {oracle}")
        return f"*wake {oracle}:*\n```\n{output}\n```"

    elif cmd == "/sleep":
        if not args or args[0].lower() not in ORACLES:
            return f"Usage: /sleep <oracle>\nOracles: {', '.join(sorted(ORACLES))}"
        oracle = args[0].lower()
        output = run_cmd(f"maw sleep {oracle}")
        return f"*sleep {oracle}:*\n```\n{output}\n```"

    elif cmd == "/status":
        output = run_cmd("maw fleet ls")
        return f"*Fleet Status:*\n```\n{output}\n```"

    elif cmd == "/inbox":
        if not args or args[0].lower() not in ORACLES:
            return f"Usage: /inbox <oracle>\nOracles: {', '.join(sorted(ORACLES))}"
        oracle = args[0].lower()
        output = run_cmd("maw inbox ls")
        return f"*inbox ({oracle}):*\n```\n{output}\n```"

    elif cmd == "/send":
        if len(args) < 2 or args[0].lower() not in ORACLES:
            return f"Usage: /send <oracle> <message>\nOracles: {', '.join(sorted(ORACLES))}"
        oracle = args[0].lower()
        msg = " ".join(args[1:])
        output = run_cmd(f"maw inbox send {oracle} \"{msg}\"")
        if "busy" in output.lower():
            return f"⏳ *{oracle} is busy* — try again when session ends\n\nReply `/send {oracle} <msg>` later"
        return f"✅ *Delivered to {oracle}*\n\n```\n{output}\n```"

    elif cmd == "/goals":
        # Read active goals from nexus vault
        goals_dir = os.path.join(PSI_DIR, "goals", "active")
        if os.path.isdir(goals_dir):
            goals = [f for f in os.listdir(goals_dir) if f.endswith(".md")]
            if goals:
                return f"*Active Goals:*\n" + "\n".join(f"• {g.replace('.md', '')}" for g in goals)
            else:
                return "*No active goals*"
        else:
            return "*Goals directory not found*"

    else:
        return f"Unknown command: {cmd}\nType /help for available commands"


def poll_updates():
    """Poll Telegram for new updates"""
    global OFFSET
    result = curl_api("getUpdates", {"offset": OFFSET, "timeout": 5, "allowed_updates": ["message"]})
    if not result or not result.get("ok"):
        return

    for update in result.get("result", []):
        OFFSET = update["update_id"] + 1

        if "message" not in update:
            continue

        msg = update["message"]
        from_id = msg.get("from", {}).get("id")

        if from_id != CHAT_ID:
            continue

        text = msg.get("text", "")
        msg_id = msg.get("message_id")

        if not text.startswith("/"):
            forward_to_nexus(text, from_id)
            continue

        print(f"Command: {text}")
        response = handle_command(text, from_id, msg_id)
        if response:
            send_message(response, reply_to=msg_id)


def forward_to_nexus(text, from_id):
    """Forward non-command messages to nexus inbox"""
    now = datetime.datetime.utcnow()
    filename = f"{now.strftime('%Y%m%d')}_{now.strftime('%H-%M')}_human_MSG-HUMAN-{now.strftime('%H%M')}.md"
    filepath = os.path.join(PSI_DIR, "inbox", filename)

    content = f"""---
msg_id: MSG-HUMAN-{now.strftime('%H%M')}
from: human
to: nexus
type: query
status: pending
sent: {now.isoformat()}Z
ack_by: "-"
result: "-"
reply_file: "-"
---

{text}
"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)

    send_message(f"📝 [nexus] Received: {text[:80]}")


def register_commands():
    """Register bot commands with Telegram"""
    commands = [
        {"command": "wake", "description": "Start oracle session (e.g., /wake emily)"},
        {"command": "sleep", "description": "Stop oracle session (e.g., /sleep emily)"},
        {"command": "status", "description": "Show fleet status"},
        {"command": "inbox", "description": "Check oracle inbox (e.g., /inbox emily)"},
        {"command": "send", "description": "Send message to oracle (e.g., /send emily hello)"},
        {"command": "goals", "description": "Show active goals"},
        {"command": "help", "description": "Show available commands"},
    ]
    result = curl_api("setMyCommands", {"commands": commands})
    if result and result.get("ok"):
        print("Bot commands registered!")
    else:
        print(f"Failed to register commands: {result}")


def main():
    print("nexus Oracle daemon starting...")
    print(f"Bot: @nexus_oracle_bot")
    print(f"Chat ID: {CHAT_ID}")
    print(f"Polling every {POLL_INTERVAL}s")

    register_commands()
    send_message("📡 [nexus] Daemon started — slash commands ready\n/wake | /sleep | /status | /inbox | /send | /goals | /help")

    print("Polling for updates...")
    while True:
        try:
            poll_updates()
        except KeyboardInterrupt:
            print("\nShutting down...")
            send_message("📡 [nexus] Daemon stopped")
            break
        except Exception as e:
            print(f"Poll error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()