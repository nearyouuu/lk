#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
[[ -f "$PROJECT_DIR/docker-compose.yml" ]] || PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

[[ "$EUID" -eq 0 ]] || { echo "ERROR: run with sudo" >&2; exit 1; }

LICENSE_SOURCE="${1:-/tmp/license.lic}"
PUBLIC_KEY_SOURCE="${2:-/tmp/license_public.pem}"
[[ -f "$LICENSE_SOURCE" ]] || { echo "ERROR: $LICENSE_SOURCE not found" >&2; exit 1; }
[[ -f "$PUBLIC_KEY_SOURCE" ]] || { echo "ERROR: $PUBLIC_KEY_SOURCE not found" >&2; exit 1; }

install -m 600 "$LICENSE_SOURCE" "$PROJECT_DIR/license.lic"
install -m 644 "$PUBLIC_KEY_SOURCE" "$PROJECT_DIR/license_public.pem"
cd "$PROJECT_DIR"
docker compose restart backend
sleep 2
curl -fsS http://127.0.0.1:6123/license/status
echo
