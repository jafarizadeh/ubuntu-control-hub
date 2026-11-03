# Operations and deployment

The Raspberry Pi currently runs a standalone working installation. This repository is a sanitized initial snapshot, **not** an automatically deployed copy. Never overwrite the live directory with a git clone without a reviewed migration and backup.

## Read-only checks

    systemctl is-active ubuntu-control-hub.service
    sudo tailscale serve status
    sudo tailscale funnel status
    curl -fsS http://127.0.0.1:8765/api/status

## Future first deployment
1. Clone this repository into a separate directory on Raspberry Pi.
2. Create a virtual environment and install requirements.txt.
3. Privately copy config/devices.json into the new clone. Do not commit it.
4. Check required configuration including controller.broadcast_ip.
5. Run static tests and inspect source changes versus the active service.
6. Back up existing service unit, local history, configuration and LG pairing database.
7. Schedule and explicitly approve the switch to the reviewed release.
8. Check the PWA, API, Tailscale Serve and systemd status; retain rollback.

## User approval
LG pairing requires acceptance on the actual TV screen. Wake-on-LAN requests only send network packets; verify actual power-on separately. Ubuntu shutdown, restart and updates are future agent functionality, not part of this MVP.
