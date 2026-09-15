#!/usr/bin/env bash
# db-query.sh — Query the nexus fleet database from any oracle
# Usage: db-query.sh <command> [args...]
#
# Commands:
#   inbox <oracle>          List pending messages for an oracle
#   outbox <oracle>         List outgoing messages from an oracle
#   fleet                   Show fleet status
#   goals [oracle]          Show active goals (filter by oracle)
#   tasks <goal_id>         Show tasks for a goal
#   workload <oracle>       Show oracle workload
#   recent [n]              Show recent messages (default 20)
#   status <msg_id>         Show message status
#   activity [n]            Show recent activity log (default 20)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NEXUS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DB_URL="${NEXUS_DATABASE_URL:-postgresql://admin:88888888@localhost:5432/nexus}"

# Try psql first, fall back to Python
if command -v psql &>/dev/null; then
  USE_PSQL=true
elif command -v python3 &>/dev/null; then
  USE_PSQL=false
else
  echo "Error: psql or python3 required"
  exit 1
fi

cmd="${1:-help}"
shift || true

case "$cmd" in
  inbox)
    oracle="${1:-}"
    if [[ -z "$oracle" ]]; then
      echo "Usage: db-query.sh inbox <oracle>"
      exit 1
    fi
    if [[ "$USE_PSQL" == true ]]; then
      psql "$DB_URL" -c "SELECT msg_id, from_oracle, type, status, LEFT(content, 80) AS preview, created_at FROM messages WHERE to_oracle = '$oracle' AND status = 'pending' ORDER BY priority DESC, created_at ASC;"
    else
      python3 -c "
import asyncio, sys
sys.path.insert(0, '$NEXUS_ROOT')
from daemon.fleetdb import get_pending_messages_for
async def main():
    msgs = await get_pending_messages_for('$oracle')
    for m in msgs:
        print(f\"{m['msg_id']} | {m['from_oracle']} | {m['type']} | {m['status']} | {m['content'][:80]} | {m['created_at']}\")
asyncio.run(main())
"
    fi
    ;;

  outbox)
    oracle="${1:-}"
    if [[ -z "$oracle" ]]; then
      echo "Usage: db-query.sh outbox <oracle>"
      exit 1
    fi
    if [[ "$USE_PSQL" == true ]]; then
      psql "$DB_URL" -c "SELECT msg_id, to_oracle, type, status, LEFT(content, 80) AS preview, created_at FROM messages WHERE from_oracle = '$oracle' ORDER BY created_at DESC LIMIT 20;"
    else
      python3 -c "
import asyncio, sys
sys.path.insert(0, '$NEXUS_ROOT')
from daemon.fleetdb import get_outbox_messages
async def main():
    msgs = await get_outbox_messages('$oracle')
    for m in msgs:
        print(f\"{m['msg_id']} | {m['to_oracle']} | {m['type']} | {m['status']} | {m['content'][:80]}\")
asyncio.run(main())
"
    fi
    ;;

  fleet)
    if [[ "$USE_PSQL" == true ]]; then
      psql "$DB_URL" -c "SELECT name, fleet_id, state, last_seen, active_goals, active_tasks, workload_pct FROM oracle_status ORDER BY fleet_id;"
    else
      python3 -c "
import asyncio, sys
sys.path.insert(0, '$NEXUS_ROOT')
from daemon.fleetdb import get_fleet_status
async def main():
    rows = await get_fleet_status()
    for r in rows:
        print(f\"{r.get('name','?'):12s} | {r.get('fleet_id','?'):12s} | {r.get('state','?'):8s} | last_seen={r.get('last_seen','?')} | goals={r.get('active_goals',0)} | tasks={r.get('active_tasks',0)} | workload={r.get('workload_pct',0)}%\")
asyncio.run(main())
"
    fi
    ;;

  goals)
    oracle="${1:-}"
    if [[ "$USE_PSQL" == true ]]; then
      if [[ -n "$oracle" ]]; then
        psql "$DB_URL" -c "SELECT goal_id, title, progress_pct, status, oracle_owner, created_at FROM goals WHERE oracle_owner = '$oracle' AND status = 'active' ORDER BY priority DESC;"
      else
        psql "$DB_URL" -c "SELECT goal_id, title, progress_pct, status, oracle_owner, created_at FROM goals WHERE status = 'active' ORDER BY priority DESC;"
      fi
    else
      python3 -c "
import asyncio, sys
sys.path.insert(0, '$NEXUS_ROOT')
from daemon.fleetdb import get_active_goals
async def main():
    goals = await get_active_goals('$oracle' if '$oracle' else None)
    for g in goals:
        print(f\"{g['goal_id']} | {g['title'][:50]} | {g['progress_pct']}% | {g['oracle_owner']} | {g['status']}\")
asyncio.run(main())
"
    fi
    ;;

  tasks)
    goal_id="${1:-}"
    if [[ -z "$goal_id" ]]; then
      echo "Usage: db-query.sh tasks <goal_id>"
      exit 1
    fi
    if [[ "$USE_PSQL" == true ]]; then
      psql "$DB_URL" -c "SELECT task_id, title, assigned_oracle, status, priority FROM tasks WHERE goal_id = '$goal_id' ORDER BY priority DESC;"
    else
      python3 -c "
import asyncio, sys
sys.path.insert(0, '$NEXUS_ROOT')
from daemon.fleetdb import get_tasks_for_goal
async def main():
    tasks = await get_tasks_for_goal('$goal_id')
    for t in tasks:
        print(f\"{t['task_id']} | {t['title'][:50]} | {t.get('assigned_oracle','unassigned')} | {t['status']} | P{t['priority']}\")
asyncio.run(main())
"
    fi
    ;;

  workload)
    oracle="${1:-}"
    if [[ -z "$oracle" ]]; then
      echo "Usage: db-query.sh workload <oracle>"
      exit 1
    fi
    if [[ "$USE_PSQL" == true ]]; then
      psql "$DB_URL" -c "SELECT active_goals, active_tasks, workload_pct, state, last_seen, session_count FROM oracle_status WHERE name = '$oracle';"
    else
      python3 -c "
import asyncio, sys
sys.path.insert(0, '$NEXUS_ROOT')
from daemon.fleetdb import get_oracle_workload
async def main():
    w = await get_oracle_workload('$oracle')
    print(f\"state={w.get('state','?')} goals={w.get('active_goals',0)} tasks={w.get('active_tasks',0)} workload={w.get('workload_pct',0)}% sessions={w.get('session_count',0)} last_seen={w.get('last_seen','?')}\")
asyncio.run(main())
"
    fi
    ;;

  recent)
    limit="${1:-20}"
    if [[ "$USE_PSQL" == true ]]; then
      psql "$DB_URL" -c "SELECT msg_id, from_oracle, to_oracle, type, status, LEFT(content, 80) AS preview, created_at FROM messages ORDER BY created_at DESC LIMIT $limit;"
    else
      python3 -c "
import asyncio, sys
sys.path.insert(0, '$NEXUS_ROOT')
from daemon.fleetdb import get_recent_messages
async def main():
    msgs = await get_recent_messages($limit)
    for m in msgs:
        print(f\"{m['msg_id']} | {m['from_oracle']}→{m['to_oracle']} | {m['type']} | {m['status']} | {m['content'][:80]} | {m['created_at']}\")
asyncio.run(main())
"
    fi
    ;;

  status)
    msg_id="${1:-}"
    if [[ -z "$msg_id" ]]; then
      echo "Usage: db-query.sh status <msg_id>"
      exit 1
    fi
    if [[ "$USE_PSQL" == true ]]; then
      psql "$DB_URL" -c "SELECT * FROM messages WHERE msg_id = '$msg_id';"
    else
      python3 -c "
import asyncio, sys
sys.path.insert(0, '$NEXUS_ROOT')
from daemon.fleetdb import get_message
async def main():
    m = await get_message('$msg_id')
    if m:
        for k,v in m.items():
            print(f'{k}: {v}')
    else:
        print('not_found')
asyncio.run(main())
"
    fi
    ;;

  activity)
    limit="${1:-20}"
    if [[ "$USE_PSQL" == true ]]; then
      psql "$DB_URL" -c "SELECT activity_type, oracle_name, entity_type, entity_id, detail, created_at FROM activity_log ORDER BY created_at DESC LIMIT $limit;"
    else
      echo "Use psql for activity queries"
    fi
    ;;

  *)
    echo "nexus fleet db-query — CLI for fleet database"
    echo ""
    echo "Commands:"
    echo "  inbox <oracle>          List pending messages"
    echo "  outbox <oracle>         List outgoing messages"
    echo "  fleet                   Show fleet status"
    echo "  goals [oracle]          Show active goals"
    echo "  tasks <goal_id>         Show tasks for a goal"
    echo "  workload <oracle>       Show oracle workload"
    echo "  recent [n]              Show recent messages (default 20)"
    echo "  status <msg_id>         Show message details"
    echo "  activity [n]            Show recent activity (default 20)"
    ;;
esac
