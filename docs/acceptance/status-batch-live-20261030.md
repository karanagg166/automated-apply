# Installed profile-status batching: completed bounded acceptance

Branch `fix/live-prepare-discovery-20261030`, base `main`; [PR 48](https://github.com/karanagg166/automated-apply/pull/48).
Exact approved installed implementation:
[`79ce5f6b514279e6d9022d85b659ad77fb31bd89`](https://github.com/karanagg166/automated-apply/commit/79ce5f6b514279e6d9022d85b659ad77fb31bd89).
Installation and intermediate evidence were published in
[6121546](https://github.com/karanagg166/automated-apply/commit/6121546fd1badd8f4d9eb24fa1b1be96620e8cc2)
and [06e3067](https://github.com/karanagg166/automated-apply/commit/06e3067b248b08beae18f74e1b8e2b3e6fe1e754).
[Sanitized final measurements](status-batch-live-metrics-20261030.json).

**Overall acceptance: FAIL.** Three full read-only cycles and recovery/control
checks completed, but three profile-status timeouts remain. Two revision-conflict
attempts interrupt the requested consecutive-success sequence. The broader
unrelated-tab preservation check also failed without causal attribution.
Complete 24/7 automation is not accepted by this report.

## Approved installation and continuation scope

The owner answer recorded at **2026-10-30 11:25:51 UTC** was
“Approve this SHA and read-only acceptance.” It excludes filling, employer
submissions, email sending, merging and cleanup. The locked-screen test remains
explicitly owner-deferred; no repeat lock request was made.

The implementation combines five profile-status reads into one SQL snapshot
and gives the monitor a two-second idle connection expiry. It preserves status
redaction, expiry/cancellation rechecks, command deadlines and connection limits.
This continuation changed acceptance documentation and private helper ordering;
no installed source or production configuration was replaced.

Installation receipts retain a revalidated **12-file rollback backup**, successful
constrained dependency installation, `pip check`, frozen pnpm installation,
frontend/extension builds and full restricted-role/TLS/catalog preflight. Cutover
ran **11:26:50–11:27:38 UTC**. Six cold-start ConnectError polls preceded the
first successful readiness request, which took **3.474s**; this is a request
duration, not total startup time. All nine subsequent installation HTTP checks
returned 200, and framed native health passed. The existing extension's **17
files** match the approved build while its older immutable install path remains.
No schema migration, profile switch or permission change occurred.

The continuation revalidated clean installed tracked source, all four service
definitions at this SHA, four fresh HTTP preflight checks, selected Profile 8
`CONNECTED`, no active commands, screen `UNLOCKED` and a paused task without
field authorization. Sending, submission and automatic execution gates were off.

## Final status matrix

| Requirement | Status | Actual evidence / limit |
| --- | --- | --- |
| Exact approved source, rollback, builds and DB preflight | PASS | Current identity revalidated; inherited installation receipts retained |
| Three completed real Open → Prepare cycles | PASS for completed count | Three distinct zero-field read-only plans across five retained attempts |
| Three uninterrupted consecutive attempts | FAIL | Attempts 1 and 4 rejected stale task versions; not relabeled as successes |
| Profile-status deadline under native work | FAIL | Three retained 12s ReadTimeout observations; server completions exceeded deadline |
| Readiness during native work | PASS for bounded window, excluding deliberate outage | 207 HTTP 200, three planned-restart ConnectError, zero 503 |
| Health polling transport | PASS outside deliberate restart | 207 HTTP 200, same three restart gaps, zero ReadError |
| Graceful API/worker restart | PASS for exercised case | Same exact SHA; first successful readiness request 3.447s |
| Quiescent execution-worker SIGKILL recovery | PASS for exercised case | LaunchAgent replacement observed at 26.198s; fresh heartbeat at 44.091s; no resume/replay |
| Concurrent task Pause / global Stop | PASS | Queued Prepare cancelled with global_stop; restoring RUNNING did not resume task or replay command |
| Packet identity and terminal-command preservation | PASS | Same packet/revision across complete cycles; zero new packets for exercised job/candidate; historical terminal commands unchanged |
| All baseline unrelated tabs preserved | FAIL; cause NOT DETERMINED | Four of five unchanged; one outside acceptance window disappeared; seven new unrelated tabs observed |
| Final task, profile and connection snapshot | PASS for observed state | Task PAUSED, no authorization/active command, selected binding unchanged, four runtime sessions plus one audit within role limit five |
| Final HTTP/native transport checks | PASS | Nine HTTP 200 checks and framed native health; not DOM/fill proof |
| Locked-screen DOM acceptance | NOT TESTED | Explicit owner deferral |
| Real filling, submission and genuine employer receipt | BLOCKED / NOT TESTED | Outside recorded read-only authorization |
| Long-term uptime and continuous discovery | NOT TESTED | Bounded checks do not establish 24/7 reliability |

## Real native attempts and controls

| Attempt | Result | Helper duration | Evidence |
| --- | --- | --- | --- |
| 1 | FAIL | 16.398s | Resume rejected before native admission |
| 2 | PASS | 182.636s | Open + Prepare complete; new read-only plan |
| 3 | PASS | 151.538s | Open + Prepare complete after restart/crash |
| 4 | FAIL | 106.492s | Open complete; Prepare admission rejected |
| 5 | PASS | 178.677s | Open + Prepare complete; new read-only plan |

The three completed cycles saved distinct `read_only` / `NEEDS_INPUT` plans with
**zero fields, actions and approved fields**. Seven Open/Prepare commands
completed in total: two in each full cycle and the Open in attempt 4. An eighth
command, the control-race Prepare, was cancelled. Request IDs and terminal states
were reconciled in private receipts; no ambiguous native command was replayed.
Helper durations include alarm/polling, reconciliation and final Pause.

Attempt 1 returned **409 / extension_task_revision_conflict** at Resume after a
focus observation advanced the paused task version and changed tab_active.
No native command was admitted. Attempt 4 completed Open, then another focus
observation advanced the task while the helper read profile status; Prepare
admission returned the same 409 and created no Prepare command. Both failures
remain visible. The helper subsequently read profile status **before** the task,
obtaining the revision closer to admission. It used a new request ID for the new
attempt; server fences and installed code did not change. This is a helper
ordering correction, not proof that product-level revision conflicts are solved.

The restart ran **11:46:24–11:46:47 UTC** with no in-flight command and a paused
task. The quiescent worker was killed at **11:46:52 UTC**; its replacement and
fresh DB heartbeat were observed before the second completed cycle. During
**11:57:55–11:58:31 UTC**, Pause/Start preserved the paused task, then concurrent
Pause/Stop cancelled a newly queued Prepare. Original RUNNING state was restored
without resuming the task, old paused executions or terminal commands.

## Completed HTTP windows and remaining latency

Three **non-overlapping** windows collected **120 + 60 + 30 = 210 samples per
endpoint**, or **630 monitor requests**, from **11:41:07–11:59:41 UTC** with
short gaps between windows. Every first-attempt failure is retained; no monitor
retry or deadline increase was used. The observer used HTTP only while one
acceptance helper occupied the remaining DB slot.

| Endpoint | Final results | Mean / p95 / maximum seconds |
| --- | --- | --- |
| Health | 207 HTTP 200; 3 ConnectError during deliberate API restart | 0.0298 / 0.0583 / 0.4819 |
| Readiness | 207 HTTP 200; same 3 restart ConnectError; zero 503 | 1.1630 / 1.5145 / 4.2275 |
| Profile status | 204 HTTP 200; same 3 restart ConnectError; **3 ReadTimeout** | 2.4880 / 6.5874 / 12.0157 |

All three endpoint connection gaps began at **11:46:28, 11:46:33 and 11:46:38
UTC**, inside the recorded deliberate API restart. The status timeout samples
began **11:45:29, 11:49:52 and 11:57:00 UTC**, outside that outage.

Server logs recorded the corresponding native inspection requests at **17.5237s,
19.6243s and 16.8151s**. Overlapping status requests eventually returned 200 after
**17.5423s, 19.1990s and 15.8539s**, beyond the observer deadline. Another native
HTTP request took 12.2539s during final verification; its internal operation was
not correlated and is retained as unattributed in the sanitized trace.

The fast status SQL still shares one business connection with long native
transactions. Queueing behind those transactions is consistent with these
overlapping timings and the configured pool. **Per-query and pool-wait tracing
has not yet isolated the full internal cost.** No cancellation/freshness check,
connection limit or command deadline was weakened to manufacture a PASS.

The [previous release](readiness-isolation-live-20261030.md) had 180 observations,
three status timeouts and two health ReadErrors. Its combined mean status duration
was **2.9362s**, versus **2.4880s** here; mean readiness was **1.1271s**, versus
**1.1630s** here. These are sequential, non-identical workloads, not a controlled
benchmark. The earlier direct remote routine improvement from 0.8554s to 0.1819s
remains valid for that measured read cost, but does not establish HTTP acceptance.

## Resource and tab audits

The following values use the same process grouping as the previous 180-sample
window. Current data has 210 samples and additional rejected attempts. Means use
samples where each service was present; execution was absent during planned
recovery in 10 current samples, versus five previous samples. Startup/restart
spikes and OS memory pressure are included. Lower RSS is not proof of a memory
optimization.

| Service | Mean CPU %, previous / current | Peak CPU %, previous / current | Peak RSS MiB, previous / current |
| --- | --- | --- | --- |
| api | 1.967 / 3.173 | 88.0 / 84.0 | 137.938 / 133.922 |
| execution | 0.993 / 1.201 | 83.0 / 93.2 | 96.359 / 94.875 |
| telegram | 0.274 / 0.293 | 5.1 / 4.0 | 62.188 / 49.781 |
| frontend | 0.015 / 0.021 | 1.5 / 1.0 | 13.656 / 9.109 |

The final read-only DB audit found one API, execution, Telegram and readiness
session, plus the temporary audit session: **five with a role limit of five**.
This is a snapshot, not continuous session telemetry. Profile and worker
heartbeats were 2.450s and 3.283s old; no active browser command remained. Packet
creation timestamps found **zero** new packets for the exercised job/candidate
over all five attempts, and the three completed cycles retained the same packet
revision. This does not assert a global historical duplicate count.

The tab comparison normalized AppleScript string IDs and native integer IDs,
then excluded the acceptance target. **Four of five** original unrelated tabs
retained their window/tab IDs and URL hashes. One tab outside the acceptance
window disappeared, no retained baseline tab changed URL, and seven new unrelated
tabs appeared. No event provenance was captured for those external-window
changes, so neither user activity nor application causation is asserted. The
initial failed audit and raw private snapshots are retained; the published
reconciled counts preserve the failure. No URL, title, DOM content or tab ID is
published. A controlled preservation rerun remains necessary.

## Validation, reproduction and next actions

Existing implementation validation remains **346 focused backend tests passed
in 36.01s**, **7 disposable PostgreSQL tests passed in 2.56s**, and Ruff E9/F/I.
Those are prior fixture/process regressions for this exact source, not new live
or unit test executions. This continuation ran **zero new automated unit tests**
for documentation/private helper ordering. New evidence comprises the actual Mac
attempts, 630 HTTP monitor requests, four continuation preflight HTTP checks,
nine final HTTP checks, native framing, controls and read-only audits. Public
JSON parsing, privacy-field scan and Git diff checks passed.

```sh
release="$HOME/Library/Application Support/Automated Apply/releases/79ce5f6b514279e6d9022d85b659ad77fb31bd89"
git -C "$release" rev-parse HEAD
git -C "$release" status --porcelain --untracked-files=no
# Use a fresh filename; never overlap DB observers or acceptance helpers.
"$release/.venv/bin/python" "$release/backend/scripts/measure_reliability.py" \
  --env-file "$HOME/Library/Application Support/Automated Apply/phase54.private.env" \
  --output /tmp/automated-apply-status-batch-new.jsonl \
  --samples 120 --interval-seconds 5
# The other bounded windows use 60 and 30 samples with new output filenames.
git diff --check
```

For native reproduction, start from the existing selected Profile 8 and paused,
unauthorized acceptance task. Use explicit Open and Prepare gestures, reconcile
the original command IDs and saved plan/tab/window/session binding, then Pause.
Read profile status before reading the task revision for command admission;
a 409 requires fresh state and a separately recorded attempt. Do not grant field
authorization. Quiescent recovery checks require verifying no active commands
and the exact service executable/PID before restarting the registered API/worker
or killing the worker; retain the deliberate outage and recovery timestamps.

Next work is to instrument and shorten the native inspection transaction while
preserving owner/packet locks, cancellation, original-command expiry and unknown
outcomes; verify HTTP deadlines under the same workload. Repeat the consecutive
cycle and tab-preservation criteria under controlled conditions. Keep the locked
cycle pending as requested. No continuous discovery workload was added on the
strength of this failed latency acceptance. Any new installed implementation
still requires owner review and approval of its exact SHA under AGENTS.md.

Private receipts remain under `status-batch-upgrade-20261030T112551Z`; all new raw
evidence is owner-readable only. Raw logs, credentials, candidate data, resumes,
Gmail contents and screenshots are excluded from Git. All current/historical
releases, private configuration, backups and runtime files remain preserved.
No hosted workflow was dispatched or rerun, no merge occurred and no cleanup
was performed. A completed bounded test run is not production automation PASS.
