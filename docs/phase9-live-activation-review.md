# Phase 9 live activation review — linked project

Recorded 2026-10-20T15:58:24.766695+00:00. Target: **jyzjgoniuwexvipbbpwa only**.
Repository `main`, HEAD `81308a23277bf04ba558cbddd0a35bb56a683cd6`.
**NO-GO for execution until the recovery, credential and owner-approval gates below.**
This review supersedes prior target/access assumptions; earlier evidence is preserved.
It does not authorize remote mutations or activate the rest of Phase 9.

## A. Actual target status

| Check | Result |
| --- | --- |
| Correct Supabase project | **YES**; CLI project list and local project-ref agree |
| Local link | **VERIFIED**; no relink, restore, new project or upgrade |
| Organization | `kzjssaxtcilclvpncosv`, CLI name `search-sphere`; this is hosting metadata, not a claim that this repository is Search Sphere |
| Region/status | `ap-northeast-2` (Seoul), `ACTIVE_HEALTHY` |
| Remote database access | **VERIFIED through authenticated Management API SQL**; backend direct/session-pooler authentication remains **BLOCKED** by missing private DSN/password |
| Database identity | `current_database()=postgres`, `current_user=session_user=postgres`, PostgreSQL **17.6**, build metadata **17.6.1.166** |
| Remote TLS | **UNVERIFIED end-to-end for the backend**; API SQL server leg observed TLSv1.3, TLS_AES_256_GCM_SHA384, 256 bits |
| Existing unrelated application | **YES**, populated public application tables and separate migration history |

Target identity depends on the authenticated project-specific API route plus CLI control-plane evidence, not the generic database/role name or shared pooler hostname.
Cached session-pooler endpoint uses port 5432 and a username containing the approved reference; it contains no password. Neither existing `.env` supplies an approved PostgreSQL URL. CLI auth is not a persistent backend database credential.
Default TLS validation was not disabled. No direct-runtime certificate/hostname verification claim is made from `pg_stat_ssl`, which shows only the server leg.

## B. Actual catalog and migration compatibility

**Case A — schema absent**, not an access-denied inference. Administrator catalog inspection returned `job_agent_exists=false`, no namespace dependencies and zero objects in every `job_agent` catalog category.
There is no `job_agent` migration ledger or `supabase_migrations` namespace. `public.alembic_version` belongs to the other app; its contents were not queried.

[Additional administrator-capability inspection](sql/phase9-administrator-capabilities.sql) reconfirmed transaction_read_only=on, job_agent absent and both proposed role names unused. Database owner is postgres; the authenticated administrator has CONNECT/CREATE and plpgsql USAGE, and the built-in gen_random_uuid resolves. PUBLIC inherits CONNECT/TEMPORARY, but not database CREATE; those shared base privileges are preserved. Temporary tables owned by the runtime and PostgreSQL catalogs remain outside the private application-schema restriction. Runtime readiness explicitly rejects database CREATE. The CLI login role had valid_until 2026-10-20 15:49:26.950167+00 (already past at the 16:04 UTC final check); no credential/role cleanup was attempted.

The nine non-system schemas are `auth`, `extensions`, `graphql`, `graphql_public`, `pgbouncer`, `public`, `realtime`, `storage`, `vault`.
The non-system relation inventory contains 58 tables/views/sequences: auth 28, extensions 2, public 14, realtime 4, storage 8, vault 2.
The public schema contains **12 tables and two sequences**. Tables: `alembic_version`, `conversations`, `document_collections`, `document_contents`, `documents`, `external_document_contents`, `external_documents`, `feedbacks`, `medical_observations`, `messages`, `service_clients`, `users`.
The sequences are `document_contents_id_seq` and `external_document_contents_id_seq`.
Nonzero `pg_stat_user_tables.n_live_tup` estimates establish existing data without selecting application rows. These are estimates, not exact counts or backup integrity evidence.

Migration compatibility: **PARTIAL (local files verified; live schema missing)**.
All eleven committed checksums match the manifest. The absent schema lacks the complete expected **39 tables, 492 columns, 233 constraints, 106 indexes, 10 functions and 15 triggers**. The historical contract also records zero policies and 90 service-role privileges. The proposed explicit restricted-role overlay replaces those security expectations without rewriting historical files/manifest.
The saved comparator reports `empty_schema`, 985 missing expected catalog entries and no conflicting definitions. This does not imply any historical file executed.

| Migration | SHA-256 (verified unchanged) |
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

Reviewed effects by file:

1. 001 creates `job_agent`, seven core tables/indexes; no explicit transaction/RLS.
2. 002 adds candidate profile, constraints, version function/trigger, RLS/client revocations.
3. 003 adds resources/evidence/answer drafts/LLM accounting and update triggers.
4. 004 adds job fields, discovery observations/people/budgets and indexes.
5. 005 adds contact enrichment/evidence/identity tracking and service-role grants.
6. 006 adds encrypted account/OAuth state and outreach draft guards/grants.
7. 007 adds send confirmation/attempt state and immutable transition guards.
8. 008 adds packets, fields, append-only events/evidence, review/submission guards.
9. 009 adds startup snapshots/shortlists/provider state, replaces its scoped trigger.
10. 010 adds encrypted private resumes and owner notification/preference state.
11. 011 adds Drive sources/versions/encrypted reviews, a profile column, and replaces two resource CHECK constraints. It is not replay-safe.

All application relations, foreign keys, functions and target index tables are scoped to `job_agent`. No extension install, unrelated-schema DDL, role provisioning or cross-schema FK is in 001–011. All ten final functions are invoker functions with fixed `pg_catalog` search paths and qualified app references. PostgreSQL 17 supplies built-in UUID generation and CREATE OR REPLACE TRIGGER support. Installed extensions: plpgsql 1.0, pgcrypto 1.3, uuid-ossp 1.1, pg_stat_statements 1.11, supabase_vault 0.3.1. No extension change is proposed.

## C. Security and isolation

The four historically non-RLS tables are exactly **companies, jobs, api_keys_pool, provider_usage_logs**. The other 35 enable RLS without policies. Stock migrations therefore require owner/BYPASSRLS access; granting a restricted role table rights alone is insufficient.

Existing unrelated public tables have broad direct anon/authenticated/service_role grants and RLS disabled. **No correction to these unrelated objects is authorized or included.** This is a separate owner security finding. Their privileges must never be inherited by the new backend role.
Existing postgres/supabase_admin and several platform service roles can bypass RLS; the proposed runtime cannot. A database administrator remains trusted and can override database protections.
Creator defaults grant clients broad privileges for objects created by postgres in public/storage. These shared defaults remain unchanged. New dedicated-owner defaults revoke PUBLIC function EXECUTE only for that new owner. Table defaults for a new role do not grant client access.
PUBLIC table ACLs observed outside system catalogs cover only the two extension statistics views; the new runtime has no extensions-schema USAGE from this plan. Public-schema USAGE alone is not row access. The runtime validator rejects effective access to other app tables, column-only access and callable user-schema SECURITY DEFINER entry points. Managed/platform catalog access remains part of PostgreSQL's trust boundary.

Actual Data API schemas are **public, graphql_public**. Confirmed by CLI `config pull --dry-run` with a sentinel schema in an isolated local config; the explicit remote comparison returned those two schemas, `written=false`. No Auth, Storage, API exposure or infrastructure setting was changed. `job_agent` remains unexposed.

Prepared operational security SQL (not a new schema version; 001–011 and their manifest remain intact):

| Proposal | SHA-256 |
| --- | --- |
| [phase9-role-bootstrap.sql](sql/phase9-role-bootstrap.sql) | `3a1e31371bc5671e56c3965eda21dc89cda7f64debc6add70db2765a8a005b5e` |
| [phase9-runtime-hardening.sql](sql/phase9-runtime-hardening.sql) | `5a7d5d0890ed7a69a1d6c2a4f89ec0fdcc6478e12c737a7f03d5ce4b0964f8da` |
| [phase9-runtime-login.sql](sql/phase9-runtime-login.sql) | `1b7fe9802b984b65134a39911f10d53ab965c82b40aee75b103f478329c6ed99` |

The bootstrap creates previously absent `job_agent_owner` (NOLOGIN) and `job_agent_runtime` (initially NOLOGIN), both NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION/NOBYPASSRLS/NOINHERIT. Runtime connection limit is 3, with no memberships in other roles. PostgreSQL 16+ may automatically grant the creating administrator postgres ADMIN OPTION on the new roles without INHERIT/SET; only this already-trusted administrator is permitted to hold such memberships. A local CREATEROLE probe and the regression fixture verified this behavior. It grants the new owner role to postgres solely for scoped migration ownership management, creates the schema owned by that role and configures runtime timeouts/search path. It does not grant runtime access to postgres, shared Supabase roles, public or other app objects.

Execute 001–011 as the authenticated migration administrator, **not SET ROLE job_agent_owner**: PostgreSQL checks database CREATE for historical 001's CREATE SCHEMA even when the schema already exists. A local test exposed that requirement. The plan avoids a database-wide CREATE grant by transferring ownership of exactly the 39 tables and ten functions in the final hardening script. Index ownership follows table ownership.

Hardening explicitly enumerates each table/function; no ALL TABLES/ALL FUNCTIONS or unrelated-schema changes:

- Enable and FORCE RLS on all 39 tables; retain existing immutable/version triggers.
- Revoke schema/table/function access from PUBLIC, anon, authenticated and service_role within job_agent.
- Schema USAGE only for runtime; no CREATE, ownership, grant option, TRUNCATE, REFERENCES, TRIGGER or MAINTAIN.
- SELECT/INSERT on six append-only tables: application_events, application_submission_evidence, company_source_observations, drive_resume_versions, provider_usage_logs, startup_shortlist_entries.
- SELECT/INSERT/UPDATE on the remaining 33 tables. DELETE only on contact_identities, required by existing privacy/suppression replacement workflows. Other retention/destructive operations remain operator-only.
- One exact policy per table: `job_agent_backend FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true)`. This permits the one trusted backend principal's single-owner rows; ACLs separately restrict commands. It is not a multitenant ownership policy.
- Revoke shared/PUBLIC EXECUTE on the ten invoker trigger functions and grant runtime EXECUTE. No sequences are required by the UUID app catalog.

The SQLAlchemy connector currently supplies search_path=job_agent,public, overriding the role default; pg_catalog is implicitly searched first, ORM/trigger app references are qualified, and runtime cannot CREATE in either application schema. A search path is not an access boundary.

The local readiness fix accepts only that explicit overlay for this exact role name. It verifies no bypass/admin/membership/ownership, all FORCE RLS flags, exact policies/definitions, effective DML allowlists, client/shared grants, column grants, function security and cross-schema access. It does not disable RLS or give runtime administrator privileges. The historical contract still applies to existing historical deployments.

## D. Validation and execution record

Read-only SQL artifact: [phase9-live-catalog-inspection.sql](sql/phase9-live-catalog-inspection.sql), 40 named catalog evidence sections in one BEGIN READ ONLY/ROLLBACK transaction with 15-second statement/2-second lock timeouts. No unrelated row data, query text, secrets or unrelated function bodies were collected.
Private raw evidence is under ignored `reports/phase9-shared-supabase/`, directory mode 0700 and evidence files 0600. The three pre-existing untracked paths, prior reports, existing env contents and all encryption/authentication keys are preserved. The root .env permission was tightened from 0644 to 0600; backend/.env was already 0600. No commit/push/reset/clean occurred.

Commands actually executed include git status/branch/log; installed CLI --version (2.119.0) and relevant --help; projects list, orgs list, backups list for the exact reference; config pull --dry-run in a newly initialized isolated local config; the identity SQL, saved catalog SQL and administrator-capability SQL; offline migration_preflight; check_database with backend/.env; Docker PostgreSQL 17 isolated tests; focused pytest, Ruff, Bandit, compileall and diff checks.
The source/command review consulted current Supabase CLI code, changelog and backup documentation. The connector organization lookup returned permission denied while the local CLI succeeded; no project switching followed.

**Safety incident — CLI preflight:** the first linked identity query printed `Initialising login role...`. CLI source reveals POST `/cli/login-role` with `read_only:false` during connection resolution even though the query itself runs via Management API. This may create/rotate `cli_login_postgres` and its postgres membership outside the read-only SQL transaction; the catalog confirms that role and membership exist. It cannot be distinguished from prior linking state without a before-image. This was not authorized by the inspection request and is disclosed rather than reported as zero remote role mutation. No cleanup/revocation was attempted because that would be another unauthorized mutation.

For the subsequent catalog query, a process-local nonsecret `SUPABASE_DB_PASSWORD=unused-management-api-preflight-placeholder` suppresses that unrelated role-mint preflight; the linked query still authenticates through the existing CLI's Management API credential. It is not used as a PostgreSQL password and proves no direct backend authentication. No further login-role initialization message appeared. A direct API approach was considered, but macOS Keychain retrieval through `security` blocked; those two helper processes were terminated without extracting or exposing the credential. The supported CLI retained its existing credential access.

Remote execution totals: three user SQL requests, all read-only transactions; no application DDL/DML, migration, export, backup, restore, resume download, paid call, email or application submission. Remote application data modified: **NO**. Remote control-plane role side effect: **possible/observed initialization**, as above; not certified absent.

Final focused pytest: **118 passed, zero skipped in 7.73 seconds**, including the PostgreSQL restricted-runtime and historical-catalog checks. The existing resume-sync PostgreSQL verifier also passed. Ruff, Bandit, compileall and git diff --check passed. Failed initial local trials and their corrections are retained in the appended operational report; they are not counted as passes. No frontend suite/build was rerun because no frontend change occurred. Prior 1,201/33/6 results are historical release evidence, not this run's counts.

## E. Recovery and exact execution plan (proposed, unexecuted)

Backup metadata for this exact project: **walg_enabled=true, pitr_enabled=false, backups=[]**, empty physical_backup_data. WAL-G enabled is not proof of an available/recoverable backup. Actual subscription tier, guaranteed retention, storage quota and RTO/RPO are **UNVERIFIED**. The connector cannot read this organization's entitlement. Do not infer Free/paid guarantees from a project name or empty list. Confirm entitlements in the approved project's dashboard; current [backup documentation](https://supabase.com/docs/guides/platform/backups) does not replace project-specific evidence.

Database size at inspection: **14,085,267 bytes**. Server max_connections 60, superuser reserve 3, snapshot six client backends; a snapshot is not older-app peak capacity. Session pooler configuration reports default pool size 15 and max clients 200. Proposed backend settings: DB_POOL_SIZE=1, DB_MAX_OVERFLOW=0, one API process, resume worker/scheduler off. Leave the shared server/pooler settings unchanged; measure older-app peaks before enabling additional workers.

No authenticated-encryption export tool (`age`, `rage`, `gpg`) is installed. No encrypted backup or source-data restore rehearsal exists. Approximately 15.8 GiB local free space was reported; verify current headroom at execution. Local schema/role tests are not a restore of real data.

**R1 — separate recovery authorization requested.** On this exact project, authorize a database logical export that necessarily includes the older application's data, plus role definitions without password hashes, to encrypted-only files in `reports/phase9-shared-supabase/recovery/` (0700 directory/0600 files, untracked). Before starting, securely provide a certificate-verified administrative libpq service/password and an owner-controlled age recipient/key through ignored local configuration or a secret store; never chat. Use approved age tooling and PostgreSQL 17 pg_dump/pg_dumpall (the host psql/pg_dump is 14 and must not dump the 17 server). Stream custom-format pg_dump into authenticated encryption with pipefail; encrypt the role metadata separately; never persist a plaintext dump. Record ciphertext SHA-256, source timestamp, versions, scope and key-recovery checks. No export is authorized by this document alone.

Authorize decryption only into a fresh isolated local PostgreSQL 17 restore container using private scratch/tmpfs and no production credentials in restored application configuration. No network access or background external integration may run; restore schema/roles/ACL dependencies before data, resolve required managed extension compatibility explicitly, and stop on missing managed extensions instead of claiming success. Validate constraints, agreed aggregate integrity/count checks and recovered app keys, and measure recovery duration/recovery point. Preserve the encrypted original; remove plaintext scratch after verification. A restored full Supabase database may require matching managed images/extensions unavailable in plain postgres:17; the local role test is not evidence of that compatibility. No live Supabase project is a restore target. Required Supabase Storage object bytes and external secrets are **not** in a database dump; authorize any separate blob/key backup explicitly before claiming full-application DR. Database migrations here do not change those blobs/settings.

**R2 — exact activation authorization requested, conditional on successful R1/database restore verification, secure credentials and fresh unchanged-target inspection.**

1. Reconfirm ref/org/status, absent job_agent/role names, public catalog/ACL baseline, API schemas, event-trigger metadata and resource headroom. If changed, stop and reconcile; approval does not cover a different catalog.
2. Obtain the owner's older-app read-only health baseline and a bounded maintenance window. Six platform DDL event triggers exist: four extension-specific handlers and pgrst_ddl_watch/pgrst_drop_watch. No extension change is included; DDL watchers can refresh shared API caches. Review their provider-managed behavior as a residual shared-service impact.
3. Execute exactly phase9-role-bootstrap.sql at the hash above, as the reviewed migration administrator. Runtime remains NOLOGIN.
4. Execute the eleven pinned files **001 → 002 → 003 → 004 → 005 → 006 → 007 → 008 → 009 → 010 → 011**, in that order, against postgres/job_agent only. Wrap 001 in its own transaction; respect the explicit transactions in 002–011. Use ON_ERROR_STOP, session lock_timeout=2s and statement_timeout=30s. Do not use db push/reset/pull or blanket replay on changed state. The necessity for the full sequence is established by the absent namespace.
5. Execute exactly phase9-runtime-hardening.sql at the hash above as administrator: 39 ownership/RLS/policy/ACL groups and ten function ownership/ACL groups. No unrelated object changes.
6. Re-inspect catalog using the restricted overlay. Provision only job_agent_runtime's password using an authenticated administrative prompt/secret store, then execute phase9-runtime-login.sql at its pinned hash. Keep credentials server-side in backend/.env or an owner-approved *.private.env file, mode 0600; preserve existing encryption/auth secrets. Use postgresql+asyncpg, port 5432 direct/session mode, DB_REQUIRE_TLS=true and a verified CA/hostname. No DSN query flags, echo logging, transaction pooling or SQLite fallback.
7. Connect as the new runtime with full TLS verification; run the corrected check_database and read-only readiness checks. Verify effective deny-access for anon/authenticated/service_role and unrelated-schema access for runtime using actual sessions. Recompare unrelated schema definitions, object owners/ACLs, role memberships (the new owner-to-postgres grant and PostgreSQL creator-administration memberships for the two new roles are expected; no client may become a member), defaults/API config and older-app health. Observe connection/latency impact. No application-level write test is covered; request its exact scope separately.

Lock/impact: CREATE/ALTER TABLE and 011 CHECK replacements take table locks in newly created job_agent; ownership transfers/FORCE RLS/policy changes also lock those tables. Short lock timeout fails instead of waiting indefinitely. No existing public table is explicitly locked/altered; catalog contention, pool use and API cache notifications still affect shared infrastructure. Avoid peak workload. Existing admin/platform bypass remains; SQL isolation is not protection against trusted database administrators.

Rollback: runtime stays NOLOGIN until verification; on failure, stop and preserve evidence, roll back the current transaction and re-inspect earlier committed stages. The historic files contain commits, so this is not a single atomic deployment. Prefer forward correction under a new exact review. Do not automatically DROP SCHEMA/roles, restore the whole shared database, or replay committed files. A whole-database restore would roll back the older app and requires its own explicit outage/data-loss authorization. Runtime credential disablement, if needed after login, is a new scoped operation unless included in the owner's activation authorization. Recommend authorizing `ALTER ROLE job_agent_runtime NOLOGIN` as the sole automatic containment action, with no termination of other app sessions.

Remaining risks: no zero-impact guarantee on shared compute/catalogs, no validated whole-app restore, unresolved external blob/key recovery, pre-existing public client exposure, stale inspection at later execution, and no real backend TLS/session credential yet. Do not proceed if any prerequisite fails.

## F. Acceptance and owner decision

**Phase 9 is NOT complete.** Real schema activation, live restricted-role persistence, actual resume import/review, Next.js end-to-end persistence, discovery/matching and a genuine packet remain pending. No personal PDF was fetched and no extracted facts were approved. The existing isolated-staging pin on pilot commands is preserved; shared-project pilot authorization/configuration must be reviewed after activation rather than relabeling the shared database as isolated staging.

The next executable prerequisite is to securely configure the approved project's administrative/direct-or-session connection and verified CA plus the backup encryption recipient, and confirm its backup entitlement. Owner authorization is then required for **R1** and, independently and conditionally, **R2** above at the exact SQL hashes. R2 excludes unrelated public security changes, Auth/Storage/API exposure/infrastructure changes, application row writes, resume import, email, paid calls and job submissions. No prior approval for the abandoned project is carried forward.


Reviewed references: [CLI query implementation](https://github.com/supabase/cli/blob/main/apps/cli/src/commands/db/query/query.handler.ts), [CLI connection resolver](https://github.com/supabase/cli/blob/main/apps/cli/src/command-internal/db-config.layer.ts), [connection modes](https://supabase.com/docs/guides/database/connecting-to-postgres), [Postgres roles](https://supabase.com/docs/guides/database/postgres/roles). Source links document current behavior; installed-command output is the evidence for this execution.
