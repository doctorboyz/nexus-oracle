# maw-js Architecture

> Multi-Agent Workflow -- wake agents, talk across machines, see the mesh.

maw-js is a CLI + API server for orchestrating multiple AI agents (Claude Code, Codex) across tmux sessions and networked machines, providing wake/sleep/hey/peek/fleet commands, a real-time WebSocket dashboard, cross-node federation with HMAC auth, and a plugin system that extends the event pipeline.

---

## Directory Structure & Philosophy

```
maw-js/
├── src/
│   ├── cli.ts                  # Entry point: arg parsing, routing, plugin bootstrap
│   ├── cli/                    # CLI infrastructure: arg parsing, command registry, usage
│   ├── commands/
│   │   ├── shared/             # Core command implementations (wake, send, fleet, etc.)
│   │   └── plugins/            # Named plugin-backed commands (inbox, oracle, scope, trust, etc.)
│   ├── core/
│   │   ├── transport/          # tmux, SSH, curl, transport abstraction
│   │   ├── runtime/            # SDK, hooks, triggers, pane finding
│   │   ├── fleet/              # Oracle registry, snapshots, tab order, audit
│   │   ├── matcher/            # Target resolution (fuzzy matching, normalize)
│   │   ├── server.ts           # Bun.serve HTTP+WS entry point
│   │   └── types.ts            # MawEngine, WSData, Handler
│   ├── engine/                 # MawEngine class: WS lifecycle, intervals, capture, crash detection
│   ├── api/                    # Elysia HTTP API (25+ route groups)
│   ├── config/                 # Config loading, validation, defaults
│   ├── lib/                    # Shared libraries: auth, feed, peers, trust-store, schemas
│   ├── plugin/                 # Plugin system: manifest, registry, invoke, tiers
│   ├── plugins/                # Plugin runtime: PluginSystem (4-phase pipeline), loader, watcher
│   ├── transports/             # Transport implementations: tmux, HTTP, hub, nanoclaw, LoRa
│   ├── views/                  # Hono views: federation lens, topology, info, timemachine
│   ├── sdk/                    # Public SDK surface (what plugins can import)
│   ├── bridges/                # External bridges (nanoclaw)
│   └── wasm/                   # WASM SDK + examples (AssemblyScript)
├── packages/
│   └── sdk/                    # Published @maw-js/sdk package
├── test/                       # 94+ test files
├── scripts/                    # Build, deploy, calver, demo scripts
├── docker/                     # Federation testing harness
├── ui/                         # Frontend source (maw-ui integration)
└── docs/                       # Federation, bud, process, plugin docs
```

Philosophy: **feature-by-command** organization. Each CLI verb (`wake`, `hey`, `peek`, `fleet`, `oracle`, etc.) has its implementation in `commands/shared/` or `commands/plugins/`. Cross-cutting concerns (config, transport, fleet) live in `core/` or `lib/`. The plugin system is deeply integrated -- even "core" commands like `inbox` and `oracle` are plugin packages.

---

## Entry Points

### 1. CLI (`src/cli.ts`)

The primary entry point. `maw <command> [args]` routes through:

1. **Verbosity stripping** -- `--quiet`/`--silent` flags removed early
2. **Core routes** -- `hey` (routeComm), then `plugins`/`plugin`/`agents`/`serve` etc. (routeTools)
3. **Plugin commands** -- `matchCommand()` against the command registry
4. **Plugin dispatcher** -- `discoverPackages()` + `resolvePluginMatch()` for installed plugins
5. **Fuzzy fallback** -- If nothing matches, fuzzy-suggest known commands or resolve as oracle name shorthand (`maw <agent>` = `maw peek <agent>`, `maw <agent> <msg>` = `maw hey`)

### 2. API Server (`src/core/server.ts`)

`maw serve` starts a Bun HTTP + WebSocket server:

- **Elysia** serves all `/api/*` routes (25+ route groups)
- **Hono** serves views and static files (the maw-ui frontend)
- **WebSocket** at `/ws` (engine events) and `/ws/pty` (terminal streaming)
- Default port **3456**, configurable via `MAW_PORT` or config
- Binds to localhost unless federation is active (security heuristic)
- Optional TLS on port+1 if cert/key configured
- Plugin system initialized at startup with hot-reload for user plugins

### 3. SDK (`src/sdk/index.ts`)

Published as `@maw-js/sdk`. Exposes: config, tmux, SSH, transport router, fleet operations, artifacts, plugin system, oracle management, and `definePlugin()`. This is the **contract boundary** -- plugins import from here.

---

## Core Abstractions & Relationships

### MawEngine (`src/engine/`)

The central runtime class. Manages:

- **WebSocket clients** -- Set of connected browser/dashboard clients
- **Interval loops** -- capture (50ms), sessions (5s), preview (2s), status (3s), teams (3s), peer fetch (10s), crash check (30s)
- **Transport router** -- routes incoming remote messages to local tmux panes
- **Feed buffer** -- in-memory ring buffer of FeedEvents, broadcast to all WS clients
- **Crash detection** -- auto-restarts crashed agents if `config.autoRestart`

### Transport Layer (`src/core/transport/` + `src/transports/`)

Abstract `Transport` interface with `TransportRouter` for failover:

| Transport | Priority | Mechanism | Scope |
|-----------|----------|-----------|-------|
| **tmux** | 1 (fastest) | `tmux send-keys`, `capture-pane` | Local machine |
| **Hub** | 2 | WebSocket to workspace hub | Remote workspace |
| **HTTP** | 3 (fallback) | `curl` POST to peer `/api/send` | Federation peers |
| **NanoClaw** | 4 | External chat bridge (Telegram, Discord) | Chat channels |
| **LoRa** | 5 (future) | Hardware radio | Stub, always `canReach() = false` |

`TransportRouter.send()` tries each transport in priority order; first success wins, retryable errors fall through.

### FeedEvent System (`src/lib/feed.ts`)

The event backbone. All oracle activity emits `FeedEvent` objects:

```
TIMESTAMP | ORACLE | HOST | EVENT | PROJECT | SESSION_ID » MESSAGE
```

Event types: `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `SubagentStart/Stop`, `SessionStart/End`, `MessageSend/Deliver/Fail`, `Notification`, `Stop`, plus plugin lifecycle events.

Feed flows:
1. CLI commands emit via `emitFeed()` and `logMessage()`
2. Engine broadcasts to all WebSocket clients
3. Plugin system receives events through `feedListeners`
4. Transports publish to remote peers

### Plugin System (`src/plugins/`)

**4-phase pipeline** (inspired by Nat's Arduino MQTT-Connector):

1. **GATE** -- Return `false` to cancel event propagation
2. **FILTER** -- Transform event before handlers see it
3. **HANDLE** -- React to event (async allowed)
4. **LATE** -- Guaranteed cleanup, always runs

Plugin types:
- **TS/JS plugins** -- Full Node access, hot-reloadable from `~/.maw/plugins/`
- **WASM plugins** -- Sandboxed, WASM SDK provides host function calls
- **Builtin plugins** -- Ship with maw-js (`~/.maw/plugins/builtin/`)

Plugin manifest (`plugin.json`) declares: name, version, entry/wasm path, CLI commands, API routes, event hooks, cron schedules, capabilities, and tier (core/standard/extra).

### Fleet & Oracle Registry (`src/core/fleet/`)

The fleet is a collection of tmux sessions, each running an AI agent. Key concepts:

- **Fleet config** (`fleet/*.json` in `~/.maw/`) -- declarative session definitions with window names, repos, worktrees
- **Oracle Registry** -- scans ghq root for repos with psi/ directories, caches to `~/.config/maw/oracles.json`
- **Oracle Manifest** (`OracleManifestEntry`) -- per-oracle metadata loaded from `psi/oracle.json` or fleet config
- **Worktrees** -- git worktree scanning for multi-branch agent windows
- **Snapshots** -- point-in-time fleet state captures
- **Tab order** -- persist/restore tmux window ordering across sessions

### Target Resolution (`src/core/matcher/resolve-target.ts`)

`resolveTarget(query, config, sessions)` is the core routing function. Returns:

- `{ type: "local", target }` -- found in local tmux sessions
- `{ type: "self-node", target }` -- matches this node in config.agents
- `{ type: "peer", target, node, peerUrl }` -- matches a remote peer
- `{ type: "error", detail, hint }` -- no match found

Canonical form: `<node>:<session>:<window>` (e.g., `white:neo:3`). Bare names are rejected (Phase 2 of #759).

---

## Inter-Session Communication

### Local: tmux send-keys

The primary local mechanism. `cmdSend()` resolves a target to a tmux pane, checks idle state, and sends text via `tmux send-keys`. Includes pane-locking (`withPaneLock`) to prevent split-pane routing errors.

### Remote: HTTP Federation

Cross-node messaging uses `curlFetch()` to POST to a peer's `/api/send` endpoint. Authentication via HMAC-SHA256 signing with `federationToken`. From-signing (`<oracle>:<node>` identity) is verified on the receiving end.

### Vault-Based: MSG-ACK-RESULT Protocol

The `inbox` plugin implements file-based inter-oracle messaging:

1. **MSG** -- sender writes `{date}_{time}_{sender}_{msg_id}.md` to target's `psi/inbox/`
2. **ACK** -- receiver updates frontmatter `status: acknowledged` + writes `ack_{msg_id}_{date}.md` to own outbox
3. **RESULT** -- receiver updates frontmatter `status: completed` + writes `result_{msg_id}_{date}.md` to outbox

Messages have YAML frontmatter with: `msg_id`, `from`, `to`, `type` (task/query/escalation/info/ack/result), `status` (pending/acknowledged/completed).

### Team Fan-Out

`maw hey team:<team-name> <msg>` fans out a message to all oracle members in a team (excluding sender). Uses `OracleManifest` for member resolution.

### ACL Gate (Cross-Node)

Cross-node `maw hey` messages are optionally queued for operator approval:
- `maw scope create` defines access control lists
- `maw inbox approve <id>` releases queued messages
- `--approve` flag bypasses the gate for a single send
- `--trust` flag persists the sender-target pair for future auto-approval

### Consent Gate (Opt-In)

When `MAW_CONSENT=1`, first-time peer connections require PIN-based mutual consent via `maw pair generate` / `maw pair <url> <code>`.

---

## The Plugin System in Detail

### Plugin Lifecycle

1. **Bootstrap** (`runBootstrap`) -- at CLI start, symlinks bundled plugins + installs from `pluginSources`
2. **Scan** (`scanCommands`) -- discovers `plugin.json` files in `~/.maw/plugins/`
3. **Load** (`loadPlugins`) -- loads TS/JS entry files or WASM modules
4. **Register** (`PluginSystem.load()`) -- hooks into the 4-phase pipeline
5. **Hot-reload** (`watchUserPlugins`) -- watches `~/.maw/plugins/` for changes

### Plugin Types & Tiers

| Tier | Meaning | Install |
|------|---------|---------|
| `core` | Essential, always enabled | Ships with maw-js |
| `standard` | Recommended, opt-out | Default install |
| `extra` | Optional, opt-in | Manual install |

### Plugin Surfaces

A plugin can declare:

- **CLI commands** -- `cli.command` + `cli.aliases` register as `maw <name>` verbs
- **API routes** -- `api.path` + `api.methods` auto-mount on the Elysia router
- **Event hooks** -- `hooks.gate/filter/on/late` plug into the 4-phase pipeline
- **Cron schedules** -- `cron.schedule` + `cron.handler` for periodic tasks
- **Module exports** -- `module.exports` + `module.path` for inter-plugin imports
- **Transport** -- `transport.peer` enables `maw hey plugin:<name>` messaging

### Command Plugins (Bundled)

17 built-in command plugins in `src/commands/plugins/`:

| Plugin | Purpose |
|--------|---------|
| `doctor` | Fleet health diagnostics |
| `federation` | Peer sync + config management |
| `fleet` | Fleet init, consolidate, health |
| `inbox` | MSG-ACK-RESULT vault messaging |
| `oracle` | Oracle scan, list, register, prune, nickname |
| `pair` | Peer pairing (6-char ephemeral codes) |
| `plugin` | Plugin lifecycle: init, build, install, search |
| `profile` | Oracle profile management |
| `run` | Generic command runner |
| `scope` | ACL scope management |
| `send` | Legacy send command (now redirects to `hey`) |
| `session` | Session management |
| `shellenv` | Shell environment setup (bash/zsh snippets) |
| `tmux` | Direct tmux operations |
| `transport` | Transport status and diagnostics |
| `trust` | Trust store management for peer ACL |

---

## Key Configuration

### `maw.config.json`

Located at `~/.maw/maw.config.json` (or `MAW_HOME` override):

| Field | Type | Purpose |
|-------|------|---------|
| `host` | string | Outbound connection target (default: "local") |
| `bind` | string | Server bind address (default: localhost or 0.0.0.0 if federation) |
| `port` | number | Server port (default: 3456) |
| `node` | string | Node identity for federation (e.g., "white", "mba") |
| `oracle` | string | Oracle family identity (default: "mawjs") |
| `agents` | Record<string,string> | Agent-to-node mapping (e.g., `{"neo": "white"}`) |
| `sessions` | Record<string,string> | Agent-to-session mapping |
| `commands` | Record<string,string> | Shell command templates per agent pattern |
| `env` | Record<string,string> | Environment variables injected into agent sessions |
| `peers` | string[] | Legacy peer URLs |
| `namedPeers` | PeerConfig[] | Named peers with URLs (e.g., `{"name":"white","url":"http://10.20.0.7:3456"}`) |
| `federationToken` | string | HMAC-SHA256 shared secret (min 16 chars) |
| `trustLoopback` | boolean | Trust 127.0.0.1 without HMAC (default: true, dangerous with reverse proxy) |
| `allowPeersWithoutToken` | boolean | Opt-in to pre-#396 insecure-open behavior |
| `autoRestart` | boolean | Auto-restart crashed agents |
| `triggers` | TriggerConfig[] | Event-driven automation (issue-close, pr-merge, agent-idle, cron) |
| `sessionIds` | Record<string,string> | Fixed Claude session UUIDs per agent |
| `tls` | {cert, key} | TLS cert/key paths |
| `intervals` | MawIntervals | Polling intervals in ms |
| `timeouts` | MawTimeouts | HTTP/operation timeouts in ms |
| `limits` | MawLimits | Buffer/display limits |
| `pluginSources` | string[] | Auto-install plugin URLs |
| `disabledPlugins` | string[] | Plugin names to skip |
| `githubOrg` | string | GitHub org for `maw bud` |
| `githubOrgs` | string[] | GitHub orgs to scan for oracle repos |
| `psiPath` | string | Path to psi/ directory |
| `pin` | string | PIN for web UI |

### Defaults (from `src/config/types.ts`)

```
intervals:  capture=50ms, sessions=5s, status=3s, teams=3s, preview=2s, peerFetch=10s, crashCheck=30s
timeouts:   http=5s, health=3s, ping=5s, pty=5s, workspace=5s, shellInit=3s, wakeRetry=500ms, wakeVerify=3s
limits:     feedMax=500, feedDefault=50, logsMax=500, messageTruncate=100, ptyCols=500, ptyRows=200
```

---

## Dependencies

### Direct (Production)

| Package | Purpose |
|---------|---------|
| `elysia` | HTTP API framework (Elysia) |
| `hono` | Views + static file serving (Hono) |
| `@elysiajs/cors` | CORS middleware |
| `@elysiajs/swagger` | API docs (Swagger UI) |
| `arg` | CLI argument parsing |
| `mqtt` | MQTT transport (for oracle-mesh-signal) |
| `@sinclair/typebox` | Schema validation |
| `@xterm/xterm` + `@xterm/addon-fit` | Terminal emulator in browser |
| `react` + `react-dom` | UI framework |
| `zustand` | State management |
| `three` | 3D visualization (federation lens) |

### Transitive Patterns

- **Bun runtime** -- The entire project targets Bun (not Node). Uses `Bun.serve()`, `Bun.sleep()`, `import.meta.dir`, Bun test runner
- **tmux** -- Core dependency for local agent orchestration; all session/window/pane operations go through tmux commands
- **ghq** -- Used for repo discovery and cloning (`maw wake org/repo`, `maw bud`)
- **Claude Code** -- The default agent command; maw manages Claude Code sessions in tmux

---

## How Communication Works End-to-End

### `maw wake neo`

1. Resolve oracle name to repo path (ghq root scan or URL clone)
2. Create tmux session `{number}-{oracle}` (e.g., `02-neo`)
3. Create main window `{oracle}-oracle` in the session
4. Send startup command (`claude --dangerously-skip-permissions --continue`)
5. Open worktree windows for existing git worktrees
6. Register agent in `config.agents` for federation routing
7. Restore tab order from saved positions

### `maw hey local:neo "hello"`

1. Resolve target `local:neo` via `resolveTarget()` -- find local tmux session
2. Auto-wake if fleet-known but not running (`shouldAutoWake`)
3. Resolve to specific pane (avoid team-agent pane collision)
4. Check idle state (reject if user is typing, unless `--force`)
5. Send via `tmux send-keys -t {target} "{message}"`
6. Log message + emit FeedEvent
7. Run `after_send` hooks

### `maw hey white:neo "hello"` (cross-node)

1. Resolve `white:neo` -- find peer URL from `config.namedPeers`
2. Auto-wake on remote node via `/api/wake` POST
3. ACL check -- evaluate scope rules, queue if needed
4. HMAC-sign the request body
5. POST to `http://10.20.0.7:3456/api/send` with signed payload
6. Remote peer receives, verifies HMAC, sends to local tmux pane
7. Log + emit FeedEvent on both sides

### `maw peek neo`

1. Resolve target to tmux session/window
2. `tmux capture-pane -t {target}` to get current screen content
3. Print to terminal with ANSI formatting

### `maw fleet ls`

1. Load fleet configs from `~/.maw/fleet/*.json`
2. List all sessions with their windows and repos
3. Show worktree status per window

### WebSocket Dashboard

1. Client connects to `ws://localhost:3456/ws`
2. Engine sends: session list, capture updates, preview images, feed events
3. Intervals push: capture (50ms), sessions (5s), previews (2s), status (3s)
4. Plugin system intercepts all events through 4-phase pipeline
5. Transport router broadcasts feed events to remote peers

---

## Federation Architecture

```
Node A (oracle-world)              Node B (white)
┌─────────────────────┐           ┌─────────────────────┐
│ maw serve :3456      │◄────────►│ maw serve :3456     │
│ ├─ Elysia API       │  HMAC     │ ├─ Elysia API       │
│ ├─ Hono Views       │  signed   │ ├─ Hono Views       │
│ ├─ WS Engine        │  HTTP     │ ├─ WS Engine        │
│ └─ Transport Router │           │ └─ Transport Router │
│    ├─ tmux (local)  │           │    ├─ tmux (local)  │
│    ├─ Hub (remote)  │           │    ├─ Hub (remote)  │
│    ├─ HTTP (peer)   │           │    ├─ HTTP (peer)   │
│    ├─ NanoClaw      │           │    ├─ NanoClaw      │
│    └─ LoRa (stub)   │           │    └─ LoRa (stub)   │
└─────────────────────┘           └─────────────────────┘
```

**Pair codes** (`maw pair generate` / `maw pair <url> <code>`) -- 6-char ephemeral handshake for secure peer onboarding.

**From-signing** (`#804`) -- Every cross-node request includes `<oracle>:<node>` identity and ed25519 signature, verified by the receiving peer.

**Duplicate detection** -- Boot-time scan warns if two oracles share the same `<oracle>:<node>` identity across the peer cache.

---

## Key Design Decisions

1. **tmux as the runtime substrate** -- Agents run in tmux windows; maw manages them via tmux commands. No daemon other than `maw serve` for the API.

2. **File-based vault (psi/)** -- Oracle identity, inbox, outbox, goals, and memory live in a `psi/` directory inside each oracle's git repo. This is the persistent brain.

3. **Plugin-first extensibility** -- Even core features (inbox, oracle, fleet, scope, trust) are plugins. The 4-phase pipeline (gate/filter/handle/late) is the extension point.

4. **Transport abstraction** -- Messages route through tmux (local), Hub (workspace), HTTP (federation), NanoClaw (chat), or LoRa (future hardware) with automatic failover.

5. **CalVer versioning** -- `v{yy}.{m}.{d}[-alpha.{hour}]` (e.g., v26.4.18-alpha.19), migrated from SemVer on 2026-04-18.

6. **Single-port serving** -- API + WebSocket + static UI all on one port (3456), with optional TLS on port+1.

7. **HMAC-SHA256 federation auth** -- Peer communication is signed. `trustLoopback` defaults to true for CLI convenience but is dangerous behind a reverse proxy.