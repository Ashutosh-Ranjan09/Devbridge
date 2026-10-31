#!/usr/bin/env bash
# Everything for a demo, in one terminal: M5 :8080, M6 :8300, assessment :8070, chat :8090,
# web :3000.
#
#   scripts/dev.sh          the web in development mode (next dev)
#   scripts/dev.sh prod     a production build (next build && next start)
#
# One key per module per run, shared with the web layer through the environment, so
# nothing is copied into a file and no key is printed. A module's own settings
# (cv-verification/.env, assessment/.env, chat/.env) still apply; the environment wins for the key.
# Logs go to .run/<name>.log. Ctrl-C stops all five.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .run

[ -f web/.env ] || { echo "web/.env is missing: cp web/.env.example web/.env" >&2; exit 1; }
key() { python3 -c 'import secrets; print(secrets.token_urlsafe(24))'; }
M5_KEY=${CVV_API_KEY:-$(key)}
ASSESS_KEY=${ASSESS_API_KEY:-$(key)}
CHAT_KEY=${CHAT_API_KEY:-$(key)}

# The chat module's encryption key is the one key kept in a file: made once, never per
# run, or every message sealed with the last one could not be read again.
if ! grep -qs '^CHAT_ENCRYPTION_KEY=.' chat/.env; then
  [ -f chat/.env ] && sed -i '/^CHAT_ENCRYPTION_KEY=$/d' chat/.env
  (cd chat && echo "CHAT_ENCRYPTION_KEY=$(uv run --quiet chat keygen)" >> .env && chmod 600 .env)
  echo "  made a chat encryption key in chat/.env: back it up; without it the messages cannot be read"
fi
chmod 600 chat/.env   # the key reads every message: for this user only

pids=()
stop() { kill "${pids[@]}" 2>/dev/null || true; wait 2>/dev/null || true; echo "stopped"; }
trap stop EXIT
trap 'exit 130' INT TERM

start() {
  local name=$1; shift
  "$@" > ".run/$name.log" 2>&1 &
  pids+=($!)
}

start m5 env CVV_API_KEY="$M5_KEY" bash -c 'cd cv-verification && exec uv run cvv serve'
start m6 bash -c 'cd skill-graph && PYTHONPATH=packages exec python3 -c "
from m6 import M6
from m6.api import serve
serve(M6(\"evidence.db\"), port=8300).serve_forever()"'
start assess env ASSESS_API_KEY="$ASSESS_KEY" bash -c 'cd assessment && exec uv run assess serve'
start chat env CHAT_API_KEY="$CHAT_KEY" bash -c 'cd chat && exec uv run chat serve'

(cd web && npx prisma migrate deploy > ../.run/migrate.log 2>&1) || { echo "migration failed: .run/migrate.log" >&2; exit 1; }
if [ "${1:-}" = prod ]; then
  (cd web && npx next build > ../.run/build.log 2>&1) || { echo "build failed: .run/build.log" >&2; exit 1; }
  web_cmd='cd web && exec npx next start -p 3000'
else
  web_cmd='cd web && exec npx next dev -p 3000'
fi
start web env M5_API_KEY="$M5_KEY" ASSESS_API_KEY="$ASSESS_KEY" CHAT_API_KEY="$CHAT_KEY" bash -c "$web_cmd"

up() { curl -sf -o /dev/null --max-time 2 "$1"; }
for name_url in "M5 http://127.0.0.1:8080/healthz" "M6 http://127.0.0.1:8300/health" \
                "assessment http://127.0.0.1:8070/healthz" "chat http://127.0.0.1:8090/healthz" \
                "web http://127.0.0.1:3000/login"; do
  set -- $name_url
  for _ in $(seq 1 60); do up "$2" && break; sleep 1; done
  if up "$2"; then echo "  ✓ $1  $2"; else echo "  ✗ $1 did not answer: see .run/" >&2; fi
done
if ! curl -sf --max-time 5 http://127.0.0.1:8070/healthz | grep -q '"image_present":true'; then
  echo "  ! the sandbox image is not built: (cd assessment && uv run assess sandbox build)" >&2
fi
echo "open http://localhost:3000 · logs in .run/ · Ctrl-C stops everything"
wait
