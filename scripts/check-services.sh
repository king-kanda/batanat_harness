#!/usr/bin/env bash
# Report whether each datastore this project needs is reachable on the host.
#
# We deliberately reuse the services already installed on the dev machine
# rather than starting containers for them. This script tells you which of
# them are actually up before you go looking for a bug in the app.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$REPO_ROOT/.env" ] && set -a && . "$REPO_ROOT/.env" && set +a

DATABASE_URL="${DATABASE_URL:-postgresql://postgres:password@localhost:5432/batanat}"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
MONGO_URL="${MONGO_URL:-mongodb://localhost:27017/}"
REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"

ok=0
fail=0

report() { # name status detail
  if [ "$2" = "ok" ]; then
    printf '  \033[32m●\033[0m %-9s %s\n' "$1" "$3"; ok=$((ok + 1))
  else
    printf '  \033[31m●\033[0m %-9s %s\n' "$1" "$3"; fail=$((fail + 1))
  fi
}

# postgres — parse host/port out of the DSN
pg_hostport="$(printf '%s' "$DATABASE_URL" | sed -E 's#.*@([^/?]+).*#\1#')"
pg_host="${pg_hostport%%:*}"
pg_port="${pg_hostport##*:}"
[ "$pg_port" = "$pg_host" ] && pg_port=5432
if out="$(pg_isready -h "$pg_host" -p "$pg_port" 2>&1)"; then
  report postgres ok "$out"
else
  report postgres down "${out:-not reachable at $pg_host:$pg_port}"
fi

# qdrant
if curl -sf -m 3 -o /dev/null "$QDRANT_URL/readyz"; then
  report qdrant ok "$(curl -s -m 3 "$QDRANT_URL/" | sed -E 's/.*"version":"([^"]+)".*/v\1/')  $QDRANT_URL"
else
  report qdrant down "not reachable at $QDRANT_URL"
fi

# mongo
if command -v mongosh >/dev/null 2>&1; then
  if mongosh --quiet --eval 'db.adminCommand({ping:1}).ok' "$MONGO_URL" >/dev/null 2>&1; then
    report mongo ok "$MONGO_URL"
  else
    report mongo down "not reachable at $MONGO_URL"
  fi
else
  report mongo down "mongosh not installed"
fi

# redis
redis_hostport="${REDIS_URL#redis://}"
redis_hostport="${redis_hostport%%/*}"
redis_host="${redis_hostport%%:*}"
redis_port="${redis_hostport##*:}"
[ "$redis_port" = "$redis_host" ] && redis_port=6379
if [ "$(redis-cli -h "$redis_host" -p "$redis_port" ping 2>/dev/null)" = "PONG" ]; then
  report redis ok "$redis_host:$redis_port"
else
  report redis down "not reachable at $redis_host:$redis_port"
fi

echo
if [ "$fail" -gt 0 ]; then
  echo "$fail of $((ok + fail)) services unreachable."
  exit 1
fi
echo "All $ok services reachable."
