#!/bin/sh
set -e

echo "[start] Applying DB migrations..."
alembic upgrade head

echo "[start] Starting uvicorn on :8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
