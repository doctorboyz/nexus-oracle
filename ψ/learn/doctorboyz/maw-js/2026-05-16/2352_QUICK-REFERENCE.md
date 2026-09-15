# maw Quick Reference

> maw (Multi-Agent Workflow) -- CLI for running multiple AI agents across machines.
> Source: `github.com/Soul-Brews-Studio/maw-js` | Version: CalVer `v26.4.50` | Runtime: Bun 1.3+

---

## What It Does

maw is an **oracle fleet manager** -- a CLI that orchestrates multiple Claude Code (or Codex) agents across one or more machines. Each agent runs inside a tmux window. maw handles:

- **Lifecycle**: wake (start), sleep (stop), and restart agent sessions
- **Messaging**: send prompts to any agent via `hey`, fan-out to teams
- **Observability**: peek at agent screens, list sessions, stream event feeds
- **Federation**: multi-node mesh with HMAC-signed peer communication
- **Fleet config**: declarative JSON files defining which agents run where
- **Inter-oracle messaging**: MSG-ACK-RESULT protocol for vault-based cross-oracle communication
- **Web UI**: built-in server (port 3456) serving a React-based "federation lens"

Architecture stack: Bun/TS CLI + Elysia HTTP API + WebSocket feed + tmux orchestration + Hono views + optional MQTT transport.

---

## Installation

```bash
# One-line install
curl -fsSL https://raw.githubusercontent.com/Soul-Brews-Studio/maw-js/main/install.sh | bash

# Or via bun
bun add -g github:Soul-Brews-Studio/maw-js

# Or from source
ghq get Soul-Brews-Studio/maw-js
cd "$(ghq root)/github.com/Soul-Brews-Studio/maw-js"
bun install && bun link
```

Recovery if `maw` vanishes:
```bash
bun add -g github:Soul-Brews-Studio/maw-js   # reinstall
maw doctor                                    # self-heal command
```

---

## Configuration

### `maw.config.json`

Primary config file (lives at project root or `~/.maw/config.json`):

```jsonc
{
  "host": "local",              // bind host
  "port": 3456,                 // API server port
  "ghqRoot": "/home/user/Code/github.com",  // ghq root (auto-resolved if omitted)
  "oracleUrl": "http://localhost:47779",

  "env": {
    "CLAUDE_CODE_OAUTH_TOKEN": "<token>"
  },

  "commands": {
    "default": "claude --dangerously-skip-permissions --continue",
    "*-oracle": "claude --dangerously-skip-permissions --continue",
    "codex-*": "codex --dangerously-auto-approve --search"
  },

  "sessions": {
    "nexus": "02-nexus",
    "emily": "00-emily"
  },

  "node": "oracle-world",                    // federation node identity
  "federationToken": "shared-secret-min-16-chars",  // HMAC signing key
  "namedPeers": [
    { "name": "white", "url": "http://10.20.0.7:3456" },
    { "name": "mba", "url": "http://10.20.0.3:3457" }
  ],

  "agents": {
    "nexus": "local",
    "emily": "local",
    "homekeeper": "mba"
  },

  "oracle": "mawjs",                         // family identity for federation auth
  "githubOrg": "Soul-Brews-Studio",
  "githubOrgs": ["Soul-Brews-Studio", "doctorboyz"],

  "triggers": [
    { "on": "agent-idle", "action": "maw sleep $AGENT", "timeout": 300 }
  ]
}
```

### Fleet Config (`~/.maw/fleet/*.json`)

Declarative session definitions. Each file = one tmux session with windows:

```json
{
  "name": "nexus",
  "windows": [
    { "name": "nexus-oracle", "repo": "doctorboyz/nexus-oracle" },
    { "name": "nexus-texty", "repo": "doctorboyz/nexus-oracle", "branch": "texty" }
  ],
  "sync_peers": ["emily"],
  "budded_from": "emily"
}
```

Numbered filenames control tmux session order: `02-nexus.json`, `00-emily.json`.

---

## Commands

### `maw wake <oracle>`

Start an agent session in tmux. Resolves the oracle name to a repo path, creates/attaches a tmux session, and launches the agent process.

```bash
maw wake neo                          # wake oracle by name
maw wake org/repo                     # clone via ghq + wake
maw wake https://github.com/org/repo  # full URL works
maw wake neo --issue 5               # clone + send GitHub issue as prompt
maw wake neo --task my-feature       # wake in existing worktree
maw wake neo --fresh                  # force new worktree
maw wake neo --attach                 # attach to tmux after wake
maw wake neo --prompt "do the thing"  # wake with initial prompt
maw wake neo --split                  # split pane after wake
```

Behavior:
1. Resolves oracle name -> repo path (via ghq, fleet config, or URL)
2. Checks if session already exists -- idempotent if so
3. Creates tmux session with main window named `<oracle>-oracle`
4. Auto-discovers git worktrees and spawns windows for each
5. Registers agent in `config.agents` for federation routing
6. Restores saved tab order from previous sleep

### `maw sleep <oracle>`

Gracefully stop sessions. When called without args, stops ALL fleet sessions:

```bash
maw sleep            # stop all fleet sessions
maw sleep neo        # (single oracle -- uses tmux kill-session)
```

Behavior:
1. Saves tab order (so next wake restores positions)
2. Kills the tmux session(s)

### `maw hey <oracle> "message"`

Send a message to an agent. Requires node prefix for cross-node routing:

```bash
# Local (canonical form)
maw hey local:nexus "check inbox"

# Remote peer
maw hey white:neo "hello"

# Specific tmux window
maw hey white:neo:3 "hello hermes"

# Team fan-out (sends to all team members)
maw hey team:dev-team "deploy ready"

# Plugin routing
maw hey plugin:summarizer "summarize this"

# With flags
maw hey local:nexus "message" --force   # skip idle check
maw hey white:nexus "message" --approve # approve ACL-gated cross-node send
maw hey white:nexus "message" --approve --trust  # approve + persist trust pair
```

Resolution order:
1. `team:` prefix -> fan-out to team members
2. `plugin:` prefix -> route to plugin
3. Local tmux session (if `local:` prefix or matches `config.node`)
4. Named peer HTTP endpoint (if `<peer>:` prefix matches `config.namedPeers`)
5. Network discovery fallback (slow path)

Auto-wake: if the target is fleet-known but not running, `hey` auto-wakes it before sending.

### `maw peek [agent]`

View an agent's terminal screen (tmux capture-pane):

```bash
maw peek              # peek ALL sessions (one line per window)
maw peek nexus        # peek specific oracle
maw peek white:neo    # peek remote peer's agent
```

Read-only operation. Never auto-wakes.

### `maw ls`

List all tmux sessions and windows with status indicators:

```bash
maw ls
```

Output shows:
- Green dot: active agent running
- Blue dot: agent running but not active pane
- Red dot: dead pane (shell only, or deleted working dir)
- Orphaned worktree detection with `--fix` cleanup suggestion

### `maw fleet ls`

List fleet configuration entries with running status:

```bash
maw fleet ls               # show all fleet entries
maw fleet init             # initialize fleet config from current sessions
maw fleet init --agents    # init from agent discovery
maw fleet health           # health report
maw fleet doctor            # config doctor (--fix to auto-repair)
maw fleet doctor --fix     # auto-repair issues
maw fleet sync             # sync fleet configs
maw fleet sync-windows     # sync window layout to match fleet config
maw fleet renumber         # fix conflicting fleet number slots
maw fleet validate          # validate fleet configs
maw fleet consolidate       # merge duplicate fleet entries
maw fleet snapshot          # save a snapshot of current session state
maw fleet snapshots         # list saved snapshots
maw fleet restore           # restore from latest snapshot
```

### `maw inbox send <oracle> "message"`

Write a MSG-ACK-RESULT file to a target oracle's vault. Full inter-oracle messaging protocol:

```bash
maw inbox send nexus "review the PR"                    # send task message
maw inbox send nexus "what's the status?" --type query  # send query
maw inbox send nexus "urgent: production down" --type escalation
maw inbox ls                                  # list own inbox
maw inbox ls --unread                         # list unread only
maw inbox ls --from emily                     # filter by sender
maw inbox ls --last 10                        # last 10 messages
maw inbox ack MSG-NEXUS-001                   # acknowledge a message
maw inbox result MSG-NEXUS-001 "task completed"  # mark completed with result
maw inbox show MSG-NEXUS-001                  # show message details
maw inbox read MSG-NEXUS-001                  # mark as read

# ACL queue (cross-node approval)
maw inbox show-pending                        # list pending cross-node messages
maw inbox approve <id>                        # approve a queued message
maw inbox reject <id>                         # reject a queued message
```

Message lifecycle: `pending -> acknowledged -> completed`

Messages are append-only markdown files with YAML frontmatter in `ψ/inbox/` directories.

### `maw oracle scan`

Discover oracle repos:

```bash
maw oracle scan              # local scan (fast, default)
maw oracle scan --remote    # GitHub API scan
maw oracle scan --all       # local + remote
maw oracle scan --json       # JSON output
maw oracle scan --stale     # find stale/orphaned oracle repos

maw oracle ls                # list known oracles
maw oracle ls --awake        # only running oracles
maw oracle ls --scan         # scan before listing
maw oracle about nexus       # show oracle identity
maw oracle register nexus    # register oracle in config
maw oracle prune --stale     # remove stale entries
maw oracle set-nickname nexus "nx"  # set short name
maw oracle get-nickname nexus        # get short name
```

### `maw bud <name>`

Create a new oracle repository:

```bash
maw bud myname --root           # fresh oracle (no parent)
maw bud myname --from neo       # bud from existing oracle
```

Always creates `<name>-oracle` repo. Never include `-oracle` in the stem.

### Other Commands

```bash
maw serve [port]               # start API server (default :3456)
maw ui                         # open federation lens in browser
maw ui install                 # download UI from GitHub releases
maw ui white                   # open lens pointed at peer node
maw contacts                   # list oracle contacts
maw soul-sync                  # sync memory across peers
maw find <keyword>             # search memory across oracles
maw ping                       # check peer connectivity
maw update                     # update maw to latest version
maw doctor                     # diagnose and fix common issues
maw done <window>              # auto-save + cleanup for a window
maw bud <name> [--from parent] # spawn new oracle repo
```

---

## Session Naming

tmux sessions follow a numbered pattern aligned with fleet configs:

```
00-emily          # emily oracle (root)
01-god-port       # god-port oracle (trading)
02-nexus          # nexus oracle (dispatcher + coordinator)
04-mkt            # mkt oracle (marketing)
05-dev            # dev oracle (development)
```

Numbers come from fleet config filenames (`00-emily.json`, etc.). The `--view` suffix denotes read-only monitoring sessions.

---

## Federation Architecture

### Node Topology

```
[Machine: oracle-world]         [Machine: mba]          [Machine: white]
  maw serve :3456                 maw serve :3457         maw serve :3456
  ┌─────────────────┐            ┌──────────────────┐    ┌──────────────────┐
  │ 00-emily        │            │ 11-homekeeper     │    │ 09-pulse          │
  │ 02-nexus        │◄──HMAC───►│                    │◄──►│ 07-hermes         │
  │ mawjs-oracle    │            │                    │    │                   │
  └─────────────────┘            └──────────────────┘    └──────────────────┘
```

### Auth

- HMAC-SHA256 signing on all cross-node HTTP requests
- `federationToken` in config (shared secret, min 16 chars)
- Pair codes for initial trust: `maw pair generate` / `maw pair <url> <code>`
- ACL scopes for fine-grained cross-node send approval

### API Endpoints (v1 Stable)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/config` | Node identity + agents map + named peers |
| `GET /api/fleet-config` | Fleet entries with lineage (`budded_from`) |
| `GET /api/feed?limit=200` | Live event stream (bounded ring buffer) |
| `GET /api/federation/status` | Peer reachability + latency |
| `POST /api/send` | Cross-node message delivery |
| `POST /api/wake` | Cross-node wake trigger |
| `POST /api/peer/exec` | Signed command relay |

---

## MSG-ACK-RESULT Protocol (Inter-Oracle Communication)

The full flow for cross-oracle messaging:

```
[Telegram] ──► nexus-daemon.py (polling bot)
                    │
                    ▼
[ψ/inbox/MSG-*.md]  ◄── maw inbox send nexus "task description"
                    │
                    ▼
nexus Oracle wakes ──► reads inbox
                    │
                    ├── maw inbox ack MSG-NEXUS-001   (acknowledge)
                    │        └── writes ψ/outbox/ack_MSG-NEXUS-001_2026-05-16.md
                    │
                    ├── (does work)
                    │
                    └── maw inbox result MSG-NEXUS-001 "completed"
                             └── writes ψ/outbox/result_MSG-NEXUS-001_2026-05-16.md
```

Inbox message format (YAML frontmatter + markdown body):

```markdown
---
msg_id: MSG-NEXUS-001
from: emily
to: nexus
type: task
status: pending
sent: 2026-05-16T12:00:00Z
ack_by: "-"
result: "-"
reply_file: "-"
---

Review the new feature branch and provide feedback.
```

---

## Usage Patterns

### Daily Workflow

```bash
# Morning: wake the whole fleet
maw fleet sync         # sync configs
maw wake --all         # or wake individual oracles

# Check status
maw ls                 # list all sessions
maw peek               # quick overview of all windows

# Send tasks
maw hey local:nexus "check inbox for new messages"
maw hey local:emily "review the PR"

# Cross-node
maw hey white:pulse "run the market analysis"

# End of day: put fleet to sleep
maw sleep
```

### Team Fan-Out

```bash
# Define team in oracle registry, then:
maw hey team:dev-team "deployment complete, run smoke tests"
# Delivers to each team member individually, skipping self
```

### Auto-Wake + Hey Pattern

```bash
# If target is fleet-known but not running, hey auto-wakes it:
maw hey local:nexus "start working on ticket #42"
# This wakes nexus (if stopped), waits for session, then sends message
```

### Inbox Workflow (Async Messaging)

```bash
# Sender oracle sends a task
maw inbox send nexus "analyze the market data from today"

# Receiving oracle acknowledges
maw inbox ack MSG-EMILY-003

# After completing the task
maw inbox result MSG-EMILY-003 "analysis complete, findings in ψ/outbox/"
```

---

## Key Internals

### Transport Layer

- **Local**: tmux `send-keys` for same-machine agents
- **Federation**: HMAC-signed HTTP (`/api/send`, `/api/wake`) for cross-node
- **Discovery**: peer URL auto-probing when bare name matches no local session
- **Multi-pane routing**: `resolveOraclePane()` picks the lowest-index claude/codex pane in multi-pane windows

### Resolution Order for `maw hey`

1. `team:` prefix -> fan-out to all team members
2. `plugin:` prefix -> invoke plugin
3. `local:<agent>` or bare `<agent>` on local node -> tmux send-keys
4. `<peer>:<agent>` -> check `namedPeers` -> HTTP POST to peer's `/api/send`
5. `<peer>:<session>:<window>` (canonical) -> HTTP POST to peer
6. Network discovery fallback (slow path)

### Auto-Wake Logic

- `wake` command: always creates session if missing
- `hey` command: auto-wakes fleet-known targets (no prompt needed)
- `peek` command: never auto-wakes (read-only)
- `ls` command: never auto-wakes (read-only)

### Idle Guard

Before sending, `hey` checks if the target pane has in-progress user input. If the shell prompt shows typing, it rejects the send (use `--force` to override).

### Fleet Config Priority

Session mapping resolution for `maw wake` / `maw hey`:
1. `config.sessions` explicit mapping (e.g., `"nexus": "02-nexus"`)
2. Fleet config file matching (`~/.maw/fleet/02-nexus.json`)
3. Direct name lookup in tmux sessions
4. Fallback: bare name as tmux session name