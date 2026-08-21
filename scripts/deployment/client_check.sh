#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
[[ -f "$PROJECT_DIR/docker-compose.yml" ]] || PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"

echo "Containers:"
docker compose ps
echo
echo "Backend logs:"
docker compose logs --tail=100 backend
echo
echo "Ping:"
curl -fsS http://127.0.0.1:6123/ping
echo
echo "License:"
curl -fsS http://127.0.0.1:6123/license/status
echo
echo "Tables and users:"
docker compose exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'
docker compose exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) AS users_count FROM users"'
echo
echo "Database revision and grade schema:"
docker compose exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM alembic_version"'
docker compose exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = '\''public'\'' AND ((table_name = '\''subjects'\'' AND column_name = '\''grade_type'\'') OR (table_name = '\''lessons'\'' AND column_name = '\''subject_type'\'')) ORDER BY table_name"'

if docker compose port db 5432 2>/dev/null | grep -q .; then
  echo "ERROR: PostgreSQL is published on the host" >&2
  exit 1
fi
if find "$PROJECT_DIR" -name license_private.pem -print -quit | grep -q .; then
  echo "ERROR: private key exists on client" >&2
  exit 1
fi
echo "Checks completed."
