#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
[[ -f "$PROJECT_DIR/docker-compose.yml" ]] || PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
[[ -f "$PROJECT_DIR/docker-compose.yml" ]] || { echo "ERROR: docker-compose.yml not found" >&2; exit 1; }
cd "$PROJECT_DIR"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "ERROR: Docker Compose not found" >&2
  exit 1
fi

"${COMPOSE[@]}" up -d db

read_db() {
  "${COMPOSE[@]}" exec -T db sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"' sh "$1" \
    | tr -d '\r[:space:]'
}

CURRENT_REVISION="$(read_db "SELECT version_num FROM alembic_version LIMIT 1")"
[[ -z "$CURRENT_REVISION" ]] || {
  echo "Alembic already has revision: $CURRENT_REVISION"
  exit 0
}

SEMESTER_COLUMNS="$(read_db "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='grades' AND column_name IN ('semester_year','semester_season')")"
LESSON_TYPE_COLUMNS="$(read_db "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='lessons' AND column_name='lesson_type'")"
SUBJECT_TYPE_COLUMNS="$(read_db "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='lessons' AND column_name='subject_type'")"
SUBJECT_GRADE_COLUMNS="$(read_db "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='subjects' AND column_name='grade_type'")"

if [[ "$SEMESTER_COLUMNS" == "2" && "$LESSON_TYPE_COLUMNS" == "1" && "$SUBJECT_TYPE_COLUMNS" == "0" && "$SUBJECT_GRADE_COLUMNS" == "0" ]]; then
  BASELINE="e4f5a6b7c8d9"
elif [[ "$SUBJECT_TYPE_COLUMNS" == "1" && "$SUBJECT_GRADE_COLUMNS" == "1" ]]; then
  BASELINE="f6a7b8c9d0e1"
else
  echo "ERROR: imported schema does not match a known safe Alembic baseline" >&2
  echo "semester columns=$SEMESTER_COLUMNS lesson_type=$LESSON_TYPE_COLUMNS subject_type=$SUBJECT_TYPE_COLUMNS subjects.grade_type=$SUBJECT_GRADE_COLUMNS" >&2
  exit 1
fi

"${COMPOSE[@]}" exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "DELETE FROM alembic_version; INSERT INTO alembic_version(version_num) VALUES ('\''$1'\'');"' sh "$BASELINE"

if grep -q '^SKIP_MIGRATIONS=' .env; then
  sed -i 's/^SKIP_MIGRATIONS=.*/SKIP_MIGRATIONS=0/' .env
else
  printf '\nSKIP_MIGRATIONS=0\n' >> .env
fi

echo "Imported schema adopted at revision $BASELINE."
echo "Recreate backend to apply remaining migrations."
