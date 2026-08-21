#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RELEASE_DIR="$ROOT_DIR/dist/ubuntu-release"
DB_CONTAINER="${DB_CONTAINER:-cabinet-db}"
DB_USER="${DB_USER:-cabinet}"
DB_NAME="${DB_NAME:-cabinet}"
EXPORT_SCHEMA=1

usage() {
  cat <<'EOF'
Usage: build_release_package.sh [--skip-schema]

Environment overrides:
  DB_CONTAINER=cabinet-db DB_USER=cabinet DB_NAME=cabinet
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-schema) EXPORT_SCHEMA=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

cd "$ROOT_DIR"
command -v docker >/dev/null || { echo "ERROR: docker not found" >&2; exit 1; }
[[ -f license_public.pem ]] || { echo "ERROR: license_public.pem not found" >&2; exit 1; }

echo "Building Linux release image..."
export DOCKER_BUILDKIT="${DOCKER_BUILDKIT:-1}"
docker build -f docker/Dockerfile.build-ubuntu -t lk-ubuntu-build .

docker rm -f lk-build-export >/dev/null 2>&1 || true
docker create --name lk-build-export lk-ubuntu-build >/dev/null
trap 'docker rm -f lk-build-export >/dev/null 2>&1 || true' EXIT

case "$RELEASE_DIR" in
  "$ROOT_DIR"/dist/*) ;;
  *) echo "ERROR: unsafe release directory: $RELEASE_DIR" >&2; exit 1 ;;
esac
rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"
docker cp lk-build-export:/out/. "$RELEASE_DIR/"
docker rm lk-build-export >/dev/null
trap - EXIT

file "$RELEASE_DIR/lk_backend"
cp license_public.pem "$RELEASE_DIR/license_public.pem"
: > "$RELEASE_DIR/license.lic"

if find "$RELEASE_DIR" -name 'license_private.pem' -print -quit | grep -q .; then
  echo "ERROR: private license key leaked into release" >&2
  exit 1
fi

tar -czf lk-ubuntu-release.tar.gz -C "$RELEASE_DIR" .

if [[ "$EXPORT_SCHEMA" -eq 1 ]]; then
  echo "Exporting schema from $DB_CONTAINER..."
  docker exec -i "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" \
    --schema-only --no-owner --no-privileges > cabinet_schema.sql
  if grep -nE '^(COPY|INSERT INTO)' cabinet_schema.sql; then
    echo "ERROR: cabinet_schema.sql contains data statements" >&2
    exit 1
  fi
fi

cp scripts/deployment/client_first_install.sh client_first_install.sh
cp scripts/deployment/client_upgrade_release.sh client_upgrade_release.sh
chmod +x client_first_install.sh
chmod +x client_upgrade_release.sh

echo "Created:"
echo "  $ROOT_DIR/lk-ubuntu-release.tar.gz"
[[ "$EXPORT_SCHEMA" -eq 0 ]] || echo "  $ROOT_DIR/cabinet_schema.sql"
echo "  $ROOT_DIR/client_first_install.sh"
echo "  $ROOT_DIR/client_upgrade_release.sh"
