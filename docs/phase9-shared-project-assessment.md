# Phase 9 assessment — jyzjgoniuwexvipbbpwa

Assessment date: 2026-10-20. Outcome: **NO-GO — exact external access blocker**.
Database classification: **DATABASE_UNVERIFIED**.

This is an audit and proposed deployment plan. It is not activation, migration,
backup, candidate import, or acceptance evidence. The sole intended project is
`jyzjgoniuwexvipbbpwa`; no other project was activated or selected.

## Verified evidence

`git fetch origin main` succeeded. Both HEAD and origin/main are
`81308a23277bf04ba558cbddd0a35bb56a683cd6`. No application code or historical
migration was changed by this assessment. The accompanying assessment SQL is a
local review artifact and has not been run on Supabase.

| Area | Actual observation |
| --- | --- |
| Connector access | `supabase_get_project(id="jyzjgoniuwexvipbbpwa")` returned permission denied |
| Local account | Supabase CLI 2.119.0 `whoami --output-format json` returned an invalid/expired-token authentication error |
| Name, account, organization, application, region, ACTIVE status | Unknown; neither Exam Arena nor Search Sphere association is established |
| Database identity, version, TLS, schemas, runtime identity | Unverified; no target connection credential is available |
| Capacity, existing workload, storage headroom, backups | Unverified |
| Local configuration | Root and backend environment files contain SQLite URLs, not this project's PostgreSQL connection; Supabase URL fields are empty |
| Secret preservation | Existing environment contents and encryption keys were not replaced or rotated |
| Read-only runtime check | `backend/venv/bin/python -m backend.scripts.check_database --env-file backend/.env` exited 2 with `actual_connection_verified=false`, `ddl_executed=false`; unsafe local configuration is rejected |
| Remote SQL / remote DDL / grants | None executed |
| Backup export / restore rehearsal of target data | None performed |
| Genuine resume / current checksum | Not downloaded or imported; the historical checksum is not current-version evidence |
| Profile approval | Pending; no candidate facts approved or activated |
| Online discovery / matching / packet | Zero observations stored by this assessment; no genuine match or packet prepared |
| Existing application regression | Not verified; no remote writes were made |
| Sending / applications / paid operations | Zero messages, submissions, or paid operations initiated |

The application paths were inspected: PostgreSQL boundary/session/readiness,
operations preflight/onboarding/pilot, resume source/download/storage/review,
Next.js owner authentication, CSRF and server gateway, and the requested release
and setup documents. Existing secure synchronization and onboarding are reused.
No live application was started with a fixture database for acceptance.

## Exact migration audit

Every checksum below matches both the committed file and
`backend/app/operations/migration_manifest.json`. All eleven files were read.

| File | SHA-256 |
| --- | --- |
| 001_initial_schema.sql | `331b1123dcc4ac1404be9ba8b13689982a63759d767adc9619ab7a549b9dd78b` |
| 002_candidate_profile.sql | `8139de9c798942ddcecc91a928087aaebd422562ce1cda24ba7fb28492a76a65` |
| 003_candidate_resources_and_answer_drafts.sql | `6e17368f8b27f64c09bdaccc0d4a36453c70653ac65d03721638311b51254319` |
| 004_job_discovery.sql | `8794f0da1c31684af47242eae33e94b4902b7a2541ac5f2ef61f8422f04c9a80` |
| 005_contact_enrichment.sql | `18aaccc7a80c62248a3570cc042a3b8d439bbdb5c87ff396b8b41ddf4109994d` |
| 006_mcp_gmail_outreach_foundation.sql | `70bb7a29fecdfc8a50a06b6d1d4777e1fce1988f8efcf70ecb320de29968752a` |
| 007_gmail_sending.sql | `7ff922da91d1e3959ded89ac7d5123d485394d1bf35392a62306e043421920d7` |
| 008_application_preparation.sql | `1f2b7b6411c8f346328259df37c954349ce6cc0d24b94b284c1a3c92566183ce` |
| 009_live_startup_intelligence.sql | `381a8943dca0af33ecb80e621a8b6be202780c7fd7d574958cc30d3b509d3bd5` |
| 010_phase7_owner_dashboard.sql | `23aab09f5f5e45c9cd099ce2dba52eb800d4e48c09fcda552eaf12c75075d97c` |
| 011_drive_resume_sync.sql | `191b947d1b6a8eedc54a159634959ea0967123fcbda8aaf99678ae0a9ed32439` |

| Migration | Objects and security findings |
| --- | --- |
| 001 | Seven core tables and indexes, all in `job_agent`. No explicit transaction, RLS, client revocations or runtime grants. Four of these tables still lack RLS at the end of 011. |
| 002 | Candidate profile and version function/trigger, RLS, PUBLIC/anon/authenticated table revocations. No service-role DML grant. |
| 003 | Resources, evidence, answer drafts, LLM usage and update triggers. RLS and client table revocations; no service-role DML grant. |
| 004 | Additive job columns/indexes and five discovery tables. RLS/client revocations cover new tables, not legacy jobs/companies. |
| 005 | Contacts and four enrichment tables gain RLS, client revocations and conditional shared `service_role` CRUD grants. |
| 006 | Gmail accounts, OAuth state and outreach draft guards. RLS and shared `service_role` CRUD grants include encrypted OAuth credentials. |
| 007 | Send confirmations/attempts and immutable transition guards; replaces the scoped 006 draft function. Shared service role has SELECT/INSERT/UPDATE on send audit tables, no DELETE. |
| 008 | Packets, fields and append-only application history; scoped invoker triggers preserve revisions/submission evidence. Shared service role has SELECT/INSERT on history and additionally UPDATE on packets/fields. |
| 009 | Four startup/provider tables; replaces only the `company_snapshot_guard` trigger in `job_agent`. Shared role has SELECT/INSERT/DELETE; UPDATE only on checks/windows. |
| 010 | Private encrypted resumes, notifications, preferences and delivery state. RLS/client revocations; shared service-role CRUD includes resume bytes. |
| 011 | Three resume sync/version/review tables and a candidate profile column. Drops/replaces exactly two resource CHECK constraints within `job_agent`; validates existing rows and takes table locks. Plain CREATE TABLE/ADD COLUMN are intentionally not replay-safe. Shared service-role CRUD includes encrypted reviews. |

The committed reference contains **39 tables, 492 columns, 233 constraints,
106 indexes, 10 functions, 15 triggers, zero policies and 90 direct service-role
table privileges**. RLS is disabled on `companies`, `jobs`, `api_keys_pool`, and
`provider_usage_logs`; the other 35 tables enable it. Those four legacy tables
have no explicit PUBLIC/client revocations anywhere in 001–011. Actual inherited
or creator-default grants must therefore be inspected, not assumed absent.

All created tables, altered tables, index target tables, functions, triggers and
foreign keys are scoped to `job_agent`. Index names are unqualified as PostgreSQL
requires; their qualified target table determines their schema. All ten final
functions are invoker functions with `SET search_path=pg_catalog`; trigger calls
and application-table references inside them are qualified. Built-ins including
`gen_random_uuid`, `now`, JSON functions and `format` are unqualified. Confirm
catalog built-in resolution under a fixed migration search path and the actual
server version. The chain uses `CREATE OR REPLACE TRIGGER`, so version support
must be established before execution. No extension installation is in the chain;
verify built-in UUID support and `plpgsql` availability.

No DROP SCHEMA, DROP TABLE, role creation, role membership, database alteration,
cross-schema foreign key, SECURITY DEFINER or global default-privilege changes
appear in these files. The scoped trigger/constraint replacements above are the
destructive DDL to review. No existing application object is explicitly targeted.
Target DDL event triggers, conflicting `job_agent` objects and existing default
privileges can still change that outcome. There is no durable historical migration
ledger in 001–009; the catalog manifest is compatibility evidence only.

Schema USAGE/CREATE, function EXECUTE and future default privileges are not
hardened by this chain. Functions normally receive PUBLIC EXECUTE by default.
Runtime connections set `search_path=job_agent,public`; this is not access control.
Do not change the manifest to make a mismatching target look compatible.

## Read-only assessment and state decision

[Reviewed assessment SQL](sql/phase9-project-assessment.sql) collects identities,
TLS server-leg evidence, capacity aggregates, schemas/object names, roles,
memberships, defaults, effective table/column/sequence/function privileges,
extensions, event triggers and the `job_agent` catalog. It reads no application
records and encloses the queries in a read-only transaction ending in ROLLBACK.
It requires the owner's separate inspection approval and a verified endpoint.
Do not relabel the shared database as isolated staging to bypass existing CLI pins.

Record external metadata separately: exact dashboard project/account/org/region,
application association, exposed Data API schemas, compute/disk quotas, pooler
limits and backups. SQL cannot prove a dashboard project identity. A pooler's
`pg_stat_ssl` row does not prove client-to-pooler TLS; preserve the certificate
and hostname checks from the configured SSLContext as separate evidence.

Decision after inspection:

- `JOB_AGENT_ABSENT`: namespace absent, no relevant conflicting dependencies.
- `JOB_AGENT_EMPTY`: namespace present, no application-owned objects, compatible
  ownership/ACLs. Zero tables alone is insufficient; inspect functions/types too.
- `JOB_AGENT_COMPATIBLE_001_010`: compare against a disposable reference built
  with the exact first ten files, including pre-011 constraints/profile columns.
- `JOB_AGENT_COMPATIBLE_001_011`: complete catalog and privilege comparison passes.
- `JOB_AGENT_PARTIALLY_MIGRATED`: identifiable subset, missing or changed expected
  objects; produce an object-by-object reconciliation and stop before DDL.
- `JOB_AGENT_SCHEMA_CONFLICT`: unrelated objects, ownership or incompatible
  definitions; do not reuse or overwrite them.
- `DATABASE_UNVERIFIED`: identity/access/catalog evidence unavailable (current).

For absent/empty only, propose 001–011 in dependency order; for compatible 010,
011 only; for compatible 011, no historical replay. Existing explicit BEGIN/COMMIT
in 002–011 mean `psql --single-transaction` is not an atomic wrapper for the whole
chain. Set ON_ERROR_STOP, bound lock waits, stop at first failure, and re-inspect
after any partial commit. Never use schema deletion as automatic rollback.

## Proposed runtime role and grants — not approved or applied

Prefer a new NOLOGIN owner and an independently authenticated runtime role with
no ownership, role memberships, admin privileges or RLS bypass. Verify these
names are unused cluster-wide before creation. Do not reuse existing app logins.
The following is a design for an absent/verified-empty application namespace;
existing objects require a separately enumerated ownership/reconciliation plan.

```sql
-- PROPOSAL ONLY: requires target inspection, recovery proof and exact approval.
CREATE ROLE job_agent_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION NOBYPASSRLS;
CREATE ROLE job_agent_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 3;
CREATE SCHEMA job_agent AUTHORIZATION job_agent_owner;
REVOKE ALL ON SCHEMA job_agent FROM PUBLIC, anon, authenticated, service_role;
GRANT USAGE ON SCHEMA job_agent TO job_agent_runtime;
-- These global defaults affect ONLY a newly created dedicated owner, never postgres.
ALTER DEFAULT PRIVILEGES FOR ROLE job_agent_owner
  REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER ROLE job_agent_runtime SET search_path = pg_catalog, job_agent;
ALTER ROLE job_agent_runtime SET statement_timeout = '30s';
ALTER ROLE job_agent_runtime SET lock_timeout = '2s';
ALTER ROLE job_agent_runtime SET idle_in_transaction_session_timeout = '30s';
```

Passwords are deliberately absent. Enable LOGIN only after setting its password
through a protected administrative prompt/secret-store operation. Migration
administration must explicitly SET ROLE to the dedicated owner; any administrative
membership needed for that is separately reviewed. Never grant it to runtime.

After the required historical files, a reviewed additive hardening transaction
would use exactly the following 39-table allowlist. `SI` means SELECT/INSERT;
`SIU` additionally permits UPDATE. No runtime DELETE, TRUNCATE, REFERENCES,
TRIGGER, schema CREATE, ownership or grant option is proposed for this pilot.
Retention and destructive maintenance remain separate operator work.

| Rights | Exact `job_agent` tables |
| --- | --- |
| SI | `application_events`, `application_submission_evidence`, `company_source_observations`, `drive_resume_versions`, `provider_usage_logs`, `startup_shortlist_entries` |
| SIU | `api_keys_pool`, `application_answer_drafts`, `application_packet_fields`, `application_packets`, `candidate_evidence`, `candidate_profiles`, `candidate_resources`, `companies`, `connected_accounts`, `contact_enrichment_runs`, `contact_evidence`, `contact_identities`, `contact_provider_lookups`, `contacts`, `discovered_company_people`, `discovery_budget_reservations`, `discovery_monthly_budgets`, `discovery_runs`, `job_source_observations`, `jobs`, `llm_monthly_usage`, `notification_deliveries`, `oauth_states`, `outreach_logs`, `outreach_send_attempts`, `outreach_send_confirmations`, `owner_notifications`, `owner_preferences`, `private_resumes`, `provider_access_windows`, `provider_connection_checks`, `resume_drive_sources`, `resume_profile_reviews` |

For EACH explicitly allowlisted table, the intended SQL is:

```sql
-- Substitute one reviewed identifier from the table above, never an external input.
ALTER TABLE job_agent.<table> ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_agent.<table> FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE job_agent.<table> FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT ON TABLE job_agent.<table> TO job_agent_runtime;
-- Only the SIU group:
GRANT UPDATE ON TABLE job_agent.<table> TO job_agent_runtime;
CREATE POLICY job_agent_runtime_access ON job_agent.<table>
  FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true);
```

The true predicate permits this one backend principal to manage the single-owner
application's rows; clients receive neither schema/table access nor a policy.
ACLs limit permitted commands, including append-only tables. Existing immutable
history/version triggers remain intact. Remove any existing column-specific
grants and unexpected policy or inherited access only after inspecting and
approving their exact sources. The placeholder SQL is intentionally not executable
and is not a finalized target migration.

Revoke shared/client/PUBLIC EXECUTE and grant only runtime EXECUTE on these ten
zero-argument trigger functions, all in `job_agent`:
`application_append_only`, `application_field_guard`, `application_history_guard`,
`application_packet_guard`, `candidate_profile_version`, `company_snapshot_guard`,
`phase2a_updated_at`, `phase4a_draft_guard`, `phase4b_attempt_guard`,
`phase4b_confirmation_guard`. No sequences are required by the current UUID schema.
Schema ownership remains with the NOLOGIN owner; administrators retain managed
platform access. Do not promise cryptographic isolation from database admins.

**Current software compatibility gate:** `operations/migrations.py` rejects any
additional policy, expects the old direct service-role grants and four non-RLS
tables. `operations/health.py` accepts only owner/superuser/BYPASSRLS access and
requires some DELETE/UPDATE rights outside this pilot's proposed scope. Thus the
preferred role plan will deliberately fail current readiness. A focused additive
deployment contract, strict policy/role/grant validation and PostgreSQL regression
coverage must be implemented and pass CI before activation with this plan. Do not
weaken readiness, edit historical checksums, grant ownership/BYPASSRLS, or execute
this draft just to get a green probe. This work is pending verified target access
and agreement on the actual role/capacity constraints.

**Shared-project limit:** PUBLIC privileges cannot be denied to one PostgreSQL
role with an individual REVOKE or NOINHERIT. Supabase documents inherited PUBLIC
access, including possible pg_net queue access and public functions. Inspect
column grants, views, SECURITY DEFINER entry points and role memberships too.
If those privileges expose the older app, strict isolation may require changing
its shared ACLs; that conflicts with this task's preservation requirement. Stop
and present the exact conflict rather than changing unrelated objects or silently
accepting the risk. No shared-project risk has been accepted here.
[Supabase effective-privilege guidance](https://supabase.com/docs/guides/troubleshooting/custom-role-inherits-privileges-that-were-not-explicitly-granted-ddaa1c).

## Recovery, capacity and unchanged-application proof

Recovery is a prerequisite, not established evidence. Inspect the exact plan's
available backups and retention. Free-plan managed backups/PITR and downloadable
physical backups must not be assumed.
[Supabase backup documentation](https://supabase.com/docs/guides/platform/backups).

If a manual export is necessary, obtain separate approval covering unrelated
application data, encrypted destination, retention, backup identity and isolated
restore target. Use a matching/supported pg_dump version and a protected libpq
service/pgpass with verify-full TLS. Require an approved encryption tool/recipient
(neither `age` nor `gpg` was found locally). Stream the dump into encryption with
pipeline failure detection; never leave the plaintext dump described in the older
staging example. Use umask 077, mode-0700 directories and mode-0600 artifacts;
preserve the immutable original encrypted backup and record its hash. Back up
resume/OAuth/Vault keys, required roles/ACLs and configuration separately without
printing passwords. Database dumps do not include Supabase Storage file bytes;
assess separate object backup needs for the older application.

Restore only a decrypted stream/copy into an approved isolated local PostgreSQL
instance with matching extensions and stub external integrations. Do not use
production network credentials for running restored application code. Disable
cron/network workers before exposing the restore to outbound networking. Verify
objects, ownership, ACLs, constraints, agreed counts/integrity and key recovery
without exposing records; capture elapsed time and acceptable recovery point.
Record omissions and failed restores as blockers. Never rehearse against live.
No backup or target-data restore has been performed in this assessment.

Before and after approved deployment, compare a protected catalog snapshot of
non-`job_agent` schemas, columns, indexes, constraints, triggers/functions, owners,
RLS/policies, role memberships, defaults and grants, plus exposed API schemas.
Observe an owner-approved read-only health path for the older app. Do not alter
its records to test availability. Include enabled DDL event triggers in the impact
review. A source-code audit cannot establish the older app's actual regression.

Proposed pilot ceiling, subject to measured headroom: **one FastAPI process,
DB_POOL_SIZE=1, DB_MAX_OVERFLOW=0**, no resume scheduler, and at most one separate
bounded operator connection at a time. Count Next.js-to-FastAPI traffic as using
that same backend pool. Reserve administration/backup and existing-app peak
connections before approval; role connection limit 3 is a ceiling, not available
capacity. Do not change shared Supavisor limits, compute or storage plans.
Database size does not reveal remaining storage: collect actual dashboard quota,
WAL/disk metrics, workload history and pooler usage. Suitability remains unknown.

## Access and remaining owner decisions

1. Run `supabase login` locally as the account authorized for
   `jyzjgoniuwexvipbbpwa`, or reconnect the Supabase connector with that account.
   Verify `supabase whoami --output-format json` and
   `supabase projects list --output-format json`. Do not paste tokens into chat.
2. Explicitly authorize read-only catalog assessment for this exact shared project.
   Obtain the exact supported direct/session URL and CA from its Connect panel.
   Supply an ignored mode-0600 `backend/phase9.private.env`, or the approved secret
   store, and disclose only its path. A management token is not a database password.
3. Preserve existing keys/tokens; supply missing backend bearer, owner password hash
   and frontend session secret privately. The inspected frontend file has no owner
   login hash/session secret and backend file has no JOB_AGENT_API_TOKEN. Do not
   blindly run `configure_frontend_owner.py`: it also generates a new resume key.
4. After actual inspection: approve the backup/export and isolated restore scope;
   then review the exact final SQL/checksums, new-role names, catalog diffs,
   recovery evidence and software compatibility changes before authorizing DDL.
5. Separately approve encrypted import of file `1ar4M8w5mTvb6yCCjjDQ5LbkTQEyVyfQ6`
   into this target, with facts pending and automatic synchronization disabled.
   Historical checksum:
   `cfc0d859eafdf99094ed643791b9532006fdf70199191d88f624f5cb3e824d6c`.
6. Review the actual PDF facts in My Profile; resolve conflicting professional
   links explicitly. Confirm proposed roles (Backend/Python/Software/Full Stack/AI
   Engineer), India/Delhi NCR/Bengaluru/Hyderabad/Pune/India-eligible remote,
   Python/FastAPI/PostgreSQL/Redis/React/Next.js/TypeScript/Node.js/Docker/LLM/RAG,
   and preference for evidenced 2–10/11–50-person technology companies. Then
   authorize a bounded public-source pilot; identify any approved Greenhouse boards.

The private backend file should preserve the actual URL components and contain
`ENVIRONMENT=development`, `DATABASE_SCHEMA=job_agent`, `DB_REMOTE_ONLY=true`,
`DB_REQUIRE_TLS=true`, `DB_SSL_ROOT_CERT=` (or the verified CA path),
`DB_ECHO=false`, the proposed pool limits, `RESUME_DRIVE_SYNC_ENABLED=false`,
`RESUME_DRIVE_SYNC_INTERVAL_HOURS=24`, and
`RESUME_DRIVE_SYNC_REQUIRES_REVIEW=true`. Use `postgresql+asyncpg://` with no query
parameters; no guessed host, user, database or region, no transaction port 6543,
no credentials in NEXT_PUBLIC variables. Reuse `check_database --env-file` only
as an actual read-only probe; it cannot make missing schema or policy changes.

After all gates pass, reuse Sync Now, verify decrypted checksum and pending review,
restart FastAPI and retrieve the same version through the real authenticated
Next.js gateway. Verify readiness/TLS, owner session/CSRF, private PDF retrieval,
dashboards, filters, notifications, connection statuses and no client secrets.
Only after owner profile approval run the existing bounded source adapters,
persist evidence online and prepare a reviewable packet with Not Applied status.
No sending, paid enrichment or automatic submissions are authorized.

## Local validation

Executed against a new disposable localhost-only PostgreSQL **16.15** container:

- `test_database_safety.py` and `test_migration_preflight.py`: **58 passed in
  3.94 seconds, no skips**, including the PostgreSQL catalog/drift/read-only test.
- Independently applied all eleven unchanged SQL files locally; the resulting
  catalog matches the committed manifest and confirms the four non-RLS tables.
- Executed `phase9-project-assessment.sql` with ON_ERROR_STOP on both an empty
  database and the complete 39-table catalog, including the proposed runtime role
  in privilege inspection. Both completed successfully and ended with ROLLBACK.
- The existing check_database command rejects the actual local SQLite environment
  before any database access. No genuine local records were used for these checks.
- Secret scan of the two new review artifacts found zero findings. The disposable
  test container was stopped/removed after verification; no test service remains.

Assessment SQL SHA-256:
`d7365fe4edf58cce2731980d3ccf04d2b95362acfbd27e146025b3edbc0a0d98`.

Disposable PostgreSQL and fictional safety tests do not establish Supabase access,
target backups, remote TLS or genuine onboarding. Full release counts in
`release-ci-evidence.md` remain historical. No application code changed, so the
full backend/frontend, browser, build, Docker and hosted CI suites were not rerun
for this assessment. A future implementation change requires the complete checks
requested for Phase 9 before merge, followed by genuine online acceptance.


## Linked-target follow-up — 2026-10-20

Historical evidence above is preserved. For the current linked target, successful live catalog inspection, the CLI login-role safety incident, local fixes/tests and exact unexecuted activation SQL, use [the live activation review](phase9-live-activation-review.md). Its target/status supersede older access assumptions. No historical approval is transferred from the abandoned target.
