# Lesson: Agentic AI Vault Architecture

**Date**: 2026-04-29
**Source**: pm-oracle /rrr
**Context**: Designing god-port as vault-driven agent, not code app

## Pattern

An agentic AI trading system works differently from a code app:

| Aspect | Code App | Agentic AI |
|--------|----------|------------|
| Lifecycle | Daemon, always running | Session-based, wakes on demand |
| State | Database | ψ/ vault files |
| Communication | API endpoints | inbox/outbox files |
| Memory | RAM/cache | ψ/memory/ persistent |
| Identity | Config file | ψ/identity.md (read on wake) |

## Wake Protocol

```
READ ψ/identity.md → know who I am
READ ψ/inbox/       → any pending requests?
READ ψ/memory/      → lessons from past sessions
READ ψ/goals/       → current targets
DECIDE → act based on inbox + goals
ACT → use broky/ metty/ code as tools
WRITE ψ/outbox/     → results, acks, reports
```

## Key Insight

Broky and Metty are NOT separate agents — they are **roles within one agent**. In a single Claude Code session, the agent activates whichever role is needed based on the task. The ψ/broky/ and ψ/metty/ sub-vaults store role-specific history, not separate agent state.

The top-level ψ/ (inbox, outbox, memory, goals) is the **shared space** for inter-agent communication (PM → god-port). Inter-role communication (broky → metty) happens within the same session context, not through vault files.