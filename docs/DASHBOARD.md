# Ubuntu-first Dashboard and remote-control plan

## Product direction (November 2026)

Raspberry Pi is the always-on connection hub, not the primary device shown on the Dashboard. The Dashboard is a workstation console for Ubuntu, powered by signed outbound telemetry. The iPhone PWA uses English, left-to-right text and a fixed light theme.

## Dashboard

1. Ubuntu overview: real CPU, GPU, estimated used RAM, OS, hostname and uptime.
2. Power: separate On and Off/Standby actions for Ubuntu Desktop and LG Display.
3. Optional metric tiles: CPU/GPU temperature, RAM available, free disk, fan RPM, uptime, GPU memory, networking, sound and current CPUWM profile.

The Customize action selects visible tiles. Preferences are stored on the viewing device in localStorage and can be reset; they never alter actual sensor measurements. Missing/stale Ubuntu telemetry is cleared, not replaced with Raspberry Pi measurements.

Actions:
- Ubuntu Power on: existing Wake-on-LAN packet, not confirmation of successful power-on.
- Ubuntu Power off: disabled until an authenticated command channel with confirmation and active-job protections exists.
- LG Power on: existing Wake-on-LAN packet.
- LG Standby: available after one-time LG webOS pairing.

## Control Center

Sound shows live PipeWire volume and mute state. Internet/Network lists NetworkManager Ethernet and Wi-Fi connections. Performance shows the current profile from the existing CPU & GPU Workload Manager. Applications and Files and Terminal/GPT Remote are visible planning categories, not live controls. LG webOS pairing, volume, mute and standby are connected to the existing Pi routes once paired.

The real Workload Manager supports the three profiles quiet, balanced and performance. Applying profiles from the phone should use its existing manager CLI only after an authenticated, narrowly allowlisted control path has been reviewed. Changes could affect scientific jobs, so require confirmation and preserve thermal ceilings.

Network disconnection must have recovery safeguards. Closing applications must allow selection and warn about unsaved data. The phone dashboard should not expose arbitrary shell command execution.

## Scope and privacy

Only Ubuntu telemetry is displayed on the Dashboard. Pi hardware telemetry remains internal to the Hub. All live device IPs, MACs, credentials, LG pairing data and command history are kept outside the public repository. All remote access remains inside the Tailnet; Tailscale Funnel is not used.

CSRF validation is not a substitute for authentication. No OS shutdown, restart, desktop application termination, or performance change is performed by this interface migration.

## Validation

Mobile Chromium tests cover the Ubuntu-first layout, separate power buttons, local preference persistence, the Control tab, offline-data clearing and JavaScript errors. iPhone Safari confirmation remains a separate end-to-end task.
