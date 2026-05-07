# texty-oracle Learning Index

## Source
- **Origin**: local (this repository)
- **GitHub**: https://github.com/doctorboyz/texty-oracle

## Explorations

### 2026-05-06 2247 (deep)
- [[2026-05-06/2247_ARCHITECTURE|Architecture]]
- [[2026-05-06/2247_CODE-SNIPPETS|Code Snippets]]
- [[2026-05-06/2247_QUICK-REFERENCE|Quick Reference]]
- [[2026-05-06/2247_TESTING|Testing]]
- [[2026-05-06/2247_API-SURFACE|API Surface]]

**Key insights**:
1. texty is a communication dispatcher between Telegram human and oracle sessions in tmux — it bridges bidirectional messaging via MSG-ACK-RESULT protocol
2. Busy/idle detection uses tmux pane scanning (find `❯` prompt + check for processing indicators like `✻`, `⏺`) — rejects messages to busy oracles instead of queueing
3. The maw inbox plugin (`~/.maw/plugins/inbox/impl.ts`) is the core integration point — all inter-oracle messaging, busy detection, and tmux notification flow through it
4. Zero automated tests — all verification is manual via `maw inbox send` smoke tests
5. Credential security gap: bot token visible in daemon error logs, `set -e` missing from 2 bash scripts