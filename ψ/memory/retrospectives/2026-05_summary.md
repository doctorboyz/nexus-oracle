# Retrospectives Summary — May 2026

Consolidated from 4 session retrospectives (2026-04-29 through 2026-05-19).

---

## 2026-04-29 10:56 — God Port Consolidation
**Duration**: ~130 min | **Type**: Refactoring + Architecture | **Session**: bd076669

Consolidated broky-oracle + metty-oracle + /MT5 into single god-port-oracle repo. Configured as vault-driven agentic AI. Tested full MSG-ACK-RESULT protocol end-to-end. Fixed maw fleet config (naming, numbering, stale entries).

**Key decisions**: Single agent with two roles (broky/metty), vault-driven not daemon, shared ψ/ top-level. Repo renamed from god-port-trading → god-port-oracle for maw convention.

**Honest feedback**: (1) Should have validated maw naming convention before creating repo. (2) Fleet config cleanup was reactive not proactive — left stale broky/metty entries. (3) Never tested `maw wake` before declaring done.

**Lessons**: Validate tooling conventions early. Clean stale config in same task. Test integration path end-to-end.

---

## 2026-04-29 15:30 — Fleet Orchestration Philosophy
**Duration**: ~6h 18min | **Type**: Feature + Architecture | **Session**: bd076669

Expanded Principle #3 from "don't command anyone" to "Orchestrate Fleet, Not Human." PM now drives fleet to completion. Dispatched S4-S8 tasks to god-port, monitored results (WR 44%→53%, PF 1.47→1.64). Human accepted WR=53% — real goal "profit consistently without blowing up" overrides proxy metric.

**Key decisions**: Principle #3 expansion, WR=53% accepted, Ollama = active session.

**Honest feedback**: (1) Too passive after monitor timeout — should have used `maw peek` immediately. (2) Assumed maw hey failure = no session instead of investigating. (3) Neutral presentation on WR=53% instead of strong recommendation based on data.

**Lessons**: Drive-to-completion not send-and-wait. Proxy metrics serve real goal. Ollama sessions are real sessions.

---

## 2026-05-13 18:09 — Telegram Channel Architecture
**Duration**: ~5 hours | **Type**: Infrastructure

Created 7 Telegram groups, rewrote daemon from polling→webhook→polling, deployed with PM2. Fixed privacy mode blocking group messages.

**Key decisions**: Polling over webhook (simpler, no cloudflared dependency). PM2 over Docker (lightweight). Per-oracle Telegram groups. Privacy mode disabled.

**Honest feedback**: (1) Webhook detour was self-inflicted complexity — 2 hours wasted. (2) Process management mess — launchd was auto-restarting killed processes. (3) Didn't test privacy mode proactively, user discovered it.

**Lessons**: Start with simplest architecture. Test incrementally. Check process management early. Anticipate platform defaults (Telegram privacy mode).

---

## 2026-05-17→19 22:58 — Daemon Stability Hardening
**Duration**: ~2 days (2 sessions) | **Type**: Feature + Research | **Session**: 223ba58e

Hardened nexus-daemon: shell injection fix, dead letter queue, API retry logic, structured logging, 45-test suite, deploy script with verification. Deep dive into maw-js communication architecture via /learn — discovered `maw hey` (tmux send-keys) is the only real-time notification mechanism.

**Key decisions**: In-memory retry counter (resets on restart = fresh retries). Dead letter at ψ/outbox/dead/YYYY-MM/. importlib.util.spec_from_file_location for hyphen filename imports. pytest before pm2 restart in deploy.

**Honest feedback**: (1) Test setup took 3 rounds due to import approach mistakes. (2) Scope creep — started with "does it crash?" ended with full rewrite. (3) Dead letter notification sends Telegram every time — should rate limit.

**Lessons**: Hyphen filenames need importlib. Analyze before acting — "crashes often" was actually "fragile but stable." In-memory tracking is adequate for daemon retry counts.
