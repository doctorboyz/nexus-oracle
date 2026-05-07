# Telegram Setup Guide — texty Oracle

## Chat ID Discovery

เพื่อให้ texty ส่งข้อความถึงมนุษย์ได้ ต้องได้ chat_id ก่อน:

1. เปิด Telegram แล้วส่งข้อความอะไรก็ได้ไปยัง bot หรือ chat ที่ต้องการ
2. ใช้ `telegram-get-unread` เพื่อดู chat list
3. หา chat_id จาก chat list

## Configuration

เก็บ chat_id ใน `ψ/credentials/telegram.json`:

```json
{
  "chat_id": "YOUR_CHAT_ID_HERE",
  "note": "Get chat_id by messaging @userinfobot",
  "created": "2026-04-29"
}
```

## Verification

หลังตั้งค่า chat_id แล้ว:

1. ทดสอบส่งข้อความ: `telegram-send-message chatId: "<chat_id>" text: "[texty] test dispatch"`
2. ยืนยันว่ามนุษย์ได้รับข้อความ

## Rate Limiting

- Telegram จำกัดการส่งข้อความ: ~30 messages/second ไปยังผู้ใช้คนเดียว
- สำหรับ texty: ส่งข้อความได้ไม่เกิน 1 ข้อความต่อ oracle ต่อนาที
- ถ้ามีหลาย escalation พร้อมกัน → รวมเป็นข้อความเดียว

## Poll for Approval

สำหรับ task ที่ต้องการ approval ให้สร้าง poll แทนข้อความธรรมดา:

```
telegram-create-poll
  chatId: "<chat_id>"
  question: "[texty] TASK from {oracle}: {description}"
  answers: ["Approve", "Reject", "Need more info"]
```

เช็ค poll results:

```
telegram-get-poll-results
  chatId: "<chat_id>"
  messageId: <poll_message_id>
```