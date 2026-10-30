# First genuine application: owner Apply is next

In the existing Profile 8, verify the saved Naukri resume and the selected
[QTrino Backend Developer listing261026028027](https://www.naukri.com/job-listings-backend-developer-naukri-e-hire-gurugram-0-to-2-years-261026028027),
check Applied Jobs for a prior application, then **the owner activates Apply
once** if still appropriate. It can submit immediately and may change company
follow state. Verify the exact listing in persistent Applied Jobs afterwards.
An actual questionnaire or blocker must be handled from its observed content.
There is no supported applicant submission API established for this project.
Extension cutover and history-fix installation do not block this manual route.

Implementation: [`0efc7cdecdf71a902ab257a4d2fea7f58e170c63`](https://github.com/karanagg166/automated-apply/commit/0efc7cdecdf71a902ab257a4d2fea7f58e170c63),
branch `fix/live-prepare-discovery-20261030`, base `main`,
[PR #48](https://github.com/karanagg166/automated-apply/pull/48).
**Implemented and locally verified; not installed. Zero new real submissions or
receipts.** [Sanitized functional metrics](first-real-application-workflow-metrics-20261030.json).

## Delivered workflow

Existing approved local Gmail monitoring checks only the selected Inbox and
exact official alert sender, validates Gmail-reported origin before reading a
selected body, and saves direct requisition links. It does not fetch links or
infer employer, requirements or vacancy status from a URL slug. Unreviewed
candidates require factual review through Naukri → Review alert facts. Owner
imports remain a free alternative when a message is absent or not selected.
The separate legacy Gmail source stays deferred/disabled; this work does not
expand any account, body, sender, folder, scope, date window or polling policy.

Reviewed imports flow through existing profile matching, confirmed-history and
requisition deduplication, bounded daily preparation and factual answer assembly.
Profile-based answers cost no model credits. Actual unknown/subjective questions
can be answered by the owner through the dashboard or an already opted-in
correlated Telegram question. Optional model generation remains behind its
existing consent/budget gates and is unnecessary for the free workflow. Required
unknown or expired answers stop handoff; candidate facts and match thresholds are
never changed to force eligibility. No portal questionnaire is invented.

The new implementation connects that preparation to durable **owner review**
notices and exact reviewed revisions to **manual Apply** notices. Both link to
the packet and explicitly retain live vacancy/resume/question verification and
`No application has been sent`. Packet-only owner review also produces a notice;
an execution intent is not required for a manual handoff. Changed context,
missing/expired answers, paused/cancelled work, global Stop/OFF, closed/unknown
submission states and disabled owner notifications suppress new notices. Stable
packet/revision keys deduplicate retries and restarts. In-app delivery history is
persisted transactionally; Telegram is queued only for the existing current
policy opt-in and configured owner channel. No external message was sent during
this task. Preparing or approving a packet grants no submission authority.

The full fixture journey exercises approved alert selection → two-message
requisition dedupe → owner factual import through the authenticated API →
profile matching → saved resume/factual answers → review notice → exact owner
approval → manual-handoff notice → copy-ready handoff → explicitly fictional
owner submission report → suppression of another application. Reports remain
`user_reported` / `self_reported_unverified`; they never become provider receipts.

## Actual Mac/installed observations

One bounded inspection used three authenticated localhost **status GETs**. All
returned200: workflow4.8280s, mailbox policy1.1705s, selected packet4.0369s, under
the unchanged12s deadline. These are functional observations, not a new workload
or performance acceptance window. No direct database audit, new mailbox scan,
browser command, GUI, profile change, Apply activation, service restart or
installation occurred. Private responses remain outside Git; only aggregate
states and field categories are published.

- Four LaunchAgent program references still identify approved90; none identify989.
  Native definitions and release files were not changed.
- The existing local Gmail account is connected, body review is enabled, and its
  Naukri alert policy version1 is already enabled. Sending is disabled. The
  distinct `GMAIL_READ_SYNC_ENABLED` and `NAUKRI_ALERT_EMAILS_ENABLED` flags remain
  false. Those legacy flags do not disable the separately approved local source.
- The last recorded alert cycle at17:01:05 UTC had **0 messages,0 direct links,
  0 candidates,0 errors**, with links_opened=false and submitted=false. This is
  an empty selected cycle, not proof of full mailbox coverage or a broken source.
  No broader search or forced poll was performed to obtain a candidate.
- The selected genuine packet is revision4, `ready_for_review`, fresh and
  unapproved. Seven non-file checklist answers are derived from saved candidate
  facts; its resume field still requires manual handling. None of these fields
  establishes a real Naukri questionnaire or verifies Naukri's current saved CV.
- Existing workflow counts show0 prepared execution packets,0 user-reported
  applications,0 confirmed submissions and1 manual-required decision. A saved
  checklist must not be counted as a genuine prepared portal application.

## Chrome cutover and exact history candidate

The read-only verifier compares files from an exact Git SHA's extension build
inventory and checks only the selected profile's saved path. The prepared989
candidate and installed90 build each match **18/18** expected files; the profile
still references historicalb069, matching **15/18**. It is missing `tab-audit.js`
and differs in `background.js`/`task-coordinator.js`. The verifier never prints
profile contents or absolute paths and never writes Chrome state. File identity
and persisted path are separate from runtime reload evidence.

[The supported stable-path procedure](../extension-stable-path.md) uses a dedicated
directory and an **owner-operated** Load unpacked/Reload in the existing profile.
No directory was installed and no runtime reload was performed. The source of
the previous path reversion remains unproven. No supported silent path migration
has been established under the strict background-only desktop constraint.

[The narrow installation review packet](history989-installation-approval-20261030.md)
pins **98965f7607a4714371599fef0143d5e1f8eed25b**, its limited history-sort delta,
independent extension artifact and preservation/rollback steps. It remains
uninstalled and needs separate exact-SHA authorization. It intentionally does
not authorize installation of the newer notification commit or the moving PR head.

## Submission support and receipt standard

The [exact owner Apply procedure and primary-source research](naukri-application-route-20261030.md#owner-operated-first-application-exact-next-action)
distinguish Naukri's employer/ATS integrations from a jobseeker submission API.
Naukri's recruiter integration descriptions and Greenhouse/Ashby setup guides
establish employer-side arrangements; none supplies this project a permitted
third-party applicant submission route. Public terms retrieval remained
robots-restricted; the earlier ordinary-profile terms observation is preserved.
No undocumented authenticated Apply POST, session replay or submission client
was implemented.

A persistent exact Applied Jobs record after the owner's action is a genuine
**Naukri-recorded manual application receipt**. Employer acknowledgment/viewing
is separate later evidence, not an extra prerequisite to acknowledge the
platform record. The app cannot independently verify an owner-entered receipt
and keeps that report self-reported. Ambiguous outcomes stop without resubmission.

## Local verification and reproducibility

Final focused verification: **217 passed,0 failed,0 skipped in28.11s**:
**21 new regression cases** (14 workflow/readiness and7 extension-audit cases),
plus196 existing cases. The existing47 history/Chrome/reliability/timing cases
are included, not added again. Fixtures use fictional accounts/candidates/jobs,
isolated in-memory SQLite and injected Gmail responses. External HTTP is denied;
no genuine email, application or receipt is implied. The workflow tests execute
real services/API/worker persistence with fixture data. The audit tests use
fixture directories and the public exact989 source inventory.

An initial test collection error (`AddQuestions` instead of `QuestionsAdd`) and
Ruff import-order errors were corrected. Final Ruff E9/F/I and diff checks pass.
No new PostgreSQL integration run, full frontend/extension suite, locked-session
journey or production installation test was needed or claimed for these Python
notification/audit changes. There are no API schema, frontend, extension runtime,
migration or dependency changes.

```sh
backend/venv/bin/python -m pytest \
  backend/tests/test_naukri_ready_workflow.py \
  backend/tests/test_extension_cutover_audit.py \
  backend/tests/test_naukri_recurring.py \
  backend/tests/test_naukri_reviewed_facts.py \
  backend/tests/test_execution_naukri.py \
  backend/tests/test_local_gmail_discovery.py \
  backend/tests/test_naukri_alert_email.py \
  backend/tests/test_application_packet_review.py \
  backend/tests/test_application_handoff.py \
  backend/tests/test_chrome_status_history.py \
  backend/tests/test_chrome_profiles.py \
  backend/tests/test_reliability.py \
  backend/tests/test_request_timing.py -q

backend/venv/bin/python -m ruff check --isolated --select E9,F,I \
  backend/app/execution/notifications.py backend/app/execution/worker.py \
  backend/app/services/applications/review.py \
  backend/scripts/verify_extension_cutover.py \
  backend/tests/test_naukri_ready_workflow.py \
  backend/tests/test_extension_cutover_audit.py
git diff --check
```

No broad optimization, timeout/pool change or performance experiment was made.
New before/after timing/resource comparisons are **NOT TESTED** because no such
change was needed. The prior measured window remains separately documented in
[approved90 evidence](approved90-installation-20261030.md); its fixture/live
distinction and failures are not overwritten. This task's three status timings
and local test wall time are not comparative production benchmarks.

| Capability | Verdict | Evidence / next action |
| --- | --- | --- |
| Approved local alert policy remains active | PASS observed state | Existing account/policy enabled; no settings changed |
| New real alert discovered in latest recorded cycle | NOT TESTED with a matching message |0 selected messages; no scan broadening |
| Alert → facts → match → dedupe → factual answers → ready notice | PASS fixtures | Real local service/API/worker journey; no real portal form claimed |
| Exact approved manual handoff and notification | PASS fixtures | Includes packet-only flow, retry dedupe and configured owner channel outbox |
| Real packet revision4/profile checklist | PASS read-only | Fresh, owner review pending; saved Naukri resume unverified |
| Existing Chrome runtime cutover | FAIL / BLOCKED | Historical persisted path; owner Load unpacked/Reload required |
| Read-only extension verifier | PASS |7 fixture cases plus3 actual disk/path comparisons |
| Exact989 installation | BLOCKED | Review packet complete; separate authorization absent |
| Supported third-party Naukri submission route | BLOCKED | No applicable official API/permission found |
| First owner-operated application and persistent Applied Jobs receipt | NOT TESTED | Owner Apply once after profile/resume/prior-application check |
| Automatic submission | BLOCKED | Unsupported; none performed |
| Hosted CI, release replacement, merge, cleanup | NOT PERFORMED |3 workflows remain workflow_dispatch-only; no dispatch |

Do the owner-operated application step next. Do not add another acceptance loop,
require extension cutover first, or invent an employer receipt.
