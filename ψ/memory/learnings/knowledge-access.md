# Knowledge Access Guide — texty Oracle

## Vault Scanning (Read-Only)

texty อ่าน vault ของ oracle อื่นแบบ passive (Principle 2) — ไม่ถาม "เป็นไง?" อ่านสิ่งที่เขียนไว้

### Oracle Vault Paths

| Oracle | Path | Content |
|--------|------|---------|
| emily | `/Users/doctorboyz/Code/github.com/doctorboyz/emily-oracle/ψ/memory/` | Root oracle memory |
| god-port | `/Users/doctorboyz/Code/github.com/doctorboyz/god-port-oracle/ψ/memory/` | Trading agent memory |
| pm | `/Users/doctorboyz/Code/github.com/doctorboyz/pm-oracle/ψ/memory/` | Coordinator memory |
| pm goals | `/Users/doctorboyz/Code/github.com/doctorboyz/pm-oracle/ψ/goals/active/` | Active goal tracking |

### Search Methods

```bash
# Quick search across all vaults
grep -ri "keyword" /Users/doctorboyz/Code/github.com/doctorboyz/*/ψ/memory/

# Search goal tracking
grep -ri "keyword" /Users/doctorboyz/Code/github.com/doctorboyz/pm-oracle/ψ/goals/

# Find specific file types
find /Users/doctorboyz/Code/github.com/doctorboyz/*/ψ/ -name "*.md" | xargs grep "keyword"
```

## DB Query (Active)

เมื่อเจอไฟล์ `.db` หรือ `.sqlite` ใน vault หรือ project:

```bash
# List tables
sqlite3 /path/to/file.db ".tables"

# Query specific table
sqlite3 /path/to/file.db "SELECT * FROM table_name LIMIT 10;"

# Search across columns
sqlite3 /path/to/file.db "SELECT * FROM table_name WHERE column LIKE '%keyword%';"
```

## Web Search (On-demand)

เมื่อ vault + DB ไม่มีคำตอบ:

1. ใช้ WebSearch tool ใน Claude Code
2. ระบุ context ชัดเจนว่าทำไมต้อง search
3. สรุปคำตอบ + ระบุ source
4. ส่งกลับผ่าน Telegram พร้อม attribution

## Response Format

เมื่อมนุษย์ถามคำถามผ่าน Telegram:

```
[texty] QUERY response:

{answer}

Sources:
- {oracle vault path}
- {DB query result}
- {web search URL}
```