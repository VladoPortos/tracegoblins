#!/usr/bin/env bash
set -Eeuo pipefail
DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"

echo "[entrypoint] waiting for Postgres at ${DB_HOST}:${DB_PORT} ..."
for i in $(seq 1 60); do
  if python - "$DB_HOST" "$DB_PORT" <<'PY'
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
try:
    with socket.create_connection((host, port), timeout=2):
        sys.exit(0)
except OSError:
    sys.exit(1)
PY
  then echo "[entrypoint] Postgres reachable."; break; fi
  if [ "$i" -eq 60 ]; then echo "[entrypoint] ERROR: Postgres unreachable" >&2; exit 1; fi
  sleep 1
done

echo "[entrypoint] alembic upgrade head ..."
alembic upgrade head

echo "[entrypoint] starting: $*"
exec "$@"
