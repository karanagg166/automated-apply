# Drive resume sync and PostgreSQL release verification — 2026-10-20

This release combines PR #13's encrypted Google Drive resume synchronization with
PR #14's PostgreSQL-only real-data persistence and fail-closed readiness. Online
activation is separately gated; no cloud restoration, remote SQL, deployment or
owner-data import was performed.

## Integration boundary

Starting main: `bb8acc51a0bb5d3edbf165ee3be63cf9e9fe93d4`.
PR #13 head: `051e10c867ae927238f6226673f31010cad8b143`.
Original PR #14 head: `4a7a2f30bfa9ec45b39bd7923c30a4788e666f9b`.

PR #13 was made draft to prevent the resume feature being merged without the
persistence correction. PR #14 was retargeted from the feature branch to `main`;
it retains every commit from both PRs, plus the CI corrections below. Both complete
workflows run on its main-targeting pull request. Use a merge commit after all
current-head checks pass, then verify both workflows on the resulting main commit.
Do not merge #13 independently. Main has no configured branch protection; the
absence of a required-check policy is never permission to bypass either workflow.

## Stall investigation and bounded correction

The original [backend run 39407671377](https://github.com/karanagg166/automated-apply/actions/runs/39407671377)
started the regression step at 10:24:49 UTC. On cancellation at 10:59:09, GitHub
still reported that step in progress, beyond the six-minute process limit,
eight-minute step limit and thirty-minute job limit. Container initialization and
all preceding lint/security steps had succeeded. No concurrency group remained in
that workflow. The job log endpoint returned 404, the run archive was an empty ZIP,
and the artifacts list was empty. These observations did not prove a database,
subprocess or application deadlock.

Instrumentation commit `dd030092ee4b94684efb9e713fe46f8c7db9b3cf` retained the entire
suite in its original order. The supervisor uses a separate process group, regular
files for child output, a six-minute deadline, TERM/KILL cleanup, thirty-second
process snapshots without command arguments/environment values, and JUnit output.
The workflow records the disposable PostgreSQL container and connection state and
uploads diagnostics even after a failed test step, with a seven-day retention.
Its [hosted run](https://github.com/karanagg166/automated-apply/actions/runs/39412712041)
again remained in the regression step while the corrected run below completed.

The new oversized-PDF parametrization used its entire **5 MiB** input as its pytest
ID. Local verbose execution produced a single **5,242,984-byte** result line. The
pre-existing PDF upload tests already had explicit short IDs for this reason.
Commit `5fab1a01fdb8056e6c539f70a7b0893c79bdd991` gives the three new PDF cases
short IDs without changing their payloads, assertions or coverage. It also makes
optional process snapshots tolerant of missing `ps` in minimal local containers;
the hosted runner has `ps`, and its retained snapshots were populated.

On that commit, [complete Backend CI](https://github.com/karanagg166/automated-apply/actions/runs/39413036754)
passed: regression 11:10:54–11:13:00 UTC, whole job completed 11:13:52 UTC. Its
downloaded artifact `backend-regression-39413036754-1` (ID `12259284880`, 50,631 bytes)
contains **1,201 tests, zero failures/errors/skips**, JUnit time 122.830 seconds,
supervisor exit 0, elapsed 125.88 seconds, and maximum test-output line 257 bytes.
The final PostgreSQL snapshot had no remaining application/test connections: only
background server processes and the diagnostic query connection remained.
[Complete Frontend CI](https://github.com/karanagg166/automated-apply/actions/runs/39413036245)
also passed on the same head.

This comparison strongly implicates oversized pytest output as the hosted stall
trigger. GitHub's internal runner/log-transport failure mechanism remains unproven:
the stalled runs supplied no usable test log or stack. Do not describe this as an
identified application deadlock, pool leak, PostgreSQL socket failure or general
GitHub outage. GitHub cancellation behavior is documented in the
[workflow cancellation reference](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-cancellation).

## Complete verification

No existing regression test or assertion was removed. Five supervisor tests cover
success/failure exit preservation, log retention, inherited child output, timeout
failure and an unavailable optional diagnostic utility.

| Check | Verified result on corrected source |
| --- | --- |
| Hosted backend, Python 3.11 / PostgreSQL 16 | 1,201 passed; no skips; complete workflow successful |
| Local macOS, Python 3.11 / disposable PostgreSQL 16 | 1,201 passed in 87.53 seconds |
| Local Linux, Python 3.11 / disposable PostgreSQL 17 | 1,201 passed in 94.62 seconds |
| Focused resume and supervisor checks | 40 passed |
| Frontend unit suite | 33 passed |
| Actual FastAPI + Next.js Chromium journeys | All 6 passed locally and hosted, fictional isolated data only |
| Migration and concurrency checks | All 001–011 verified, including resume deduplication/concurrent approval, restart persistence, rollback, grants/RLS and direct anon SELECT rejection |
| Ruff / Bandit / secret scanning | All backend workflow checks passed locally and hosted |
| Formatting / API contract | Frontend Prettier passed; new CI files passed Ruff format; regenerated API types unchanged |
| Frontend | Typecheck, production build and dependency high-severity audit passed; zero audit vulnerabilities |
| Images | Backend and frontend built locally and hosted; non-root runtime checks and standalone frontend boundary checks passed |
| Runtime database rejection | Actual backend container exits before readiness for missing configuration and development SQLite |
| Actual TLS handshakes against disposable PostgreSQL | Untrusted certificate rejected; hostname mismatch rejected; trusted matching certificate accepted and server confirmed TLS/database identity |

The local runs used separate disposable PostgreSQL instances. Local results are
independent evidence and never substitutes for GitHub-hosted CI. TLS handshake
verification used an ephemeral local test CA; it does not establish the identity,
certificate or reachability of an online Supabase project.

Review covered the complete combined application, migrations, API/types, UI, test,
configuration and documentation diffs. Real execution requires explicit asyncpg
PostgreSQL, verified remote TLS, the `job_agent` catalog and runtime permissions;
failed startup cannot select SQLite. The API and worker share those checks.
Resume PDFs and extracted review snapshots are encrypted; source generations,
profile versions, locks and unique checksums protect reviews and retries. Browser
roles cannot read private tables, and the Next.js gateway keeps backend/database
credentials server-side. No genuine local database, environment file or encryption
key was modified. CodeRabbit CLI was signed out; review was performed directly.

## Separate owner activation gates

Read-only project metadata discovery on 2026-10-20 still reports
`lsvzmrzzhbegdmtayrpw`, `apply-bot-db`, `us-east-1`, **INACTIVE**. Metadata access
does not select or authorize the database. Actual online connection, schema/grants,
backups, migrations, encrypted resume synchronization and candidate activation are
unverified. No worker has been deployed or left running by this work.

Each operation requires its own explicit owner approval:

1. Select this exact project as the canonical database and confirm ownership and
   isolation from unrelated data. A project name is insufficient.
2. Restore this exact inactive project, or have the owner restore it personally.
3. Authorize read-only assessment of its actual schema, permissions and backup
   metadata. Backup creation or a restoration rehearsal is a separate write scope.
4. After assessment, approve exact migration files/checksums and runtime permission
   changes. An empty schema may need 001–011; compatible 001–010 may need 011 only.
   Actual SQL/grants cannot be finalized before inspection. Do not replay migrations
   on an unidentified/partial schema or grant private tables to browser roles.
5. Authorize encrypted resume and candidate-record import, preserving the original
   encryption key. Keep extracted facts pending until a separate owner review.

Selection authorizes none of operations 2–5. Restoration authorizes no SQL or
candidate writes. See [online PostgreSQL activation](online-postgresql.md) for the
connection, backup, migration and end-to-end acceptance procedure.
