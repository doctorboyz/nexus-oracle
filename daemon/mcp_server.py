"""MCP server for nexus Oracle — coordination tools for the fleet.

Tools:
  oracle_send      — Send a message to an oracle
  oracle_status    — Get status of all registered oracles
  oracle_broadcast — Broadcast a message to all oracles
  oracle_wake      — Wake an oracle session (maw wake)
  oracle_sleep     — Put an oracle to sleep (maw sleep)

Principle 1: Nothing is Deleted — all writes are INSERTs.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys

# Ensure daemon/ is importable from project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logger = logging.getLogger("nexus.mcp")

# ─── Tool Definitions ───────────────────────────────────────────────

TOOLS = [
    Tool(
        name="oracle_send",
        description="Send a message to a specific oracle. Message will be delivered "
                    "to their inbox and the oracle will be auto-woken if offline.",
        inputSchema={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Target oracle name (e.g. emily, dev, mkt, infra)",
                },
                "message": {
                    "type": "string",
                    "description": "Message content to send",
                },
                "msg_type": {
                    "type": "string",
                    "description": "Message type: task, query, info, escalation",
                    "default": "query",
                },
            },
            "required": ["to", "message"],
        },
    ),
    Tool(
        name="oracle_status",
        description="Get the current status of all registered oracles: "
                    "which are active, idle, workload, active goals and tasks.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="oracle_broadcast",
        description="Broadcast a message to all registered oracles simultaneously.",
        inputSchema={
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Broadcast message content",
                },
                "msg_type": {
                    "type": "string",
                    "description": "Message type: info, task, escalation",
                    "default": "info",
                },
            },
            "required": ["message"],
        },
    ),
    Tool(
        name="oracle_wake",
        description="Wake an oracle — start its Claude Code session via maw.",
        inputSchema={
            "type": "object",
            "properties": {
                "oracle": {
                    "type": "string",
                    "description": "Oracle name to wake (e.g. emily, dev, infra)",
                },
            },
            "required": ["oracle"],
        },
    ),
    Tool(
        name="oracle_sleep",
        description="Put an oracle to sleep — stop its Claude Code session via maw.",
        inputSchema={
            "type": "object",
            "properties": {
                "oracle": {
                    "type": "string",
                    "description": "Oracle name to sleep (e.g. emily, dev, infra)",
                },
            },
            "required": ["oracle"],
        },
    ),
]

# ─── FleetDB Integration ─────────────────────────────────────────────

_fleetdb_initialized = False


async def _ensure_fleetdb():
    """Initialize fleetdb on first use (tables + registry sync)."""
    global _fleetdb_initialized
    if _fleetdb_initialized:
        return
    from daemon import fleetdb as fdb
    try:
        await fdb.init_fleet_db()
    except Exception:
        # Tables may already exist — sync registry directly
        await fdb.sync_oracle_registry()
    _fleetdb_initialized = True


async def _get_fleetdb():
    """Get fleetdb module, ensuring it's initialized."""
    await _ensure_fleetdb()
    from daemon import fleetdb as fdb
    return fdb


# ─── Maw CLI Integration ─────────────────────────────────────────────

def _run_maw(args: list[str], timeout: int = 20) -> str:
    """Run a maw CLI command and return output."""
    try:
        result = subprocess.run(
            ["maw"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout.strip()
        if result.stderr and not output:
            output = result.stderr.strip()
        return output[:4000] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out (20s)"
    except Exception as e:
        return f"Error: {e}"


# ─── Tool Implementations ────────────────────────────────────────────

async def _handle_oracle_send(arguments: dict) -> list[TextContent]:
    """Send a message to an oracle via fleetdb + maw inbox."""
    to_oracle = arguments["to"]
    message = arguments["message"]
    msg_type = arguments.get("msg_type", "query")

    fdb = await _get_fleetdb()

    # 1. Write to fleetdb (NOTIFY triggers will fire)
    db_result = await fdb.create_message(
        "nexus", to_oracle, msg_type, message,
    )

    # 2. Deliver via maw inbox send (file-based for oracle session visibility)
    inbox_output = _run_maw(["inbox", "send", to_oracle, message])

    # 3. Auto-wake if oracle is offline
    wake_output = _run_maw(["wake", to_oracle], timeout=15)

    result = {
        "msg_id": db_result.get("msg_id", "unknown") if db_result else "unknown",
        "to": to_oracle,
        "type": msg_type,
        "db_written": db_result is not None,
        "inbox_delivered": "Error" not in inbox_output and "not found" not in inbox_output,
        "wake_attempted": True,
        "maw_output": wake_output[:500],
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def _handle_oracle_status(arguments: dict) -> list[TextContent]:
    """Get fleet status from fleetdb + maw."""
    fdb = await _get_fleetdb()
    db_status = await fdb.get_fleet_status()

    # Enrich with maw fleet ls
    maw_output = _run_maw(["fleet", "ls"])

    result = {
        "oracles": db_status,
        "count": len(db_status),
        "maw_fleet": maw_output,
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def _handle_oracle_broadcast(arguments: dict) -> list[TextContent]:
    """Broadcast a message to all registered oracles."""
    message = arguments["message"]
    msg_type = arguments.get("msg_type", "info")

    fdb = await _get_fleetdb()

    # Get all oracle names from fleetdb status
    status_list = await fdb.get_fleet_status()
    oracle_names = [s.get("name") for s in status_list if s.get("name") != "nexus"]

    results = {}
    for oracle in oracle_names:
        db_result = await fdb.create_message("nexus", oracle, msg_type, message)
        inbox_output = _run_maw(["inbox", "send", oracle, message])
        results[oracle] = {
            "db_written": db_result is not None,
            "inbox_delivered": "Error" not in inbox_output and "not found" not in inbox_output,
        }

    result = {
        "broadcast_to": len(results),
        "results": results,
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def _handle_oracle_wake(arguments: dict) -> list[TextContent]:
    """Wake an oracle via maw wake."""
    oracle = arguments["oracle"]
    output = _run_maw(["wake", oracle])

    # Update oracle state in fleetdb
    fdb = await _get_fleetdb()
    if "running" in output.lower() or "started" in output.lower():
        await fdb.update_oracle_state(oracle, "active")
    await fdb.log_activity("wake", oracle, detail=output[:500])

    result = {
        "oracle": oracle,
        "output": output,
        "status": "wake_attempted",
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_oracle_sleep(arguments: dict) -> list[TextContent]:
    """Put an oracle to sleep via maw sleep."""
    oracle = arguments["oracle"]
    output = _run_maw(["sleep", oracle])

    # Update oracle state in fleetdb
    fdb = await _get_fleetdb()
    await fdb.update_oracle_state(oracle, "idle")
    await fdb.log_activity("sleep", oracle, detail=output[:500])

    result = {
        "oracle": oracle,
        "output": output,
        "status": "sleep_attempted",
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# ─── Server Factory ──────────────────────────────────────────────────

async def create_app():
    server = Server("nexus")

    @server.list_tools()
    async def list_tools():
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            if name == "oracle_send":
                return await _handle_oracle_send(arguments)
            elif name == "oracle_status":
                return await _handle_oracle_status(arguments)
            elif name == "oracle_broadcast":
                return await _handle_oracle_broadcast(arguments)
            elif name == "oracle_wake":
                return await _handle_oracle_wake(arguments)
            elif name == "oracle_sleep":
                return await _handle_oracle_sleep(arguments)
            else:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": f"Unknown tool: {name}"}),
                )]
        except Exception as e:
            logger.exception(f"Tool {name} failed")
            return [TextContent(
                type="text",
                text=json.dumps({"error": f"Tool failed: {e}"}),
            )]

    return server


async def run_server():
    app = await create_app()
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_server())
