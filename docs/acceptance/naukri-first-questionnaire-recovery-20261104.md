# First genuine questionnaire attempt and recovery limits

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`. **OPEN: one new Apply admission, zero new
verified submission receipts. Recurring AUTOMATIC is disabled.**

At 2026-11-04 16:16:36 UTC the installed worker admitted Apply exactly once for
requisition `080524010245`, after account/PDF/eligibility/prior-status checks.
The listing scored 67.17, reported 35 applicants and a current posting date.
It opened a genuine recruiter questionnaire. This is actual installed behavior,
not a fixture or a submission receipt. QTrino and the older uncertain internship
were not replayed.

The real question had a contenteditable text box plus a separate “Skip this
question” chip. Extension 1.3.29 misclassified that combination as a choice whose
only answer was Skip. The new adapter recognizes this exact observed combination
as text, retains exact-choice handling for genuine choices and never clicks Skip
as a substitute for a missing personal answer. The unknown training fact was
asked through Telegram once; the owner supplied the missing fact in this session.
That reply is retained privately for this application. **No questionnaire answer
was admitted or saved to Naukri.**

The connection's browser-session ID subsequently differed from the original
Apply binding, its volatile parked-form ownership was absent, and the exact
original tab eventually returned `No tab with id`. Earlier guarded reads had
found its unanswered first question. The cause of the session/tab loss is not
established. The recovery adapter correctly refused the missing original tab;
it did not create another application, repeat Apply or invent form persistence.
The durable packet remains `submitting` and the attempt is quarantined as
`SUBMISSION_UNKNOWN`, with history reads only. Actual reconciliation has returned
`exact_application_history_row_required`; no exact persistent sent receipt has
been established. An absent row is not proof that retrying Apply is safe.

The earlier private progress view excluded waiting rows created before its new-job
cohort, so it missed this admitted waiting questionnaire and incorrectly reported
zero admissions in that view. The corrected observer includes **every** work item
with an admitted action, regardless of creation date, stage or waiting status.
Full-ledger evidence is authoritative. Earlier statements of zero *receipts*
remain true; zero-*admission* observations must not be used as the current total.

## Implementation and installed state

- Text/Skip fix: [f5dd610](https://github.com/karanagg166/automated-apply/commit/f5dd61095c8f3e2ce6138637a953dcb9a134af90).
- Scoped settings-page continuation and explicit retained-work selection:
  [9a28b38](https://github.com/karanagg166/automated-apply/commit/9a28b386e9c43417545488bc82b885c615b72f75),
  [3919d44](https://github.com/karanagg166/automated-apply/commit/3919d44a567cef10e36fa01b3635caaed02901d0).
- Untouched-first-question recovery and local diagnostic details:
  [2162eb1](https://github.com/karanagg166/automated-apply/commit/2162eb182e422f67b50f4038f887f2232e52f61e),
  [dc47f94](https://github.com/karanagg166/automated-apply/commit/dc47f9448cdf5dfc3ed81c80e360d70c35206264).
  Recovery requires STOP, the exact inactive original tab/URL and first empty
  question, one original Apply and zero answer admissions, unchanged current
  packet/profile/account, fresh observation and a matching current connection.
  Old binding/step evidence is retained. The operator-only backend helper has no
  new HTTP route. Successful real recovery is **not** claimed.
- Stop/Start reconciliation fix:
  [581ec79](https://github.com/karanagg166/automated-apply/commit/581ec79f0c3b73892a043b81e2327c4265a1a7d5).
  A retained-form flag no longer changes queued account/history reconciliation
  into questionnaire work. API 581ec79 also incorporates the already reviewed
  a4e52e2 owner-lock existing-row fast path.

Actual installation completed at 17:23:50 UTC:

| Component | Exact installed implementation |
| --- | --- |
| API | `581ec79f0c3b73892a043b81e2327c4265a1a7d5` |
| Extension runtime and 25 disk files, 1.3.30 | `dc47f9448cdf5dfc3ed81c80e360d70c35206264` |
| Execution / Telegram / native host | `b6b069051cdddc26683e67ef64646a90a2a7f753` |
| Frontend | `ae66975691a75cb0a3a43010dcfdba26a5100128` |

The extension ID remains `gdjbmkffcpicbpiikcohlmokkmcpipgp`. Early adapter disk
cutovers refreshed only an owned inactive settings document to preserve a still
potentially recoverable session; they were explicitly **not** full runtime reloads.
After the original tab was confirmed unavailable, ordinary Reload on the owned
inactive extension-manager tab verified the complete 1.3.30 runtime and a fresh
native reconnect. No personal tab was navigated or activated by the agent.

API replacement used STOP revision129 and preserved all 2,041 queue records,
profile version5, approved binding revision1, policy and protected private/native/
other-service files. `/ready` and frontend login returned200; full database catalog
readiness passed. The actual frontend then started RUNNING revision130 with
score50, age14 days, applicant threshold1,000, any-skill matching, unknown counts
held, SUPERVISED lifetime1/hour1, all other platforms disabled. The lifetime Apply
allowance is consumed and was not reset; one additional distinct test attempt
requires the owner's pending authorization. First-receipt prerequisites remain.

An exact rollback inventory retains API48fafb7's catalog003-compatible plist,
24 extension1.3.29 bytes, all hashes and protected references. It preserves the
new module in the rollback archive if reverting. Every intermediate immutable
candidate/backup remains. **Do not narrow schema003 or restore a database snapshot
after this admitted packet.** No release deletion or cleanup was performed.

## Validation and limits

- 56 targeted Node parser/queue checks passed, including four new text/Skip
  regressions. Separately, 20 retained-recovery/settings checks passed, including
  original-tab/session/owner-adoption/unknown-progress and unrelated-work fences.
  Intermediate15/14/58-test runs overlap; do not add them to these counts.
- 44 isolated Chromium cases passed in112.433 seconds: genuine class structure,
  optional-Skip text plus Save, single-use admission, choices, identity, profile,
  PDF, follow controls and independent history. All provider pages/responses in
  this group are fictional; zero live Naukri requests, unexpected requests or
  chooser events. This does not prove the lost live form was filled.
- Source and independent exact API581ec79 candidate each passed30 targeted backend
  tests, in11.21/11.08 seconds. They cover questionnaires, nine untouched-recovery
  cases, timing locks and two Stop/Start history regressions. Counts overlap.
  Independent requirements installation and `pip check` passed. Ruff E9/F/I and
  diff checks passed.
- The unchanged lock fast path previously passed four actual disposable local
  PostgreSQL concurrency groups (0.253 seconds); see the
  [lock report](naukri-owner-lock-profile-20261104.md). No pool/connection/timeout
  limit was increased. Production PostgreSQL remains the only real-data queue.
- The latest pre-replacement Stop took10.076 seconds, including the subsequent
  status snapshot. A previous direct Stop response took7.121 seconds. These are
  different operations/samples, not proof of a complete Stop performance fix.
  New live authorized-native samples took2.574/2.488/5.398 seconds; the first two
  had10 reads and one write, with negligible pool acquisition. The third had18
  reads and three writes. Command mix differs; this is not a controlled benchmark.
- The final replacement's front window and bound automation window's active tab
  stayed the same; an unrelated active-tab ID changed, so strict equality of the
  entire before/after metadata snapshot was false. An earlier inactive setup
  navigation also coincided with a front-window change; attribution is unknown.
  There are no agent focus/activation/keyboard/clipboard commands. Continuous
  focus-preservation acceptance is not claimed from these mixed snapshots.

Reproduce targeted regressions without real application data:

```sh
pnpm -C extension exec node --test tests/naukri-chatbot.test.mjs tests/naukri-queue.test.mjs
pnpm -C extension exec node --test tests/naukri-retained.test.mjs tests/ui.test.mjs
pnpm -C extension exec node tests/naukri-execution.browser.mjs
.venv/bin/python -m pytest backend/tests/test_naukri_questionnaires.py backend/tests/test_naukri_unanswered_recovery.py backend/tests/test_request_timing.py -q
```

| Acceptance | Result | Actual limit |
| --- | --- | --- |
| Account binding and genuine provider PDF before initial Apply | PASS | Preserved; no email overwrite or filename-only verification |
| Genuine discovery/filter/match | PASS | Repeated actual cycles; seven more new identities after restart, still subject to all checks |
| One durable worker Apply and real questionnaire reached | PASS | Exactly one Apply, zero answer admissions; not a receipt |
| Optional-Skip text support | PASS regressions | Lost live form prevented end-to-end filling acceptance |
| Untouched-first-question recovery | PASS fences / FAIL live availability | Actual original tab unavailable; no recovery or replay |
| Independent new submission receipt | FAIL / unconfirmed | Exact persistent sent row not found |
| Installed readiness, data, policy and rollback | PASS | API581ec79, extension1.3.30,2041 records; all other services preserved |
| Stop/Start preserves history-only reconciliation | PASS regressions | Live history remains read-only; no reset of admissions |
| Continuous owner-focus preservation | NOT FULLY VERIFIED | Mixed snapshots; no deliberate agent focus action |
| Recurring AUTOMATIC / genuine locked-Mac applications | BLOCKED / NOT TESTED | First receipt absent; bounded test allowance used; no heartbeat-based acceptance |

Next: finish bounded independent history reconciliation, retain every uncertain
attempt without replay, obtain the explicitly requested additional supervised
allowance before another distinct Apply, and use the fixed adapter on a fresh
eligible job. Enable bounded AUTO only after a strict persistent first worker
receipt. Restart/locked-Mac and recurring real applications remain required.
Gmail sending, other-platform activation, hosted Actions, merge and cleanup remain
unused. Raw DOM, owner answers, profile/email/PDF bytes, credentials and logs stay
private.
