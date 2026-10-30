# Installed profile-status batching: live acceptance

Branch `fix/live-prepare-discovery-20261030`, base `main`; [PR 48](https://github.com/karanagg166/automated-apply/pull/48).
Exact owner-approved installed implementation:
[`79ce5f6b514279e6d9022d85b659ad77fb31bd89`](https://github.com/karanagg166/automated-apply/commit/79ce5f6b514279e6d9022d85b659ad77fb31bd89).
The recorded owner answer at **2026-10-30 11:25:51 UTC** was
“Approve this SHA and read-only acceptance.” The locked-screen test remains
explicitly owner-deferred. This approval excludes field filling, employer
submissions, email sends, merging and cleanup.

## Installation and recovered handoff

The previous task installed the approved release on October 30 and stopped
before starting its native workload acceptance. This continuation verified the
private approval receipt, clean installed tracked source, all four service
definitions pointing at this SHA, current gates and the paused acceptance task.
No second installation or source replacement was performed by this continuation.

The installation preserved and revalidated a **12-file rollback backup**. Its
private receipts record successful constrained dependency installation, `pip
check`, frozen pnpm installation, frontend and extension builds, and full
restricted-role/TLS/catalog preflight. Cutover ran **11:26:50–11:27:38 UTC**.
The first successful readiness request took **3.474s**, including its database
probe; this is a request duration, not total service-start time. Native wrapper
health passed with a matching framed request ID. The existing Profile 8
extension remains at its older immutable release path; its **17 files** match
the approved build, with no profile, identity or permission change.

All **nine initial HTTP checks returned 200**. The three readiness requests took
1.231s, 1.056s and 1.052s; profile status took 1.484s. A fresh continuation
preflight found the selected profile `CONNECTED`, command transport enabled,
screen `UNLOCKED`, no active commands and the task `PAUSED` without field
authorization. Sending, submission and automatic execution gates remain off.

## Acceptance status

| Check | Status | Evidence / limitation |
| --- | --- | --- |
| Exact approved release and preserved rollback | PASS | Current SHA and service definitions revalidated; installed tracked source clean |
| Dependency/build and full DB preflight | PASS | Completed installation receipts; no new schema migration |
| Initial HTTP and framed native health | PASS | Nine HTTP 200 checks and actual installed native wrapper |
| Existing selected profile and paused task | PASS | Fresh continuation preflight; no fill authorization or active command |
| Three new real Open → Prepare cycles | NOT TESTED to completion | Two cycles passed; third running; first rejected attempt retained below |
| Installed HTTP latency under native work | FAIL | Two 12s status timeouts in the first completed 120-sample window; no monitor retries |
| Graceful API/worker restart on this SHA | PASS | Same approved source; no active commands; first successful readiness request 3.447s |
| Quiescent worker SIGKILL recovery on this SHA | PASS | LaunchAgent new worker observed at 26.198s; fresh heartbeat at 44.091s; no task resume/replay |
| Concurrent Stop on this SHA | NOT TESTED to completion | New control check pending |
| Locked-screen DOM cycle | NOT TESTED | Explicit owner deferral; no repeated lock request |
| Real fill, submission and genuine employer receipt | BLOCKED / NOT TESTED | Outside the recorded read-only approval |
| Complete 24/7 operation and continuous discovery | NOT TESTED | A bounded acceptance window does not establish long-term operation |

The implementation's existing validation is **346 focused backend tests passed
in 36.01s** and **7 disposable PostgreSQL tests passed in 2.56s**, plus Ruff
E9/F/I and diff checks. These are carried-forward fixture/process regressions,
not new live tests or additional executions in this continuation. No source
change requires repeating them at this checkpoint.

## Comparison and retained failures

The [previous installed workload](readiness-isolation-live-20261030.md) recorded
180 readiness observations: 177 HTTP 200, three connection failures during a
planned API restart and zero HTTP 503. It also retained **three profile-status
12s timeouts and two health ReadErrors**. Those failures remain historical
evidence. The [candidate investigation](profile-status-latency-20261030.md)
measured remote routine cost falling from five reads averaging 0.8554s to one
read averaging 0.1819s. That direct read-only benchmark does not substitute for
the newly installed HTTP workload or resource measurements.

The new monitor uses the approved two-second idle connection expiry, retains
every first-attempt error and observes process CPU/RSS without a database
connection. Only one native acceptance helper may occupy the fifth runtime
role slot; no independent DB observer runs concurrently. Final HTTP/resource
comparisons will be published when the window finishes.

## Reproduction, evidence and next actions

```sh
release="$HOME/Library/Application Support/Automated Apply/releases/79ce5f6b514279e6d9022d85b659ad77fb31bd89"
git -C "$release" rev-parse HEAD
git -C "$release" status --porcelain --untracked-files=no
# Use a fresh filename and do not start a second concurrent observer.
"$release/.venv/bin/python" "$release/backend/scripts/measure_reliability.py" \
  --env-file "$HOME/Library/Application Support/Automated Apply/phase54.private.env" \
  --output /tmp/automated-apply-status-batch-new.jsonl \
  --samples 120 --interval-seconds 5
```

Private installation, preflight, monitor and command-reconciliation receipts
remain under `status-batch-upgrade-20261030T112551Z`. Raw response bodies, account
details, tab URLs, candidate data, credentials and screenshots are not published.
Complete and reconcile the third read-only native cycle and concurrent control
check; then finalize timing/resource counts and every remaining failure.
Preserve the deferred lock check and all rollback releases. No hosted
workflow was dispatched or rerun, no merge occurred, and no cleanup was performed.

## Two-cycle and recovery checkpoint

Two genuine Open → Prepare cycles passed on this installed SHA. Each saved a
distinct zero-field, zero-action, zero-approved-field read-only `NEEDS_INPUT`
plan, then paused. Their helper durations were **182.636s** and **151.538s**,
including polling and reconciliation. The second followed both a graceful
backend/worker restart and an injected quiescent-worker SIGKILL. The task stayed
paused across recovery; no terminal command was replayed.

One earlier attempt failed before admitting any native command: Resume returned
**409 / `extension_task_revision_conflict`** after a concurrent focus observation
advanced the paused task's version and changed `tab_active` from true to false.
The task remained paused without authorization. A fresh attempt used the new
version; no stale request was blindly replayed. The failed attempt remains in
the [sanitized measurements](status-batch-live-metrics-20261030.json).

The first monitor completed **120 samples per endpoint**, retaining all first
attempts:

| Endpoint | Results | Mean / maximum seconds |
| --- | --- | --- |
| Health | 117 HTTP 200; 3 ConnectError during deliberate API restart | 0.0294 / 0.3183 |
| Readiness | 117 HTTP 200; same 3 restart ConnectError; zero 503 | 1.1711 / 4.2275 |
| Profile status | 115 HTTP 200; same 3 restart ConnectError; **2 ReadTimeout** | 2.3455 / 12.0157 |

The timeout samples began **11:45:29 UTC** and **11:49:52 UTC**. For the first,
server logs show `inspect_form` took **17.5237s** and the overlapping status route
eventually returned HTTP 200 after **17.5423s**, beyond the observer's 12s
deadline. Thus a fast one-statement status routine still queues behind long
native transactions in the single business connection. This is direct timing
evidence of overlap and a queueing explanation consistent with the configured
pool; per-query/pool-wait tracing has not yet been collected, so it does not
assign all 17.5 seconds to one internal operation.

The second, non-overlapping monitor continues through the third cycle and Stop
check. Its eventual counts and resource comparison will be appended. The
batching improvement is **not** an unconditional HTTP latency PASS; no timeout,
pool limit or cancellation fence was relaxed to make the acceptance succeed.
