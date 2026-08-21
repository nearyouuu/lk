#!/usr/bin/env bash
set -e

# --- Wait for Postgres (если указаны переменные окружения) ---
if [ -n "$DB_HOST" ]; then
  echo "⏳ Waiting for DB ${DB_HOST}:${DB_PORT:-5432}..."
  for i in {1..10}; do
    if pg_isready -h "$DB_HOST" -p "${DB_PORT:-5432}" >/dev/null 2>&1; then
      echo "✅ Database is ready"
      break
    fi
    echo "⏳ Attempt $i/30: database not ready yet..."
    sleep 2
  done
fi

# --- Run Alembic migrations (если есть) ---
if [ -f "alembic.ini" ] && [ "${SKIP_MIGRATIONS}" != "1" ]; then
  echo "🚀 Running alembic upgrade head..."
  # Do not start the application against an outdated database schema.
  # With `set -e`, a failed migration stops the container and leaves the
  # original Alembic error visible in `docker compose logs backend`.
  alembic upgrade head
fi

# --- Start FastAPI ---
echo "🚀 Starting FastAPI (Uvicorn)..."
exec uvicorn app.main:app --host 0.0.0.0 --port 6123 --reload
