# nexus-oracle — Testing & Quality Patterns

## 1. Test Structure — No Tests Exist

**Zero test files.** No `tests/` directory, no `conftest.py`, no `pytest.ini`, no `requirements.txt`. The project has no automated test infrastructure.

The only test-related content found was a retrospective markdown file at `psi/memory/retrospectives/2026-04/29/10.56_consolidation-wake-test.md` — a session retrospective, not an automated test.

**Testing framework used**: None.

**Total source lines**: ~1,980 lines across 12 files (877 in `nexus-daemon.py` alone).

---

## 2. How the Daemon Is Tested — Manual Testing Only

The daemon is verified through entirely manual, operational means:

- **PM2 / launchd management**: `nexus-daemon-launcher.sh` (line 15) uses `exec "$PYTHON3" -u` with stdout/stderr redirected to log files
- **Manual Telegram commands**: Sending `/wake`, `/sleep`, `/status`, `/inbox`, `/send`, `/broadcast`, `/goals` through the Telegram bot
- **Log inspection**: `logs/nexus-daemon.log` and `logs/nexus-daemon.err`
- **Process liveness check**: `nexus-daemon.sh` sleeps 2 seconds then checks `kill -0 $DAEMON_PID` after launch
- **Operational tooling**: `pm/inject-hook.sh` injects Stop hooks into other oracle repos for session-end reports

---

## 3. Error Handling Patterns

### Python Daemon (`nexus-daemon.py`)

**13 try/except blocks** with the following patterns:

| Pattern | Locations | Behavior |
|---------|-----------|----------|
| Broad `except Exception` (silent swallow) | Lines 88, 115, 133, 173, 219, 707 | `continue` — no log, no alert, no retry |
| `except ValueError` | Lines 217, 274 | Returns `None` on `int()` conversion failure |
| `except subprocess.TimeoutExpired` | Line 556 | Returns `"Command timed out (15s)"` |
| `except OSError` (cross-device rename) | Line 317 | Falls back to `shutil.move` |
| Top-level poll loop | Lines 870-873 | Catches all exceptions, continues polling |

### Shell Scripts

| Script | Strict Mode | Key Pattern |
|--------|-------------|-------------|
| `dispatch.sh` | `set -euo pipefail` | Validates credentials, exits on missing |
| `nexus-daemon.sh` | `set -euo pipefail` | Tunnel URL wait loop with 20 retries |
| `notify-nexus.sh` | `set -uo pipefail` | `\|\| echo "Warning: ..."` graceful degradation |
| `inbox-watcher.sh` | No strict mode | PID file management, `\|\| true` on osascript |
| `outbox-write.sh` | `set -euo pipefail` | Validates required args, reads stdin |
| `session-summary.sh` | `set -uo pipefail` | `\|\| echo "Warning: ..."` on curl failures |

### Error Handling Gaps

- **No retry logic**: `curl_api()` makes a single attempt. Network blips cause silent message loss.
- **No dead letter queue**: Failed outbox files stay for retry but with no max retry count or alerting.
- **Shell injection risk**: `run_cmd()` uses `shell=True` with minimal sanitization (only `"` and `` ` `` escaped).
- **No structured logging**: All error reporting via `print()`. No log levels, no rotation, no timestamps on most messages.
- **Credentials loaded at module level**: Lines 56-68 — if `telegram.json` is malformed, the entire daemon crashes on import.

---

## 4. Logging Patterns

### Python Daemon

All logging is via `print()` statements (29 occurrences):
- **Startup banner** (lines 845-854): Config summary
- **Per-message log** (line 778): `[HH:MM:SS] msg from chat {chat_id}: {text[:50]}`
- **Outbox processing** (lines 300, 304, 345, 347): `[outbox]` prefix for success/failure/retry
- **API errors** (line 523): `API error ({method}): {e}`
- **Poll errors** (line 873): `Poll error: {e}`

**No `logging` module.** No rotation. No structured format.

### Dispatch Audit Trail

The most robust logging: `dispatch.sh` and `notify-nexus.sh` write markdown files to `psi/dispatch/YYYY-MM/` with YAML frontmatter. This is append-only and git-trackable.

---

## 5. Quality Patterns

### Input Validation
- `ALLOWED_SENDERS = {CHAT_ID, BOT_ID}` — two-layer auth gate (lines 768-772)
- `AUTHORIZED_CHATS` — union of private + all group channel IDs
- Loaded at startup, never refreshed (requires daemon restart)

### Cache TTL
- `ROUTING_CACHE_TTL = 300` (5 minutes) — routing table refresh
- `ORACLE_DIRS_CACHE_TTL = 300` (5 minutes) — oracle directory refresh
- Avoids re-reading fleet configs on every message

### Graceful Shutdown
- `signal.signal(SIGINT, shutdown)` and `signal.signal(SIGTERM, shutdown)`
- Sends "Daemon stopped" notification to Telegram before exiting
- Does NOT drain pending outbox messages or wait for in-flight API calls

### Unicode Safety
- `find_psi_dir()` checks both `ψ` and `psi` directory names (lines 37-46)

---

## 6. Test Coverage Assessment

### What exists: Zero.

### What should exist (ranked by risk):

**Critical (P0) — Security/safety risks:**
1. `route_by_intent()` routing logic — bugs route messages to wrong oracle
2. `ALLOWED_SENDERS`/`AUTHORIZED_CHATS` authorization — unauthorized access possible
3. `run_cmd()` shell injection — `shell=True` with minimal escaping

**High (P1) — Functional correctness:**
4. `process_outbox_file()` YAML frontmatter parsing — string splitting, not YAML parser
5. `deliver_to_oracle()` message delivery — auto-wake, fallback paths untested
6. `handle_command()` slash command parsing — argument validation, `@bot_name` stripping
7. `poll_updates()` message routing — the 3-tier CASE logic

**Medium (P2) — Robustness:**
8. Cache refresh logic — TTL expiry verification
9. Outbox archive logic — cross-device rename fallback
10. Shell script argument parsing — edge cases
11. `find_psi_dir()` unicode handling

**Low (P3) — Nice to have:**
12. `curl_api()` mock HTTP responses
13. `write_to_inbox()` direct fallback
14. Shell script credential loading

### Recommended Approach

- **Python**: `pytest` with `unittest.mock` for `nexus-daemon.py`
- **Shell**: `bats-core` for `dispatch.sh`, `msg-protocol.sh`, `outbox-write.sh`
- **Integration**: Dedicated test bot token and test chat
- **CI**: Add `pyproject.toml` with `test` target; parameterize `vault-paths.sh` paths