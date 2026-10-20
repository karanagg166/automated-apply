# Canonical online PostgreSQL

All genuine application data belongs in one owner-approved online Supabase
PostgreSQL database, in `job_agent`, through the existing async SQLAlchemy and
asyncpg repository/transaction layers. This includes profiles, encrypted resume
versions and reviews, jobs, companies, contacts, packets, Gmail state and notifications.
The browser talks to the Next.js server gateway, which talks to FastAPI; database
credentials stay exclusively in the backend environment/secret store.

SQLite is restricted to isolated automated tests and fictional fixtures. The former
live SQLite commands `local_public_pilot.py`, `public_source_smoke.py`, and the live
mode of `startup_discovery_demo.py` now reject execution. Real source reads use the
existing `run_startup_pilot.py` against an approved isolated online staging target.
Old local stores are preserved for owner retention decisions and are never imported
automatically. Existing encryption keys must be preserved separately and recovered
with any encrypted backup. No key is generated or rotated by this correction.

## Approval and connection

Project names do not authorize a target. Confirm the connected account's authority,
organization, exact project reference, region, database name, pooler username, status,
and isolation from production/unrelated data. An inactive project must be restored by
the owner or with explicit approval of that exact operation before connectivity and
schema inspection can be completed. Discovery is read-only. Restoration approval
does not authorize migrations or data writes.

Use the selected project's **Connect** panel to obtain a supported direct connection
or session pooler URL; preserve its actual username, hostname, port and database.
For an IPv4-only local network, use the dashboard's session pooler (5432). The
persistent asyncpg backend rejects transaction pooling on 6543 until compatibility
is separately implemented and tested. See [Supabase connection modes](https://supabase.com/docs/guides/database/connecting-to-postgres).

Set secrets only in an ignored, access-controlled backend environment file or the
approved secret store. Template values below are intentionally empty:

```dotenv
ENVIRONMENT=development
DATABASE_URL=
DATABASE_SCHEMA=job_agent
DB_REMOTE_ONLY=true
DB_REQUIRE_TLS=true
DB_SSL_ROOT_CERT=
```

`DATABASE_URL` must use `postgresql+asyncpg://`. Do not add `sslmode`, `ssl`,
`host` overrides or other query parameters. TLS is supplied to asyncpg as an
SSLContext with certificate and hostname verification in development as well as
staging/production. If necessary, download the selected project's root CA through
its dashboard and supply its local path in `DB_SSL_ROOT_CERT`. Never disable TLS
to work around a certificate error. `DB_REMOTE_ONLY=false` is only for an explicitly
isolated local PostgreSQL infrastructure test; it does not establish online persistence.

Missing configuration, SQLite, in-memory stores, non-asyncpg dialects, unsafe remote
TLS, local/private addresses in remote mode, query overrides and schema mismatches
are rejected before data access. Changing an initialized target requires a restart.
An unavailable remote database never selects a local fallback.

The API and resume worker probe actual connectivity and the committed 001–011
catalog before accepting real work. The probe uses a read-only transaction, checks
columns/constraints/indexes/triggers/functions, RLS and effective client/service-role
grants, and checks runtime schema/table access and DML permissions. `/health` is
liveness only; `/ready` returns 503 when the database probe fails. No startup path
executes migrations or `create_all` for real data.

For sanitized read-only connection evidence, from the repository root:

```sh
backend/venv/bin/python -m backend.scripts.check_database --env-file /secure/approved.private.env
```

It prints version, schema, target fingerprint and migration compatibility only after
connecting. It never prints a URL/password or claims historical migration execution:
001–009 have no durable ledger, so compatibility remains catalog evidence. The target
fingerprint includes the username because Supabase pooler hosts and database names
can be shared by multiple projects. Existing pins must be independently reverified
and recomputed after this change; a fingerprint is still not owner authorization.

## Migration approval scope

Review all SQL **001–011** and their manifest checksums before any cloud DDL.
Use the [backup and restore procedure](staging-setup.md#backup-and-recovery-rehearsal)
to take an encrypted backup and successfully restore it into an explicitly approved
isolated target. Recover encryption keys separately. Record the restore result,
backup timestamp, recovery time and acceptable data-loss window.

Inspect the actual selected schema read-only, including effective grants to `PUBLIC`,
`anon`, `authenticated` and `service_role`, RLS, function definitions, and the intended
runtime role. Private tables must remain inaccessible to browser client roles.
The migrations enable RLS without client access policies; a runtime role needs
appropriate scoped grants and RLS access. Legacy 001–003 tables do not all grant
service-role DML automatically. Additional runtime grants require an exact reviewed
scope, preserving append-only tables. Do not fix this by granting all tables to clients.

For an empty `job_agent` schema, propose the exact reviewed 001–011 scope. For a
compatible 001–010 schema, propose **011 only**. For drift or an unidentified database,
stop and review the differences. Obtain explicit owner approval of the exact project,
database/schema, SQL files/checksums and runtime grants after reviewing the backup.
Never replay all files on a partial schema or apply migrations during API startup.

## Resume and end-to-end acceptance

After project approval, credentials, migration/grant approval and successful probes:

1. Run fictional create/read/restart, transaction rollback, idempotency, encrypted
   round-trip and unauthorized-client checks in an explicitly isolated database.
   Never seed fictional records into the real candidate profile.
2. Configure the real Next.js server's `BACKEND_ORIGIN` for that FastAPI process.
   Keep the backend token and database URL out of `NEXT_PUBLIC_*` and client bundles.
3. Fresh-sync the canonical owner-approved Google Drive PDF using the existing
   [resume sync service](google-drive-resume-sync.md), retaining the existing Fernet key.
   Verify the SHA-256 of decrypted bytes, source metadata, pending review and profile
   version. No development SQLite database is copied.
4. Restart the actual API and retrieve the same encrypted version/review. Display it
   in **My Profile → Resume Sync** through the real dashboard gateway.
5. Leave candidate facts pending until the owner explicitly reviews and approves
   them. Existing approved facts and active resume remain intact.

Record evidence of the exact approved project, an actual remote connection and
PostgreSQL version, schema/011 compatibility, API restart persistence, frontend target,
genuine encrypted resume/checksum, visible pending review, candidate approval status,
no SQLite usage, and test/CI links. Disposable PostgreSQL results are infrastructure
tests and never establish real online persistence.
