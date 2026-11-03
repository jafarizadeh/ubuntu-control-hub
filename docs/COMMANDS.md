# Private outbound command channel

The backend and Control Center support audio and confirmed CPUWM commands only. Ubuntu
opens outbound HTTPS connections to the Pi's private `*.ts.net` endpoint; there
is no incoming Ubuntu listener, SSH command channel, sudo, or arbitrary shell.

## Authorization boundary

The hub must remain bound to `127.0.0.1:8765` behind private Tailscale Serve, never
Funnel or a publicly reachable proxy. Serve supplies `Tailscale-User-Login` from
its authenticated user identity and strips spoofed incoming identity headers.
This is a required deployment trust boundary: do not place an intermediary that
passes client-supplied identity headers, and verify Serve's header replacement
before enabling control. Local processes on the Pi are trusted; a process that
can connect to the loopback backend can impersonate the proxy. Host headers alone
do not authenticate a proxy. Tailnet ACLs should limit access as well.

Create private `config/operator.json` from `config/operator.example.json`:

```json
{"allowed_login":"placeholder@example.com"}
```

Replace the placeholder privately with the exact Serve login. Keep the file
owned by the Hub user with exact mode 0600. Missing, malformed or empty configuration denies control.
Missing, duplicate or mismatched login headers and localhost Host values also
deny control. Matching is exact and case sensitive. Identities are never returned
by these endpoints or included in errors.

`GET /api/control/capabilities` returns only `{"can_control":true}` or false.
`POST /api/commands` also requires the existing same-Origin check, session cookie
and `X-UC-CSRF` token, with JSON content. An accepted command returns HTTP 202
with an opaque `id` and `status: "queued"`; this does not mean execution succeeded.
`GET /api/commands/<id>` requires operator authorization and returns only
`{"status":"queued"}` (or another status), without action details or identity.

## Fixed request allowlist

Only these JSON shapes are accepted; additional fields are rejected:

```json
{"action":"audio.set_volume","value":40}
{"action":"audio.set_mute","value":true}
{"action":"cpuwm.set_profile","value":"balanced","confirm":true}
```

Volume must be an integer from 0 through 100 (booleans are rejected). Mute must be
a boolean. Profiles are exactly `quiet`, `balanced`, `performance`, and require
literal `confirm: true` because changes may affect running workloads.

The agent calls `/usr/bin/wpctl set-volume @DEFAULT_AUDIO_SINK@ 40%` or
`/usr/bin/wpctl set-mute @DEFAULT_AUDIO_SINK@ 1` (0 for unmute). CPUWM uses the
current Python interpreter with the fixed script
`~/cpu-workload-manager/cpuwm.py profile balanced`, substituting only an allowed
profile. The script must be an existing regular, non-symlink file; otherwise the
command fails safely. This assumes the installed manager supports that CLI;
verify compatibility separately before enabling profile control. No manager
files or services are modified by this implementation. Execution uses argv lists,
`shell=False`, a 15 second timeout, and captured output that is never returned.
Nonzero exits, missing binaries and timeouts produce `failed`, without retries.

Power, shutdown, reboot, timers, terminal, network changes and arbitrary commands
remain locked out of this channel. Existing unrelated Pi routes are unchanged.

## Delivery, acknowledgement and failure

The durable Pi queue allows 16 outstanding commands, each with a 45 second TTL.
States are `queued`, `delivered`, `succeeded`, `failed`, `expired`. The Pi returns
at most one command per valid signed report and durably marks it delivered before
responding. It never redelivers a command, including after restart or response
loss. The next signed report may contain `ack: {"id":"<opaque-id>",
"status":"succeeded"}` or `failed`; the signature covers the ack and telemetry.
Only delivered, unexpired commands can be completed. Late or unknown acks have
no effect. Unacknowledged commands expire; expiry cannot undo an execution.

Ed25519 body signatures and the existing 75 second clock window remain mandatory.
Nonce replay state persists across Pi restarts. State is stored privately under
`data/command-state.sqlite`; keep the database and rollback journal together.
Do not delete transport state during ordinary restarts.

Before executing, the agent independently validates all fields, the allowlist,
and the 45 second lifetime against its clock. Both clocks must be accurate.
It atomically saves a failure reservation before any subprocess, then records
success only after a zero exit. IDs and pending acknowledgements persist in
`command-state.json` beside the agent client configuration, with mode 0600.
A private advisory lock serializes state changes and execution. Corrupt or unsafe
state refuses execution; never remove it merely to retry an uncertain command.
A crash after reservation may lose an execution, but cannot retry that ID.
Lost responses, execution failures and restarts never trigger automatic retries.
Dedupe entries are retained indefinitely. Back up private state securely; replacing
it defeats deduplication. Acknowledgements are sent on the next report, so `--once`
may leave a completed execution pending until a later run.

Offline tests mock HTTP and all command subprocesses. No test changes audio, applies a CPUWM profile, or alters system power. Deployment validation on 2026-11-03 confirmed the real Tailnet owner identity is recognized through private Tailscale Serve, while direct localhost requests are denied. The live API rejects unsupported shutdown, unconfirmed CPUWM, and invalid volume requests with HTTP 400. The actual CPUWM and audio setters remain unexercised until the user explicitly invokes them on the phone.
