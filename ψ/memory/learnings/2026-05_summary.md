# Learnings Summary — May 2026

Consolidated from 16 dated lesson files (2026-04-29 through 2026-05-19).

---

## 2026-04-29 — Agentic AI Vault Architecture
god-port designed as vault-driven agent, not code app. Wake protocol: read ψ/identity.md, ψ/inbox/, ψ/memory/, ψ/goals/ → decide → act → write ψ/outbox/. Broky and Metty are roles within one agent session, not separate agents. Shared ψ/ top-level is for inter-agent comm (PM→god-port); inter-role comm happens within same session context.

## 2026-04-29 — maw Naming Convention
maw expects GitHub repos to follow `{name}-oracle` pattern. Renamed god-port-trading to god-port-oracle to match. When consolidating oracle repos: remove old fleet entries, renumber sequentially, update all CLAUDE.md references, test `maw wake` before done.

## 2026-04-29 — Ollama Session Equivalence
`ollama launch claude` in maw is equivalent to an active Claude Code session. `running: ollama` in `maw fleet ls` means the oracle is awake and can receive `maw hey` commands. The `--force` flag is only needed when no session is detected at all.

## 2026-04-29 — PM Fleet Orchestration (Principle #3)
PM drives fleet to completion when human sets goals — not send-and-wait. Decompose goals into measurable steps with KPIs, use `maw wake`/`maw hey` to dispatch, monitor outbox/inbox, verify each step before proceeding. PM commands the fleet, not the human. `--force` handles maw hey rejection for ollama sessions.

## 2026-04-29 — Real Goal vs Proxy Metrics
When proxy metrics (WR, PF, MaxDD) conflict with real goal, real goal wins. WR=53% accepted because PF=1.64 and MaxDD=11.8% already satisfy "profit consistently without blowing up." The 2pp WR gap has negligible impact on the real goal.

## 2026-05-13 — PM2 Daemon Deployment
PM2 chosen over Docker/webhook for Telegram daemon management. Lightweight, auto-restart, simple logs. Webhook approach abandoned due to cloudflared tunnel complexity, port conflicts, and DNS propagation issues. Polling mode with 10s timeout, authorized chats only.

## 2026-05-13 — Telegram Channel Routing
7 Telegram groups (Emily, God-Port, Nexus, FamMe, Kappy, Infra, Fleet) with per-oracle routing. Bot privacy mode must be disabled in BotFather. Dynamic ORACLES from fleet config — no code changes for new oracles. `write_to_inbox()` fallback when `maw inbox send` can't resolve oracle name.

## 2026-05-14 — Smart Routing
Three-tier routing: oracle group → direct delivery, fleet group → auto-route by keyword matching (confidence >= 0.5), private chat → nexus inbox. Fleet configs have `routing.keywords` and `routing.domains` fields. Tie-breaking by longest matched keyword length. `auto_wake: true` wakes sleeping oracles on delivery.

## 2026-05-16 — maw Communication Architecture
Three channels: tmux send-keys (immediate), file inbox (async), Telegram bot (~3s). Critical gap: `maw inbox send` writes file but does NOT notify running session. Solution: use `maw hey` AFTER inbox send to inject notification. Complete flow: human→Telegram→daemon→deliver_to_oracle()→maw inbox send + maw hey→oracle reads→responds→daemon reads outbox→sends Telegram→archives.

## 2026-05-19 — Hyphen Filename Import
Python files with hyphens (e.g. nexus-daemon.py) cannot be imported with standard `import` statement. Solution: `importlib.util.spec_from_file_location()`. Module-level side effects (reading config, opening connections) require test environment setup BEFORE import. Import once, override constants for testing — don't mock the import environment.

## Operational Guides (undated)

### Coordination Patterns
Three comm channels: vault-based (async, persistent), maw-based (sync via tmux), file-based (shared project). Key patterns: God Port internal broky→metty signal flow, Emily→Child budding, PM→Fleet drive-to-completion. MSG-ACK-RESULT protocol with timeout escalation (1 session=wait, 2=peek, 3=log, 3+=escalate).

### Dispatch Guide
Four message types: escalation (forward immediately, sound alert), query (forward with vault context), task (forward with approval poll), info (auto-ACK, log only). Dispatch flow: read inbox→evaluate type→dispatch→wait response→MSG-RESULT→log.

### Goal Tracking Guide
Evidence over assertion, append-only progress, clear Definition of Done, escalate early. Goal file format: YAML frontmatter + CSV status tracking + DoD checklist + Audit Trail + Blockers + Escalation History. Read oracle vaults for real status (outbox, resonance, handoff, knowledge, work logs), not stated intentions.

### Knowledge Access Guide
Read vaults passively: emily, god-port, pm vault paths. Search methods: grep across vaults, sqlite3 for .db files, WebSearch as fallback. texty searches first, only asks oracle if data not found.

### Message Protocol (MSG-ACK-RESULT)
Full spec: Send (write to target ψ/inbox/), Acknowledge (status pending→acknowledged, write ack to own outbox), Result (status→completed, write result to own outbox), Record (PM updates goal file). Message ID format: MSG-{SENDER}-{NNN}. Timeout rules at 1/2/3 sessions. Directory map for all 3 oracles.

### Channel Operations (texty)
Telegram MCP tools for send, poll, read, search. Message prefix convention: [texty] ESCALATION/QUERY/TASK/INFO. Dispatch log format in ψ/dispatch/YYYY-MM/ with frontmatter (dispatch_id, from, to, type, status, sent, result).
