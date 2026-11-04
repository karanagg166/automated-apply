# Any verified skill installed; genuine submission exposed public-schema blocker

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`. Naukri remains **OPEN**.

The owner's latest correction requires **at least one verified listed skill**.
This supersedes the previous strict-skill choice. Score50, age14 days,
applicants1000, unknown-count review, experience/location/history/account/PDF checks
and submission quotas remain enforced. Missing skills remain unverified.

## Exact changes and genuine installed behavior

- [`0eca742b250802e1e6a11dd2eeeefc45b2df37d9`](https://github.com/karanagg166/automated-apply/commit/0eca742b250802e1e6a11dd2eeeefc45b2df37d9)
 adds per-platform `skill_match_mode: all|any`, backwards-compatible strict defaults,
 zero-match rejection, ordinary held-job reconsideration and frontend controls.
 API/execution/Telegram/frontend were replaced together under STOP114/1651 records;
 readiness200, login200, profile5/account-binding1 and protected data/files passed.
 The actual installed frontend saved only the requested skill change at STOP115,
 then started RUN116. The approved decision is durable, with its previous choice
 retained. Native414a260 and stable-ID extension1.3.24/2c9d481 stayed unchanged.
- A real Fullstack Developer Intern listing, requisition031126029747, passed all
 retained-fact checks and received an audited priority ordinary fresh read. The
 worker independently progressed DISCOVERED→ELIGIBLE→PREPARING→READY_TO_APPLY.
 Score90.56; eight verified skill matches; AWS stayed unverified. Fresh actual
 listing evidence showed25 applicants. A new packet was prepared; the provider
 account and downloaded saved PDF were checked again at20:00:03UTC November3,
 followed by a genuine NOT_APPLIED/job/control observation at20:00:18.
- Its actual admission request returned503 after25.166s. The fixed native code
 was `backend_not_ready`; the backend logged `storage_unavailable`. There were
 **0 committed Apply admissions and0 new verified receipts**. The original live
 log did not retain the underlying SQLSTATE, so it is not claimed here.
 Read-only reconciliation then returned `exact_application_history_row_required`.
 This identity remains quarantined; do not repeat Apply. Historical QTrino is
 separately protected and was never replayed.
- Overnight discovery continued at the300-second interval. At11:15:30UTC November4,
 RUN116 had1865 identities and0 admitted Apply/new receipts; the recheck had
 examined1564 held records and scheduled2 ordinary fresh reads. This establishes
 discovery activity, not successful unattended applications or locked acceptance.
- The queue was deliberately STOPPED117 with1884 records while repairing the
 confirmed schema incompatibility. Policy values and all records were retained.

## Concrete schema repair

Read-only inspection found the old public SQL constraints still reject
`submitting`, `applied_verified`, `completed_verified`, worker event/origin labels
and Naukri evidence. Existing trigger functions additionally reject provider
confirmation and require packet revisions/states before audit inserts. Fixture
ORM `create_all` did not include these actual public-schema protections.

[`ae66975691a75cb0a3a43010dcfdba26a5100128`](https://github.com/karanagg166/automated-apply/commit/ae66975691a75cb0a3a43010dcfdba26a5100128)
prepares the compatible runtime and the atomic
[003 SQL](../../supabase/fresh_public/followups/003_naukri_worker.sql):

`SHA-256 21d6282790f396ffd1447af2f521e3d2eb57fff50a2d44236b22d2291419d6f0`

Exactly eight CHECK constraints and three existing trigger-function bodies change.
All original valid states remain. New submission states require the precise
packet/profile/revision and durable original Apply admission. Confirmation requires
linked worker evidence, two distinct history documents, matching account/status
and persistent receipt metadata. Protected packet content/fields cannot reopen.
No table, column, row, grant, RLS policy, credential, connection cap or timeout is
changed. Preconditions reject catalog drift and migration replay. The full catalog
verifier accepts only complete pinned before/after states, including all guards.

The worker now flushes durable admission, packet transition and its event in the
correct order within the same transaction; receipt transitions likewise precede
their events. Quotas fetch only admission histories once. New fixed diagnostics
distinguish SQL23514 and P0001 without publishing SQL parameters.

[The rollback SQL](../../supabase/fresh_public/followups/003_naukri_worker.rollback.sql)
has SHA-256 `d765b3076ef69cda7d262f3123541d62b96d556abc129c2bee14138caec0983b`.
It restores the exact old catalog only before any new worker admission/evidence.
After a real or uncertain worker outcome, narrowing rollback is prohibited:
keep STOP and a catalog-compatible runtime; repair forward without erasing history.

**Online DDL remains UNAPPLIED.** The existing runtime role cannot ALTER the schema.
[Database policy](../online-postgresql.md#migration-approval-scope)
requires separately reviewed owner approval for the exact cloud DDL. Local service
installation authorization does not supply a database-administrator session.
An owner action in the selected project's SQL editor is needed after review.

## Validation, timing and recovery inventory

- Source:97 skill/reconsideration/background regressions passed15.39s;10 frontend
 tests passed2.85s for the initial rule. Source and immutable0eca candidate passed
 the same targeted groups; overlapping counts are not added together.
- Actual saved-response UI race was found: an old refetch briefly restored the old
 rule/revision after a successful save. Sourcebc502e8 adopts authoritative save and
 control responses and refuses older polling revisions.11 frontend tests, typecheck
 and Prettier passed; the independent candidate also built and passed11 tests.
- Final schema/runtime source:108 targeted backend regressions passed19.11s;
 immutableae669 candidate108 passed19.47s. Exact candidate frontend11 tests and
 production build passed; frozen offline dependency installation and `pip check`
 passed. Ruff E9/F/I and diff checks passed. Unchanged extension suites were not
 repeated.
- Actual disposable PostgreSQL17 bootstrapped the committed public SQL, with its
 original constraints/triggers/RLS/grants:9 acceptance groups passed. They reproduce
 old-schema23514, accept the complete pinned repair, commit the production
 native/packet/receipt path across connections, test exact pre-admission rollback
 and reapply, reject rollback after worker evidence, preserve history/content and
 reject migration replay. These are fictional-provider tests with0 real requests.
 Initial local PostgreSQL14 and schema-dump normalization mismatches were rejected;
 acceptance used PostgreSQL17 with the original SQL bootstrap, not weakened checks.
- Actual read-only online query comparison under STOP117,1884 records: previous
 double full-value reads transferred15,103,588 JSON bytes in2.924s; the single
 history projection transferred5653 bytes in0.637s. This is not an end-to-end
 submission latency or contention-resolution claim. No limits/timeouts increased.
- A fresh online public-schema archive was encrypted directly from memory using
 the preserved private key:4,896,919 archive bytes,6,529,316 encrypted bytes,
 438 directory entries. Decrypt/checksum and archive-directory validation passed
 in23.693s. No plaintext archive was written. A full restore of this real archive
 was **NOT TESTED**; it was not copied into a fictional local database.
- Exact prior0eca plists, wrappers, runtimes, protected-file hashes and the new
 release plan are retained. Before online DDL, failed local installation restores
 all four exact previous services under STOP. All historical releases remain.
 Runtime installation at11:37:15UTC passed: all four servicesae66975 under STOP117,
1884 records, ready200/login200, worker online, profile5/binding1 and protected
files unchanged. Native414a260 and extension1.3.24/2c9d481/stable ID remain exact.
An isolated headless authenticated read of the actual installed dashboard verified
any-skill, score50,14 days,1000 applicants, unknown-count review and STOPPED state.
Only local GET/HEAD requests were allowed;0 unexpected requests. Password login
itself was not tested. No owner's Chrome tab, focus, keyboard or clipboard changed.

| Acceptance item | Result | Evidence / limit |
| --- | --- | --- |
| At least one verified skill policy | PASS | Actual frontend save; durable owner decision; unchanged other filters |
| Genuine eligible handoff and PDF/account/prior checks | PASS | Actual031126029747 worker sequence above |
| First new provider submission / receipt | FAIL | Admission503;0 committed Apply/new receipt; quarantined without replay |
| Recurring discovery | PASS | Actual repeated cycles/independent worker polls; no dashboard dependency |
| Compatible runtime and guarded public SQL repair | PASS / UNAPPLIED | Targeted tests and actual PostgreSQL17; online DDL not run |
| Runtime installation / installed frontend | PASS | Exactae66975 four services; STOP117/1884; ready200; actual dashboard fields verified |
| Real-archive full restore | NOT TESTED | Encrypted archive/decrypt/directory checks only |
| Recurring AUTOMATIC / restart / locked application acceptance | NOT TESTED | First receipt prerequisite still enforced |
| Other platforms / contact-provider enrichment | NOT TESTED | Disabled; Naukri remains first priority |

Reproduce only on a fresh, disposable loopback PostgreSQL17 cluster:

```sh
PHASE1_DISPOSABLE_DATABASE_URL=postgresql://postgres@127.0.0.1:55493/candidate_profile_test \
  .venv/bin/python backend/scripts/phase1/verify_public.py --bootstrap
.venv/bin/python backend/scripts/phase1/verify_naukri_worker.py \
  --url postgresql://postgres@127.0.0.1:55493/candidate_profile_test
.venv/bin/python -m pytest backend/tests/test_public_worker_catalog.py \
  backend/tests/test_naukri_submission.py backend/tests/test_naukri_questionnaires.py \
  backend/tests/test_native_queue_rollback.py backend/tests/test_queue_response_commit.py \
  backend/tests/test_reliability.py -q
pnpm -C frontend test tests/application-queue.test.tsx
```

Next: complete the reviewed administrator migration/backup decision, independently
verify the full online catalog, then resume a different never-attempted eligible
job under the remaining lifetime-one supervised allowance. Independently verify
its receipt before bounded AUTO. No Gmail send, other-platform activation,
CAPTCHA/rate bypass, hosted Actions, merge, release deletion or cleanup occurred.
Raw DOM, candidate facts, accounts, resume bytes/checksum, tokens and raw logs remain
private. No heartbeat, fixture or Apply lease is presented as a submission receipt.
