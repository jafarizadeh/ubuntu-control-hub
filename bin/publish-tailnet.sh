#!/bin/sh
set -eu
STATUS="$(sudo -n tailscale status --json | jq -r '.BackendState')"
if [ "$STATUS" != "Running" ]; then
  printf 'Tailscale has not been authenticated yet (state: %s).\n' "$STATUS"
  printf 'Visit the authentication link shown by: sudo tailscale status\n'
  exit 2
fi
echo 'Publishing Ubuntu Control privately within the Tailscale tailnet; no Funnel.'
sudo -n tailscale serve --bg 8765
sudo -n tailscale serve status
