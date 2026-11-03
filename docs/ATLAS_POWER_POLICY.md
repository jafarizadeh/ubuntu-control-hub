# Atlas-aware power policy: explicit user stop is not idle

Status: read-only guard and Power Safety UI. NO real shutdown, restart, owner-stop or Codex stop is enabled by this integration.

## Critical distinction

An inactive agent, empty queue, finished task or exhausted provider quota does NOT prove that the human owner stopped Codex. While Atlas has mode RUN, the scheduler may claim a new task at any moment, including after quota resets. Power must remain blocked.

Atlas already exposes a global owner-stop --confirm command that changes the authoritative scheduler mode to STOP and records an owner_mode event. Ubuntu Control DOES NOT invoke this command. The planned per-Codex owner-stop feature is NOT equivalent to the global Atlas stop; it must supply independent stop acknowledgements.

| Verified Atlas evidence | UI classification | Power gate |
| --- | --- | --- |
| RUN with in-flight work | Running | Blocked |
| RUN, no active work, even with empty/limited queues | Armed idle; can dispatch | Blocked |
| STOP with no verified owner event | Unverified stop | Blocked |
| STOP with owner event, running attempts remaining | Owner stop draining | Blocked |
| STOP with owner event, no outstanding database attempts | Owner stop; no active attempts | Still blocked until all-Codex stop and checkpoint verified |

Only a future explicit all-Codex stop acknowledgement may release the ATLAS-SPECIFIC gate. It must verify all physical execution lanes cannot start more work, in-flight tasks have drained or safely checkpointed, and the acknowledgement is fresh, bound to the latest owner stop event. Resuming any worker automatically invalidates it; existing queues are preserved for later resumption.

Even after Atlas is cleared, GNOME/systemd inhibitors, CPUWM/other jobs, unsaved desktop work, explicit user confirmation and cancellation are independent checks. A requested power action is rejected if any prerequisite becomes invalid before execution.

## Current read-only implementation

The file agent/atlas_guard.py reads only the existing database at /var/lib/twt-roadmap-atlas/roadmap.sqlite. It checks:
- meta.mode for RUN vs STOP
- latest owner_mode event, requiring exact explicit owner-stop provenance
- ordinary and legacy unsettled attempt counts
- RUNNING and READY package counts (READY is backlog, not permission to dispatch)

It returns sanitized status enums and counts, with no IDs, owner identity, paths, process arguments or raw event reasons. It performs no Atlas CLI call, stop/resume, SQLite write or model action.

agent/power_safety.py combines the result with read-only systemd, CPUWM and desktop observations. The existing signed outbound agent transmits it to the private Pi. The Raspberry Pi validates and redacts the result before returning it in the owner-only Power Safety endpoint.

codex_user_stop_verified is strictly false until the new per-Codex control protocol is implemented, and atlas_power_gate_clear and safe_to_request also remain false. User interface fields cannot override these.

## Future Codex stop contract (not implemented)

An explicit authenticated owner request must carry an unambiguous event generation. Atlas should atomically disable new dispatch across all lanes, and each physical Codex, Validator and Auditor worker must report STOPPED/DRAINED and zero active jobs. After checkpoints and session acknowledgements, an attestation can be issued for that generation. Immediately before real shutdown, Ubuntu Control must recheck it. Evidence becomes invalid after any resume, new claim, unknown lane, unexpected restart or staleness.

Idle, quota-limited, finished and empty-queue states are NOT substitutes for this owner stop. Power Timer remains preview only.
