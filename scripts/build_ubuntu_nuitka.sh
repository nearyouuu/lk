#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/build/nuitka"
RELEASE_DIR="$ROOT_DIR/dist/ubuntu-release"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "Using Python: $PYTHON_BIN"
"$PYTHON_BIN" --version

if [[ "${SKIP_BUILD_DEP_INSTALL:-0}" == "1" ]]; then
  echo "Using build dependencies preinstalled by the container image."
else
  echo "Installing build dependencies..."
  "$PYTHON_BIN" -m pip install --upgrade pip
  "$PYTHON_BIN" -m pip install -r "$ROOT_DIR/req.txt"
  "$PYTHON_BIN" -m pip install nuitka ordered-set zstandard
fi

rm -rf "$BUILD_DIR" "$RELEASE_DIR"
mkdir -p "$BUILD_DIR" "$RELEASE_DIR"

echo "Building Nuitka standalone binary..."
"$PYTHON_BIN" -m nuitka \
  --standalone \
  --assume-yes-for-downloads \
  --follow-imports \
  --output-dir="$BUILD_DIR" \
  --output-filename=lk_backend \
  --include-package=app \
  --include-package=fastapi \
  --include-package=uvicorn \
  --include-package=sqlalchemy \
  --include-package=passlib \
  --include-package=bcrypt \
  --include-module=psycopg2 \
  --include-module=email_validator \
  --include-module=jwt \
  --include-module=multipart \
  "$ROOT_DIR/scripts/run_backend.py"

cp -R "$BUILD_DIR/run_backend.dist/." "$RELEASE_DIR/"
cp -R "$ROOT_DIR/alembic" "$RELEASE_DIR/alembic"
cp "$ROOT_DIR/alembic.ini" "$RELEASE_DIR/alembic.ini"
mapfile -t ALEMBIC_HEADS < <(
  cd "$ROOT_DIR"
  "$PYTHON_BIN" -m alembic heads | awk '/\(head\)/ {print $1}'
)
[[ "${#ALEMBIC_HEADS[@]}" -eq 1 ]] || {
  echo "ERROR: expected exactly one Alembic head, got ${#ALEMBIC_HEADS[@]}" >&2
  exit 1
}
printf '%s\n' "${ALEMBIC_HEADS[0]}" > "$RELEASE_DIR/alembic_head.txt"
cp "$ROOT_DIR/LICENSE_SETUP.md" "$RELEASE_DIR/LICENSE_SETUP.md"
if [ -f "$ROOT_DIR/CLIENT_DEPLOYMENT.md" ]; then
  cp "$ROOT_DIR/CLIENT_DEPLOYMENT.md" "$RELEASE_DIR/CLIENT_DEPLOYMENT.md"
fi
if [ -f "$ROOT_DIR/CLIENT_UPDATE_SCRIPTS.md" ]; then
  cp "$ROOT_DIR/CLIENT_UPDATE_SCRIPTS.md" "$RELEASE_DIR/CLIENT_UPDATE_SCRIPTS.md"
fi
cp "$ROOT_DIR/scripts/create_initial_users.sql" "$RELEASE_DIR/create_initial_users.sql"
cp "$ROOT_DIR/scripts/add_grade_semester.sql" "$RELEASE_DIR/add_grade_semester.sql"
cp "$ROOT_DIR/scripts/client_apply_grade_semester.sh" "$RELEASE_DIR/client_apply_grade_semester.sh"
cp "$ROOT_DIR/scripts/client_recreate_backend.sh" "$RELEASE_DIR/client_recreate_backend.sh"
cp "$ROOT_DIR/scripts/client_update.sh" "$RELEASE_DIR/client_update.sh"
cp "$ROOT_DIR/scripts/client_adopt_schema_migrations.sh" "$RELEASE_DIR/client_adopt_schema_migrations.sh"
cp "$ROOT_DIR/scripts/deployment/client_first_install.sh" "$RELEASE_DIR/client_first_install.sh"
cp "$ROOT_DIR/scripts/deployment/client_install_license.sh" "$RELEASE_DIR/client_install_license.sh"
cp "$ROOT_DIR/scripts/deployment/client_create_initial_users.sh" "$RELEASE_DIR/client_create_initial_users.sh"
cp "$ROOT_DIR/scripts/deployment/client_backup_db.sh" "$RELEASE_DIR/client_backup_db.sh"
cp "$ROOT_DIR/scripts/deployment/client_check.sh" "$RELEASE_DIR/client_check.sh"
cp "$ROOT_DIR/scripts/deployment/client_upgrade_release.sh" "$RELEASE_DIR/client_upgrade_release.sh"
cp "$ROOT_DIR/license.lic.example" "$RELEASE_DIR/license.lic.example"
cp "$ROOT_DIR/license_public.pem.example" "$RELEASE_DIR/license_public.pem.example"
cp "$ROOT_DIR/docker/Dockerfile.client" "$RELEASE_DIR/Dockerfile.client"
cp "$ROOT_DIR/docker/.dockerignore.client" "$RELEASE_DIR/.dockerignore"
mkdir -p "$RELEASE_DIR/docker"
cp "$ROOT_DIR/docker/nginx.conf" "$RELEASE_DIR/docker/nginx.conf"
cp "$ROOT_DIR/docker/nginx.default.conf" "$RELEASE_DIR/docker/nginx.default.conf"
cp "$ROOT_DIR/docker-compose.client.yml" "$RELEASE_DIR/docker-compose.yml"
cp "$ROOT_DIR/.env.client.example" "$RELEASE_DIR/.env.example"

mkdir -p "$RELEASE_DIR/app"
cp -R "$ROOT_DIR/app/static" "$RELEASE_DIR/app/static"

mkdir -p \
  "$RELEASE_DIR/app/media" \
  "$RELEASE_DIR/app/media/avatars" \
  "$RELEASE_DIR/app/media/tmp" \
  "$RELEASE_DIR/app/media/news" \
  "$RELEASE_DIR/app/media/achievements" \
  "$RELEASE_DIR/app/media/materials" \
  "$RELEASE_DIR/app/media/applications" \
  "$RELEASE_DIR/app/media/document_orders"

cat > "$RELEASE_DIR/start.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
chmod +x ./lk_backend || true
exec ./lk_backend
EOF
chmod +x \
  "$RELEASE_DIR/start.sh" \
  "$RELEASE_DIR/client_apply_grade_semester.sh" \
  "$RELEASE_DIR/client_recreate_backend.sh" \
  "$RELEASE_DIR/client_update.sh" \
  "$RELEASE_DIR/client_adopt_schema_migrations.sh" \
  "$RELEASE_DIR/client_first_install.sh" \
  "$RELEASE_DIR/client_install_license.sh" \
  "$RELEASE_DIR/client_create_initial_users.sh" \
  "$RELEASE_DIR/client_backup_db.sh" \
  "$RELEASE_DIR/client_check.sh" \
  "$RELEASE_DIR/client_upgrade_release.sh"

echo "Ubuntu release created in: $RELEASE_DIR"
echo "Run it on Ubuntu with: ./start.sh"
