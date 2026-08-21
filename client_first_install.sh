#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="/opt/lk"
ARCHIVE="./lk-ubuntu-release.tar.gz"
SCHEMA="./cabinet_schema.sql"
CONFIRM_RESET=0

usage() {
  cat <<'EOF'
Usage: sudo ./client_first_install.sh --confirm-reset-db [options]

Options:
  --archive PATH       release archive (default: ./lk-ubuntu-release.tar.gz)
  --schema PATH        schema SQL (default: ./cabinet_schema.sql)
  --install-dir PATH   installation directory (default: /opt/lk)
  --confirm-reset-db   required: confirms DROP SCHEMA on the new client DB
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --archive) ARCHIVE="$2"; shift ;;
    --schema) SCHEMA="$2"; shift ;;
    --install-dir) INSTALL_DIR="$2"; shift ;;
    --confirm-reset-db) CONFIRM_RESET=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

[[ "$EUID" -eq 0 ]] || { echo "ERROR: run with sudo" >&2; exit 1; }
[[ "$CONFIRM_RESET" -eq 1 ]] || { echo "ERROR: --confirm-reset-db is required" >&2; exit 2; }
[[ -f "$ARCHIVE" ]] || { echo "ERROR: archive not found: $ARCHIVE" >&2; exit 1; }
[[ -f "$SCHEMA" ]] || { echo "ERROR: schema not found: $SCHEMA" >&2; exit 1; }
[[ "$INSTALL_DIR" == /* && "$INSTALL_DIR" != "/" ]] || { echo "ERROR: unsafe install directory" >&2; exit 1; }

if [[ -d "$INSTALL_DIR" ]] && find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
  echo "ERROR: $INSTALL_DIR is not empty; first-install script refuses to overwrite it" >&2
  exit 1
fi
mkdir -p "$INSTALL_DIR"

tar -xzf "$ARCHIVE" -C "$INSTALL_DIR"
cp "$SCHEMA" "$INSTALL_DIR/cabinet_schema.sql"
cd "$INSTALL_DIR"

LK_DB_PASSWORD="$(openssl rand -hex 24)"
LK_JWT_SECRET="$(openssl rand -hex 32)"
LK_MACHINE_ID="$(tr -d '\n' < /etc/machine-id)"
umask 077
printf '%s\n' \
  'POSTGRES_DB=cabinet' \
  'POSTGRES_USER=cabinet' \
  "POSTGRES_PASSWORD=${LK_DB_PASSWORD}" \
  "DATABASE_URL=postgresql+psycopg2://cabinet:${LK_DB_PASSWORD}@db:5432/cabinet" \
  "JWT_SECRET=${LK_JWT_SECRET}" \
  "LICENSE_MACHINE_ID=${LK_MACHINE_ID}" \
  'JWT_ALG=HS256' \
  'ACCESS_TOKEN_EXPIRES_MIN=15' \
  'REFRESH_TOKEN_EXPIRES_DAYS=30' \
  'APP_PORT=6123' \
  'BIND_ADDRESS=127.0.0.1' \
  'SKIP_MIGRATIONS=1' > .env
touch license.lic
chmod 600 .env license.lic
chmod 644 license_public.pem

docker compose up -d db
for attempt in $(seq 1 30); do
  if docker compose exec -T db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
    break
  fi
  [[ "$attempt" -lt 30 ]] || { echo "ERROR: PostgreSQL is not ready" >&2; exit 1; }
  sleep 2
done

docker compose exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'
docker compose exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' \
  < cabinet_schema.sql

# A schema-only dump contains the alembic_version table but not its row.
# Detect the imported schema baseline, stamp it, then enable normal migrations.
./client_adopt_schema_migrations.sh

docker compose up -d --build backend
docker compose ps
echo "License status and client fingerprint:"
curl -fsS http://127.0.0.1:6123/license/status || true
echo
echo "First installation completed in $INSTALL_DIR"
