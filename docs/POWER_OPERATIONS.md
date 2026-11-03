# Ubuntu Control real power and unsaved-data policy

Real power (shutdown, restart, and delayed operation) is independent of
application/file/terminal management. No file is automatically saved, closed
or modified when the owner confirms a power request.

## Required operator flow

1. The Raspberry Pi verifies recent signed Ubuntu telemetry. Atlas must
   have an explicit owner-issued STOP, all three physical agent switches must
   be OFF with recorded owner provenance, all known in-flight/remote sessions
   must be settled, and CPUWM must certify zero managed work.
2. The owner chooses Shutdown or Restart and a delay (Now = 30-second
   cancellable grace; otherwise up to 240 minutes).
3. The app shows a clear data-loss warning. The owner explicitly checks
   acknowledgement of permanent loss of unsaved documents, browser edits,
   forms, and terminal work, even if files have not been saved.
   It never asks the owner to claim that everything was saved.
4. A second iPhone-style modal asks for confirmation. If rejected, no real
   timer is created.
5. The Raspberry Pi persists the request and supports cancellation until a
   signed fresh Ubuntu report authorizes at-most-once dispatch.
6. Immediately before systemd shutdown/reboot, a root-owned fixed helper
   repeats the Atlas/CPUWM/process checks. GNOME's shutdown inhibitor can be
   bypassed by '--check-inhibitors=no' because the owner accepted data loss.
   No '--force', shell execution or process kill is used.
7. If work resumes, a deadline is missed, or signed telemetry is unavailable,
   the action is blocked instead of retried. A delivered command is not proof
   of completed shutdown; verify the device state separately.
8. Turning Ubuntu back on uses a Wake-on-LAN magic packet from Raspberry Pi.
   The iPhone must confirm an actual fresh Ubuntu heartbeat after waking.

## Separation from app/file management

A future dedicated Applications, Files and Terminals section can list work,
save documents where supported, close apps, and manage terminal sessions.
Those features are optional and not a prerequisite to power when the
user knowingly accepts data loss.

This design does not change Atlas queues, agent controls, saved files or
CPUWM policy. Model work is still a hard stop condition and cannot be bypassed
merely by accepting loss of unsaved files.

## Test policy

Never run a live poweroff/reboot as part of automated tests or deployment.
All shutdown dispatch tests use mocks and disposable SQLite databases.
Wake-on-LAN packet configuration may be verified without sending a packet.
Live iPhone/firmware power-cycle testing requires a separate deliberate user
action and the user should expect the remote desktop connection to drop.

## Privilege isolation and installation

The signed Ubuntu Agent must keep NoNewPrivileges=true. It does NOT call
sudo or pkexec. When it receives an already authorized signed Pi command,
it can ask systemd to START only a fixed system service:

- ubuntu-control-power-shutdown.service
- ubuntu-control-power-restart.service

A minimal Polkit rule authorizes START of these two exact services (plus a
read-only self-check service) only for the local workstation account. No
general systemd management permission is granted. All three units and their
executables are root-owned. The root helper re-checks Atlas, the three
explicit Codex owner stops, unsettled API sessions, CPUWM and known processes
immediately before issuing normal systemd poweroff/reboot. NoNewPrivileges
also remains enabled in each root unit.

Install reviewed source files as root under
/usr/local/libexec/ubuntu-control-power/power_gate.py and power_execute.py,
the three source-provided service templates under /etc/systemd/system/, and
the owner-specific Polkit template under /etc/polkit-1/rules.d/. Set the
template's __OWNER_USER__ placeholder to the actual local owner only in the
root-owned installation copy; never commit personal credentials or live config.

Start ONLY ubuntu-control-power-check.service during deployment. It reads
current safety and prints a sanitized status without performing any power
action. NEVER start either shutdown/restart unit in automated testing.

Keep the Raspberry Pi Hub localhost-only behind private Tailscale Serve.
The owner-only real-power POSTs still require verified Tailnet identity,
same-origin checks, CSRF and two explicit UI confirmations. No wake packet is
sent by deployment or QA.

The later Applications, Files and Terminals feature will be a separate
navigation area. It must never silently force a save before poweroff.
