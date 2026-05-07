# Dispatch Guide — texty Oracle

## ประเภทข้อความและการจัดการ

### escalation
- 🚨 ส่งต่อทันทีผ่าน Telegram
- ไม่ต้องรอ — ส่งเลยพร้อม sound alert
- ตัวอย่าง: Oracle พบ critical error, ต้องการ human intervention

### query
- ❓ ส่งต่อพร้อม context ที่ค้นหาจาก vault
- ก่อนส่ง: scan vault ของ oracle ที่ถามเพื่อเติม context
- ตัวอย่าง: "สถานะ MT5 ยังไง?" → ส่ง context จาก god-port vault

### task
- ✅ ส่งต่อพร้อม approval poll
- ใช้ `telegram-create-poll` เพื่อให้มนุษย์ approve/reject
- ตัวอย่าง: "ขออนุมัติ deploy version X"

### info
- ℹ️ ACK อัตโนมัติ — ไม่ต้องส่ง Telegram
- เขียนใน dispatch log ว่า received + auto-acked
- ตัวอย่าง: "build completed", "test passed"

## ขั้นตอน Dispatch

1. อ่าน inbox messages (`maw inbox ls` หรืออ่าน ψ/inbox/ โดยตรง)
2. ประเมิน type ของแต่ละ message
3. สำหรับ escalation/query/task → ส่งต่อ Telegram
4. สำหรับ info → ACK อัตโนมัติ + log
5. รอ human response (อ่าน Telegram messages)
6. แปลง response → MSG-RESULT
7. เขียน result กลับไปยัง oracle ที่ถาม
8. Log ทุก dispatch ใน ψ/dispatch/

## Response Format

เมื่อส่งต่อไปยัง Telegram ใช้ format:

```
[texty] TYPE from {oracle}: {message}

Context: {summary from vault}
```

เมื่อได้รับคำตอบจากมนุษย์ → ส่งกลับ:

```
maw inbox result {msg_id} "{human_response}"
```