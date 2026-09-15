#!/usr/bin/env python3
"""
migrate_to_db.py — Migrate existing file-based inbox/outbox/dispatch to PostgreSQL.

Reads YAML-frontmatter .md files from nexus-oracle ψ/ directories and imports
them into the nexus database tables (messages, activity_log).

Principle 1: Original files are NOT deleted — they remain as historical archive.
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

NEXUS_ROOT = Path(os.environ.get("NEXUS_ROOT", Path(__file__).resolve().parent.parent))
PSI_DIR = NEXUS_ROOT / "ψ"
DB_URL = os.environ.get("NEXUS_DATABASE_URL", "postgresql://admin:88888888@localhost:5432/nexus")

YAML_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(filepath: Path) -> dict | None:
    """Parse YAML-style frontmatter from a .md file."""
    text = filepath.read_text()
    m = YAML_FRONT_RE.match(text)
    if not m:
        return None
    fm = {}
    for line in m.group(1).strip().split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"')
            fm[key] = val
    # Content is everything after the frontmatter
    content = YAML_FRONT_RE.sub("", text).strip()
    fm["_content"] = content
    fm["_filepath"] = str(filepath)
    return fm


async def migrate_inbox(conn: asyncpg.Connection):
    """Migrate inbox files to messages table."""
    inbox_dir = PSI_DIR / "inbox"
    if not inbox_dir.exists():
        print(f"[skip] No inbox directory at {inbox_dir}")
        return 0

    count = 0
    for f in sorted(inbox_dir.glob("*.md")):
        fm = parse_frontmatter(f)
        if not fm:
            continue

        msg_id = fm.get("msg_id", f"MSG-MIGRATED-{count:03d}")
        from_oracle = fm.get("from", "unknown")
        to_oracle = fm.get("to", "nexus")
        msg_type = fm.get("type", "info")
        status = fm.get("status", "completed")
        content = fm.get("_content", "")

        # Check if already exists
        existing = await conn.fetchrow(
            "SELECT id FROM messages WHERE msg_id = $1", msg_id
        )
        if existing:
            continue

        await conn.execute(
            """
            INSERT INTO messages (msg_id, from_oracle, to_oracle, type, status,
                                  content, respond_in, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (msg_id) DO NOTHING
            """,
            msg_id,
            from_oracle,
            to_oracle,
            msg_type,
            status,
            content,
            fm.get("respond_in"),
            fm.get("sent", str(datetime.now(timezone.utc))),
        )
        count += 1

    return count


async def migrate_outbox(conn: asyncpg.Connection):
    """Migrate outbox files to messages table."""
    outbox_dir = PSI_DIR / "outbox"
    if not outbox_dir.exists():
        print(f"[skip] No outbox directory at {outbox_dir}")
        return 0

    count = 0
    for f in sorted(outbox_dir.glob("*.md")):
        fm = parse_frontmatter(f)
        if not fm:
            continue

        msg_id = fm.get("msg_id", f"MSG-MIGRATED-OUT-{count:03d}")
        from_oracle = fm.get("from", "nexus")
        to_oracle = fm.get("to", "unknown")
        msg_type = fm.get("type", "result")
        content = fm.get("_content", "")

        existing = await conn.fetchrow(
            "SELECT id FROM messages WHERE msg_id = $1", msg_id
        )
        if existing:
            continue

        await conn.execute(
            """
            INSERT INTO messages (msg_id, from_oracle, to_oracle, type, status,
                                  content, respond_in, created_at)
            VALUES ($1, $2, $3, $4, 'completed', $5, $6, $7)
            ON CONFLICT (msg_id) DO NOTHING
            """,
            msg_id,
            from_oracle,
            to_oracle,
            msg_type,
            content,
            fm.get("respond_in"),
            fm.get("sent") or fm.get("timestamp", str(datetime.now(timezone.utc))),
        )
        count += 1

    return count


async def migrate_dispatch(conn: asyncpg.Connection):
    """Migrate dispatch logs to messages + activity_log."""
    dispatch_dir = PSI_DIR / "dispatch"
    if not dispatch_dir.exists():
        print(f"[skip] No dispatch directory at {dispatch_dir}")
        return 0

    count = 0
    for f in sorted(dispatch_dir.rglob("*.md")):
        fm = parse_frontmatter(f)
        if not fm:
            continue

        dispatch_id = fm.get("dispatch_id", f"DSP-MIGRATED-{count:03d}")
        from_oracle = fm.get("from", "nexus")
        to_target = fm.get("to", "human (Telegram)")
        msg_type = fm.get("type", "info")
        content = fm.get("_content", "")

        existing = await conn.fetchrow(
            "SELECT id FROM messages WHERE msg_id = $1", dispatch_id
        )
        if existing:
            continue

        await conn.execute(
            """
            INSERT INTO messages (msg_id, from_oracle, to_oracle, type, status,
                                  content, created_at)
            VALUES ($1, $2, $3, $4, 'completed', $5, $6)
            ON CONFLICT (msg_id) DO NOTHING
            """,
            dispatch_id,
            from_oracle,
            to_target,
            msg_type,
            content,
            fm.get("sent", str(datetime.now(timezone.utc))),
        )
        count += 1

    return count


async def main():
    print(f"[migrate_to_db] Nexus root: {NEXUS_ROOT}")
    print(f"[migrate_to_db] Database: {DB_URL}")

    conn = await asyncpg.connect(DB_URL)

    inbox_count = await migrate_inbox(conn)
    print(f"[migrate] Inbox: {inbox_count} messages migrated")

    outbox_count = await migrate_outbox(conn)
    print(f"[migrate] Outbox: {outbox_count} messages migrated")

    dispatch_count = await migrate_dispatch(conn)
    print(f"[migrate] Dispatch: {dispatch_count} messages migrated")

    total = inbox_count + outbox_count + dispatch_count
    print(f"[migrate] Total: {total} messages migrated to database")

    await conn.close()
    print("[migrate] Done — original files preserved in ψ/")


if __name__ == "__main__":
    asyncio.run(main())
