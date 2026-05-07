# texty-oracle Testing & Quality Patterns

## 1. Test Structure

**There are zero automated tests in this repository.** No pytest, no shellcheck, no Makefile test targets, no CI/CD pipeline. Verification is manual only (e.g., `maw inbox send texty 'test dispatch'`).

## 2. Error Handling Patterns

### Bash `set` Flags (Inconsistent)

| Script | `set` Flags | Assessment |
|--------|------------|------------|
| `dispatch.sh` | `-euo pipefail` | Best — exits on error, undefined var, pipe failure |
| `query.sh` | `-euo pipefail` | Best |
| `notify-texty.sh` | `-uo pipefail` | Missing `-e` — will NOT exit on command failure |
| `session-summary-to-texty.sh` | `-uo pipefail` | Missing `-e` — will NOT exit on command failure |
| `texty-daemon-launcher.sh` | None | No safety flags |

The `-e` flag is notably absent from two scripts, meaning they silently continue after command failures.

### Python Error Handling (texty-daemon.py)

- **`curl_api()`**: Broad `except Exception`, returns `None`. Callers check for `None` or `result.get("ok")`.
- **`run_cmd()`**: Catches `subprocess.TimeoutExpired` (15s), truncates output to 4000 chars (Telegram limit). Falls back to stderr when stdout is empty — can leak internal error messages.
- **Main loop**: Catches `KeyboardInterrupt` for graceful shutdown, broad `Exception` continues polling. No backoff on repeated failures.
- **No retry logic**: A single network hiccup means that Telegram update is lost forever.
- **Missing `try/except` for credential loading**: If `telegram.json` is missing or malformed, the daemon crashes at startup.

## 3. Telegram API Failure Modes

The daemon log shows repeated timeout failures:

```
API error (getUpdates): Command 'curl ... getUpdates ...' timed out after 30 seconds
```

Key issues:
- **No exponential backoff** on failures
- **No offset advancement on failure** — same update ID is retried indefinitely
- **No partial processing tracking** — which updates have been processed is unclear

The bash scripts (`dispatch.sh`, `notify-texty.sh`) use `curl -s` and redirect to `/dev/null`. No HTTP status code checking — 401, 429, and 500 are treated identically to success.

## 4. Busy/Idle Detection Reliability

The daemon's busy detection (line 154):

```python
if "busy" in output.lower():
    return f"... {oracle} is busy ..."
```

**Fragile heuristics:**
- Relies on `maw inbox send` output containing the literal word "busy"
- Substring matching — any message containing "busy" triggers false positive
- No timeout case — if `maw` hangs beyond 15s, returns "Command timed out" which doesn't contain "busy", so user gets false "Delivered"
- `shell=True` in `run_cmd()` with user-influenced input (`oracle` name) — command injection risk if `ORACLES` validation is relaxed

## 5. Credential Security

**Good:**
- `ψ/credentials/telegram.json` is gitignored
- CLAUDE.md Golden Rules explicitly state "Never store credentials in git"

**Problems:**
- **Bot token leaked in plaintext** in daemon log files (visible in error output)
- **`chat_id` type mismatch**: JSON stores as string, Python casts to `int` — crashes on non-numeric values
- **No file permission check**: No script verifies `chmod 600` on credentials
- **No env var fallback**: Only file-on-disk approach, harder for containerized deployments

## 6. Logging

- **Dispatch logs**: Structured YAML frontmatter, append-only, monthly partitioning — strongest quality mechanism
- **Daemon logs**: `logs/texty-daemon.log` (stdout) and `logs/texty-daemon.err` (stderr), gitignored
- **No structured logging**: All `print()` statements, no `logging` module usage, no log levels
- **tmux capture**: Creative approach to session context, but filtering relies on hardcoded Unicode characters that could change with Claude Code updates

## 7. Session-End Hook Failure Modes

| Failure | Handling | Verdict |
|---------|----------|---------|
| No oracle name | `exit 1` | Good |
| Psi dir not found | `exit 1` | Good |
| Credentials missing | `exit 1` | Good |
| tmux not running | Falls through, sends generic message | Acceptable |
| Telegram send fails | `|| echo "Warning"` — dispatch still records "forwarded" | **Weak** — audit trail becomes inaccurate |
| `python3` unavailable | `2>/dev/null || echo ""` — hits `exit 1` on empty vars | Safe (checks happen before writes) |

**Critical gap**: When Telegram `curl` fails, the dispatch log still records `status: forwarded` and `result: awaiting`. No retry, no status update, no alternate channel notification.

## 8. Summary of Issues

**Critical:**
1. Zero automated tests
2. Bot token leaked in daemon logs
3. `chat_id` type mismatch (string vs int)
4. Missing `set -e` in two bash scripts
5. Telegram send failures recorded as "forwarded"

**Moderate:**
6. No retry/backoff for API failures
7. No offset advancement on poll failure
8. Fragile busy detection (substring match)
9. `shell=True` with user input
10. No credential file permission enforcement
11. All logging via `print()` instead of `logging`

**Well-designed:**
12. Dispatch log audit trail (structured, append-only, monthly)
13. Credential gitignore properly configured
14. Daemon main loop continues on exceptions
15. tmux absence handled gracefully
16. Unicode psi directory discovery (creative but fragile)