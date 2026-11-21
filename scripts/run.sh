#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8

# single-instance guard
if ss -ltn 2>/dev/null | grep -q ':8000 '; then
  echo "[gudang] already running on :8000 — open http://localhost:8000"
  exit 0
fi

PY=python3.12
command -v "$PY" >/dev/null 2>&1 || PY=python3
[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

python -m app.core.prestart
if ls migrations/versions/*.py >/dev/null 2>&1; then
  alembic upgrade head
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
