# Independent audit and unified Power UI

Baseline: commit aa894fc (v1.0). The audit used an isolated archive of public
source, not the live deployment, secrets, Atlas data, or private configuration.
Codex CLI 0.163.0 ran model gpt-6.1-sol with reasoning effort xhigh, read-only
sandbox, no approvals, no web access, ephemeral session and a bounded CPUWM
managed generic workload. The Atlas execution switches were not changed.
The reviewer inspected source only; it did not implement fixes or execute
application tests. Implementation and tests were reviewed separately here.

## Findings and disposition

| Priority | Confirmed baseline finding | Implemented correction |
| --- | --- | --- |
| P1 | Failed polling erased the known armed state and removed Cancel; a lost arm response could be reported as not armed. | Keep schedule state separate from connection health, explicitly warn may still execute, preserve cancellation recovery, bound fetches and reconcile uncertain writes. |
| P1 | Backend permitted replacing a sent request, allowing misleading cancellation of a later row. | Reject rearm while sent; expose schedule_id and require it when canceling an existing row. Keep delivery distinct from execution. |
| P2 | Real power used 15-second readiness while legacy inspection could display older 35-second eligibility. | One live response contains the sanitized inspection and remaining readiness budget; expire UI authorization with monotonic time. |
| P2 | Removing preview HTML alone would break shared iOS initialization and wheel controls. | Remove preview-specific handlers and references; preserve generic wheel/profile/dialog helpers and test custom duration. |
| P2 | Diagnostic worker proof and save-required copy could contradict actual authorization/unsaved-loss policy. | Preserve root real gate unchanged, label proof supplementary, use optional-saving/mandatory-loss-consent language consistently. |
| P3 | Reloading an armed Restart timer showed locked default Shutdown/Now selections. | Restore action and initial duration from the active server schedule. |

## Verification scope

Python regressions use disposable SQLite databases, fake times and mocked root
execution. Browser regressions in tests/browser_unified_power.cjs serve source
and fake APIs on loopback, including 320/390/1440 layouts, custom duration,
explicit consent and modal cancellation, old/unknown evidence, lost arm/poll
responses, cancellation across schedule generations, timeout and recovery.
No real power, TV, Wake-on-LAN or Atlas execution command is part of this audit.

To run the browser suite with an installed Puppeteer and Chrome:

    PUPPETEER_MODULE=/path/to/puppeteer CHROME_PATH=/path/to/chrome node tests/browser_unified_power.cjs

This is a focused code review and regression exercise, not proof that every
possible shutdown or hardware wake condition is safe. Physical Safari behavior,
actual shutdown completion and firmware wake still require deliberate user
validation. Existing root power safety, signed transport and owner consent are
not weakened by the UI consolidation.
