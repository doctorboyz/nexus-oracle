# texty-oracle Code Snippets

## 1. Main Entry Points

### texty-daemon.py — Telegram Bot Daemon

**File**: `scripts/texty-daemon.py`

Central polling daemon. Uses `curl` for all Telegram API calls (avoids Python SSL issues on macOS):

```python
def curl_api(method, params=None):
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

Unicode psi directory resolver (handles both `"psi"` and `"ψ"`):

```python
def find_psi_dir():
    for entry in os.listdir(TEXTY_ROOT):
        full_path = os.path.join(TEXTY_ROOT, entry)
        if os.path.isdir(full_path) and entry in ("psi", "ψ"):
            return full_path
    for entry in os.listdir(TEXTY_ROOT):
        full_path = os.path.join(TEXTY_ROOT, entry)
        if os.path.isdir(full_path) and len(entry) <= 2 and not entry.startswith("."):
            return full_path
    return None
```

Busy-aware `/send` command:

```python
elif cmd == "/send":
    if len(args) < 2 or args[0].lower() not in ORACLES:
        return f"Usage: /send <oracle> <message>..."
    oracle = args[0].lower()
    msg = " ".join(args[1:])
    output = run_cmd(f"maw inbox send {oracle} \"{msg}\"")
    if "busy" in output.lower():
        return f"... {oracle} is busy -- try again when session ends..."
    return f"... Delivered to {oracle}..."
```

### dispatch.sh — Manual Dispatch to Telegram

**File**: `scripts/dispatch.sh`

Supports plain text and polls. Auto-incrementing dispatch IDs:

```bash
DISPATCH_DIR="$SCRIPT_DIR/../ψ/dispatch/$(date +%Y-%m)"
mkdir -p "$DISPATCH_DIR"
COUNT=$(ls "$DISPATCH_DIR" 2>/dev/null | wc -l | tr -d ' ')
DISPATCH_ID="DSP-$(date +%Y%m%d)-$(printf '%03d' $((COUNT + 1)))"
```

### notify-texty.sh — Cross-Oracle Notification

**File**: `scripts/notify-texty.sh`

Any oracle calls this with `<source> <event_type> <message>`. Dual-writes: inbox + dispatch log + Telegram.

Emoji-mapped event types:

```bash
case "$EVENT_TYPE" in
  escalation|error) EMOJI="🚨" ;;
  session-end) EMOJI="📋" ;;
  commit) EMOJI="📝" ;;
  *) EMOJI="ℹ️" ;;
esac
```

### session-summary-to-texty.sh — Stop Hook

**File**: `scripts/session-summary-to-texty.sh`

Captures tmux pane output, filters noise, extracts summary:

```bash
CAPTURED=$(tmux capture-pane -t "$PANE_TARGET" -p -S -80 2>/dev/null \
  | grep -v '^$' | grep -v '^[─═━]' | grep -v '⏵⏵' | grep -v '✻' | grep -v '❯' | tail -10)
```

---

## 2. MSG-ACK-RESULT Protocol (maw inbox plugin)

**File**: `~/.maw/plugins/inbox/impl.ts`

Frontmatter schema:

```typescript
export interface InboxFrontmatter {
  msg_id: string;
  from: string;
  to: string;
  type: "task" | "query" | "escalation" | "info" | "ack" | "result";
  status: "pending" | "acknowledged" | "completed";
  sent: string;
  ack_by: string;
  result: string;
  reply_file: string;
}
```

Oracle name to vault path resolution:

```typescript
const nameToRepo: Record<string, string> = {
  "emily": "emily-oracle",
  "pm": "pm-oracle",
  "god-port": "god-port-oracle",
  "texty": "texty-oracle",
  "broky": "broky-oracle",
  "metty": "metty-oracle",
  "skilly": "skilly-oracle",
};
```

Atomic file updates (tmp + rename):

```typescript
function updateMessageFile(msg: InboxMessage): void {
  const tmp = msg.path + ".tmp";
  writeFileSync(tmp, content, "utf-8");
  renameSync(tmp, msg.path);  // atomic on POSIX
}
```

---

## 3. Busy/Idle Detection

### isOracleIdle() in maw inbox plugin

**File**: `~/.maw/plugins/inbox/impl.ts`

Scans tmux pane for Claude Code's `❯` prompt and processing indicators:

```typescript
function isOracleIdle(target: string): boolean {
  try {
    const raw = execSync(`tmux capture-pane -t ${target} -p -S -50`, { encoding: "utf-8", timeout: 5000 });
    const lines = raw.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, "").split("\n").map(l => l.trimEnd());

    // Find last ❯ prompt
    let lastPromptIdx = -1;
    for (let i = lines.length - 1; i >= 0; i--) {
      if (/❯/.test(lines[i])) { lastPromptIdx = i; break; }
    }
    if (lastPromptIdx === -1) return false;

    // Check for processing indicators below prompt
    const afterPrompt = lines.slice(lastPromptIdx + 1).filter(l => l.trim().length > 0);
    const processingIndicators = /^[·✻⏺]|Julienning|Churned|Cogitated|Still thinking/i;
    if (afterPrompt.some(l => processingIndicators.test(l.trim()))) return false;

    // Check if prompt is empty (idle) vs has text (pending input)
    return /^❯\s*$/.test(lines[lastPromptIdx].trimStart());
  } catch {
    return true;
  }
}
```

### checkPaneIdle() in maw comm-send

**File**: `~/.maw-js/src/commands/shared/comm-send.ts`

Uses regex on last line to detect prompt state:

```typescript
export async function checkPaneIdle(target: string, host?: string): Promise<{ idle: boolean; lastInput: string }> {
  const content = await capture(target, 5, host);
  const clean = lastLine.replace(/\x1b\[[0-9;]*[mGKHFJA-Z]/g, "").replace(/\r/g, "");
  if (/[#$%>❯»]\s*$/.test(clean)) return { idle: true, lastInput: "" };
  const notIdleMatch = clean.match(/[#$%>❯»]\s+(\S.*)$/);
  if (notIdleMatch) return { idle: false, lastInput: notIdleMatch[1] };
  return { idle: true, lastInput: "" };
}
```

### StatusDetector in maw engine

**File**: `~/.maw-js/src/engine/status.ts`

Screen-hash based state machine. Transitions: `busy` → `ready` (stable 15s) → `idle` (agent exits) → `crashed` (agent exits unexpectedly).

---

## 4. Error Handling Patterns

### Graceful Telegram Failure (best-effort, non-blocking)

```bash
curl -s -X POST "${API_URL}/sendMessage" ... > /dev/null 2>&1 || echo "Warning: Telegram send failed"
```

### Command Timeout in Daemon

```python
def run_cmd(cmd):
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

### Poll Error Resilience

```python
while True:
    try:
        poll_updates()
    except KeyboardInterrupt:
        send_message("Daemon stopped")
        break
    except Exception as e:
        print(f"Poll error: {e}")
    time.sleep(POLL_INTERVAL)
```

### Frontmatter Parsing with Defaults (never crashes)

```typescript
const parsed: InboxFrontmatter = {
  msg_id: fm.msg_id || f.replace(/\.md$/, ""),
  from: fm.from || "unknown",
  to: fm.to || "unknown",
  type: (fm.type as InboxFrontmatter["type"]) || "info",
  status: (fm.status as InboxFrontmatter["status"]) || "pending",
  // ...
};
```

---

## 5. Credential Management

Credentials stored in `ψ/credentials/telegram.json` (gitignored):

```bash
BOT_TOKEN=$(python3 -c "import json; print(json.load(open('$CREDENTIALS_FILE')).get('bot_token', ''))" 2>/dev/null || echo "")
CHAT_ID=$(python3 -c "import json; print(json.load(open('$CREDENTIALS_FILE')).get('chat_id', ''))" 2>/dev/null || echo "")
if [[ -z "$BOT_TOKEN" || -z "$CHAT_ID" ]]; then
  echo "Error: bot_token or chat_id not configured"
  exit 1
fi
```

---

## 6. Oracle Pane Resolution (multi-pane routing)

**File**: `~/.maw-js/src/commands/shared/comm-send.ts`

```typescript
export async function resolveOraclePane(target: string): Promise<string> {
  if (/\.[0-9]+$/.test(target)) return target;  // already pane-specific
  const raw = await t.run("list-panes", "-t", target, "-F", "#{pane_index} #{pane_current_command}");
  for (const line of lines) {
    const idx = parseInt(line.slice(0, spaceIdx), 10);
    const cmd = line.slice(spaceIdx + 1);
    if (Number.isFinite(idx) && /claude|codex|node/i.test(cmd)) {
      agentIndexes.push(idx);
    }
  }
  if (agentIndexes.length === 0) return target;
  return `${target}.${Math.min(...agentIndexes)}`;
}
```

---

## 7. ACL Gate for Cross-Oracle Messaging

**File**: `~/.maw-js/src/commands/shared/comm-send.ts`

```typescript
if (result?.type === "peer" && !opts.approve && process.env.MAW_ACL_BYPASS !== "1") {
  const scopes = loadAllScopes();
  if (scopes.length > 0) {
    const decision = evaluateAclFromDisk(senderOracle, targetOracle);
    if (decision === "queue") {
      const record = savePending({ sender, target, message, query });
      console.log(`queued for approval ${record.id} ${senderOracle} -> ${targetOracle}`);
      return;
    }
  }
}
```

---

## 8. Team Fan-Out Routing

**File**: `~/.maw-js/src/commands/shared/comm-send.ts`

`maw hey team:<name> <msg>` fans out to all members:

```typescript
const origExit = process.exit;
for (const member of members) {
  let memberFailed = false;
  process.exit = ((code?: number) => { memberFailed = true; }) as never;
  try {
    await cmdSend(member, message, force);
    if (!memberFailed) delivered++;
    else failed++;
  } catch (e: any) { failed++; }
}
process.exit = origExit;
```

---

## 9. Destructive Command Safety Gates

**File**: `~/.maw-js/src/commands/plugins/tmux/impl.ts`

Three-gate `tmux send-keys` safety:

1. Destructive-command deny-list (blocks `rm`, `sudo`, etc.)
2. Claude-pane refusal (prevents injecting into live AI turns)
3. Fleet/view session kill protection

```typescript
const destCheck = checkDestructive(command);
if (destCheck.destructive && !opts.allowDestructive) { throw new Error(...); }
if (isClaudeLikePane(paneCurrentCommand) && !opts.force) { throw new Error(...); }
if (isFleetOrViewSession(session, fleetSessions) && !opts.force) { throw new Error(...); }
```