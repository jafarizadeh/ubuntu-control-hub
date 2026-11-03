# Ubuntu Control — implementation checklist

Observed state: 2026-11-03. Checked items are implemented or directly observed in the existing Raspberry Pi MVP. Unchecked items need implementation or end-to-end verification.

## P0: baseline and access
- [x] Raspberry Pi hub uses localhost and systemd auto-start.
- [x] Tailscale private HTTPS Serve; no Funnel.
- [x] English/LTR/light Ubuntu-first Dashboard (no Raspberry Pi metrics on home screen).
- [x] Separate Ubuntu and LG power cards; live status and disabled actions are explicit.
- [x] Per-browser metric visibility preferences (localStorage) and offline/stale data handling.
- [x] Control tab for audio, network, CPUWM, app/file management, remote/GPT, and LG.
- [x] Origin and CSRF checks on command requests.
- [x] Separate safe Git source, sample config, CI and basic tests.
- [ ] Review Tailnet ACL/grants for device and user access.
- [ ] Confirm updated dashboard and PWA installation on real iPhone Safari (mobile Chromium smoke test passed).
- [x] Stage separate Raspberry Pi release and preserve backed-up previous systemd service.
- [ ] Automate tested GitHub-to-Pi deployment with rollback.

## P1: Ubuntu Desktop
- [x] LAN availability monitoring.
- [x] Send Wake-on-LAN packet.
- [ ] Confirm physical wake from powered-off state.
- [x] Read-only desktop telemetry CLI built, tested and running as a user service.
- [x] Implement signed outbound HTTPS telemetry with a private Ed25519 key on Ubuntu and public verification key on Pi.
- [x] Deploy and verify the outbound agent on Ubuntu and Raspberry Pi.
- [x] Read-only Ubuntu audio, NetworkManager connectivity, and CPUWM current profile detected.
- [x] Authenticated, allowlisted outbound command channel for Ubuntu Volume/Mute and CPUWM profile.
- [ ] Verify command authorization and actions on real iPhone Safari end-to-end.
- [x] Live CPU, GPU, RAM, disk, temperature, fans and uptime telemetry.
- [ ] Advanced per-interface network telemetry.
- [ ] Protected shutdown and restart with explicit confirmation.
- [x] Preview-only timer, server remaining-time display, persistence and cancellation (no execution).
- [x] Read-only power safety: Atlas, shutdown inhibitors and best-effort workload categories; unknown data blocks.
- [ ] Real timer execution after explicit future approval and activation gates.
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

Current power controls are simulation only and have not been deployed by this iteration. Next activation gates: explicit future approval for real actions, a second confirmation, a fresh safety check at the deadline, verified CPUWM active-job checks without bypassing the manager, and protection for unsaved desktop work. Never perform a blind shutdown of unsaved work. Cancellation and failure behavior must be verified before any real power execution is enabled. Continue iPhone verification of sound/CPUWM receipts, LG pairing and other remote operations separately.
