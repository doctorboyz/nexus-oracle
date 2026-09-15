# nexus Oracle — Roadmap

> Set: 2026-05-15 18:25 | Previous: (first roadmap)

## Identity
- **Oracle**: nexus — สายส่งเสียงผ่าน และเข็มทิศนำทาง
- **Human**: doctorboyz
- **Born**: 2026-05-07
- **Theme**: The Nexus — where signals converge and direction begins

## Vision

nexus เป็นศูนย์กลางที่คุยกับ oracle session ได้จริง — อ่าน เขียน แนะนำ โต้ตอบ และขับเคลื่อนตามเป้าหมาย
ไม่ใช่แค่ส่งข้อความแล้วรอ แต่เป็น coordinator ที่ทำให้ทุก oracle ทำงานร่วมกันได้

---

## Active Goals

### G-001: ปิดวงโต้ตอบ — Oracle ตอบกลับ Telegram ได้จริง

**Status**: on-track
**Priority**: critical
**Phase**: short-term
**Definition of Done**: ส่งข้อความใน oracle group → oracle รับใน inbox → oracle เขียนคำตอบใน outbox → nexus ส่งคำตอบกลับ Telegram group — ทั้งวงจบทำงานภายใน 30 วินาที
**Created**: 2026-05-15
**Updated**: 2026-05-15

#### Objectives
| ID | Objective | Status | Evidence | Updated |
|----|-----------|--------|----------|---------|
| O-1 | Smart routing (oracle group → direct, fleet → keyword) | completed | route_by_intent() + 3-tier routing working | 2026-05-14 |
| O-2 | Outbox watcher (oracle outbox → Telegram) | completed | poll_outboxes() + process_outbox_file() tested | 2026-05-14 |
| O-3 | Inbox มี respond_in + outbox protocol hint | completed | deliver_to_oracle() writes respond_in, how-to section | 2026-05-14 |
| O-4 | outbox-write.sh helper script | completed | shared/outbox-write.sh created | 2026-05-14 |
| O-5 | ทดสอบ end-to-end กับ oracle จริง | completed | E2E test: infra outbox → [infra] response in Telegram group #32 | 2026-05-15 |
| O-6 | Oracle CLAUDE.md มี outbox protocol ให้รู้จักตอบ | completed | Added nexus Outbox Protocol to emily, god-port, kappy, infra CLAUDE.md | 2026-05-15 |

#### Blockers
_(none)_

#### Audit Trail
- 2026-05-15 18:25 — roadmap created — status: at-risk (infrastructure done, but oracle doesn't write to outbox yet)
- 2026-05-15 — O-6 completed: added nexus Outbox Protocol section to 4 oracle CLAUDE.md files, blocker resolved
- 2026-05-15 — O-5 completed: E2E test passed — infra outbox → Telegram message #32 in infra group. Fixed misleading log ("sent" for skipped ack files)

---

### G-002: แก้ UX Critical — User ไม่มืดหม่น

**Status**: completed
**Priority**: critical
**Phase**: short-term
**Definition of Done**: ทุก API failure มี feedback ใน Telegram, private chat ไม่เป็นทางตัน, command ทุกอันตอบ error ที่เข้าใจได้
**Created**: 2026-05-15
**Updated**: 2026-05-16

#### Objectives
| ID | Objective | Status | Evidence | Updated |
|----|-----------|--------|----------|---------|
| O-1 | C1: sendMessage fail → แจ้ง user | completed | process_outbox_file sends error notification to private chat on failure | 2026-05-16 |
| O-2 | C2: Private chat → auto-route หรือแนะนำคำสั่ง | completed | forward_to_nexus now tries route_by_intent + suggests /send command | 2026-05-16 |
| O-3 | H1: Auto-wake fail → แจ้ง user | completed | wake_msg shows ⚠️ when auto-wake fails | 2026-05-16 |
| O-4 | H2: Markdown v1 → HTML + escape_html | completed | All commands use HTML parse_mode with escape_html() | 2026-05-16 |
| O-5 | H3: /inbox ใช้ oracle argument จริง | completed | /inbox reads oracle's inbox dir directly, shows file count + last 10 | 2026-05-16 |

#### Blockers
_(none)_

#### Audit Trail
- 2026-05-15 18:25 — roadmap created — status: pending
- 2026-05-16 — all 5 objectives completed, daemon restarted and running

---

### G-003: ความมั่นคง — Daemon ไม่พัง

**Status**: completed
**Priority**: high
**Phase**: mid-term
**Definition of Done**: Shell injection ปิด, retry logic มี, structured logging, dead letter queue, test coverage ≥ 50%
**Created**: 2026-05-15
**Updated**: 2026-05-17

#### Objectives
| ID | Objective | Status | Evidence | Updated |
|----|-----------|--------|----------|---------|
| O-1 | H4: Shell injection — เปลี่ยน shell=True → subprocess list | completed | run_cmd() ใช้ list args ทั้งหมด, ไม่มี shell=True | 2026-05-17 |
| O-2 | retry logic สำหรับ curl_api() + dead letter queue | completed | curl_api retry on timeout (2s backoff), outbox dead letter after 3 retries | 2026-05-17 |
| O-3 | structured logging (logging module แทน print) | completed | logging.basicConfig + logger.info/warning/error ทั้งไฟล์ | 2026-05-17 |
| O-4 | test coverage สำหรับ route_by_intent, process_outbox_file, handle_command | completed | 45 tests ผ่านหมด — route_by_intent, escape_html, run_cmd, curl_api retry, process_outbox_file, dead letter, handle_command, poll_outboxes | 2026-05-17 |
| O-5 | CI/CD — pytest + pm2 restart on deploy | completed | texty/deploy.sh: pytest → pm2 restart → verify | 2026-05-17 |

#### Blockers
_(none — all resolved)_

#### Audit Trail
- 2026-05-15 18:25 — roadmap created — status: pending
- 2026-05-17 — O-1, O-2, O-3 completed: shell injection fixed, API retry + dead letter queue, structured logging
- 2026-05-17 — O-4, O-5 completed: 45 tests passing, deploy script working

---

### G-004: Goal Tracking จริง — ขับเคลื่อนเป้าหมาย

**Status**: pending
**Priority**: high
**Phase**: mid-term
**Definition of Done**: /goals แสดง goal + progress จริง, daemon อ่าน goal files + track evidence, auto-escalate blockers, cross-oracle goal visibility
**Created**: 2026-05-15
**Updated**: 2026-05-15

#### Objectives
| ID | Objective | Status | Evidence | Updated |
|----|-----------|--------|----------|---------|
| O-1 | /goals อ่าน goal files + แสดง progress | pending | — | 2026-05-15 |
| O-2 | Goal format มี objectives + evidence + blockers | pending | — | 2026-05-15 |
| O-3 | Auto-escalate: blocker > 2 session → แจ้ง emily | pending | — | 2026-05-15 |
| O-4 | Cross-oracle: goal ที่ต้องหลาย oracle มองเห็นได้ | pending | — | 2026-05-15 |
| O-5 | /goal <id> แสดงรายละเอียด + audit trail | pending | — | 2026-05-15 |

#### Blockers
- [CAPABILITY] ต้องออกแบบ goal file format ให้เข้ากับ MSG-ACK-RESULT protocol

#### Audit Trail
- 2026-05-15 18:25 — roadmap created — status: pending

---

### G-005: Inbox Auto-Processing — Oracle คุยกันได้

**Status**: pending
**Priority**: medium
**Phase**: long-term
**Definition of Done**: ข้อความจาก oracle อื่นใน nexus inbox → daemon อ่าน → ประเมิน type → dispatch หรือ coordinate อัตโนมัติ → ตอบกลับ oracle ผ่าน outbox
**Created**: 2026-05-15
**Updated**: 2026-05-15

#### Objectives
| ID | Objective | Status | Evidence | Updated |
|----|-----------|--------|----------|---------|
| O-1 | Inbox watcher → ส่ง Telegram แทน macOS notification เฉยๆ | pending | — | 2026-05-15 |
| O-2 | อ่าน inbox type → ตัดสินใจ dispatch หรือ coordinate | pending | — | 2026-05-15 |
| O-3 | Auto-ack สำหรับ info-type messages | pending | — | 2026-05-15 |
| O-4 | Auto-result สำหรับ status queries | pending | — | 2026-05-15 |
| O-5 | Escalation-type → ส่งต่อ human ทันที | pending | — | 2026-05-15 |

#### Blockers
- [DEPENDENCY] G-001 ต้องเสร็จก่อน (outbox protocol ต้องทำงาน)

#### Audit Trail
- 2026-05-15 18:25 — roadmap created — status: pending

---

### G-006: Session Lifecycle — ตื่น-ทำ-สรุป-หลับ

**Status**: pending
**Priority**: medium
**Phase**: long-term
**Definition of Done**: Oracle session จบ → auto summary → ส่ง Telegram → อัปเดต goal → archive inbox → sleep. ทั้งวงจรอัตโนมัติ
**Created**: 2026-05-15
**Updated**: 2026-05-15

#### Objectives
| ID | Objective | Status | Evidence | Updated |
|----|-----------|--------|----------|---------|
| O-1 | Stop hook ส่ง session summary อัตโนมัติ | pending | inject-hook.sh exists but not wired | 2026-05-15 |
| O-2 | Session summary → ส่ง Telegram group | pending | session-summary.sh exists | 2026-05-15 |
| O-3 | Session summary → อัปเดต goal evidence | pending | — | 2026-05-15 |
| O-4 | Archive processed inbox on session end | pending | — | 2026-05-15 |
| O-5 | Auto-sleep oracle หลัง idle timeout | pending | — | 2026-05-15 |

#### Blockers
- [DEPENDENCY] G-004 goal tracking ต้องทำงานก่อน

#### Audit Trail
- 2026-05-15 18:25 — roadmap created — status: pending

---

## Completed Goals
_(none yet)_

## Archived Roadmaps
_(none — first roadmap)_