# Channel Operations — texty Oracle

## Telegram (Primary Channel)

texty ใช้ Telegram MCP tools ที่มีอยู่ใน Claude Code

### ส่งข้อความไปหามนุษย์

```
telegram-send-message
  chatId: "<chat_id>"
  text: "ข้อความ"
```

### ส่งข้อความพร้อม formatting

```
telegram-send-message
  chatId: "<chat_id>"
  text: "ข้อความ"
  parseMode: "md"
```

### สร้าง Approval Poll

```
telegram-create-poll
  chatId: "<chat_id>"
  question: "texty: อนุมัติ X?"
  answers: ["Approve", "Reject"]
```

### อ่านข้อความตอบกลับ

```
telegram-read-messages
  chatId: "<chat_id>"
  limit: 5
```

### ค้นหาข้อความ

```
telegram-search-messages
  chatId: "<chat_id>"
  query: "approve"
```

## Message Prefix Convention

ทุกข้อความที่ texty ส่งผ่าน Telegram ต้องมี prefix:

- 🚨 `[texty] ESCALATION` — กรณีฉุกเฉิน
- ❓ `[texty] QUERY` — คำถามที่ต้องการคำตอบ
- ✅ `[texty] TASK` — งานที่ต้องการ approval
- ℹ️ `[texty] INFO` — ข้อมูล (ถ้าต้องส่งแจ้ง)

## Dispatch Log Format

ทุกข้อความที่ส่งต่อ log ใน `ψ/dispatch/YYYY-MM/`:

```markdown
---
dispatch_id: DSP-{YYYYMMDD}-{NNN}
from: {oracle_name}
to: human (Telegram)
type: escalation|query|task|info
status: forwarded|responded|timeout
sent: {ISO timestamp}
result: {human response or "awaiting"}
---

{message content}
```