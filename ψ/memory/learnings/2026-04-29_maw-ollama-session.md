---
name: maw-ollama-session-equivalence
description: Ollama launch claude = active Claude session in maw fleet
type: project
---

## maw Ollama Sessions

**Fact**: `ollama launch claude` in maw is equivalent to an active Claude session. When `maw fleet ls` shows an oracle running with `(running: ollama)`, that oracle has an active Claude session and can receive and process `maw hey` commands.

**Why**: maw uses ollama as the runtime for Claude Code sessions. "running: ollama" means the oracle is awake and listening — not a different or lesser state than a native Claude session.

**How to apply**: Don't treat `(running: ollama)` as "not a real session". It IS an active session. `maw hey` messages will be received and processed. The `--force` flag is only needed when no session is detected at all.