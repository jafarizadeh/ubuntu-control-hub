#!/bin/sh
set -eu
umask 077
BASE="$(cd "$(dirname "$0")/.." && pwd)"
TV_IP="$("$BASE/.venv/bin/python" -c 'import json,sys; print(json.load(open(sys.argv[1]))["tv"]["ip"])' "$BASE/config/devices.json")"
cd "$BASE/config"
echo "Turn on the LG TV and approve the webOS pairing prompt using its remote."
timeout 90 "$BASE/.venv/bin/bscpylgtvcommand" \
  -p "$BASE/config/.aiopylgtv.sqlite" --log WARNING \
  "$TV_IP" get_system_info
chmod 600 "$BASE/config/.aiopylgtv.sqlite"
echo "TV pairing completed."
