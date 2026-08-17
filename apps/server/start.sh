#!/bin/sh
set -e

echo "[boot] initdb: jadvallar yaratilmoqda..."
python -m app.initdb

echo "[boot] seed: boshlang'ich ma'lumot..."
python -m app.seed

echo "[boot] uvicorn ishga tushmoqda, port=${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
