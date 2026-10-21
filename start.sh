#!/usr/bin/env bash
# Start the SEC 10-K Analyzer: FastAPI backend + Streamlit app, then open
# it in the Windows browser. Safe to re-run: anything already running is
# left alone.
#
#   ./start.sh          start (or reuse) both servers and open the browser
#   ./start.sh stop     stop both servers

cd "$(dirname "$0")"
LOGS="${TMPDIR:-/tmp}/sec-analyzer-logs"
mkdir -p "$LOGS"

pid_on_port() {
    ss -ltnp 2>/dev/null | grep "127.0.0.1:$1 \|0.0.0.0:$1 " | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2
}

if [ "$1" = "stop" ]; then
    for port in 8000 8501; do
        pid=$(pid_on_port "$port")
        [ -n "$pid" ] && kill "$pid" && echo "Stopped server on port $port"
    done
    exit 0
fi

if curl -s -m 2 http://127.0.0.1:8000/health >/dev/null; then
    echo "Backend already running on :8000"
else
    echo "Starting backend on :8000 (log: $LOGS/backend.log)"
    nohup uvicorn backend.main:app --port 8000 --reload --reload-dir backend \
        > "$LOGS/backend.log" 2>&1 &
fi

if curl -s -m 2 -o /dev/null http://localhost:8501; then
    echo "App already running on :8501"
else
    echo "Starting app on :8501 (log: $LOGS/streamlit.log)"
    nohup streamlit run app_beautiful_final.py --server.headless true --server.port 8501 \
        > "$LOGS/streamlit.log" 2>&1 &
fi

for _ in $(seq 1 30); do
    curl -s -m 1 http://127.0.0.1:8000/health >/dev/null \
        && curl -s -m 1 -o /dev/null http://localhost:8501 && break
    sleep 1
done

echo "Open http://localhost:8501"
# Open in the Windows default browser when running under WSL.
if command -v cmd.exe >/dev/null; then
    (cd /mnt/c && cmd.exe /c start "" "http://localhost:8501" >/dev/null 2>&1)
fi
