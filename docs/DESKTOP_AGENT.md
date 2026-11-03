# Ubuntu Desktop read-only agent (prototype)

This is the first stage of the Ubuntu Control desktop integration. It collects system statistics without sudo, an HTTP server, an incoming listening port or any power commands.

## Output

On Ubuntu Desktop:

    python3 agent/desktop_status.py

It emits one JSON document containing schema version, hostname, OS, uptime, CPU usage/temperature, memory, disk, available hardware fan readings, and NVIDIA GPU metrics if available. Unsupported sensors produce null or an empty array, not guessed values.

The Raspberry Pi uses a safe SSH client in bin/desktop_agent_client.py. It is DISABLED by default, so it does not contact Ubuntu until explicitly enabled in the private config/devices.json.

## SSH key restricted to status only

Use a separate SSH key exclusively for status; never reuse an administrative key or GitHub deploy key.

1. Install reviewed source on Ubuntu and Pi WITHOUT overwriting the live Pi installation.
2. On Pi, generate a new Ed25519 SSH key with private key permission 0600, e.g. ~/.ssh/ubuntu-control-status-readonly, and keep it outside Git.
3. On Ubuntu, append its PUBLIC key to ~/.ssh/authorized_keys using a forced command. Replace each placeholder and confirm file ownership:

       restrict,command="/usr/bin/python3 /home/YOUR_UBUNTU_USER/ubuntu-control-hub/agent/desktop_status.py --ssh" ssh-ed25519 YOUR_PUBLIC_KEY_HERE

   The SSH restrict option disables interactive PTY and all forwarding. The script itself rejects any requested command other than ubuntu-control-status-v1.
4. Verify the Ubuntu SSH host fingerprint independently, and add that host to the Pi user's known_hosts. Never disable host verification.
5. Add the agent_ssh section to the DESKTOP object in Pi's PRIVATE config/devices.json, using your real account and key path:

       "agent_ssh": {
         "enabled": true,
         "username": "YOUR_UBUNTU_USER",
         "identity_file": "/home/YOUR_PI_USER/.ssh/ubuntu-control-status-readonly"
       }

   The existing desktop.ip remains the connection target and is validated as an IPv4 or IPv6 address.
6. From the Pi, test the restricted command:

       ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes -i ~/.ssh/ubuntu-control-status-readonly YOUR_UBUNTU_USER@YOUR_UBUNTU_IP ubuntu-control-status-v1

   It must return JSON and never offer an interactive shell. Confirm unrelated commands fail with this key.
7. Pi merges the agent response into desktop.metrics. The PWA displays telemetry only when desktop.control_agent is online; otherwise it shows a clear status message.

## Limitations

- NOT deployed to the live Raspberry Pi hub in this change.
- No shutdown, restart, timer, fan override, package update, arbitrary commands or file transfer API.
- Some hardware sensors are inaccessible; missing values are intentional.
- For future privileged commands use a separate narrowly restricted channel with confirmations, job-aware preflight and clear receipts.
- No new SSH server is installed by this change; existing SSH on Ubuntu is reused.

## Tests

    python3 -m unittest discover -s tests -v
    node --check web/static/app.js
    node --check web/static/sw.js

Only non-destructive checks are permitted without explicit approval.
