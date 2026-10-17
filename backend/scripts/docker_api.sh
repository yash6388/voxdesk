#!/bin/sh
# API container entrypoint: migrate, make sure voice models exist, then serve.
set -e

echo "Applying database migrations…"
alembic upgrade head

# Idempotent: skips files that are already in the volume. Voice is optional, so a failed
# download (e.g. offline) must not stop the API from starting.
python -m scripts.download_voice_models || echo "WARNING: voice models unavailable — voice disabled"

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers
