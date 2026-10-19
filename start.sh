#!/usr/bin/env bash
# FrameFlow (AI Auto Video Editor): one command, one URL -> http://localhost:8000
# FastAPI serves the API, the media files and the built React UI from a single process.
set -e
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
URL="http://localhost:$PORT"

[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; }

listening() { .venv/bin/python -c "import socket,sys; s=socket.socket(); s.settimeout(0.3); sys.exit(0 if s.connect_ex(('127.0.0.1', int(sys.argv[1]))) == 0 else 1)" "$1"; }

is_frameflow() { curl -fs "$URL/api/system" >/dev/null 2>&1; }
# Stale = the server reports it, or it is so old it does not report anything about itself.
is_stale() { body=$(curl -fs "$URL/api/system"); echo "$body" | grep -q '"stale":true' || ! echo "$body" | grep -q '"server"'; }

# A server started BEFORE the code last changed is missing the newer endpoints (the browser then shows errors such as
# "Unexpected token '<'"). "./start.sh --restart" replaces it.
if listening "$PORT" && is_frameflow && is_stale; then
  if [ "$1" = "--restart" ]; then
    PIDS=$(lsof -ti tcp:"$PORT" -sTCP:LISTEN || true)
    if [ -n "$PIDS" ] && ps -o command= -p $PIDS | grep -q "backend.main"; then
      echo "Restarting the FrameFlow server on port $PORT..."
      kill $PIDS
      for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do listening "$PORT" || break; sleep 0.5; done
    else
      echo "Port $PORT is not a FrameFlow server; leaving it alone." >&2
      exit 1
    fi
  else
    echo "FrameFlow is running at $URL, but it was started BEFORE the code was updated, so some features are missing." >&2
    echo "Restart it with:  ./start.sh --restart   (running exports are stopped)" >&2
    exit 1
  fi
fi

if listening "$PORT"; then
  if is_frameflow; then
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
exec .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port "$PORT"
