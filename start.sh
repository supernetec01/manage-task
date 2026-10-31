#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.10+ is required. Install Python 3 and try again." >&2
  exit 1
fi
exec python3 server.py --host 0.0.0.0 --port "${PORT:-5001}"
