# Database correction evidence — 2026-10-20

Follow-up: [combined release and hosted CI evidence](release-ci-evidence.md) records
the subsequent hosted success and safe PR integration strategy. The observations
below describe the earlier correction, before that CI investigation.

This is a partial implementation and discovery record. Online persistence has **not**
been established. No cloud project was changed, no remote SQL was applied and no
genuine PDF was synced during this correction.

| Required evidence | Observed state |
| --- | --- |
| Approved project | None; owner confirmation pending |
| Candidate reference | `lsvzmrzzhbegdmtayrpw` (`apply-bot-db`) |
| Connected organization | `karan`, ID `vhkpxihkzpetmkqnrfic`, free plan |
| Account/ownership authority | Connector can list organization/project; account email and owner role not established by the available discovery tools |
| Status / region | `INACTIVE` / `us-east-1` from read-only Supabase project discovery |
| Reported database | `db.lsvzmrzzhbegdmtayrpw.supabase.co`, PostgreSQL `17.6.1.121` (metadata only) |
| Database identity and isolation | Unverified; no project selected merely by its name |
| Actual remote connection | Not verified; project inactive and no approved credential configured |
| Remote schema / migration 011 | Unknown; intended schema `job_agent`, cloud inspection blocked |
| Remote API startup / restart | Not performed |
| Real frontend using remote backend | Not verified |
| Genuine resume online / checksum | Not performed |
| Online pending review visible | Not verified |
| Candidate facts activated by this work | No; activation requires explicit owner review |
| SQLite in new genuine workflow | No new genuine workflow executed; runtime correction rejects SQLite outside testing |
| Existing local data and encryption key | Preserved; local environment files were not rewritten |

Before corrections, PR #13's exact head `8deec1d37f7ac4f9747a4b8d334a21fb10474160`
passed all **1,152** backend tests with disposable PostgreSQL on macOS and Linux
(96.38s / 94.70s). Frontend: **33 tests**, plus typecheck, passed locally. These
results did not reproduce the hosted stall and do not substitute for required CI.
The old hosted runs exceeded their process deadline and did not respond promptly
to cancellation. Their downloaded run-log archive was empty, so an application
deadlock/root cause cannot honestly be asserted from those runs.

Backend CI now retains unbuffered test output as an artifact, retains its process
and job limits, and runs once per PR head instead of duplicating push and PR
backend suites. Fresh heads do not queue behind an unresponsive concurrency group. No existing test was removed or skipped.
PR #13 must remain unmerged until its current checks complete successfully.

Correction verification (isolated infrastructure only):

- **1,196 backend tests passed** on Linux with disposable PostgreSQL 17 in 102.96s.
  The full earlier PostgreSQL 16 correction run passed 1,194 tests before two further
  safety cases were added. No original test was removed or skipped.
- After the final catalog/identity changes, **78 targeted tests passed**, covering
  migration preflight, PostgreSQL resume sync, database safety and health boundaries.
- **33 frontend unit tests**, typecheck, production build, and **6 Chromium browser
  journeys** passed. Browser tests used the actual FastAPI process and isolated
  fictional SQLite fixtures, including encrypted resume review and client-secret checks.
- All backend workflow lint/security checks, offline demo/smoke and migration plan
  passed locally. The non-root production image built; startup without a configured
  database failed before accepting work. Secret scanning passed using only explicit
  allowlists for fictional test passwords.
- Resume infrastructure tests recreate the pool and retrieve/decrypt/checksum the
  pending version, retain profile facts, verify rollback/idempotency/concurrent
  approval, and reject a direct private-resume SELECT as the `anon` database role.

[PR #13](https://github.com/karanagg166/automated-apply/pull/13) latest investigated head:
`051e10c`.
[Backend CI](https://github.com/karanagg166/automated-apply/actions/runs/39407671377)
remains unverified;
[frontend CI](https://github.com/karanagg166/automated-apply/actions/runs/39407671366)
passed. GitHub's job-log endpoint returned `404 BlobNotFound` for cancelled backend
jobs, and their run-log archive was empty. The exact hosted stall cause remains
unproven; diagnostic changes must not be described as a verified root-cause fix.

Required owner actions: confirm the exact isolated project and authority; approve
restoration or restore it personally; provide its supported connection through the
approved secret store; authorize read-only schema/backup review; then approve the
exact migration/grant scope. Restoration approval alone never authorizes SQL or
resume writes. See [the acceptance procedure](online-postgresql.md).
