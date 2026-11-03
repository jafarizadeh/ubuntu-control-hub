# Ubuntu Control

A private English-language, light-themed, left-to-right PWA for remotely managing Ubuntu Desktop and LG webOS TV through an always-on Raspberry Pi.

**MVP status (v1.0 UI):** The Ubuntu-first PWA remains privately
available through Tailscale HTTPS on the Raspberry Pi. It displays live signed
Ubuntu metrics, iOS-style CPU Details, LG webOS power controls and Wake-on-LAN.
A separate owner-authenticated real-power workflow offers Shutdown, Restart and
cancelable 30-second-to-4-hour scheduling, with an explicit permanent-data-loss
warning for unsaved browser tabs, documents and terminal work. Saving and
closing files are NOT required; the user must consciously accept the risk.
Atlas and all three physical Codex accounts must have explicit recorded owner
stops, no active attempts, and CPUWM must be verified idle. A root-owned helper
rechecks those gates immediately before normal systemd poweroff/reboot; there
is no force flag, shell command, job kill or implicit Atlas stop. Existing
preview/simulation and CPU/GPU controls remain separate. Real firmware WOL
from power-off has not yet been physically verified. See
[Power Operations](docs/POWER_OPERATIONS.md) for precise controls and limits.

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
- web/static/: English LTR/light Ubuntu-first PWA, sanitized owner-supplied SVG icons including stateful on/off logos and power symbol, metric selection, iPhone-style action sheets, wheel-based timer preview, custom confirmations, one power button per device and service worker (see docs/ASSETS.md).
- CPU load tile opens a dedicated CPU Details page with a four-column per-core grid, red live-history sparkline, GPU status, and processor information. Measurements come from the signed Ubuntu Agent, never Pi CPU data.
- CPU Details uses 2-second page and signed Agent updates while an authorized owner views it; the other pages remain on the 15-second UI refresh and the Agent normally reports every 10 seconds.
- bin/: Raspberry Pi status, Wake-on-LAN, LG pairing and Tailnet publication.
- agent/desktop_status.py: read-only Ubuntu telemetry (no root, no daemon).
- agent/power_safety.py: signed read-only Atlas, CPUWM, GNOME and desktop warnings; real power readiness remains a separate explicit opt-in workflow.
- agent/power_gate.py and agent/power_execute.py: fail-closed real power safety gate and fixed privileged helper, with no automatic file saving or process kill.
- deploy/ubuntu-control-power-*.service and deploy/51-ubuntu-control-power.rules.example: root-owned restricted one-shot power services and narrowly scoped PolicyKit authorization; the outbound Agent keeps NoNewPrivileges=true.
- web/power_schedule.py: durable owner-armed, cancelable real timer and at-most-once signed Ubuntu dispatch.
- agent/atlas_guard.py: read-only Atlas SQLite proof separating idle/RUN from owner STOP and verifying future per-Codex stop acknowledgements; no stopping or power action (see docs/ATLAS_POWER_POLICY.md and docs/ATLAS_CODEX_STOP_BRIDGE.md).
- agent/codex_stop_attestation.py: fail-closed 15-second, reboot-bound 3-worker owner-stop receipt verifier for the future Atlas producer; current Atlas does not publish these receipts.
- web/power_preview.py: persisted timer simulation, separate from the command queue.
- agent/outbound.py: outgoing HTTPS-only sender to the private Raspberry Pi hub.
- agent/cpu_monitor.py: 1-second read-only /proc/stat per-core sampler and bounded 90-second activity history.
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
    node --check web/static/power-live.js
    python3 -m json.tool config/devices.example.json

These checks do not send power or TV commands.

## Project policy

Use feature/fix branches and pull requests. Command authorization is configured exclusively in the Pi-local, ignored config/operator.json; see docs/COMMANDS.md. Keep user-visible UI and docs in English. Protect the Raspberry Pi service and data when deploying. The active Raspberry Pi installation runs from a separate release directory and is not auto-deployed from GitHub; see docs/OPERATIONS.md and docs/ROADMAP.md. The desktop status agent uses outbound HTTPS from Ubuntu to the Raspberry Pi; see docs/OUTBOUND_AGENT.md. No inbound SSH daemon is necessary.

## Confidentiality

Never commit config/devices.json, the LG pairing database, data/history.jsonl, private keys, credentials or device logs. The device template contains reserved documentation IPs only. Tailscale provides a private network boundary; **CSRF is not user authentication**. Review Tailnet ACLs and add authorization before granting sensitive controls to multiple users.
