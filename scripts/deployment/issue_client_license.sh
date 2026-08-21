#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CUSTOMER=""
FINGERPRINT=""
LICENSE_ID=""
TARIFF="premium"
EXPIRES_AT=""
MAX_USERS="500"
OUTPUT="$ROOT_DIR/license.lic"
GENERATE_KEYS=0

usage() {
  cat <<'EOF'
Usage: issue_client_license.sh --customer TEXT --fingerprint VALUE \
  --license-id ID --expires-at ISO8601 [--tariff premium] [--max-users 500] \
  [--output PATH] [--generate-keys]

Use --generate-keys only once, when neither license key exists yet.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --customer) CUSTOMER="$2"; shift ;;
    --fingerprint) FINGERPRINT="$2"; shift ;;
    --license-id) LICENSE_ID="$2"; shift ;;
    --tariff) TARIFF="$2"; shift ;;
    --expires-at) EXPIRES_AT="$2"; shift ;;
    --max-users) MAX_USERS="$2"; shift ;;
    --output) OUTPUT="$2"; shift ;;
    --generate-keys) GENERATE_KEYS=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

[[ -n "$CUSTOMER" && -n "$FINGERPRINT" && -n "$LICENSE_ID" && -n "$EXPIRES_AT" ]] || {
  usage >&2
  exit 2
}

cd "$ROOT_DIR"
if [[ "$GENERATE_KEYS" -eq 1 ]]; then
  if [[ -e license_private.pem || -e license_public.pem ]]; then
    echo "ERROR: refusing to replace an existing license key" >&2
    exit 1
  fi
  python3 scripts/generate_license_keys.py
fi
[[ -f license_private.pem ]] || {
  echo "ERROR: license_private.pem not found; restore it or use --generate-keys for a new installation" >&2
  exit 1
}
[[ -f license_public.pem ]] || { echo "ERROR: license_public.pem not found" >&2; exit 1; }
python3 scripts/issue_license.py \
  --customer "$CUSTOMER" \
  --fingerprint "$FINGERPRINT" \
  --license-id "$LICENSE_ID" \
  --tariff "$TARIFF" \
  --expires-at "$EXPIRES_AT" \
  --max-users "$MAX_USERS" \
  --private-key "$ROOT_DIR/license_private.pem" \
  --output "$OUTPUT"

echo "Created signed license: $OUTPUT"
echo "Send only the license and license_public.pem; never send license_private.pem."
