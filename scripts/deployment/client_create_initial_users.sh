#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
[[ -f "$PROJECT_DIR/docker-compose.yml" ]] || PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SQL_FILE="$PROJECT_DIR/create_initial_users.sql"
[[ -f "$SQL_FILE" ]] || SQL_FILE="$PROJECT_DIR/scripts/create_initial_users.sql"
[[ -f "$SQL_FILE" ]] || { echo "ERROR: create_initial_users.sql not found" >&2; exit 1; }
cd "$PROJECT_DIR"

ADMIN_PASSWORD="$(openssl rand -hex 12)"
TEACHER_PASSWORD="$(openssl rand -hex 12)"
STUDENT_PASSWORD="$(openssl rand -hex 12)"

docker compose exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
    -v admin_password="$1" -v teacher_password="$2" -v student_password="$3"' \
  sh "$ADMIN_PASSWORD" "$TEACHER_PASSWORD" "$STUDENT_PASSWORD" < "$SQL_FILE"

printf '\nADMIN\nadmin@example.kz\n%s\n' "$ADMIN_PASSWORD"
printf '\nTEACHER\nteacher@example.kz\n%s\n' "$TEACHER_PASSWORD"
printf '\nSTUDENT\nstudent@example.kz\n%s\n' "$STUDENT_PASSWORD"
echo "Save these passwords now; they are not written to disk."
