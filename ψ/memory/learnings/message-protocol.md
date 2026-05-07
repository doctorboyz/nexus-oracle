# Oracle Message Protocol — Feedback Loop

> Vault-based message protocol with acknowledgment and result reporting

## Problem

Oracle ส่งข้อความถึงกันผ่าน vault แต่ไม่มี mechanism ยืนยันว่า "รับทราบแล้ว" หรือ "ทำเสร็จแล้ว" — ฝั่งส่งไม่รู้สถานะคำขอ

## Protocol: MSG-ACK-RESULT

### 1. ส่งคำขอ (Send)

ผู้ส่งเขียนไฟล์ลง `ψ/inbox/` ของ **ผู้รับ**:

```
{target-vault}/ψ/inbox/{date}_{time}_{sender}_{msg_id}.md
```

**รูปแบบไฟล์:**

```markdown
---
msg_id: MSG-{SENDER}-{NNN}
from: {sender}
to: {receiver}
type: task | query | escalation | info
status: pending        ← pending → acknowledged → completed
sent: {ISO timestamp}
ack_by: -              ← ผู้รับกรอกเมื่อรับทราบ
result: -              ← ผู้รับกรอกเมื่อทำเสร็จ
reply_file: -          ← ผู้รับกรอก path ไฟล์ผลลัพธ์
---

{เนื้อความคำขอ}
```

**ตัวอย่าง:**

```markdown
---
msg_id: MSG-PM-001
from: pm
to: god-port
type: task
status: pending
sent: 2026-04-29T09:00:00Z
ack_by: -
result: -
reply_file: -
---

Run backtest parameter sweep on XAUUSD H1.
Focus on PF > 1.5, MaxDD < 20%, WR > 55%.
Report results to outbox.
```

### 2. รับทราบ (Acknowledge)

ผู้รับเมื่ออ่าน inbox:
1. แก้ `status: pending` → `acknowledged`
2. แก้ `ack_by: -` → `ack_by: {ISO timestamp}`
3. เขียนไฟล์ ack ลง `ψ/outbox/` ของ **ตัวเอง**:

```
{receiver-vault}/ψ/outbox/ack_{msg_id}_{date}.md
```

```markdown
---
msg_id: MSG-PM-001
type: ack
from: god-port
to: pm
---

ACK — รับทราบคำขอ backtest sweep
เริ่มดำเนินการ
```

### 3. รายงานผล (Result)

ผู้รับเมื่อทำเสร็จ:
1. แก้ `status: acknowledged` → `completed`
2. แก้ `result: -` → `result: {สรุปผล}`
3. แก้ `reply_file: -` → `reply_file: {path ไฟล์ผลลัพธ์}`
4. เขียนไฟล์ผลลัพธ์ลง `ψ/outbox/`:

```
{receiver-vault}/ψ/outbox/result_{msg_id}_{date}.md
```

```markdown
---
msg_id: MSG-PM-001
type: result
from: god-port
to: pm
status: success | partial | failed
---

Backtest sweep เสร็จ — ผลลัพธ์:
- Best config: PF 1.63, MaxDD 18.2%, WR 52.1%
- ยังไม่ถึงเป้า WR > 55%
- รายละเอียด: ψ/memory/learnings/backtest-sweep-results.md
```

### 4. บันทึก (Record)

ผู้ส่ง (PM) เมื่ออ่าน ack/result:
1. อัพเดท goal file audit trail
2. อัพเดท CSV status ใน goal file
3. เขียน log ใน `ψ/outbox/` ของตัวเอง

## Message ID Format

```
MSG-{SENDER}-{NNN}
```

- SENDER: pm, god-port, emily
- NNN: running number per sender (001, 002, ...)

PM ติดตาม message ID ใน goal file หรือ `ψ/memory/learnings/message-log.md`

## Status Flow

```
pending → acknowledged → completed
   │           │              │
   │           │              └─ result file written to outbox
   │           └──────── ack file written to outbox
   └──────── inbox file written to target vault
```

## Timeout Rules

PM ตรวจสอบ inbox ของตัวเองและ outbox ของ target:

| เวลาที่ผ่าน | สถานะ | การกระทำ |
|-------------|--------|----------|
| < 1 session | pending | รอต่อ — oracle อาจยังไม่เปิด session |
| > 1 session | pending | `maw peek {oracle}` ตรวจสอบ หรือเขียน reminder ใน inbox |
| > 2 sessions | pending | บันทึกใน goal file: "[TIMEOUT] MSG-PM-001 ไม่ได้รับการตอบ" |
| > 3 sessions | pending | Escalate ถึง emily |

## PM's Tracking Process

1. **ส่ง**: เขียนไฟล์ไป `{target}/ψ/inbox/{date}_{time}_pm_{msg_id}.md`
2. **ตรวจ ack**: อ่าน `{target}/ψ/outbox/ack_{msg_id}_*.md`
3. **ตรวจ result**: อ่าน `{target}/ψ/outbox/result_{msg_id}_*.md`
4. **บันทึก**: อัพเดท goal file audit trail + CSV

## Directory Map (สำหรับ PM)

| Oracle | Inbox (ส่งคำขอไปที่นี่) | Outbox (อ่าน ack/result จากที่นี่) |
|--------|--------------------------|-----------------------------------|
| god-port | `/Users/doctorboyz/Code/github.com/doctorboyz/god-port-oracle/ψ/inbox/` | `/Users/doctorboyz/Code/github.com/doctorboyz/god-port-oracle/ψ/outbox/` |
| emily | `/Users/doctorboyz/Code/github.com/doctorboyz/emily-oracle/ψ/inbox/` | `/Users/doctorboyz/Code/github.com/doctorboyz/emily-oracle/ψ/outbox/` |
| pm (ตัวเอง) | `/Users/doctorboyz/Code/github.com/doctorboyz/pm-oracle/ψ/inbox/` | `/Users/doctorboyz/Code/github.com/doctorboyz/pm-oracle/ψ/outbox/` |