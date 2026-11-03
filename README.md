# Ubuntu Control

A private English-language, light-themed, left-to-right PWA for remotely managing Ubuntu Desktop and LG webOS TV through an always-on Raspberry Pi.

**MVP status (v0.4 UI):** The Raspberry Pi hub runs privately over Tailscale HTTPS. The default Dashboard is **Ubuntu-first**: live signed Ubuntu CPU/GPU/RAM/disk/temperature/fan/uptime telemetry, two power cards for Ubuntu and LG, and locally customizable metric tiles. The Control tab shows actual Ubuntu audio/network/CPUWM status and clearly marks unimplemented remote controls as disabled. Wake-on-LAN and LG webOS controls (once paired) are already connected. Volume/Mute and confirmed CPUWM profile changes are available through an opt-in, verified Tailnet-owner command channel (see docs/COMMANDS.md). Control now includes read-only Ubuntu power safety and a durable, cancelable timer preview. This is simulation only: it never shuts down or restarts Ubuntu, and real power and terminal operations remain disabled. Power safety now observes bounded CPUWM managed-scope counts and GNOME/Atlas blockers, but cannot verify all running jobs or unsaved files. Safety remains blocked. See [the command protocol](docs/COMMANDS.md) for activation gates.

## Architecture

    iPhone PWA  -- private Tailscale HTTPS --> Raspberry Pi Hub (localhost:8765)
                                                   |          |
                                             LAN status/WOL   LG webOS (paired)
                                                   ^
                                  signed outbound HTTPS telemetry
                                                   |
                                        Ubuntu read-only agent

The backend is Python, and the frontend is static HTML/CSS/JavaScript with no build step. No public port or Tailscale Funnel should be enabled.

## Structure

- web/server.py: private API, allowlisted command handlers and static file server.
- web/static/: English LTR/light Ubuntu-first PWA, locally sanitized SVG icons supplied by the owner, metric selection, power cards and service worker (see docs/ASSETS.md).
- bin/: Raspberry Pi status, Wake-on-LAN, LG pairing and Tailnet publication.
- agent/desktop_status.py: read-only Ubuntu telemetry (no root, no daemon).
- agent/power_safety.py: conservative read-only Atlas, CPUWM status, desktop work and inhibitor checks. No power execution.
- web/power_preview.py: persisted timer simulation, separate from the command queue.
- agent/outbound.py: outgoing HTTPS-only sender to the private Raspberry Pi hub.
- config/devices.example.json: fictional sample addresses only.
- deploy/: sample systemd unit.
- docs/: dashboard/control specification, authenticated command protocol, roadmap, operations, security and development workflow.
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

Use feature/fix branches and pull requests. Command authorization is configured exclusively in the Pi-local, ignored config/operator.json; see docs/COMMANDS.md. Keep user-visible UI and docs in English. Protect the Raspberry Pi service and data when deploying. The active Raspberry Pi installation runs from a separate release directory and is not auto-deployed from GitHub; see docs/OPERATIONS.md and docs/ROADMAP.md. The desktop status agent uses outbound HTTPS from Ubuntu to the Raspberry Pi; see docs/OUTBOUND_AGENT.md. No inbound SSH daemon is necessary.

## Confidentiality

Never commit config/devices.json, the LG pairing database, data/history.jsonl, private keys, credentials or device logs. The device template contains reserved documentation IPs only. Tailscale provides a private network boundary; **CSRF is not user authentication**. Review Tailnet ACLs and add authorization before granting sensitive controls to multiple users.
