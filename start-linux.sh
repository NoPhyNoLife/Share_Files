#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt

if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

if [ "${START_PORT:-auto}" = "auto" ]; then
  APP_PORT="$(python3 -c 'import socket; s = socket.socket(); s.bind(("0.0.0.0", 0)); print(s.getsockname()[1]); s.close()')"
else
  APP_PORT="${START_PORT}"
fi

echo "Starting service on port ${APP_PORT}"
echo "Open: http://localhost:${APP_PORT}"

exec uvicorn app.main:app --host 0.0.0.0 --port "$APP_PORT"
