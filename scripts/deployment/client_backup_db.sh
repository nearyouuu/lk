#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
[[ -f "$PROJECT_DIR/docker-compose.yml" ]] || PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTPUT="${1:-$PROJECT_DIR/cabinet-$(date +%F_%H-%M-%S).dump}"
cd "$PROJECT_DIR"

OUTPUT_DIR="$(dirname "$OUTPUT")"
[[ -d "$OUTPUT_DIR" ]] || { echo "ERROR: backup directory not found: $OUTPUT_DIR" >&2; exit 1; }
[[ ! -e "$OUTPUT" ]] || { echo "ERROR: refusing to overwrite backup: $OUTPUT" >&2; exit 1; }
TEMP_OUTPUT="$(mktemp "${OUTPUT}.tmp.XXXXXX")"
trap 'rm -f "$TEMP_OUTPUT"' EXIT
docker compose exec -T db sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$TEMP_OUTPUT"
[[ -s "$TEMP_OUTPUT" ]] || { echo "ERROR: empty backup" >&2; exit 1; }
mv "$TEMP_OUTPUT" "$OUTPUT"
trap - EXIT
echo "Backup created: $OUTPUT"
