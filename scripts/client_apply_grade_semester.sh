#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR=""
for candidate in "$SCRIPT_DIR" "$SCRIPT_DIR/.." "$SCRIPT_DIR/../.."; do
  if [[ -f "$candidate/docker-compose.yml" ]]; then
    PROJECT_DIR="$(cd "$candidate" && pwd)"
    break
  fi
done
[[ -n "$PROJECT_DIR" ]] || { echo "ERROR: docker-compose.yml not found" >&2; exit 1; }

SQL_FILE="$PROJECT_DIR/add_grade_semester.sql"
[[ -f "$SQL_FILE" ]] || SQL_FILE="$PROJECT_DIR/scripts/add_grade_semester.sql"
[[ -f "$SQL_FILE" ]] || { echo "ERROR: add_grade_semester.sql not found" >&2; exit 1; }

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "ERROR: Docker Compose not found" >&2
  exit 1
fi

cd "$PROJECT_DIR"
"${COMPOSE[@]}" up -d db
"${COMPOSE[@]}" exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' < "$SQL_FILE"

COLUMN_COUNT="$("${COMPOSE[@]}" exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM information_schema.columns WHERE table_schema = '\''public'\'' AND table_name = '\''grades'\'' AND column_name IN ('\''semester_year'\'', '\''semester_season'\'');"' | tr -d '\r[:space:]')"
[[ "$COLUMN_COUNT" == "2" ]] || { echo "ERROR: semester columns verification failed" >&2; exit 1; }
TEACHER_NULLABLE="$("${COMPOSE[@]}" exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT is_nullable FROM information_schema.columns WHERE table_schema = '\''public'\'' AND table_name = '\''grades'\'' AND column_name = '\''teacher_id'\'';"' | tr -d '\r[:space:]')"
[[ "$TEACHER_NULLABLE" == "YES" ]] || { echo "ERROR: grades.teacher_id is still NOT NULL" >&2; exit 1; }
echo "Grade semester migration applied successfully."
