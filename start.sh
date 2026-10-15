#!/usr/bin/env bash
# FrameFlow (AI Auto Video Editor): one command, one URL -> http://localhost:8000
# FastAPI serves the API, the media files and the built React UI from a single process.
set -e
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
URL="http://localhost:$PORT"

[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; }

listening() { .venv/bin/python -c "import socket,sys; s=socket.socket(); s.settimeout(0.3); sys.exit(0 if s.connect_ex(('127.0.0.1', int(sys.argv[1]))) == 0 else 1)" "$1"; }

if listening "$PORT"; then
  if curl -fs "$URL/api/system" >/dev/null 2>&1; then
    echo "FrameFlow is already running at $URL"
    exit 0
  fi
  echo "Port $PORT is used by another program. Free it, or choose another port: PORT=8123 ./start.sh" >&2
  exit 1
fi

# Rebuild the UI when it is missing or older than its sources.
if [ ! -f frontend/dist/index.html ] || [ -n "$(find frontend/src frontend/index.html frontend/tailwind.config.js -newer frontend/dist/index.html -type f 2>/dev/null | head -1)" ]; then
  (cd frontend && { [ -d node_modules ] || npm install; } && npm run build)
fi

echo "FrameFlow running at $URL"
exec .venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port "$PORT"
