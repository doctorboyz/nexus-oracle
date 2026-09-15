#!/usr/bin/env bash
# query.sh — Search knowledge across oracle vaults, DBs, and web
# Usage: query --scope vault|db|web --keyword "search term"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NEXUS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$NEXUS_ROOT/shared/vault-paths.sh"

SCOPE="vault"
KEYWORD=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --scope) SCOPE="$2"; shift 2 ;;
    --keyword) KEYWORD="$2"; shift 2 ;;
    *) shift ;;
  esac
done

if [[ -z "$KEYWORD" ]]; then
  echo "Usage: query --scope vault|db|web --keyword \"search term\""
  exit 1
fi

ORACLE_BASE="/Users/doctorboyz/Code/github.com/doctorboyz"

case "$SCOPE" in
  vault)
    echo "Searching vaults for: $KEYWORD"
    echo "=== Memory files ==="
    grep -ri "$KEYWORD" "$ORACLE_BASE"/*/ψ/memory/ 2>/dev/null || echo "(no results)"
    echo ""
    echo "=== Goal files ==="
    grep -ri "$KEYWORD" "$NEXUS_GOALS/" 2>/dev/null || echo "(no results)"
    echo ""
    echo "=== Inbox files ==="
    grep -ri "$KEYWORD" "$ORACLE_BASE"/*/ψ/inbox/ 2>/dev/null || echo "(no results)"
    echo ""
    echo "=== Dispatch logs ==="
    grep -ri "$KEYWORD" "$NEXUS_DISPATCH/" 2>/dev/null || echo "(no results)"
    ;;
  db)
    echo "Searching databases for: $KEYWORD"
    while IFS= read -r dbfile; do
      echo "=== $dbfile ==="
      sqlite3 "$dbfile" ".tables" 2>/dev/null || echo "(not a valid sqlite db)"
      for table in $(sqlite3 "$dbfile" ".tables" 2>/dev/null); do
        sqlite3 "$dbfile" "SELECT * FROM $table LIMIT 5;" 2>/dev/null | grep -i "$KEYWORD" || true
      done
    done < <(find "$ORACLE_BASE" -name "*.db" -o -name "*.sqlite" 2>/dev/null)
    ;;
  web)
    echo "Web search requires Claude Code WebSearch tool"
    echo "Keyword: $KEYWORD"
    echo "Use: WebSearch with query: $KEYWORD"
    ;;
  *)
    echo "Unknown scope: $SCOPE (use vault, db, or web)"
    exit 1
    ;;
esac