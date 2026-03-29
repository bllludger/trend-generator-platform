#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-8788}"

if [[ ! "$PORT" =~ ^[0-9]+$ ]]; then
  echo "PORT must be numeric" >&2
  exit 1
fi

LATEST_HTML="$(ls -1t "$ROOT_DIR"/reports/private/users_*_activity_*.html "$ROOT_DIR"/reports/private/users_activity_*.html 2>/dev/null | head -n 1 || true)"
if [[ -z "$LATEST_HTML" ]]; then
  echo "No private report found in $ROOT_DIR/reports/private" >&2
  echo "Build one first: $ROOT_DIR/scripts/build_private_users_report.py" >&2
  exit 1
fi

REL_PATH="${LATEST_HTML#$ROOT_DIR/}"

echo "Starting private report server on 127.0.0.1:${PORT}"
echo "Local (on VPS): http://127.0.0.1:${PORT}/${REL_PATH}"
echo "SSH tunnel example (run on your laptop):"
echo "  ssh -N -L ${PORT}:127.0.0.1:${PORT} <user>@<vps-host>"
echo "Then open in browser on your laptop:"
echo "  http://127.0.0.1:${PORT}/${REL_PATH}"
echo
echo "Security note: server is bound to loopback only (127.0.0.1)."

cd "$ROOT_DIR"
exec python3 -m http.server "$PORT" --bind 127.0.0.1
