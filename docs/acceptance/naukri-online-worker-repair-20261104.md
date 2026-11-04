# Online worker schema repaired; genuine application acceptance remains open

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`. This report supersedes the pending cloud
migration and untested full-restore status in the earlier November 4 report.
**Naukri remains OPEN: zero new verified submissions.**

## Actual online repair and preserved installation

At 13:38 UTC November 4, the exact reviewed
[003 SQL](../../supabase/fresh_public/followups/003_naukri_worker.sql) was applied
once through the owner's existing authenticated Supabase CLI administrator access.
Its SHA-256 is
`21d6282790f396ffd1447af2f521e3d2eb57fff50a2d44236b22d2291419d6f0`.
The command exited zero in 3.418 seconds including transport. Full online catalog
verification accepted both ordered followups, restricted runtime permissions and
the existing data. Queue STOP117, 1,884 records, profile version5, approved account
binding revision1, policy values and protected local files were unchanged;
readiness returned200. No application/provider action was part of the migration.

The existing MCP OAuth refresh failed, but the already authenticated CLI worked.
No replacement token, new Supabase account, owner sign-in or repeated approval
was needed. This does not claim that the MCP OAuth connection itself is repaired.
The migration was a direct execution of the pinned SQL; no Supabase migration
ledger entry is claimed. Do not reapply it.

Installed components remain:

| Component | Exact installed implementation |
| --- | --- |
| API, execution worker, Telegram, frontend | `ae66975691a75cb0a3a43010dcfdba26a5100128` |
| Native host | `414a260a01b94609bc71eddd2bb037fbb274c3b9` |
| Extension1.3.24 | `2c9d4815f011db27b5dcc7f092f927b50f790095` |

The extension ID remains `gdjbmkffcpicbpiikcohlmokkmcpipgp`. Historical releases,
exact prior service wrappers/plists, encrypted backup and rollback inventory remain
retained. The reviewed SQL rollback restores the old catalog only before worker
admission/evidence; after any real or uncertain admission, preserve history, STOP
and use a catalog-compatible runtime with a forward repair.

## Actual encrypted archive recovery

The genuine pre-migration encrypted archive was fully restored on a private,
task-owned loopback PostgreSQL17 instance on this FileVault-enabled Mac. SCRAM
authentication and a private directory protected the rehearsal. The plaintext
archive stayed in memory; no production fallback or provider connection was made.

- All47 restored table counts matched the archive:20,937 rows.
- Profile5, binding1 and stopped queue117 matched the backup.
- Two resume payloads decrypted and matched their stored checksums.
- Two OAuth envelopes decrypted without refresh; zero packet invariant violations.
- Restore and data checks took2.378 seconds; zero online mutations/provider calls.
- An independent restricted-runtime catalog/security check passed on the restored
  database. The task-owned rehearsal server was stopped afterward; files retained.

Two initial rehearsal attempts failed on the fresh default public schema and an
omitted Supabase global role. They were stopped and retained. The successful
attempt removed only its own empty default schema before restore and precreated
the required NOLOGIN roles. Schema-scoped archives omit global role/event-trigger
metadata: the separate catalog check restored reviewed runtime role attributes
and recreated the managed event trigger only after matching its pinned function
checksum. This is a recovery rehearsal, not a claim of production failover.

Actual restore exposed equivalent PostgreSQL array-cast and email-AND deparses.
[Implementation b0f3709](https://github.com/karanagg166/automated-apply/commit/b0f370924f569f9b11eda5a96e2ecd906316587a)
compares these two observed forms while preserving the complete pinned catalog,
labels, operators, clauses, validation flags, functions, ownership and ACLs. It is
source-only; it has not replaced the installed runtime. Sixteen focused catalog
tests passed in0.90 seconds, including changed-label/bounds/regex/predicate/function
rejection. Ruff E9/F/I and diff checks passed. Unchanged broad suites were not rerun.

## Genuine resumed worker behavior

The actual installed frontend started RUN118 after the online catalog passed.
Naukri remains SUPERVISED, lifetime-one/hour-one, score50, any verified listed
skill, age14 days, applicant threshold1,000 and unknown-count review. Other
platforms remain disabled. The uncertain internship and historical QTrino were
not replayed; recurring AUTOMATIC remains guarded by the first worker receipt.

At13:55 UTC the durable ledger had1,909 identities, zero committed Apply admissions
and zero new receipts. Live worker heartbeat and repeated five-minute discovery
continued. Of the inspected jobs,816 failed verified experience,479 required an
applicant-count decision,431 exceeded posting age,52 lacked recognized required
facts and41 had conflicting experience evidence. These are overlapping decision
stages across different records, not a claim that all remaining jobs qualify.

One never-attempted retained candidate passed current matching but its fresh
listing inspection returned `provider_context_changed`; no packet/action followed.
A second prepared candidate scored57.5 but returned
`supported_direct_apply_control_required`. One audited fresh ordinary account/PDF
and control inspection confirmed the actual inactive page has **Apply on company
site**, rather than direct Naukri Apply. Its applicant label had also changed to
50+, which supplies no upper bound. No external application or Apply was forced.

The first operator inspection request rolled back on an overlength audit key;
the corrected bounded key committed once. Owner-lock contention caused two
skip-locked refusals and one lock-timeout rollback; neither changed data. A
separate live snapshot showed three idle production connections plus one operator,
zero blocking PIDs and no idle transaction. This sample does not establish that
contention or overall latency is resolved. No connection limit/timeout increased.

| Acceptance | Result | Actual evidence / remaining limit |
| --- | --- | --- |
| Exact cloud003 repair, full catalog and preserved data | PASS | One administrator execution; restricted runtime verified; ready200 |
| Full real archive restore and secret decryption | PASS |47 table counts,20,937 rows; protected private local recovery only |
| Restored catalog equivalence fix | PASS / SOURCE ONLY |16 regressions and actual restored runtime audit; not installed |
| Real repeated discovery and durable deduplication | PASS | RUN118, five-minute cycles,1,909 retained identities |
| Fresh account/PDF and genuine Apply-control inspection | PASS | Ordinary inactive worker tab; external-only control recognized |
| First new supported application and persistent receipt | BLOCKED | No currently accepted direct candidate; zero admissions/receipts |
| Recurring AUTOMATIC, restart and locked application operation | NOT TESTED | First-receipt prerequisite remains enforced |
| Other platforms and email enrichment/drafts | NOT TESTED | Disabled; Naukri first |

Reproduce the source-only catalog checks with:

```sh
.venv/bin/python -m pytest backend/tests/test_public_worker_catalog.py -q
.venv/bin/ruff check --isolated --select E9,F,I \
  backend/app/local_agent/public_database.py backend/tests/test_public_worker_catalog.py
git diff --check
```

For cloud verification, use the existing restricted-runtime verification procedure;
never rerun the DDL as a diagnostic. Raw journals, restore contents, DOM, profile,
resume/account hashes and credentials remain private. No owner focus/keyboard/
clipboard use, Gmail send, other-platform activation, CAPTCHA/rate bypass, hosted
Actions, merge, release deletion or cleanup occurred.

Next: inspect genuine required-fact parser failures and new eligible direct jobs,
complete one supported application once, verify independent persistent history,
then activate bounded AUTOMATIC and test repeated/restart/locked operation.
