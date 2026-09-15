# maw-js Learning Index

## Source
- **Origin**: ./origin/
- **GitHub**: https://github.com/doctorboyz/maw-js

## Explorations

### 2026-05-16 2352 (default)
- [[2026-05-16/2352_ARCHITECTURE|Architecture]]
- [[2026-05-16/2352_CODE-SNIPPETS|Code Snippets]]
- [[2026-05-16/2352_QUICK-REFERENCE|Quick Reference]]

**Key insights**: maw is a CLI + API server orchestrating AI agents across tmux sessions and networked machines. Core communication uses tmux send-keys (hey), file-based inbox/outbox (MSG-ACK-RESULT), and HTTP federation for cross-node. Even core commands are plugins. The hey command resolves targets through 4-layer lookup, checks pane idle state, and uses buffer+paste for long messages.