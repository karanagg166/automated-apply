# Phase 5.3 reviewed-facts correction and scope decision

The owner placed PR #45 head `1d2bb5a0aadf684b2ad445fe140bcf7be9cefef3`
on **HOLD**. That SHA must not be merged or installed. This correction belongs
to the same PR; its exact replacement SHA is the commit containing this report.
It requires renewed exact-head release review and explicit installation approval.
The earlier frozen installation plan names the old SHA and cannot authorize this
replacement. No merge, installation, service restart or live activation ran.

## Root cause and behavior

Matching already overlaid imported criteria on the canonical Job row. Review
decisions still exposed the canonical historical title and Company, so the
scheduler could accept a newly reviewed role outside the policy's exact title
list. Packet snapshots, answer context and answer-reuse fingerprints could also
use those historical facts.

`reviewed_job_context` now supplies the same current reviewed listing to review
decisions, matching, worker preparation, packet construction, answer generation
and answer-reuse context. Policy admission and post-claim/Resume validation use
these current decisions. Scheduler queries and post-claim reads refresh database
state even when a session retains a previously loaded Job. Canonical human
title, employer association, skills, application status and history are preserved.

Only the authenticated owner import can correct the employer label for the
same normalized Naukri requisition. The generic importer continues rejecting
unreviewed employer identity conflicts. A corrected employer label does not
inherit the original employer's ID, domain or enrichment. Its packet company ID
is unknown until independently established; no new company identity is invented.
Updated descriptions, required skills, experience rules, dates and destinations
remain part of the reviewed listing. Missing facts do not borrow old values.
Listing corrections invalidate old packet review and answer-reuse fingerprints.

No title-specific exception, score relaxation, submission authority, browser
fallback or provider permission is added. The employer submission cap remains zero.

## Focused regressions and validation

`backend/tests/test_naukri_reviewed_facts.py` contains 20 cases:

- Eight changed-fact variants before scheduling: changed exact title, excluded
  employer, unverified required skill, removed required skills, experience outside
  verified experience, range outside policy, and preferred/unknown experience
  requirements. Each queues zero executions and creates no packet.
- The same eight variants after a committed worker claim, with an old Job still
  cached in that session and a separate authenticated owner import request. Each
  pauses before packet creation, clears the lease, and refuses Resume/reclaim.
- Allowed corrections use the same title/employer/match in review and an actual
  fictional worker-created packet; the historical canonical rows stay unchanged.
- Corrected facts stale the previous packet and change answer-reuse context.
- Answer generation rejects historical company/description context and accepts
  the reviewed context without calling a model for deterministic facts.
- Generic ingestion retains the employer-conflict rejection.

Results on the correction:

| Check | Result | Evidence boundary |
| --- | --- | --- |
| Focused backend files below | **236 passed** | Fictional in-memory fixtures; real HTTP blocked |
| Original immutable Stage 1 reproduction | **4 passed** | Unchanged external fixture against corrected source |
| Nine affected frontend files | **81 passed**, no unhandled errors | Includes prior review fixes, new Gmail deferral UI check |
| Extension coordinator/bridge/network guard | **61 passed** | Existing exact-tab/profile/revision/permission/Stop protections |
| TypeScript typecheck | Passed | No API contract change |
| Changed-file Ruff E9/F/I, frontend Prettier, whitespace | Passed | No migration, dependency or extension-source changes |
| Existing installation preservation | **10/10 hashes unchanged** | Primary checkout clean at `39a49507…`; no execution LaunchAgent |

The removed-skills regression initially expected an earlier eligibility reason;
the implementation correctly blocked through the stricter policy reason. Its
assertion now requires that specific rejection and still asserts zero preparation.
No production guard was weakened. The existing documented frontend React `act`
warning remains distinct from a failure or unhandled exception.

Commands (run from the correction worktree using the existing test venv):

```sh
python -m pytest backend/tests/test_naukri_reviewed_facts.py \
  backend/tests/test_naukri_recurring.py backend/tests/test_naukri_alert_email.py \
  backend/tests/test_execution_naukri.py backend/tests/test_chrome_profiles.py \
  backend/tests/test_extension_tasks.py backend/tests/test_application_packets.py \
  backend/tests/test_application_answer_service.py backend/tests/test_discovery_ingestion.py \
  backend/tests/test_job_ingestion.py backend/tests/test_packet_telegram_questions.py \
  backend/tests/test_answer_reuse.py backend/tests/test_phase3_missing_input.py -q
pnpm -C frontend exec vitest run tests/naukri.test.tsx tests/naukri-automation.test.tsx \
  tests/chrome-profiles.test.tsx tests/applications.test.tsx \
  tests/browser-assistant-improvements.test.tsx tests/browser-policy.test.tsx \
  tests/field-review-experience.test.tsx tests/local-connections.test.tsx \
  tests/phase4-job-dashboard.test.tsx --reporter=verbose
node --test extension/tests/task-coordinator.test.mjs \
  extension/tests/form-bridge.test.mjs extension/tests/network-guard.test.mjs
pnpm -C frontend typecheck
```

Local ignored evidence is under `reports/role-policy-correction/`: `backend.log`,
`frontend.log`, `extension.log`, `original-release-repro.log`, `typecheck.log` and
`preservation.private.json`. Prior disposable PostgreSQL/Chromium engineering
evidence is reused. No full suite, repeated live browser journey or hosted Action
ran. Workflows remain manual-only.

## Phase 5.4 deferral — owner scope decision, 2026-10-30

**Two Gmail accounts, Naukri alert detection and multi-account deduplication are
deferred to Phase 5.4. All Gmail intake stays disabled in Phase 5.3.**

The dormant Naukri email adapter has a release-scope gate, unavailable through
environment configuration. Phase 5.3 refuses an email policy at save/Start/
post-claim validation and refuses mailbox polling even for a previously persisted
RUNNING email policy with all three deployment flags true. The dashboard disables
email-source selection and states the deferral. Tests assert that the reader is
never constructed under the Phase 5.3 gate. Existing dormant adapter unit tests
explicitly monkeypatch the gate only inside fictional test fixtures; this is not
a runtime activation option or live evidence.

Keep `NAUKRI_ALERT_EMAILS_ENABLED`, `GMAIL_READ_SYNC_ENABLED` and
`GMAIL_READ_BODY_REVIEWED` false. No private settings were changed. No two-account
integration, cross-account discovery/deduplication, mailbox connection or read
was implemented or activated in this correction. Earlier documentation of possible
Phase 5.3 Gmail activation is superseded by this decision.

## Updated release recommendation

The reproduced policy blocker is fixed and focused checks pass. Recommend the
replacement head for renewed Stage 1 exact-SHA release review. Installation still
requires a new approval scope; the old frozen plan is invalid for this head.
Do not merge/install/restart/activate based on this engineering result.

Existing Start/Pause/Stop and Chrome-profile safeguards pass; both previous review
fixes remain intact. Genuine normal-Chrome profile/native communication,
read-only bound-tab operation and locked-but-awake Mac acceptance remain pending
separate installation/activation approvals. Field filling needs exact-field
authorization. Naukri automatic submission remains unsupported and disabled.
Phase 5.3 remains **PARTIAL / live acceptance NOT TESTED**. Gmail is a deferred
Phase 5.4 capability, not a requirement to activate for Phase 5.3 acceptance.
