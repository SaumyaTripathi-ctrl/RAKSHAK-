#!/bin/sh
set -eu
# Apply migrations, then serve. (Postgres is already healthy: compose waits for it.)
python -m alembic upgrade head
exec python -m uvicorn rakshak.main:create_app --factory --host 0.0.0.0 --port 8000
