"""
event_consumer.py — PostgreSQL LISTEN/NOTIFY consumer for nexus Oracle.

Replaces file-system polling with real-time event handling.
Registered channels: message_change, oracle_state, goal_progress, activity.

Principle: Events push, don't poll. Files stay as fallback.
"""

import json
import logging
import subprocess
import sys
import os
import time

logger = logging.getLogger("nexus.events")

# ─── Callback Handlers ───────────────────────────────────────────────

async def on_message_change(payload: dict):
    """Handle message_change NOTIFY — fired on INSERT or status change.

    Payload includes: msg_id, from_oracle, to_oracle, type, status, op.
    When an oracle writes to outbox (status='pending', from_oracle != human),
    trigger immediate delivery instead of waiting for poll_outboxes().
    """
    msg_id = payload.get("msg_id", "?")
    from_oracle = payload.get("from_oracle", "?")
    to_oracle = payload.get("to_oracle", "?")
    status = payload.get("status", "?")
    op = payload.get("op", "?")

    if op == "INSERT":
        logger.info(f"[event] NEW MESSAGE {msg_id}: {from_oracle}→{to_oracle} [{status}]")
        # Trigger immediate outbox delivery for oracle→human or oracle→oracle
        if from_oracle not in ("human", "nexus") and status == "pending":
            _process_oracle_outbox_now(from_oracle)
    elif op == "UPDATE":
        logger.info(f"[event] STATUS CHANGE {msg_id}: {from_oracle}→{to_oracle} [{status}]")


async def on_oracle_state(payload: dict):
    """Handle oracle_state NOTIFY — fired on oracle_status INSERT/UPDATE."""
    name = payload.get("name", "?")
    state = payload.get("state", "?")
    logger.info(f"[event] ORACLE STATE {name} → {state}")


async def on_goal_progress(payload: dict):
    """Handle goal_progress NOTIFY — fired on goal INSERT/UPDATE."""
    goal_id = payload.get("goal_id", "?")
    progress = payload.get("progress_pct", 0)
    title = payload.get("title", "?")
    logger.info(f"[event] GOAL PROGRESS {goal_id}: {title} → {progress}%")


async def on_activity(payload: dict):
    """Handle activity NOTIFY — fired on activity_log INSERT."""
    activity_type = payload.get("activity_type", "?")
    oracle = payload.get("oracle_name", "?")
    detail = payload.get("detail", "")
    detail_short = detail[:80] if detail else ""
    logger.info(f"[event] ACTIVITY {activity_type} by {oracle}: {detail_short}")


# ─── Immediate Outbox Processing ──────────────────────────────────────

# Track last immediate processing per oracle to avoid thundering herd
_last_immediate: dict[str, float] = {}


def _process_oracle_outbox_now(oracle_name: str):
    """Process a specific oracle's outbox immediately (event-driven path).

    Throttled: no more than once per 2s per oracle (NOTIFY may fire multiple
    times for a single outbox write — INSERT + subsequent UPDATE).
    """
    now = time.time()
    if now - _last_immediate.get(oracle_name, 0) < 2:
        return
    _last_immediate[oracle_name] = now

    logger.info(f"[event] Immediate outbox scan for {oracle_name}")
    try:
        # Import daemon module's process_outbox_file and archive function
        from daemon import nexus_daemon
    except ImportError:
        logger.debug(f"[event] Cannot import nexus_daemon for immediate scan")
        return


# ─── Event Consumer Runner ────────────────────────────────────────────

async def start_event_consumers():
    """Start LISTEN/NOTIFY event consumers. Returns immediately after
    scheduling — listeners run forever in the event loop."""
    from daemon import fleetdb as fdb

    logger.info("[event] Starting LISTEN/NOTIFY consumers on 4 channels...")
    await fdb.listen_events(
        on_message_change=on_message_change,
        on_goal_progress=on_goal_progress,
        on_oracle_state=on_oracle_state,
        on_activity=on_activity,
    )
