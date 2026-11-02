#!/usr/bin/env bash
# រត់ Qoder OpenAI-compatible Proxy (Port 3000)។
#   ./scripts/run_qoder_proxy.sh            → foreground
#   ./scripts/run_qoder_proxy.sh --bg       → background + PID/log ។
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
LOG_FILE="logs/qoder_proxy.log"
PID_FILE="logs/qoder_proxy.pid"
PORT="${QODER_PROXY_PORT:-3000}"

bin_for_check="${QODER_CLI_BIN:-qodercli}"
if ! command -v "$bin_for_check" >/dev/null 2>&1; then
  echo "❌ រកមិនឃើញ '$bin_for_check' — សូមរត់: ./scripts/install_qoder.sh" >&2
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "❌ គ្មាន .venv — សូមរត់: python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

.venv/bin/python -c "import fastapi, uvicorn" 2>/dev/null || {
  echo "➕ កំពុងដំឡើង fastapi/uvicorn ..."
  .venv/bin/pip install -q fastapi "uvicorn[standard]"
}

mkdir -p logs

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "ℹ️  Proxy កំពុងដំណើរការរួចហើយ (PID $(cat "$PID_FILE"))។"
  echo "   បើកសារថ្មី៖ kill \$(cat $PID_FILE) && rm -f $PID_FILE រួចរត់ម្តងទៀត"
  exit 0
fi

if [ "${1:-}" = "--bg" ]; then
  nohup .venv/bin/python scripts/qoder_proxy.py >>"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
  echo "🚀 Proxy នៅក្នុង background — PID $(cat "$PID_FILE"), port $PORT"
  echo "   Log: $LOG_FILE"
  echo "   Stop: kill \$(cat $PID_FILE)"
else
  echo "🚀 Proxy នៅក្នុង foreground (Ctrl+C ដើម្បីបញ្ឈប់)"
  exec .venv/bin/python scripts/qoder_proxy.py
fi
