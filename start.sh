#!/usr/bin/env bash
# FrameFlow: build the UI once, then serve everything from one local server.
set -e
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; }
# If something else already listens on the port, use the next free one instead of failing.
port_busy() { .venv/bin/python -c "import socket,sys; s=socket.socket(); s.settimeout(0.3); sys.exit(0 if s.connect_ex(('127.0.0.1', int(sys.argv[1]))) == 0 else 1)" "$1"; }
START_PORT="$PORT"
while port_busy "$PORT"; do PORT=$((PORT + 1)); done
[ "$PORT" = "$START_PORT" ] || echo "Port $START_PORT is in use; using $PORT."
if [ ! -f frontend/dist/index.html ]; then
  (cd frontend && npm install && npm run build)
fi
echo "FrameFlow running at http://localhost:$PORT"
exec .venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port "$PORT"
