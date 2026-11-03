# Ubuntu Control

A private English-language, light-themed, left-to-right PWA for remotely managing Ubuntu Desktop and LG webOS TV through an always-on Raspberry Pi.

**MVP status:** The Raspberry Pi hub already runs and provides an HTTPS Tailnet dashboard. The initial implementation supports Pi health monitoring, network availability, Wake-on-LAN packet requests, local command history, and optional webOS controls after on-screen pairing. Ubuntu shutdown/restart, desktop metrics, and timers require a future authenticated desktop agent.

## Architecture

    iPhone PWA  -- private Tailscale HTTPS --> Raspberry Pi Hub (localhost:8765)
                                                   |          |
                                             LAN status/WOL   LG webOS (paired)
                                                   |
                                          Ubuntu Agent (planned)

The backend is Python, and the frontend is static HTML/CSS/JavaScript with no build step. No public port or Tailscale Funnel should be enabled.

## Structure

- web/server.py: private API, allowlisted command handlers and static file server.
- web/static/: English LTR/light PWA, assets and service worker.
- bin/: Raspberry Pi status, restricted SSH desktop client, Wake-on-LAN, LG pairing and Tailnet publication.
- agent/desktop_status.py: read-only Ubuntu telemetry (no root, no daemon).
- config/devices.example.json: fictional sample addresses only.
- deploy/: sample systemd unit.
- docs/: roadmap, operations, security and development workflow.
- tests/: safe, non-destructive repository and desktop-agent tests.

## Local setup (Raspberry Pi OS)

    git clone https://github.com/jafarizadeh/ubuntu-control-hub.git
    cd ubuntu-control-hub
    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
    cp config/devices.example.json config/devices.json

Replace all documentation IPs and placeholder MACs with your own private device values in config/devices.json. The sample addresses are deliberately non-functional. Configure the correct controller.broadcast_ip (LAN subnet broadcast address).

Start locally for testing:

    .venv/bin/python web/server.py
    curl http://127.0.0.1:8765/api/status

Use deploy/ubuntu-control-hub.service.example as a template for systemd. Do not replace the currently running Pi installation automatically. After checking Tailnet permissions, privately publish with:

    sudo tailscale serve --bg 8765
    sudo tailscale serve status
    sudo tailscale funnel status

Do not run tailscale funnel. A private HTTPS hostname appears in tailscale serve status.

## Testing

    python3 -m unittest discover -s tests -v
    python3 -m compileall -q bin web tests
    node --check web/static/app.js
    node --check web/static/sw.js
    python3 -m json.tool config/devices.example.json

These checks do not send power or TV commands.

## Project policy

Use feature/fix branches and pull requests. Keep user-visible UI and docs in English. Protect the Raspberry Pi service and data when deploying. The existing live installation is not yet connected to GitHub releases; see docs/OPERATIONS.md and docs/ROADMAP.md. The desktop status agent is a separate, opt-in feature; see docs/DESKTOP_AGENT.md.

## Confidentiality

Never commit config/devices.json, the LG pairing database, data/history.jsonl, private keys, credentials or device logs. The device template contains reserved documentation IPs only. Tailscale provides a private network boundary; **CSRF is not user authentication**. Review Tailnet ACLs and add authorization before granting sensitive controls to multiple users.
