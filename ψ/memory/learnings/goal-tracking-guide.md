# Goal Tracking Guide

> PM Oracle's methodology for tracking project goals across the Oracle family

## Core Principles

1. **Evidence over assertion**: PM reads oracle vaults, not oracle claims
2. **Append-only progress**: Audit Trail entries are timestamped and never deleted
3. **Clear Definition of Done**: Every goal has measurable completion criteria
4. **Escalate early**: Don't wait for a blocker to become a crisis

## Goal File Format

Each project has one `.md` file in `ψ/goals/active/`:
- YAML frontmatter: goal_id, project, responsible, status, created
- CSV block: status tracking per objective (id, objective, status, owner, deadline, evidence, updated)
- Definition of Done: checklist
- Audit Trail: timestamped append-only log
- Blockers: tagged [CAPABILITY], [DEPENDENCY], or [RESOURCE]
- Escalation History: when emily was asked to intervene

## Status Values

- **on-track**: Evidence shows progress toward objective
- **at-risk**: Objective not yet met, but path forward exists
- **blocked**: No path forward without external intervention
- **completed**: Objective met with evidence
- **pending**: Not yet started, waiting for prerequisites

## Reading Oracle Vaults for Status

### What to look for
- Outbox files: what the oracle last announced
- Resonance files: oracle's self-assessed state
- Handoff files: what the human expects the oracle to do next
- Knowledge files: what the oracle has learned (indicates progress)
- Work logs: what the oracle actually did

### What NOT to rely on
- Oracle's stated intentions (Principle 2: Patterns Over Intentions)
- Missing updates (no outbox file may mean stalled, not just quiet)
- Human's assumptions about oracle progress (verify with evidence)

## Escalation Decision Tree

1. Is the blocker a DEPENDENCY? → Flag in goal file, wait for dependency to resolve
2. Is the blocker a RESOURCE? → Flag in goal file, inform human
3. Is the blocker a CAPABILITY? → Escalate to emily with full evidence
4. Is the blocker unclear? → Read more vault files, ask oracle via `maw hey`

## maw Integration

### Pulse Bridge
When a goal objective needs action, create a pulse issue:
```bash
maw pulse add "{objective description}" --oracle {owner}
```

### Artifact Bridge
When a goal objective is completed, write an artifact:
```bash
maw art write {team} {id} "{result summary}"
```

### Oracle Scan
Periodically scan for new oracles that emily may have created:
```bash
maw oracle scan
```