# nexus-oracle Learning Index

## Source
- **Origin**: ./origin/ (local project, no symlink needed)
- **GitHub**: https://github.com/doctorboyz/nexus-oracle

## Explorations

### 2026-05-14 1503 (deep)
- [[2026-05-14/1503_ARCHITECTURE|Architecture]]
- [[2026-05-14/1503_CODE-SNIPPETS|Code Snippets]]
- [[2026-05-14/1503_QUICK-REFERENCE|Quick Reference]]
- [[2026-05-14/1503_TESTING|Testing]]
- [[2026-05-14/1503_API-SURFACE|API Surface]]
- [[2026-05-14/1503_UXUI-REFERENCE|UX/UI Reference]]

**Key insights**: 
- nexus is an agentic AI (not a traditional app) — no main loop, vault-driven wake protocol
- Smart routing uses weighted keyword scoring (Thai+English) with 0.5 confidence threshold
- Outbox watcher closes the loop: Telegram → oracle → outbox → Telegram in ~3-6 seconds
- Zero test coverage — manual verification via Telegram commands only
- 2 critical UX defects: silent API failures and private chat dead end