#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR=""
NO_CACHE=0
[[ "${1:-}" != "--no-cache" ]] || NO_CACHE=1
[[ $# -le 1 ]] || { echo "Usage: client_recreate_backend.sh [--no-cache]" >&2; exit 2; }
[[ $# -eq 0 || "${1:-}" == "--no-cache" ]] || { echo "Usage: client_recreate_backend.sh [--no-cache]" >&2; exit 2; }

for candidate in "$SCRIPT_DIR" "$SCRIPT_DIR/.." "$SCRIPT_DIR/../.."; do
  if [[ -f "$candidate/docker-compose.yml" ]]; then
    PROJECT_DIR="$(cd "$candidate" && pwd)"
    break
  fi
done
[[ -n "$PROJECT_DIR" ]] || { echo "ERROR: docker-compose.yml not found" >&2; exit 1; }

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "ERROR: Docker Compose not found" >&2
  exit 1
fi

cd "$PROJECT_DIR"
BUILD_ARGS=(build)
[[ "$NO_CACHE" -eq 0 ]] || BUILD_ARGS+=(--no-cache)
BUILD_ARGS+=(backend)
"${COMPOSE[@]}" "${BUILD_ARGS[@]}"
"${COMPOSE[@]}" up -d --no-deps --force-recreate backend

for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:6123/ping >/dev/null 2>&1; then
    break
  fi
  [[ "$attempt" -lt 30 ]] || break
  sleep 2
done
if ! curl -fsS http://127.0.0.1:6123/ping >/dev/null 2>&1; then
  "${COMPOSE[@]}" logs --tail=100 backend >&2
  echo "ERROR: backend health check failed" >&2
  exit 1
fi

ALEMBIC_REVISION="$("${COMPOSE[@]}" exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT version_num FROM alembic_version LIMIT 1"' \
  | tr -d '\r[:space:]')"
ALEMBIC_HEAD_FILE="$PROJECT_DIR/alembic_head.txt"
[[ -f "$ALEMBIC_HEAD_FILE" ]] || {
  echo "ERROR: release Alembic head manifest not found: $ALEMBIC_HEAD_FILE" >&2
  exit 1
}
EXPECTED_ALEMBIC_REVISION="$(tr -d '\r[:space:]' < "$ALEMBIC_HEAD_FILE")"
[[ "$EXPECTED_ALEMBIC_REVISION" =~ ^[0-9a-f]+$ ]] || {
  echo "ERROR: invalid Alembic head manifest: ${EXPECTED_ALEMBIC_REVISION:-empty}" >&2
  exit 1
}
[[ "$ALEMBIC_REVISION" == "$EXPECTED_ALEMBIC_REVISION" ]] || {
  "${COMPOSE[@]}" logs --tail=100 backend >&2
  echo "ERROR: expected Alembic revision $EXPECTED_ALEMBIC_REVISION, got: ${ALEMBIC_REVISION:-missing}" >&2
  exit 1
}

SCHEMA_COLUMN_COUNT="$("${COMPOSE[@]}" exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM information_schema.columns WHERE table_schema = '\''public'\'' AND ((table_name = '\''subjects'\'' AND column_name = '\''grade_type'\'') OR (table_name = '\''lessons'\'' AND column_name = '\''subject_type'\''));"' \
  | tr -d '\r[:space:]')"
[[ "$SCHEMA_COLUMN_COUNT" == "2" ]] || {
  echo "ERROR: grade/subject type schema verification failed" >&2
  exit 1
}

echo "Backend recreated successfully (database revision: $ALEMBIC_REVISION)."
