#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="/opt/lk"
ARCHIVE="/tmp/lk-ubuntu-release.tar.gz"
NO_CACHE=0

usage() {
  cat <<'EOF'
Usage: sudo ./client_upgrade_release.sh [options]

Options:
  --archive PATH       new release archive (default: /tmp/lk-ubuntu-release.tar.gz)
  --install-dir PATH   existing installation (default: /opt/lk)
  --no-cache           rebuild backend image without Docker cache
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --archive) ARCHIVE="$2"; shift ;;
    --install-dir) INSTALL_DIR="$2"; shift ;;
    --no-cache) NO_CACHE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

[[ "$EUID" -eq 0 ]] || { echo "ERROR: run with sudo" >&2; exit 1; }
[[ -f "$ARCHIVE" ]] || { echo "ERROR: archive not found: $ARCHIVE" >&2; exit 1; }
[[ "$INSTALL_DIR" == /* && "$INSTALL_DIR" != "/" ]] || { echo "ERROR: unsafe install directory" >&2; exit 1; }
[[ -f "$INSTALL_DIR/.env" ]] || { echo "ERROR: existing .env not found in $INSTALL_DIR" >&2; exit 1; }
[[ -f "$INSTALL_DIR/docker-compose.yml" ]] || { echo "ERROR: existing docker-compose.yml not found" >&2; exit 1; }
[[ -f "$INSTALL_DIR/license.lic" ]] || { echo "ERROR: existing license.lic not found" >&2; exit 1; }

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "ERROR: Docker Compose not found" >&2
  exit 1
fi

STAGE_DIR="$(mktemp -d)"
TEMP_BACKUP=""
cleanup() {
  [[ -z "$TEMP_BACKUP" ]] || rm -f "$TEMP_BACKUP"
  rm -rf "$STAGE_DIR"
}
trap cleanup EXIT

if tar -tzf "$ARCHIVE" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
  echo "ERROR: unsafe path in release archive" >&2
  exit 1
fi
tar -xzf "$ARCHIVE" -C "$STAGE_DIR"
[[ -f "$STAGE_DIR/docker-compose.yml" ]] || { echo "ERROR: invalid release archive" >&2; exit 1; }
[[ -f "$STAGE_DIR/Dockerfile.client" ]] || { echo "ERROR: Dockerfile.client missing in release" >&2; exit 1; }
if find "$STAGE_DIR" -name license_private.pem -print -quit | grep -q .; then
  echo "ERROR: private license key found in release" >&2
  exit 1
fi

mkdir -p "$INSTALL_DIR/backups"
BACKUP_FILE="$INSTALL_DIR/backups/cabinet-before-update-$(date +%F_%H-%M-%S).dump"
TEMP_BACKUP="$(mktemp "${BACKUP_FILE}.tmp.XXXXXX")"
cd "$INSTALL_DIR"
"${COMPOSE[@]}" up -d db
"${COMPOSE[@]}" exec -T db sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$TEMP_BACKUP"
[[ -s "$TEMP_BACKUP" ]] || { echo "ERROR: database backup is empty" >&2; exit 1; }
mv "$TEMP_BACKUP" "$BACKUP_FILE"
TEMP_BACKUP=""
echo "Backup created: $BACKUP_FILE"

tar -C "$STAGE_DIR" \
  --exclude='./.env' \
  --exclude='./license.lic' \
  --exclude='./license_public.pem' \
  --exclude='./client_upgrade_release.sh' \
  -cf - . | tar -C "$INSTALL_DIR" -xf -

install -m 755 "$STAGE_DIR/client_upgrade_release.sh" "$INSTALL_DIR/.client_upgrade_release.sh.new"
mv "$INSTALL_DIR/.client_upgrade_release.sh.new" "$INSTALL_DIR/client_upgrade_release.sh"
chmod +x "$INSTALL_DIR"/client_*.sh

# A first installation made from a schema-only pg_dump has an empty
# alembic_version table. Adopt that imported schema before normal upgrades.
"$INSTALL_DIR/client_adopt_schema_migrations.sh"

UPDATE_ARGS=()
[[ "$NO_CACHE" -eq 0 ]] || UPDATE_ARGS+=(--no-cache)
"$INSTALL_DIR/client_update.sh" "${UPDATE_ARGS[@]}"

echo "Release upgraded successfully."
echo "Preserved: .env, license.lic, license_public.pem and PostgreSQL volume."
