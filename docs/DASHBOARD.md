# Ubuntu-first Dashboard and remote-control plan

## Product direction (November 2026)

Raspberry Pi is the always-on connection hub, not the primary device shown on the Dashboard. The Dashboard is a workstation console for Ubuntu, powered by signed outbound telemetry. The iPhone PWA uses English, left-to-right text and a fixed light theme.

## Dashboard

1. Ubuntu overview: real CPU, GPU, estimated used RAM, OS, hostname and uptime.
2. Power: one stateful SVG action per device. The label, badge and on/off icon change only with verified Ubuntu or webOS status.
3. Optional metric tiles: CPU/GPU temperature, RAM available, free disk, fan RPM, uptime, GPU memory, networking, sound and current CPUWM profile.

The Customize action selects visible tiles. Preferences are stored on the viewing device in localStorage and can be reset; they never alter actual sensor measurements. Missing/stale Ubuntu telemetry is cleared, not replaced with Raspberry Pi measurements.

Actions:
- Ubuntu with a fresh signed heartbeat: show On and a single disabled Power off unavailable button (no unprotected shutdown).
- Ubuntu not reachable: show Not reachable, never claim it is confirmed Off, and offer Send wake signal if a MAC address is configured.
- Ubuntu Power off: disabled until an authenticated command channel with confirmation and active-job protections exists.
- LG webOS Active: show On and only Standby display. Screen Off: offer the paired screen-on API. Verified Suspend / Power Off: offer Wake-on-LAN. If the power state is unverified, show Unknown or Not reachable; never claim that ping equals screen-on.
- LG Standby: enabled only when the paired webOS get_power_state read-only query verifies Active. A new state is checked after the request; success of sending a command is not proof of a completed power transition.

## Control Center

Sound shows live PipeWire volume and mute state and supports explicit remote volume/mute after verified owner authorization. Internet/Network lists NetworkManager Ethernet and Wi-Fi connections. Performance shows the current profile from the existing CPU & GPU Workload Manager and can request an explicitly confirmed profile change. All remote actions are queued through the private Hub and show actual agent receipts. Applications and Files and Terminal/GPT Remote remain visible planning categories, not live controls. LG webOS pairing, volume, mute and standby are connected to the existing Pi routes once paired.

The real Workload Manager supports the three profiles quiet, balanced and performance. Requests from the phone use an authenticated, narrowly allowlisted outbound control path, with explicit user confirmation and agent execution receipts. Changes could affect scientific jobs, so require confirmation and preserve thermal ceilings.

Network disconnection must have recovery safeguards. Closing applications must allow selection and warn about unsaved data. The phone dashboard should not expose arbitrary shell command execution.

## Scope and privacy

Only Ubuntu telemetry is displayed on the Dashboard. Pi hardware telemetry remains internal to the Hub. All live device IPs, MACs, credentials, LG pairing data and command history are kept outside the public repository. All remote access remains inside the Tailnet; Tailscale Funnel is not used.

CSRF validation is not a substitute for authentication. No OS shutdown, restart, desktop application termination, or performance change is performed by this interface migration.

## Validation

Mobile Chromium tests cover the Ubuntu-first layout, separate power buttons, local preference persistence, the Control tab, offline-data clearing and JavaScript errors. iPhone Safari confirmation remains a separate end-to-end task.

## iPhone interface (v0.5 UI)

Power preview selection uses a two-way iOS-style segmented control for Shutdown
or Restart simulation, six quick duration presets, and a bottom sheet with
independent hours/minutes scrolling wheels. The allowed duration remains 1 to
240 minutes. The ring interpolates the server's remaining-seconds snapshot for
display, but the Raspberry Pi is authoritative and performs **no power action**
when a preview reaches zero.

Workload Manager profile selection uses a separate accessible bottom sheet for
Quiet, Balanced, and Performance. Changing the selection does not change the
actual profile: Apply opens a custom confirmation panel, and the request still
uses the existing authenticated agent command queue and execution receipt.
Wake, LG standby and pairing confirmations likewise use a custom in-app
accessible dialog instead of a browser confirm window. Success/error feedback
is styled as a dismissible in-app notification.

These are presentation and interaction changes only. No new privileged API
capability, arbitrary shell, or real shutdown/restart has been enabled.
