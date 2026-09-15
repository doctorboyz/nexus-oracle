# maw-js Codebase Analysis

> Extracted 2026-05-16 from `/Users/doctorboyz/Code/github.com/doctorboyz/maw-js`

---

## 1. CLI Entry Point & Command Dispatch (`src/cli.ts`)

The entire CLI is a single `main()` function with layered routing:

```
args → verbosity strip → auto-bootstrap plugins → scanCommands → routeComm? → routeTools? → plugin match? → plugin registry? → fuzzy/oracle fallback
```

Key flow:

1. **`applyInstancePreset()`** runs first (before any imports that evaluate `MAW_HOME`).
2. **Verbosity flags** (`--quiet`, `-q`, `--silent`, `-s`) are stripped from args before command detection.
3. **`runBootstrap()`** auto-symlinks bundled plugins into `~/.maw/plugins/` if empty.
4. **`scanCommands()`** loads user plugins from `~/.maw/plugins/`.
5. Core routes (`hey`, `plugins`, `serve`, etc.) are tried first via `routeComm` and `routeTools`.
6. If no core route matches, **plugin command registry** (`matchCommand`) is consulted.
7. If no plugin command matches, the **plugin dispatcher** (`resolvePluginMatch`) tries two-pass matching (exact then prefix).
8. If nothing matches, a **fuzzy suggester** kicks in. If even that fails and the arg looks like an oracle name, it falls back to `cmdSend` / `cmdPeek` (the original `maw <agent> <msg>` shorthand).

Error handling uses `UserError` (suppresses stack trace) and `AmbiguousMatchError` (renders actionable disambiguation). Unknown commands get fuzzy suggestions against known commands with distance <= 2.

---

## 2. The `hey` Command (`routeComm` + `comm-send.ts`)

`maw hey <target> <message>` is the core messaging transport. The full pipeline:

### Target Resolution

- **Bare-name rejection** (#759 Phase 2): Targets without `:` or `/` are rejected with a formatted error suggesting canonical forms (`local:<agent>`, `<node>:<session>`, `<node>:<session>:<window>`).
- **Team fan-out** (`team:<name>`): Resolves team members via `getOracleMembers`, then calls `cmdSend` for each. Temporarily overrides `process.exit` so one failure doesn't abort the fan-out. Reports `delivered`/`failed` counts.
- **Plugin routing** (`plugin:<name>`): Discovers the plugin, invokes it with `{ source: "peer", args: { message, from } }`.

### Auto-Wake (#736 / #791)

Before resolution, `shouldAutoWake()` decides whether to silently wake a fleet-known target that isn't running:

- **Local scope**: If the target is fleet-known and not live, `cmdWake` is called, then sessions are refreshed.
- **Cross-node**: Sends `POST /api/wake` to the peer before `/api/send`. Wake errors are surfaced (not silently swallowed).

### ACL Gate (#842)

Cross-node sends go through `evaluateAclFromDisk`:
- If any scopes are defined and the verdict is `"queue"`, the message is persisted to `<CONFIG_DIR>/pending/` for later `maw inbox approve <id>`.
- `--approve` bypasses the gate for this send. `--approve --trust` also persists the sender-target pair to the trust store.
- `MAW_ACL_BYPASS=1` env var bypasses the gate (used by re-issued sends after approval).
- Default-allow when no scopes exist (preserves existing setups).

### Consent Gate (#644)

Opt-in via `MAW_CONSENT=1`. First-time cross-node sends require PIN approval.

### Local Send (tmux)

1. `resolveOraclePane()` finds the correct pane in multi-pane windows.
2. `getPaneCommand()` checks if the pane is running an agent (`claude|codex|node`). If not, exits with a "no active Claude session" error and a hint to `maw wake`.
3. `checkPaneIdle()` inspects the last visible line for prompt markers (`$`, `%`, `>`, `>>`, `#`). If the user is mid-typing, it retries after 500ms, then aborts unless `--force` is used.
4. `sendKeys()` sends the message (see Long Messages below).
5. After delivery, captures the last line of the target pane as a delivery receipt.

### Remote Send (federation HTTP)

Posts to `<peerUrl>/api/send` with `{ target, text, from: "auto" }`. On failure, surfaces the remote error explicitly.

### Fallback: Peer Discovery

If `resolveTarget()` returns null (no local session, no config-mapped peer), `findPeerForTarget()` does a network scan. Never falls through to "not found" if the real problem was a network failure.

---

## 3. `resolveTarget()` (`core/routing.ts`)

Pure synchronous function. Four-step resolution:

| Step | Strategy | Returns |
|------|----------|---------|
| 1 | `findWindow()` on local writable sessions | `{ type: "local" }` |
| 2 | Fleet config + `findWindow()` | `{ type: "local" }` |
| 3 | `node:agent` syntax (`phaith:01-hojo`) | `{ type: "peer" }` or `{ type: "self-node" }` |
| 3a | **OracleManifest** lookup (Sub-PR 3 of #841) | `{ type: "peer" }` if manifest has a remote node + config has the peer URL |
| 4 | `config.agents` map | `{ type: "peer" }` or `{ type: "error" }` |

The manifest step (3a) is additive: local and `node:` syntax always win. Manifest misses or self-node entries fall through to the agents map unchanged. Failures in `loadManifestCached()` are swallowed so filesystem races never brick the hot path.

The manifest is cached at 30s TTL. Cold-start cost: one config read + one fleet dir scan + one oracles.json read, all sync.

---

## 4. `resolveOraclePane()` (`comm-send.ts`)

When an oracle window has multiple panes (e.g., team-agents spawned as splits), `tmux send-keys -t session:window` would land in the **last-active pane**, which might be a teammate, not the oracle.

Strategy:
1. If the target already has a `.N` pane suffix, pass through (caller knows best).
2. Run `tmux list-panes -t <target>` to get all pane indices + their running commands.
3. Filter for panes running `claude|codex|node`.
4. Return `target.<lowest_agent_pane_index>` (pane 0 is conventionally the oracle's main pane).
5. On any error or no agent panes found, return the target unchanged.

This prevents the "message lands in wrong pane" bug when team-agents are split beside the oracle.

---

## 5. `checkPaneIdle()` — Idle Guard (#405)

Prevents `send-keys` from interrupting a user who is mid-typing:

```typescript
async function checkPaneIdle(target, host?): Promise<{ idle: boolean; lastInput: string }>
```

1. Captures the last 5 lines of the pane.
2. Strips ANSI escape codes.
3. Checks if the last non-empty line ends with a prompt marker (`$`, `%`, `>`, `>>`, `#`) followed by optional whitespace -> idle.
4. Checks if the last line matches a prompt marker followed by non-whitespace text -> not idle, returns the user's partial input.
5. If no prompt is visible (e.g., command running, agent output scrolling), conservatively returns idle=true.

In `cmdSend`, if the first check returns not-idle, it retries after 500ms before giving up. The `--force` flag bypasses the check entirely.

---

## 6. Long Message Handling (`tmux-class.ts`)

The `sendText()` method implements a two-path strategy:

```typescript
async sendText(target: string, text: string): Promise<void> {
  if (text.includes("\n") || text.length > 500) {
    // Buffer method: load-buffer + paste-buffer
    await this.loadBuffer(text);
    await this.pasteBuffer(target);
    await sleep(1500);
    await this.sendKeys(target, "Enter");   // submit
    await sleep(700);
    await this.sendKeys(target, "Enter");   // fallback 1
    await sleep(1200);
    await this.sendKeys(target, "Enter");   // fallback 2
  } else {
    // Literal send: -l flag prevents tmux from interpreting |, etc.
    await this.sendKeysLiteral(target, text);
    await sleep(1500);
    await this.sendKeys(target, "Enter");   // submit
    await sleep(700);
    await this.sendKeys(target, "Enter");   // fallback 1
    await sleep(1200);
    await this.sendKeys(target, "Enter");   // fallback 2
  }
}
```

The **triple-Enter pattern** (submit + 2 fallbacks) is crucial: tmux's paste-buffer delivery is asynchronous, and the target program (claude/codex) may not have processed the input by the first Enter. The staggered timing (1.5s, 0.7s, 1.2s) gives the target time to process each keystroke.

`loadBuffer` escapes single quotes in the text and pipes it via `printf '%s' | tmux load-buffer -`.

`sendKeysLiteral` uses tmux's `-l` flag to send text literally, preventing special characters like `|`, `&`, `;` from being interpreted by tmux.

---

## 7. `wake` Command (`wake-cmd.ts` + `wake-resolve.ts` + `wake-session.ts`)

`maw wake <oracle>` creates or attaches to a tmux session for an oracle:

1. **Resolve oracle** to a repo path (via `resolveOracle` which uses ghq + fleet config).
2. **Detect existing session** via `detectSession` (checks tmux sessions for matching names).
3. **`shouldAutoWake()`** determines if creation is needed (idempotent: already-live => no-op).
4. **If no session**: `tmux.newSession(name, { window, cwd })`, set env vars, send startup command via `sendText`.
5. **If session exists**: Re-attach, respawn any dead windows (shells that fell back to `zsh`/`bash` with no children), restore tab order from saved snapshots.
6. **Worktree support**: `--task` / `--wt` flags create git worktrees and open windows for them.
7. **Auto-register**: After creating a session, the oracle is added to `config.agents` for federation routing.

The `ensureSessionRunning` helper checks each window's pane command. If it's a bare shell (`zsh`, `bash`, `sh`, or empty) and `isPaneIdle` (no child processes), it retries the startup command.

---

## 8. `peek` Command (`comm-peek.ts`)

`maw peek [target]` captures tmux pane content:

- No target: shows one-line summary per agent window (active dot + window name + last line).
- With target: resolves via `findWindow`, captures the full pane content.
- **Never auto-wakes** (peek is read-only by design).
- Supports **cross-node peek**: `maw peek <node>:<agent>` fetches from the peer's `/api/capture` endpoint.

---

## 9. `findWindow()` — Fuzzy Session/Window Matching (`core/runtime/find-window.ts`)

Three-pass matching strategy:

1. **Exact match**: session name or window name exactly matches query (case-insensitive).
2. **Oracle-name match**: strips `\d+-` prefix from session names (e.g., `08-mawjs` matches `mawjs`).
3. **Substring match**: query is a substring of session/window name (skipped in strict mode).

For `session:window` syntax (e.g., `08-mawjs:1`):
- Uses **strict** mode on the session part to prevent `white:mawjs` matching `105-whitekeeper` via substring.
- Window part uses substring match on window names.

**Ambiguity guard**: If multiple candidates match in any pass, throws `AmbiguousMatchError` with the candidates listed. This is caught at the top level and rendered as actionable CLI output.

---

## 10. Plugin Architecture

### Plugin Manifest (`plugin/types.ts`)

```typescript
interface PluginManifest {
  name: string;           // /^[a-z0-9-]+$/
  version: string;        // semver
  sdk: string;            // semver range (^1.0.0)
  weight?: number;        // execution order (default 50)
  tier?: "core" | "standard" | "extra";
  entry?: string;         // TS/JS entry (full access, Bun only)
  wasm?: string;          // WASM entry (sandboxed)
  cli?: { command, aliases?, help?, flags? };
  api?: { path, methods };
  hooks?: { gate?, filter?, on?, late? };
  cron?: { schedule, handler? };
  transport?: { peer?: boolean };
  artifact?: { path, sha256 };
  module?: { exports, path };
}
```

### Plugin Discovery (`plugin/registry.ts`)

1. Scans `~/.maw/plugins/` for directories with `plugin.json`.
2. **Phase A gates**:
   - **Semver gate**: `manifest.sdk` must satisfy the runtime SDK version.
   - **Artifact hash**: If `sha256` is set on a real install, the on-disk bundle must match. Symlink installs (dev mode) skip hash verification.
   - **Legacy manifests** (no `artifact` field): allowed with a one-shot warning.
3. **Weight sorting**: Plugins sorted by `weight` (lower = first, default 50), like Drupal module weights.
4. **Profile filtering**: Active profile can narrow the loaded plugin set. Untiered plugins default to `"core"` tier.
5. **Discovery cache**: Result is memoized per process. `resetDiscoverCache()` clears it after installs.

### Plugin Dispatch (`cli/dispatch-match.ts`)

Two-pass matching (exact before prefix):
- **Pass 1**: Collect all exact `cmdName === name` matches.
- **Pass 2** (if pass 1 empty): Collect all `cmdName startsWith (name + " ")` matches.
- Single survivor = match. Multiple survivors = ambiguous error.

### Plugin Invocation (`plugin/registry-invoke.ts`)

**TS plugins**: Imported dynamically, `default` or `handler` export called with `InvokeContext`. A `writer` function is injected based on `ctx.source` (CLI = `process.stdout`, API/peer = `undefined` for log capture). No sandboxing; full Bun access.

**WASM plugins**: Compiled, instantiated with a host-provided import object (`buildImportObject`), and called via `handle(ptr, len)` protocol. Context is JSON-encoded into shared memory. 5-second hard timeout. 16MB memory limit (256 pages).

**Universal flags**: Every plugin gets `-v`/`--version` and `-h`/`--help` for free, showing metadata, surfaces, and directory.

### Command Registry (`cli/command-registry.ts`)

User commands live in `~/.maw/plugins/commands/` as `.ts`, `.js`, or `.wasm` files:

```typescript
export const command = { name: "hello", description: "Say hello" };
export default async function(args, flags) { ... }
```

Loaded at boot via `scanCommands()`. Supports subcommands (e.g., `"fleet doctor"`) and longest-prefix matching.

---

## 11. Error Handling Patterns

### `UserError` (`core/util/user-error.ts`)

A custom error class for expected failures. At the top level, `UserError` triggers `process.exit(1)` without Bun's default stack trace. Used for invalid input, missing targets, ambiguous matches, etc.

### `AmbiguousMatchError` (`core/runtime/find-window.ts`)

Extends `Error` with `query` and `candidates` fields. Caught at the top level and rendered with `renderAmbiguousMatch()` for actionable disambiguation.

### Error messages consistently use:
- Red `\x1b[31m` for error markers (`error`, `X`)
- Cyan `\x1b[36m` for commands and suggestions
- Yellow `\x1b[33m` for hints
- Dim `\x1b[90m` for secondary info
- Every error includes a `hint:` line suggesting how to fix it.

### Graceful degradation:
- Plugin load failures: logged with `console.error`, skipped (not fatal).
- Fleet/wake best-effort: `try/catch` around auto-wake in `cmdSend`, falls through to existing error path.
- ACL evaluation errors: logged as warnings, delivery continues.
- `tryRun()` on the `Tmux` class: swallows errors for best-effort cleanup ops.
- `listSessions()`: returns `[]` if no tmux server is running (not an error).

---

## 12. Interesting Patterns & Idioms

### `hostExec()` — Local/SSH Transport Abstraction

```typescript
async function hostExec(cmd: string, host?: string): Promise<string> {
  const local = host === "local" || host === "localhost" || IS_LOCAL;
  const args = local ? ["bash", "-c", cmd] : ["ssh", host, cmd];
  // ... spawn, check exit code, throw HostExecError on failure
}
```

Every tmux operation goes through `hostExec`, making the entire CLI work transparently over SSH for remote oracle hosts.

### `Tmux` Class — Type-Safe tmux Wrapper

All tmux subcommands are typed methods on the `Tmux` class. Arguments are built as arrays and passed through `q()` (shell-quoting helper). The class holds an optional SSH host and socket path.

### `tmux.newWindow` — Trailing Colon Trick

```typescript
async newWindow(session, name, opts) {
  const args = ["-t", `${session}:`, "-n", name];  // trailing colon!
  // Without trailing colon, tmux interprets `-t session` as `-t session:<current_window>`
  // and tries to create AT that index -> "index 1 in use" error.
}
```

### `tmuxCmd()` + `resolveSocket()`

The `resolveSocket()` function locates the tmux socket by checking `TMUX`, `MAW_TMUX_SOCKET`, and fallback paths, enabling multi-instance tmux operation.

### Session Environment

`setSessionEnv()` in wake-resolve sets environment variables in the tmux session (like `MAW_SESSION`, oracle name, etc.) so that nested `maw` calls know their context.

### Fan-Out with `process.exit` Override

In team fan-out (`cmdSend` with `team:` prefix), `process.exit` is temporarily replaced:

```typescript
const origExit = process.exit;
process.exit = ((code?: number) => { memberFailed = true; }) as never;
// ... send to each member
process.exit = origExit;
```

This allows iterating through all team members even if one fails.

### `shouldAutoWake()` — Decision Matrix as Pure Function

All wake/no-wake decisions are centralized in a single pure function with explicit site discrimination (`"peek"`, `"hey"`, `"wake-cmd"`, etc.). Returns `{ wake: boolean, reason: string }` so callers can log/assert WHY the decision was made. No I/O, no module dependencies.

### Two-Phase Plugin Bootstrap

On every CLI invocation, `runBootstrap()` auto-symlinks bundled plugins from the source tree into `~/.maw/plugins/`. Then `scanCommands()` loads them. This means new plugins appear without manual install steps.

### Triple-Enter Pattern for Reliability

Both the short-message (`sendKeysLiteral`) and long-message (`loadBuffer` + `pasteBuffer`) paths use three staggered Enter keypresses (1500ms, 700ms, 1200ms). This handles the case where the target program hasn't finished processing the input by the first Enter.

### Fuzzy Command Suggestion

Unknown commands get fuzzy-matched against known commands (distance <= 2). If no close match is found and the arg looks like an oracle name (`[a-z0-9][a-z0-9:_-]*`), it checks tmux sessions before giving up, preserving the `maw <agent> <msg>` shorthand.

### Instance Preset (`--as <name>`)

`applyInstancePreset()` runs before any other side effects. It sets `MAW_HOME` based on the `--as` flag, enabling multi-instance maw operation where different named instances use different config/state directories.