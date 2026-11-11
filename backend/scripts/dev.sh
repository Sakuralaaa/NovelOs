#!/usr/bin/env bash
# 本地开发启动后端：http://127.0.0.1:8000/api/health
# 前端另开终端：cd ../frontend && npm run dev （Vite 在 5173，已允许 CORS）
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements-dev.txt

export NOVELOS_DATA_DIR="${NOVELOS_DATA_DIR:-./data}"
export NOVELOS_STATIC_DIR="${NOVELOS_STATIC_DIR:-../frontend/dist}"
exec uvicorn app.main:app --reload --host 127.0.0.1 --port "${PORT:-8000}"
