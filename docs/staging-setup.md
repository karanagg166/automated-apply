# Reproducible staging setup

This is a deployment procedure, not deployment evidence. No hosting provider is selected or
provisioned by this phase. Use a single FastAPI container behind HTTPS and an isolated PostgreSQL
16 database/Supabase project, restricted to the owner through a VPN/access gateway and bearer
authentication. No scheduler, Redis, browser service, extension, Compose stack or Kubernetes is
needed. Use staging-only secrets and no production candidate data by default.

1. Select the hosting provider and obtain explicit deployment authorization. Provision isolated
   PostgreSQL and a private network/firewall. Record project ownership and database identity.
2. Copy `backend/.env.staging.example` to `staging.private.env` outside Git, chmod 0600. Supply a
   dedicated asyncpg DSN without query parameters, exact API hostnames, and independent random
   API token/SECRET_KEY. `DB_REQUIRE_TLS=true` uses certificate-verified TLS. Provision a trusted
   CA if your managed database needs one; do not turn off verification to fix an unknown issuer.
3. Run `check_environment.py --env-file staging.private.env`. It prints only a target fingerprint.
   Independently confirm that target is isolated staging; set STAGING_DATABASE_ID to that hash.
   Optional integrations can remain unconfigured. Never set ENVIRONMENT=staging on production
   credentials as a shortcut.
4. Make and restore-test a staging backup before DDL. Run the offline migration plan, review all
   ten SQL files (001–010) and their checksums, then inspect the target with the pinned staging preflight.
5. For an empty staging schema only, apply reviewed SQL in order as a separate owner action.
   Use a password-protected libpq service file named `automated_apply_staging` and a 0600 pgpass
   file; do not put database passwords on a command line. Confirm service identity independently
   against the pin. Example for **one reviewed file**:

   ```sh
   psql 'service=automated_apply_staging' --set ON_ERROR_STOP=1 \
     --single-transaction --file supabase/migrations/001_initial_schema.sql
   ```

   Repeat for 002–010 in order after review, stopping on any failure. Do not run this command on
   production in this phase. Do not use this sequence to repair a partial schema without a DBA
   reviewing the actual drift. On vanilla PostgreSQL provision the expected Supabase-compatible
   roles (`anon`, `authenticated`, `service_role`) separately with no client logins. The existing
   migrations conditionally grant privileges to service_role; see the security review before
   selecting a runtime role. They must exist before preparing the catalog reference parity.
6. Run catalog preflight again. Supply a runtime credential with appropriate DML rights and
   RLS access, separately from the migration administrator. Verify actual API reads/writes using
   only fictional staging fixtures first. `/ready` checks table SELECT access; it cannot prove all
   write permissions or every trigger invariant. Never grant all tables to browser client roles.
7. Build the container locally from the repository root:

   ```sh
   docker build --build-arg SOURCE_REVISION=YOUR_REVIEWED_COMMIT -t automated-apply:staging .
   ```

   Runtime dependencies are constrained in `backend/requirements.lock`. The base image is a
   Python 3.11 slim tag pinned to its verified digest; record the built image digest in your
   deployment and review base/security updates regularly. No secrets or tests enter the image.
   CI/offline dependencies remain separate. The container runs as an unprivileged user.
8. The default CMD binds 8000, disables forwarded headers, gives idle keepalive five seconds and
   graceful shutdown 30 seconds. Behind a TLS ingress, override the command to trust only the
   ingress IP/network:

   ```sh
   uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 \
     --proxy-headers --forwarded-allow-ips=YOUR_EXACT_INGRESS_IP \
     --timeout-keep-alive 5 --timeout-graceful-shutdown 30
   ```

   Do not use `--forwarded-allow-ips='*'`. Restrict direct container access so public clients cannot
   reach the trusted-ingress socket. The ingress must overwrite Forwarded/X-Forwarded-* headers,
   preserve the approved Host, enforce HTTPS/HSTS, cap bodies to 1 MiB (64 KiB for profile/packet
   paths, 5 MiB only for the private-resume upload), and limit slow uploads/connections. Runtime Host/Origin/TLS checks apply to REST;
   MCP keeps its separate stricter token/transport boundary and stays disabled in staging.
   Only loopback process probes may bypass TLS for `/health` and `/ready`, never private APIs.
9. Inject runtime secrets through the host secret manager (Docker --env-file is suitable only
   for an access-controlled local rehearsal). Keep root filesystem read-only, drop capabilities,
   set no-new-privileges and use a small tmpfs if your host supports them. Do not expose port 8000
   publicly. No secret belongs in Docker build args, image labels or container logs.
10. Check `/health`, `/ready`, authentication rejection and the owner operations endpoint through
    HTTPS. Run staging read-only smoke, then explicitly authorize a bounded public source check.
    Gmail sending, application submission and remote MCP remain disabled. Production deployment
    is a separate approval after backup, access, monitoring and real-profile pilot review.

Use one worker initially. With DB_POOL_SIZE=3/DB_MAX_OVERFLOW=2 it opens up to five connections;
reserve administrative/backup capacity and multiply that maximum before increasing workers or
replicas. Prefer direct PostgreSQL or Supabase session pooling. Transaction pooling needs a
separate asyncpg prepared-statement compatibility assessment; do not assume the direct DSN can
be replaced without tests. pool_pre_ping and pool_recycle handle stale connections, not overload.

## Backup and recovery rehearsal

Before rollout, take an encrypted PostgreSQL custom-format dump using a protected service file:

```sh
pg_dump 'service=automated_apply_staging' --format=custom --file=staging-backup.private.dump
```

Store it outside Git with restricted permissions; it includes private profiles, encrypted OAuth
tokens and operational ledgers. Back up encryption keys separately in the secret manager.
Restore into a **new disposable isolated** database, verify row counts, migration preflight,
packet invariants, and OAuth decryption locally without refreshing tokens or sending anything.
Use `pg_restore --exit-on-error` against that new target; never restore over production for a
rehearsal. Record recovery time and data-loss window. Managed PITR is useful only after a tested
restore. Securely remove rehearsal data afterwards using the owner's retention procedure.

Committed schema changes are not undone by rolling back a later transaction or deploying an
older image. Restoring a snapshot loses writes since that snapshot; a forward repair often
preserves more data. Stop writers and reconcile uncertain external send/provider attempts before
any rollback. No automated reset, destructive downgrade or production credential rotation exists.
