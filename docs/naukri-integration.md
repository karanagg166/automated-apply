# Naukri integration and execution contract

The supported flow is owner-provided Naukri postings/structured alert facts →
saved-profile matching → durable preparation → owner-reviewed local assistance,
with correlated Telegram questions. This does not certify a connected Naukri
account, genuine form compatibility or an employer submission. Do not start Phase
5.2 while Phase 5.1 acceptance gates remain unmet.

## Evidence and capabilities

Research: 2026-10-28/29. Indexed official
[Naukri account guidance](https://www.naukri.com/blog/how-naukri-works/amp/) describes
profile completion, recommendations and applications. Indexed official
[communications guidance](https://www.naukri.com/blog/greater-control-over-communication-from-naukri-com/)
describes recommendation emails and Applied Jobs updates. Both direct page reads
returned HTTP 403; no retry, private endpoint or bypass followed. This is
published-feature evidence, not live acceptance or automation permission. No
authorized public jobseeker API/OAuth integration was established.

| Capability | Supported path | Boundary |
| --- | --- | --- |
| Discovery | Import selected posting URLs/structured alert facts; find saved imports | No scraper, portal search or private API |
| Account/profile association | Existing owner-operated local-session indicator/manual acknowledgment | No password/cookie access; indicators are not authenticated account proof and expire |
| Job-alert import | Owner-supplied URL, role, employer, criteria and message reference | No mailbox reads or inferred sender authenticity |
| History import | Existing reviewed Gmail-evidence history and owner-reported packet tracking | Gmail live activation/consent remains blocked; uncertain evidence is not a confirmed application |
| Job URL import | Public HTTPS posting/requisition validation; tracking removed for identity | No fetch, redirect following or vacancy verification |
| Preparation | Saved preferences/resume, deterministic matching, grounded answer engine | Unknown facts/weak fit pause; narratives require review |
| Browser assistance | Explicit active-tab gesture on a clean Naukri posting in the owner's browser | Fictional Chromium/native acceptance only; live DOM unverified |
| Submission | Owner operates the official site | Automated dispatch/confirmation unavailable; grants and transitions fail closed |

Required/preferred skills, explicit experience bands and salary/currency/period
are preserved when supplied. Required, preferred and unknown experience remain
distinct. Junior/SDE-1/backend/full stack/AI-ML roles are evaluated against the
owner's actual saved titles, skills, locations/remote preference and experience;
candidate preferences are never edited to force a match. Reviewed prior history,
saved submissions and unknown submission outcomes exclude prior applications.
Requisition identity deduplicates changed posting slugs.

## Dashboard, Telegram and API

The /naukri workspace imports/listings, prepares selected jobs, displays status and
supports pause/resume/cancel. Optional import criteria support matching. Re-import
updated criteria and Resume to recheck a waiting match. Existing profile/resume,
grounded generation, packet review and browser controls remain shared.

All routes below are owner authenticated under /api/v1/execution:

| Route | Behavior |
| --- | --- |
| GET/PUT /naukri | Matrix, configuration and durable executions |
| POST /naukri/import | Bounded jobs array with URL/title/employer, optional factual criteria; job-alert provenance requires message_reference |
| GET /naukri/jobs | Saved imports only |
| POST /naukri/apply | Selected job_ids create/coalesce preparation intent, never submission |
| POST /{id}/control | action=pause/resume/cancel and expected_revision |
| POST /{id}/questions/{field_id} | Queue the exact packet question |
| GET /questions | Protected delivery/answer status |
| POST /questions/{id}/approve-reuse | Separate explicit reuse approval |
| POST /{id}/questions/{field_id}/reuse/{question_id} | Copy a compatible, approved, unexpired answer into a draft requiring review |
| GET /events; POST /events/{id}/ack | Stable event IDs, at-least-once consumption and idempotent acknowledgment |

Telegram commands are /naukri find, /naukri apply <job UUID...>,
/naukri pause|resume|cancel <execution UUID>, and /naukri status. Find explicitly
lists saved imports without running a portal search. Existing natural-language
discovery remains unchanged.

## State, durability and modes

The shared engine persists DISCOVERED → MATCHED → ELIGIBLE → PREPARING →
FILLING/NEEDS_INPUT → READY_FOR_REVIEW. It also models PAUSED, REJECTED,
FAILED_RETRYABLE, FAILED_FINAL, SUBMITTING, SUBMISSION_UNKNOWN and
SUBMITTED_CONFIRMED. Naukri denies entering SUBMITTING/SUBMITTED_CONFIRMED because
no submission contract is verified. Expired SUBMITTING leases recover as
SUBMISSION_UNKNOWN and never replay. Fill evidence always records submitted=false.

Existing private owner_preferences storage needs no new live DDL. Stable
platform/requisition intent retains attempt ID, job/URL/employer/requisition,
packet, candidate version, reviewed answer revisions and evidence. Short
transactions take the common owner lock before context locks. Claims commit
before work and carry expiring leases/fences and heartbeat support. Cancellation
and freshness are rechecked before field actions. Bounded retries reuse existing
packets and preserve owner edits across sessions/process restarts.

Default is ON_DEMAND. OFF pauses/fences active work. WATCH_AND_NOTIFY checks only
already imported records and deduplicates qualified in-app alerts; it does not
poll Naukri or Gmail and needs an explicitly started worker. Mode, source,
destination and submission permission are separate. Naukri rejects
AUTO_APPLY_WHEN_AUTHORIZED enablement and all submission/destination grants until
a permitted contract has been demonstrated. Discovery never grants submission.

The local Mac must be awake. Continuous browser work needs a separately approved
always-on deployment. No launch service is installed here.

## Questions, answers and browser fields

Actual unanswered required factual form questions become packet fields and
durable Telegram requests containing employer/role, exact question, application
reference, job URL, expected type and reply instructions. The existing owner-only
worker delivers them with expiring delivery leases. Lost acknowledgments may
duplicate a notification, never an application action. Unknown message IDs cannot
resolve a question.

Both owner user ID and private chat ID authenticate replies. Only recorded
reply-to-message IDs correlate. Changed candidate/source/packet revisions,
paused/cancelled applications, expired questions and invalid choices block
resolution. Multiple questions/employers stay independent across restarts.
Owner replies carry update/reply provenance and resume only their application.
Reuse starts OFF; explicit approval still requires matching profile version,
employer, role, exact question/options and job description in a compatible draft.

Interview availability requires a future date/time/IANA time zone, for example
2026-11-02T14:00 Asia/Kolkata. A yes/no control accepts
Yes | 2026-11-02T14:00 Asia/Kolkata, or No; only the exact choice fills the control.
Availability expires at the appointment or seven days, whichever comes first.
Salary/relocation/work authorization require current verified owner facts, expire
after seven days and never silently change profile facts. Other answers expire
after thirty days; questions expire after two days. Sensitive credentials,
identity numbers and legal-consent answers are not retained.

Subjective answers use the existing explicitly invoked, budget/consent-gated
grounded generation endpoint. Job descriptions/DOM labels are untrusted data and
cannot authorize tools or invent candidate facts. Answer resolution requires a
fresh inspection and explicit field review before filling an associated form.

The shared engine retains text, React-controlled text, textareas, safe native
selects, grouped choices, stale/conditional DOM detection, validation handoff,
explicit multi-page review, reload/session-expiry/cancellation guards and
canonical-PDF attachment checks in the dedicated worker. Unsupported widgets and
extension uploads stay manual. Naukri local assistance accepts only clean
selected posting pages; login/profile/query/redirect pages are denied. Other
restricted platforms and dedicated-browser network restrictions are unchanged.
No CAPTCHA bypass, fingerprint changes or session extraction is added.

## Installation and acceptance

Phase 4 engineering is complete; installed services remain at
975b8fc0afa6b9ce1f30a21c0cdfa667bcfc3009. Keep #39/#40 histories intact. After
owner-approved #39 merge, verify its head ancestry before retargeting #40 to main.
This change stacks on #40 and merges neither prerequisite.

For an authorized installation: pin the approved SHA; preserve current release,
configuration and encryption keys for rollback; install requirements/pnpm
dependencies in the release directory; build frontend/extension; compare
regenerated OpenAPI; and run readiness/tests. Review the existing
backend/scripts/phase1/install_local.py plan modes. Do not replace launchd/native
services or execute install/uninstall until the owner approves the exact release.
Preserve the extension's stable public key/ID on any approved reload.

The optional execution worker command is:

    backend/venv/bin/python -m backend.scripts.execution_worker --env-file /PRIVATE/OWNER_APPROVED.env

It validates database health and handles shutdown. Run only after target,
configuration and installation approval; watching remains opt-in.

Gmail separately needs the exact target administrator service, owner-controlled
age recipient, full encrypted backup/disposable restore receipt and writer
coordination in the existing [operator procedure](phase3/phase35-gmail-operator.md).
The owner directed a stop before backup/DDL. Runtime replacement, OAuth consent,
mailbox reads and employer actions remain separate approvals.

Acceptance uses /tmp/automated-apply-heavy-tests.lock, isolated fictional fixtures
and disposable PostgreSQL 17. Run full backend/extension suites, Chromium native/
React/form journeys, frontend unit/build/typecheck/format checks and the real
FastAPI/PostgreSQL dashboard suite. Set PROFILE_TEST_DATABASE_URL to the disposable
localhost candidate_profile_test database and P22_TEST_POSTGRES_CONTAINER to its
explicit Docker restart target so recovery checks do not skip. New tests cover
intent/leases/restart, correlation/concurrency, expiry/reuse and capability guards;
existing grounding/injection, 403/429, DOM and submission-unknown suites remain
required. Distinguish fictional versus genuine evidence in receipts. Hosted
workflows stay manual-only; do not dispatch or rerun them.
