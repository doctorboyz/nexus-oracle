---
name: pm-fleet-orchestration-principle
description: PM drives fleet to completion when human sets goals, not send-and-wait
type: feedback
---

## PM Orchestrates Fleet to Completion

**Rule**: When the human sets a goal through PM, PM drives the fleet until that goal is achieved. PM does not send-and-wait — PM dispatches, monitors, verifies each step, then proceeds to the next.

**Why**: The human delegated goal-setting to PM. If PM only sends messages and waits passively, goals drift. PM must actively push: wake oracles, send tasks, check results, verify KPIs, and iterate.

**How to apply**:
- Decompose goals into measurable steps (each step must have verifiable KPIs)
- Use `maw wake` + `maw hey` to dispatch tasks to oracles
- Monitor oracle outbox and PM inbox for results
- Verify each step passes its KPI before proceeding
- If a step fails, adjust approach and re-dispatch
- Only report completion to human when all steps pass

**Key distinction**: PM does NOT command the human (present options, let human decide). PM DOES command the fleet (drive to completion). Human → PM → Fleet → Result → Verify → Next step.

**maw session note**: `(running: ollama)` in `maw fleet ls` = active Claude session. Use `--force` if maw hey rejects, but the session IS active.