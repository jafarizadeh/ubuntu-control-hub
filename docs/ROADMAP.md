# Ubuntu Control — implementation checklist

Observed state: 2026-11-03. Checked items are implemented or directly observed in the existing Raspberry Pi MVP. Unchecked items need implementation or end-to-end verification.

## P0: baseline and access
- [x] Raspberry Pi hub uses localhost and systemd auto-start.
- [x] Tailscale private HTTPS Serve; no Funnel.
- [x] English, left-to-right, light PWA with Dashboard / Control / History.
- [x] Origin and CSRF checks on command requests.
- [x] Separate safe Git source, sample config, CI and basic tests.
- [ ] Review Tailnet ACL/grants for device and user access.
- [ ] Confirm dashboard, controls and PWA installation on iPhone Safari.
- [ ] Controlled GitHub-to-Pi deployment with backup and rollback.

## P1: Ubuntu Desktop
- [x] LAN availability monitoring.
- [x] Send Wake-on-LAN packet.
- [ ] Confirm physical wake from powered-off state.
- [x] Read-only desktop telemetry CLI built and tested locally (not deployed).
- [ ] Configure and verify restricted SSH channel from Raspberry Pi (not yet deployed).
- [ ] Authenticated, least-privilege, allowlisted command agent.
- [ ] Live CPU, GPU, RAM, disk, temperature, fans, uptime, network.
- [ ] Protected shutdown and restart with explicit confirmation.
- [ ] Shutdown timer, remaining time display, cancellation.
- [ ] Service controls: allowlisted systemd start/stop/restart.
- [ ] Read-only processes, long-running jobs, logs and errors.
- [ ] Approved updates, backups, file transfer and limited energy controls.
- [ ] Job-aware protection against disrupting active work.

## P1: LG webOS TV
- [x] LAN/webOS reachability probes.
- [x] Send a TV Wake-on-LAN packet.
- [ ] Confirm screen-on state (reachable network is insufficient).
- [ ] One-time TV webOS pairing with on-screen approval.
- [ ] Volume, mute and standby controls after pairing.
- [ ] HDMI input selection, app launch and verified command results.

## P2: Raspberry Pi hub
- [x] Pi CPU temperature, RAM, storage and uptime.
- [ ] CPU usage, throttling, network throughput and error monitoring.
- [ ] Auto-restart allowlisted failed services; alert on repeated failure.
- [ ] Protected hub reboot/shutdown and safe update procedure.
- [ ] Backup/restore and health checks.

## P2: iPhone and automation
- [x] Tailnet dashboard with local command history.
- [ ] True action outcomes: accepted / sent / completed / failed.
- [ ] Schedules, workflows, guardrails, pause/cancel controls.
- [ ] Push alerts for device offline, high temperature and job completion.
- [ ] Configurable devices and long-term log retention policy.

## Approval gate
No real system shutdown, restart, package update, fan override or disruptive job action without explicit approval, preflight checks and a rollback plan. Test dry-runs before enabling new controls.

Next focus: safe Git base, Ubuntu agent and metrics, then timer and service controls, LG pairing, and automation.
