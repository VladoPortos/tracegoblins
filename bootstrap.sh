#!/usr/bin/env bash
# Tracegoblins — one-shot setup: generate a .env with strong, unique secrets.
# Usage:  ./bootstrap.sh           (creates .env, refuses to clobber an existing one)
#         ./bootstrap.sh --force   (overwrite an existing .env)
#
# Only needs python3 (standard library) — no extra packages.
set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE=".env"
if [ -f "$ENV_FILE" ] && [ "${1:-}" != "--force" ]; then
  echo "Refusing to overwrite an existing $ENV_FILE (pass --force to replace it)." >&2
  exit 1
fi

PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then echo "python3 is required to generate secrets." >&2; exit 1; fi

# SECRET_KEY signs session + CSRF cookies. TOKEN_ENC_KEY is a Fernet key (32 random bytes,
# url-safe base64) used to encrypt AWX tokens + the TOTP secret at rest — generated with the
# stdlib so no 'cryptography' install is needed here.
SECRET_KEY="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(64))')"
TOKEN_ENC_KEY="$("$PY" -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
PG_PASSWORD="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(24))')"

cp .env.example "$ENV_FILE"
sed -i \
  -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${PG_PASSWORD}|" \
  -e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+asyncpg://tracegoblins:${PG_PASSWORD}@db:5432/tracegoblins|" \
  -e "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET_KEY}|" \
  -e "s|^TOKEN_ENC_KEY=.*|TOKEN_ENC_KEY=${TOKEN_ENC_KEY}|" \
  "$ENV_FILE"

chmod 600 "$ENV_FILE" 2>/dev/null || true
echo "Wrote $ENV_FILE with freshly generated secrets."
echo "Next:  docker compose up -d   (then open http://localhost:8000/setup)"
