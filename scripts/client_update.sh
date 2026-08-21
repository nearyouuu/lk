#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ $# -le 1 ]] || { echo "Usage: client_update.sh [--no-cache]" >&2; exit 2; }
[[ $# -eq 0 || "${1:-}" == "--no-cache" ]] || { echo "Usage: client_update.sh [--no-cache]" >&2; exit 2; }

"$SCRIPT_DIR/client_apply_grade_semester.sh"
"$SCRIPT_DIR/client_recreate_backend.sh" "$@"
echo "Client update completed. Database volume was preserved."
