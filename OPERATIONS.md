# Local Test Mode operations

From `D:\RecoverAI`, after installing the locked requirements, configuring the
operator and applying the reviewed database migration:

```bat
.venv\Scripts\python.exe -m scripts.run_local --check
.venv\Scripts\python.exe -m scripts.run_local
```

Keep that terminal running. The supervisor starts the private API on 8001,
webhook-only gateway on 8002, dashboard on 8501, and replay/review/outcome workers.
All listeners bind to 127.0.0.1. The child dashboard uses the private API on 8001.
It rejects non-Test Mode key IDs and never starts ngrok or changes provider settings.
The existing webhook tunnel must continue to point only to port 8002.

From another terminal:

```bat
cd /d D:\RecoverAI
.venv\Scripts\python.exe -m scripts.run_local --status
.venv\Scripts\python.exe -m scripts.run_local --stop
```

Status exits 0 only when every configured service is running. `--stop` requests
shutdown; check status again to verify completion. Ctrl+C also stops owned child
processes. Shutdown does not delete payment records, reset claims, cancel links,
refund funds or issue a replacement recovery action.

## Ownership and failure behavior

A kernel-held file lock admits one supervisor per checkout. A crash releases that
lock; the presence of `supervisor.lock` by itself is not a stale lock to delete.
Existing manual app/worker processes from this checkout and occupied ports are
refused without terminating them. Stop their original terminals before switching.
Do not run independent clones/workers against this same SQLite database.

The supervisor polls process exits. The API additionally needs a successful
internal `/ready`, the dashboard needs its health endpoint, and the gateway
needs a listening TCP socket. The gateway check is not a signed delivery test.
Workers currently have **process liveness only**: a live but stuck worker is not
a completed-job heartbeat. The JSON status distinguishes these monitor types.
A stale supervisor status (>30 seconds) is reported as unresponsive; a mismatched
PID creation time is treated as stopped. No credentials appear in status output.

An exited process, or repeated failed HTTP checks after a 60-second startup grace,
gets up to three restarts within ten minutes, with 2/4/8-second backoff. Exceeding
that budget stops the group for investigation. Provider retries still obey the
existing durable event/intent/case claims. The supervisor never expires an
in-progress financial claim to make an operation run again.

Shutdown targets only process identities it launched and recorded descendants,
using PID plus creation time. This handles the Windows venv launcher/interpreter
pair. Forced termination of the supervisor itself, a machine crash, and a process
that forks and exits before observation can still leave children. Inspect owned
processes before restarting; the existing-process and port checks block ordinary
duplicates. This is not an OS startup service or a guarantee of crash recovery.

## Local files and maintenance

Status/stop requests live under ignored `var/runtime`; each start gets its own
ignored `var/logs/<run>/` directory. Temporary files stay under `var/tmp` on the
project drive. API/gateway access logging is disabled to avoid logging request
URLs. Application/framework logs are still private operational data: restrict
folder access and redact before sharing. Log rotation/retention and centralized
alerts remain deployment work; inspect disk usage and archive old run logs.

Before migrations, stop the supervisor, confirm `--status` says stopped and verify
no manual app/worker processes remain. Follow [migration steps](migrations/README.md)
and retain the verified backup. Then restart. Never migrate while workers run.

## Verified on the D drive installation (9 November 2026)

The exact legacy baseline matched and passed integrity/reference checks. With
services stopped, explicit adoption created a verified backup and retained all
three payment cases, including the two historically recovered Test Mode cases.
Internal readiness then passed. The six-service supervisor started successfully:
API `/ready` and dashboard health returned 200, anonymous operator checkout 401,
and gateway `/ready` and `/docs` 404. No new payment was made by these checks.

The full local regression suite passed (495 tests). Focused supervisor tests also
cover lock release after actual interpreter termination, stopping an owned nested
process while leaving an unrelated process alive, restart-budget exhaustion,
HTTP startup grace, busy ports, stale/PID-reused status, stop-request ownership,
Test Mode refusal and schema-readiness refusal.

## Original order success and duplicate collection

Each known original provider order has one permanent recovery owner. Multiple
already-acted legacy cases block new collection for investigation. A fresh order
and payment-history read runs before scoring/execution and again before creating
follow-up resources. Paid original orders settle as `paid_original`, expire pending
reviews and do not create successful recovery outcomes or recovered-revenue credit.
Pending/authorized, partial, refunded, inconsistent or unavailable evidence blocks
new full-amount collection for reconciliation. Signed original-capture events use
fresh provider evidence, not webhook amounts. Busy processing claims stay owned;
a paid stop flag can be recorded without resetting that claim.

If both the original order and a recovery resource are verified paid, the case is
held for investigation and excluded from recovered-case totals. No automatic refund
is issued. Operators can review/cancel an unpaid old recovery link for a directly
paid closed case. Already shared links and separate provider orders cannot be made
atomically exclusive with a local database lock. A customer can pay between the
last provider read and a new creation, or through a previously shared link: monitor
late captures and investigate duplicates. Distinct original orders for one merchant
invoice still require explicit invoice mapping before live use.

All Razorpay requests now reject non-Test Mode authentication at the SDK transport
boundary. Order/link creation also refuses non-test configuration before invoking
the SDK. This applies when manually launching the API as well as using the local
supervisor. Switching to Live Mode requires a deliberately reviewed implementation
and merchant pilot approval; editing an environment key is insufficient.

Dashboard headline amounts group known original-order attempts once. Direct original
success and groups with conflicting amounts/owners, multiple recoveries or held
duplicate payments are excluded from recovered totals. The Action Distribution
view still counts individual payment cases and executions, with its unit stated.
Payments without original-order references remain standalone: invoice-level
uniqueness cannot be inferred from contacts or amounts.
