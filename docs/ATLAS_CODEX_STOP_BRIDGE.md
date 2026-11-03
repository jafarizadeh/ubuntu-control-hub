# Atlas Codex User Stop → Ubuntu Control: producer contract

Status (v0.9): the Ubuntu Control verifier, private signed telemetry transport,
Raspberry Pi receipt validation and iPhone status display are implemented and
tested. The Atlas *producer* and its user-facing Stop All Codex control are not
yet implemented. No existing Atlas source, database, running worker, account or
scheduler was modified during this work.

This is the exact interoperable contract for the forthcoming Atlas feature.
A global owner-stop, low CPU utilization, empty queue or provider quota limit
is not a substitute for the independently acknowledged user stop.

## Atlas-owned SQLite schema (future migration; DO NOT apply manually)

The following tables belong in the existing, private Atlas roadmap.sqlite
database, maintained exclusively by its own authenticated owner controls.
Ubuntu Control must never create, update, delete or repair these tables.

~~~sql
CREATE TABLE codex_owner_stop_control (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  generation TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN
    ('STOP_REQUESTED','DRAINING','STOPPED','RESUMED')),
  event_seq INTEGER NOT NULL,
  dispatch_barrier_active INTEGER NOT NULL CHECK (dispatch_barrier_active IN (0,1)),
  barrier_checked_at REAL NOT NULL,
  roster_sha256 TEXT NOT NULL,
  active_worker_processes INTEGER NOT NULL CHECK (active_worker_processes >= 0),
  all_lanes_drained INTEGER NOT NULL CHECK (all_lanes_drained IN (0,1)),
  boot_id TEXT NOT NULL
);

CREATE TABLE codex_owner_stop_acks (
  role TEXT PRIMARY KEY,
  account TEXT NOT NULL,
  state TEXT NOT NULL,
  generation TEXT NOT NULL,
  acknowledged_at REAL NOT NULL
);
~~~

The role/account roster must match the current Atlas policy. In the current
permanent three-physical-account configuration, these are exactly the primary,
secondary and codex3 scientific roles, each with a distinct physical account.
The verifier hashes the sorted role-to-account JSON object using SHA-256.
A different or newly enabled parallel lane must block until the contract and
roster verifier are intentionally updated to account for it.

- generation: a unique lower-case 32-character random hexadecimal identifier
  for one explicit owner Stop All Codex request; never reuse it.
- event_seq: sequence number of the latest trusted Atlas events row, of kind
  codex_owner_stop_request. Its JSON details must contain action equal to
  stop_all_codex_workers, initiator equal to interactive_owner, confirmed
  equal to true, and the exact generation.
- dispatch_barrier_active: 1 only when ALL claim paths are atomically gated,
  including Architect, API Validator, Auditor, legacy reviews, AutoFeed,
  externally scheduled reviewers and any permanent/temporary roster variants.
- barrier_checked_at: Unix seconds of the most recent independently checked
  barrier and worker state, renewed no less often than every 15 seconds.
- active_worker_processes: count of actual active worker processes, not just
  attempts in the database, and must be zero.
- all_lanes_drained: 1 only after every lane acknowledges STOPPED, no
  uncommitted task, review, ongoing model session, or unfinished publication
  remains. Persist or checkpoint every in-flight task safely.
- boot_id: current value of the local Linux kernel boot ID, to invalidate all
  receipts after a system restart.
- Each acknowledgements row uses the exact expected role and account from
  Atlas policy, state STOPPED, matching generation, and a fresh (<=15 seconds)
  acknowledged_at timestamp. Every ack must be independently checked and
  renewed only while that worker remains truly stopped.
- The status STOPPED is a claim made by the trusted Atlas producer AFTER all
  these checks, not an editable option in Ubuntu Control.

## Required Atlas producer sequence (not yet implemented)

1. The owner explicitly confirms Stop All Codex in Atlas (not the Hub).
2. Inside one Atlas transaction, persist the unique generation and the
   authenticated owner event, then erect the dispatch barrier BEFORE another
   task can be claimed. All independent scheduler paths must honor this.
3. Wait for any executing workers; do not kill or forcibly interrupt them.
   Save results and checkpoint in-progress work; keep queues intact.
4. On independent worker acknowledgement, add its role/account STOPPED row
   for the current generation. Do not infer it from inactivity, rate limits,
   CPU usage, user logout or an empty queue.
5. Once every actual worker has stopped and all jobs drained, persist the
   STOPPED state with the barrier active, 0 processes and all_lanes_drained 1.
   Continuously reconfirm these facts before renewing both the barrier
   heartbeat and each worker acknowledgement.
6. If the owner resumes a Codex, a new claim occurs, a worker becomes unknown,
   a service restarts unexpectedly, a worker receipt expires, or new parallel
   roles appear, invalidate the stop evidence immediately. Resume must be an
   authenticated event (codex_owner_resume) newer than the stop request.
7. The owner may later resume normally. Queues, priorities, history and
   scientific evidence are preserved; Ubuntu Control never modifies them.

The producer must atomically prevent new claims during proof renewal. A stop
receipt is valid only within the transactionally consistent Atlas snapshot.

## Consumer already implemented and testable

The Ubuntu Agent reads only Atlas-owned SQLite and policy.json, checks the
latest owner event, roster SHA, three independent fresh acknowledgements,
active barrier heartbeat, host boot identity and zero unsettled attempts and
running packages. It returns only small sanitized fields, never account names,
generation IDs, event data, paths, PIDs or raw jobs.

The source snapshot is inside a SQLite read-only transaction. The existing
signed Ed25519 HTTPS telemetry carries the result to the private Raspberry Pi.
The Hub validates all cross-field invariants and recomputes lease expiry
independently: its general 35-second agent freshness must never prolong the
15-second Codex stop proof. The UI distinguishes:
- Awaiting Atlas support: the live Atlas has no producer tables yet
- Not requested, Waiting for workers, Expired, Resumed, Invalid and Unavailable
- Verified owner stop, with X/Y independent worker acknowledgements
- Dispatch barrier active or unverified

An Atlas-specific gate can clear only with a fresh verified stop, but total
Power Safety stays blocked until independent CPUWM, GNOME, unsaved-file and
other workstation checks pass and the owner explicitly authorizes real power.
No real shutdown, restart, real timer or direct stop command is enabled.

## Review and handoff when Atlas implements User Stop

Implement the source producer in the Atlas repository with a dedicated
code-reviewed migration and scheduler/worker tests. Do not paste a STOPPED row
into the production database, and do not treat the test fixture as a real
acknowledgement. Verify all dispatch paths in a disposable Atlas test database,
then explicitly authorize an isolated end-to-end test of the Stop All Codex
workflow. Only after that may the private Hub display a genuine verified stop.
