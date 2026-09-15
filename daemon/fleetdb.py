"""
fleetdb.py — asyncpg-based fleet database operations for nexus Oracle.

Principle 1: Nothing is Deleted — all writes are INSERTs or status transitions.
Event-driven: LISTEN/NOTIFY replaces file-system polling.
"""

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import asyncpg

# ─── Configuration ─────────────────────────────────────────────────

DEFAULT_DB_URL = "postgresql://admin:88888888@localhost:5432/nexus"
FLEET_CONFIG_DIR = Path.home() / ".config" / "maw" / "fleet"

DATABASE_URL = os.environ.get("NEXUS_DATABASE_URL", DEFAULT_DB_URL)

# ─── Connection Pool ───────────────────────────────────────────────

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def ensure_tables():
    """Run schema.sql to ensure all tables exist."""
    pool = await get_pool()
    schema_path = Path(__file__).parent / "schema.sql"
    if not schema_path.exists():
        return
    async with pool.acquire() as conn:
        sql = schema_path.read_text()
        # Execute schema in a transaction — skip errors for existing objects
        await conn.execute(sql)


# ─── Oracle Registry ───────────────────────────────────────────────

async def sync_oracle_registry():
    """Sync oracle_status table from fleet config files (~/.config/maw/fleet/*.json)."""
    pool = await get_pool()
    if not FLEET_CONFIG_DIR.exists():
        return

    fleet_files = sorted(FLEET_CONFIG_DIR.glob("*.json"))
    async with pool.acquire() as conn:
        for fp in fleet_files:
            try:
                config = json.loads(fp.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            name = config.get("name", "")
            if not name:
                continue

            fleet_id_match = re.match(r"^(\\d{2})", fp.stem)
            fleet_id = f"{fleet_id_match.group(1)}-{name}" if fleet_id_match else name

            await conn.execute(
                """
                INSERT INTO oracle_status (name, fleet_id, metadata)
                VALUES ($1, $2, $3)
                ON CONFLICT (name) DO UPDATE
                    SET fleet_id = EXCLUDED.fleet_id,
                        metadata = EXCLUDED.metadata,
                        updated_at = now()
                """,
                name,
                fleet_id,
                json.dumps({
                    "sync_peers": config.get("sync_peers", []),
                    "auto_wake": config.get("auto_wake", False),
                    "routing": config.get("routing", {}),
                }),
            )


async def get_fleet_status() -> list[dict[str, Any]]:
    """Get status of all registered oracles."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT name, fleet_id, state, last_seen, session_count,
                   active_goals, active_tasks, workload_pct, updated_at
            FROM oracle_status
            ORDER BY fleet_id
            """
        )
    return [dict(r) for r in rows]


async def get_oracle_workload(oracle_name: str) -> dict[str, Any]:
    """Get workload summary for a specific oracle."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT name, state, active_goals, active_tasks, workload_pct,
                   last_seen, session_count
            FROM oracle_status
            WHERE name = $1
            """,
            oracle_name,
        )
    return dict(row) if row else {}


async def update_oracle_state(oracle_name: str, state: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO oracle_status (name, state, last_seen)
            VALUES ($1, $2::oracle_state, now())
            ON CONFLICT (name) DO UPDATE
                SET state = EXCLUDED.state,
                    last_seen = EXCLUDED.last_seen,
                    updated_at = now()
            """,
            oracle_name,
            state,
        )


# ─── Messages ──────────────────────────────────────────────────────

def _generate_msg_id(from_oracle: str) -> str:
    """Generate human-readable message ID: MSG-{FROM}-{counter}"""
    return f"MSG-{from_oracle.upper()}"


async def _next_msg_counter(from_oracle: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) + 1 AS n FROM messages WHERE from_oracle = $1",
            from_oracle,
        )
    return row["n"] if row else 1


async def create_message(
    from_oracle: str,
    to_oracle: str,
    msg_type: str,
    content: str,
    *,
    respond_in: Optional[str] = None,
    reply_to_msg_id: Optional[str] = None,
    content_json: Optional[dict] = None,
    priority: int = 0,
    conversation_id: Optional[int] = None,
) -> dict[str, Any]:
    """Create a new message. Returns the created row."""
    pool = await get_pool()
    prefix = _generate_msg_id(from_oracle)
    counter = await _next_msg_counter(from_oracle)
    msg_id = f"{prefix}-{counter:03d}"

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO messages (msg_id, from_oracle, to_oracle, type, content,
                                  content_json, respond_in, reply_to_msg_id,
                                  priority, conversation_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *
            """,
            msg_id,
            from_oracle,
            to_oracle,
            msg_type,
            content,
            json.dumps(content_json or {}),
            respond_in,
            reply_to_msg_id,
            priority,
            conversation_id,
        )
    return dict(row)


async def update_message_status(msg_id: str, status: str):
    """Transition a message to a new status."""
    pool = await get_pool()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE messages
            SET status = $2::message_status,
                updated_at = $3,
                ack_at = CASE WHEN $2::text = 'acknowledged' THEN $3 ELSE ack_at END,
                completed_at = CASE WHEN $2::text = 'completed' THEN $3 ELSE completed_at END
            WHERE msg_id = $1
            """,
            msg_id,
            status,
            now,
        )


async def get_pending_messages_for(oracle_name: str) -> list[dict[str, Any]]:
    """Get all pending messages for an oracle."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM messages
            WHERE to_oracle = $1 AND status = 'pending'
            ORDER BY priority DESC, created_at ASC
            """,
            oracle_name,
        )
    return [dict(r) for r in rows]


async def get_outbox_messages(oracle_name: str) -> list[dict[str, Any]]:
    """Get outbox messages (sent by oracle, pending delivery)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM messages
            WHERE from_oracle = $1 AND status IN ('pending', 'in_progress')
            ORDER BY created_at ASC
            """,
            oracle_name,
        )
    return [dict(r) for r in rows]


async def mark_message_delivered(msg_id: str):
    """Mark message as completed (delivered to recipient)."""
    await update_message_status(msg_id, "completed")


async def get_message(msg_id: str) -> Optional[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM messages WHERE msg_id = $1", msg_id)
    return dict(row) if row else None


async def get_recent_messages(limit: int = 50) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM messages ORDER BY created_at DESC LIMIT $1", limit
        )
    return [dict(r) for r in rows]


# ─── Goals ─────────────────────────────────────────────────────────

async def create_goal(
    title: str,
    oracle_owner: str,
    *,
    description: Optional[str] = None,
    priority: int = 0,
    tags: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) + 1 AS n FROM goals"
        )
    goal_id = f"GOAL-{row['n']:03d}" if row else "GOAL-001"

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO goals (goal_id, title, description, oracle_owner,
                               priority, tags, metadata, started_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, now())
            RETURNING *
            """,
            goal_id,
            title,
            description,
            oracle_owner,
            priority,
            tags or [],
            json.dumps(metadata or {}),
        )
    return dict(row)


async def update_goal_progress(goal_id: str, progress_pct: int, note: str, oracle_name: str):
    """Update goal progress with append-only log entry (Principle 1)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE goals SET progress_pct = $2, updated_at = now() WHERE goal_id = $1",
            goal_id,
            progress_pct,
        )
        await conn.execute(
            """
            INSERT INTO goal_progress_log (goal_id, oracle_name, progress_pct, note)
            VALUES ($1, $2, $3, $4)
            """,
            goal_id,
            oracle_name,
            progress_pct,
            note,
        )


async def complete_goal(goal_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE goals
            SET status = 'completed', progress_pct = 100,
                completed_at = now(), updated_at = now()
            WHERE goal_id = $1
            """,
            goal_id,
        )


async def get_active_goals(oracle_name: Optional[str] = None) -> list[dict[str, Any]]:
    pool = await get_pool()
    if oracle_name:
        rows = await pool.fetch(
            "SELECT * FROM goals WHERE oracle_owner = $1 AND status = 'active' ORDER BY priority DESC",
            oracle_name,
        )
    else:
        rows = await pool.fetch(
            "SELECT * FROM goals WHERE status = 'active' ORDER BY priority DESC"
        )
    return [dict(r) for r in rows]


async def get_goal_progress_history(goal_id: str) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM goal_progress_log WHERE goal_id = $1 ORDER BY created_at ASC",
            goal_id,
        )
    return [dict(r) for r in rows]


# ─── Tasks ─────────────────────────────────────────────────────────

async def create_task(
    goal_id: str,
    title: str,
    *,
    description: Optional[str] = None,
    assigned_oracle: Optional[str] = None,
    priority: int = 0,
    depends_on: Optional[list[int]] = None,
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) + 1 AS n FROM tasks")
    task_id = f"TASK-{row['n']:03d}" if row else "TASK-001"

    status = "assigned" if assigned_oracle else "pending"

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO tasks (task_id, goal_id, title, description, assigned_oracle,
                               priority, depends_on, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::task_status)
            RETURNING *
            """,
            task_id,
            goal_id,
            title,
            description,
            assigned_oracle,
            priority,
            depends_on or [],
            status,
        )
    return dict(row)


async def assign_task(task_id: str, oracle_name: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE tasks
            SET assigned_oracle = $2, status = 'assigned', updated_at = now()
            WHERE task_id = $1
            """,
            task_id,
            oracle_name,
        )


async def update_task_status(task_id: str, status: str, oracle_name: Optional[str] = None):
    """Update task status with timestamps."""
    pool = await get_pool()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE tasks
            SET status = $2::task_status,
                updated_at = $3,
                started_at = CASE WHEN $2::text = 'in_progress' AND started_at IS NULL THEN $3 ELSE started_at END,
                completed_at = CASE WHEN $2::text = 'completed' THEN $3 ELSE completed_at END
            WHERE task_id = $1
            """,
            task_id,
            status,
            now,
        )


async def get_tasks_for_goal(goal_id: str) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM tasks WHERE goal_id = $1 ORDER BY priority DESC, created_at ASC",
            goal_id,
        )
    return [dict(r) for r in rows]


async def get_tasks_for_oracle(oracle_name: str) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM tasks
            WHERE assigned_oracle = $1 AND status NOT IN ('completed', 'cancelled')
            ORDER BY priority DESC, created_at ASC
            """,
            oracle_name,
        )
    return [dict(r) for r in rows]


# ─── Conversations ─────────────────────────────────────────────────

async def get_or_create_conversation(
    chat_id: str, conv_type: str = "group", title: Optional[str] = None
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO conversations (chat_id, type, title)
            VALUES ($1, $2, $3)
            ON CONFLICT (chat_id) DO UPDATE
                SET title = COALESCE(EXCLUDED.title, conversations.title),
                    updated_at = now()
            RETURNING *
            """,
            chat_id,
            conv_type,
            title,
        )
    return dict(row)


# ─── Activity Log ──────────────────────────────────────────────────

async def log_activity(
    activity_type: str,
    oracle_name: str,
    *,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    detail: Optional[str] = None,
    metadata: Optional[dict] = None,
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO activity_log (activity_type, oracle_name, entity_type, entity_id, detail, metadata)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            activity_type,
            oracle_name,
            entity_type,
            entity_id,
            detail,
            json.dumps(metadata or {}),
        )


# ─── Event Listener (LISTEN/NOTIFY) ────────────────────────────────

async def listen_events(
    on_message_change: Optional[callable] = None,
    on_goal_progress: Optional[callable] = None,
    on_oracle_state: Optional[callable] = None,
    on_activity: Optional[callable] = None,
):
    """
    Listen for PostgreSQL NOTIFY events and dispatch to callbacks.

    Usage:
        asyncio.create_task(listen_events(
            on_message_change=lambda p: print(f"New message: {p}"),
            on_goal_progress=lambda p: print(f"Progress: {p}"),
        ))
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        for channel in ("message_change", "goal_progress", "oracle_state", "activity"):
            await conn.add_listener(channel, lambda *args: None)  # register
            await conn.execute(f"LISTEN {channel}")

        callbacks = {
            "message_change": on_message_change,
            "goal_progress": on_goal_progress,
            "oracle_state": on_oracle_state,
            "activity": on_activity,
        }

        while True:
            try:
                notification = await asyncio.wait_for(conn.get_notify(), timeout=30.0)
                cb = callbacks.get(notification.channel)
                if cb and notification.payload:
                    payload = json.loads(notification.payload)
                    cb(payload)
            except asyncio.TimeoutError:
                continue
            except Exception:
                await asyncio.sleep(1)


# ─── Initialization ────────────────────────────────────────────────

async def init_fleet_db():
    """Initialize fleet database: ensure tables, sync registry."""
    await ensure_tables()
    await sync_oracle_registry()
    print("[fleetdb] Database initialized — tables ensured, registry synced")
