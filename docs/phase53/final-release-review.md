# Phase 5.3 renewed release review

Reviewed PR #45 from base `8c1635139a8943e9c2b72f39c4db593e1ccaa5b5`
through supplied head `2274b34e6139b0b36268e3ebf538c971ee209811`, including
all four combined commits. The replacement approval candidate is the commit
containing this report. The final owner handoff and frozen private installation
plan record its full SHA. No earlier SHA approval applies to it.

**RELEASE READY FOR OWNER APPROVAL**, for the bounded preparation release described
below. Phase 5.3 remains **PARTIAL**: genuine normal-Chrome, Naukri, locked-Mac
and Telegram acceptance has not run on this release. No merge, installation,
service restart, account access, channel activation or employer action ran.

## Findings corrected during renewed review

1. The supplied head fixed the role-policy bypass, but execution intent records
   still used canonical historical title/employer/company ID. The dashboard could
   describe a current packet as the old employer's application. A regression
   reproduced this before scheduling and again with a correction after a
   committed claim. Intent creation now uses `reviewed_job_context`; preparation
   refreshes execution identity before checking policy, including a change that
   must pause. A changed employer gets no historical company ID. Canonical Job
   and Company rows remain preserved. Tests assert agreement among queued intent,
   prepared execution, packet and review, and current labels on rejected changes.
2. Direct absolute-file invocation of the acceptance monitor failed with
   `ModuleNotFoundError: backend`, including from the checkout. The existing
   documented `python -m backend.scripts.monitor_naukri_acceptance` invocation
   was unaffected. The file entry point now resolves its own release root,
   consistently with the other immutable-release tools. A child-process test runs
   outside the checkout with no PYTHONPATH and requires the actual configuration
   rejection before any API, database or OS observation. This is entry-point
   evidence, not proof of a locked-screen observation.

Both new assertions failed against the supplied production source before the
fixes. No eligibility, approval, submission, retry or authorization gate was
relaxed. No frontend, extension, dependency, API schema or migration change was
needed for these corrections.

## Review conclusions and evidence

The full combined diff was inspected across owner import normalization, reviewed
listing/employer views, scheduler admission, committed claims, Resume, profile
confirmation, pinned resume, packet/answer digests, duplicate exclusions,
Start/Pause/Stop, native authorization, selected-profile isolation, command leases,
bound-tab inspection, frontend status and installation/rollback tooling.

Historical titles cannot satisfy a changed role's exact allowed-role policy.
Current employer corrections cannot borrow old identity/domain/enrichment.
Changed required skills and experience block before scheduling and after claims;
Resume checks current eligibility. Policy revisions, owner locking, daily UTC
reservations and Stop fence delayed work. Start revives no paused application or
old field approval. An uncertain native command is not automatically replayed.
Remote Prepare resolves the exact authenticated bound tab/window without changing
focus, and validates current task/packet/profile/session/URL/permission before and
after DOM inspection. Isolated browser execution remains an explicit choice.

The two earlier review findings remain resolved: the 21 frontend failures and 11
errors are individually classified in [the follow-up](pr45-review-followup.md),
and unrelated foreground tabs/windows no longer force remote Prepare to inspect
the active tab. The four frontend files selected here have zero unhandled errors.
The previously recorded disposable PostgreSQL/Chromium journeys are reused,
clearly dated engineering evidence; they were not rerun as genuine Chrome tests.

| Check on replacement source | Result | Boundary |
| --- | --- | --- |
| Eight targeted backend selections | 165 passed | Fictional in-memory records; HTTP blocked |
| Original unchanged four-case release reproduction | 4 passed | Same private external reproduction; fictional data |
| Naukri, automation, Chrome-profile and browser-policy frontend files | 24 passed, zero unhandled errors | Mock transports |
| Coordinator, form bridge and network guard | 61 passed | Simulated extension events |
| Real Python native-host framing/auth/offline case | 1 passed | Synthetic origin/configuration; no installed host change |
| TypeScript typecheck | Passed | No API contract changes |
| Changed-file Ruff E9/F/I and whitespace | Passed | Five Python files |

The external reproduction initially lacked this checkout's pytest configuration
when selected by absolute path. That invocation produced three fixture errors;
using the repository's unchanged `pytest.ini` (`asyncio_mode=auto`) passed all
four cases. No production code or assertion was changed for that invocation fix.
The earlier standalone monitor and execution-identity failures were real defects,
not fixture errors. No full suite or hosted Action ran.

Local ignored receipts: `reports/final-release-review/backend.log`,
`original-release-repro.log`, `frontend.log`, `extension.log`, `native.log`,
`typecheck.log` and private preservation/installation records. Exact backend scope:

```sh
python -m pytest backend/tests/test_naukri_reviewed_facts.py \
  backend/tests/test_naukri_lock_monitor.py backend/tests/test_naukri_recurring.py \
  backend/tests/test_execution_naukri.py backend/tests/test_chrome_profiles.py \
  backend/tests/test_extension_tasks.py \
  backend/tests/test_naukri_alert_email.py::test_phase53_deferral_cannot_be_overridden_by_gmail_flags \
  backend/tests/test_phase1_installation.py -q
```

## Installation scope and approvals

The replacement frozen plan follows [installation and rollback](install-and-rollback.md).
After approval, recheck the PR head and base; merge only that exact head and verify
the merge tree. Build an immutable detached linked release with its own constrained
Python and frozen pnpm dependencies. Preserve the existing release at
`8c1635139a8943e9c2b72f39c4db593e1ccaa5b5`, private env files/keys, service and
native definitions, launcher, history and database. No DDL or data restore runs.
The primary checkout stays at `39a49507d3b5bf93a0a65ecbbffdcc4c3469dfa2`.

Only the existing API/frontend/Telegram services and native wrapper are upgraded.
The existing Telegram poller restarts within its already installed scope; no test
message, second poller or new provider authority is included. Stage the execution
LaunchAgent outside `~/Library/LaunchAgents`, then install/bootstrap it only after
separate activation approval. The existing `launchd-install` command bootstraps
immediately, so it must not be used to stage an inactive service.

With owner assistance load extension 1.3.1 in the chosen existing normal Chrome
profile. Verify actual version, ID `gdjbmkffcpicbpiikcohlmokkmcpipgp`, native health
and granted DNR permission. A source-derived ID or a running PID is insufficient.
No Playwright browser download/fallback is required. Install no paid service and
enable no cloud AI budget, Gmail polling or employer action. Keep
`NAUKRI_ALERT_EMAILS_ENABLED`, `GMAIL_READ_SYNC_ENABLED`,
`GMAIL_READ_BODY_REVIEWED` and the Chrome command channel disabled.

Later approvals separately cover profile connection/selection, Chrome channel
activation, execution service/policy/Start and bounded locked-session monitoring,
an exact legitimate job and permitted inspection, actual Telegram delivery, and
any exact field/value/provenance/side-effect set. Naukri submission stays blocked:
there is no verified permitted submission integration and independent employer
receipt capability. Gmail's two-account intake stays deferred to Phase 5.4.

Rollback restores the snapshotted service/native/frontend definitions to the
preserved `8c163513…` release and owner-reloads its extension 1.3.0. It preserves
all new records and uncertainty; there is no down migration or replay. If later
channels were activated, first Stop/revoke/fence and stop that separately approved
worker. Older rollback helpers targeting a different release are not substitutes.

## Acceptance matrix at the Stage 1 boundary

| Requirement | Status | Evidence / remaining gate |
| --- | --- | --- |
| Final release review | PASS | Combined review and focused checks above; replacement exact SHA in handoff |
| Installation / rollback readiness | PASS | Immutable procedure, frozen replacement plan and proposed definitions; cutover awaits approval |
| Actual installation | NOT TESTED | Existing services remain on `8c163513…` |
| Real Chrome profile connection | NOT TESTED | Owner installation/connection approval needed |
| Persistent Start/Pause/Stop | PASS engineering; NOT TESTED live | Targeted execution/revision/fence tests; no activated worker |
| Genuine Naukri matching | NOT TESTED | Owner-selected current legitimate job and verified facts needed |
| Automatic packet preparation | PASS engineering; NOT TESTED live | Fictional worker-created packets, pinned resume and revalidation |
| Genuine form inspection | NOT TESTED | Selected real profile, permitted job and exact bound tab needed |
| Approved field filling | NOT TESTED | Exact fields, values, provenance and effects require specific approval |
| Locked-Mac execution | NOT TESTED | CLI/telemetry fixtures are not real locked-session evidence |
| Telegram delivery | NOT TESTED | Specific live-test approval and actual delivery receipt needed |
| Genuine automatic submission | BLOCKED | No verified permitted Naukri submission integration |
| Independently confirmed employer receipt | BLOCKED | No submission or independent receipt capability |
| Existing data/configuration preservation | PASS for review; installation pending | Ten private/service/native preservation hashes, launcher and primary unchanged; no live DB access or mutation |

No short engineering run demonstrates 24/7 uptime. A heartbeat does not establish
DOM execution; a filled form does not establish submission or employer receipt.
