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
| Three new real Open → Prepare cycles | NOT TESTED to completion | First cycle and HTTP-only monitor started on this installed SHA |
| Installed HTTP latency under native work | NOT TESTED to completion | New bounded 120-sample window; 12s deadline and no hidden monitor retries |
| Restart, worker crash and concurrent Stop on this SHA | NOT TESTED to completion | Prior release results retained separately; new checks pending |
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
Complete and reconcile the three read-only native cycles and recovery/control
checks; then publish sanitized timing/resource counts and every remaining
failure. Preserve the deferred lock check and all rollback releases. No hosted
workflow was dispatched or rerun, no merge occurred, and no cleanup was performed.
