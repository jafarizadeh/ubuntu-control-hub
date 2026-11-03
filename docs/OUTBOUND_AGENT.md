# Ubuntu Control outgoing telemetry agent

Ubuntu reports status to the always-on Raspberry Pi hub over **outbound private HTTPS**, so the desktop needs no incoming SSH or HTTP port.

## Operation

1. The desktop runs agent/outbound.py as an unprivileged user service.
2. It reads CPU/RAM/storage/temperature/fan/GPU metrics and sends one JSON report every 10 seconds.
3. The private endpoint https://YOUR_PI_HOSTNAME.YOUR_TAILNET.ts.net/api/agent/report accepts only a valid Ed25519 signature checked against a trusted public key.
4. The Pi marks the agent online for 35 seconds after the most recent successful report.
5. The PWA displays fresh metrics, and hides them if the agent is unavailable.

The sender accepts no incoming network connections. It can execute only the narrow, authenticated command allowlist described in [COMMANDS.md](COMMANDS.md).

## Setup

- The Pi and Ubuntu must already be on the same authorized Tailscale network.
- The Pi hub remains on localhost:8765 behind private Tailscale Serve.
- Generate an Ed25519 key pair on Ubuntu. Keep identity.key private with file mode 0600.
- Copy ONLY the public key identity.pub to Pi config/desktop_agent.pub. Do not copy the private key.
- Create private Ubuntu ~/.config/ubuntu-control-agent/client.json with:

    {
      "hub_url": "https://YOUR_PI_HOSTNAME.YOUR_TAILNET.ts.net",
      "identity_file": "/home/YOUR_UBUNTU_USER/.config/ubuntu-control-agent/identity.key",
      "interval_seconds": 10
    }

Test without touching any system services:

    python3 agent/outbound.py --config ~/.config/ubuntu-control-agent/client.json --once

Then install the user service using deploy/ubuntu-control-agent.service.example, replacing YOUR_UBUNTU_USER and paths.

    systemctl --user daemon-reload
    systemctl --user enable --now ubuntu-control-agent.service
    systemctl --user is-active ubuntu-control-agent.service

For startup without an interactive login, an administrator may use:

    sudo loginctl enable-linger YOUR_UBUNTU_USER

## Verification

- On Pi: GET http://127.0.0.1:8765/api/health reports agent online.
- On iPhone: the Ubuntu card displays CPU/RAM/disk/temperature when the agent is connected.
- Disconnect Ubuntu: after at most 35 seconds, the agent is unavailable.
- POST to agent endpoint without a valid signature returns HTTP 403.
- Never enable Tailscale Funnel.

Audio and confirmed CPUWM profiles use the outbound command channel; see [COMMANDS.md](COMMANDS.md) for private operator setup, delivery guarantees and state files. Shutdown, restart, timers and other power actions remain locked out of that channel.
