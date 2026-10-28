# Read-only Gmail migration operator steps

The engineering milestone does not require live Gmail activation. These steps prepare a reviewable change; no live DDL, deployment, OAuth consent or mailbox read is authorized by this document.

1. Pin the tested integration commit in `phase35-engineering-conclusion.md`. Use its Python environment, migrations, schema manifest and checksum together. The target is the existing owner-approved online PostgreSQL database, schema `public`; never point a disposable test verifier at it.
2. Stop Gmail OAuth/connect/sync writers. Preserve the existing private OAuth encryption keys and configuration. Establish a recoverable database backup and verify the restoration procedure before requesting maintenance approval.
3. Render both SQL files locally. This command has no database connection and does not apply DDL:

```sh
umask 077
export GMAIL_REVIEW_DIR="$HOME/Library/Application Support/Automated Apply/gmail-readonly-review"
backend/venv/bin/python - <<'PY'
import hashlib
import os
from pathlib import Path
from backend.app.integrations.gmail.schema import (
    MIGRATION, render_review_sql, render_rollback_sql,
)
from backend.app.integrations.gmail.schema_checksum import REVIEW_SQL_SHA256
assert hashlib.sha256(MIGRATION.read_bytes()).hexdigest() == REVIEW_SQL_SHA256
root = Path(os.environ['GMAIL_REVIEW_DIR'])
root.mkdir(parents=True, exist_ok=True, mode=0o700)
for name, sql in [('forward.public.sql', render_review_sql('public')),
                  ('rollback.empty.public.sql', render_rollback_sql('public'))]:
    path = root / name
    path.write_text(sql)
    path.chmod(0o600)
    print(name, hashlib.sha256(path.read_bytes()).hexdigest())
PY
```

4. Review the rendered forward SQL, its SHA-256, exact target, maintenance identity/window and backup receipt with the owner. The additive scope is only `public.gmail_read_accounts`, `public.gmail_read_oauth_states`, their constraints/indexes, forced RLS and existing backend policies. The runtime gets SELECT/INSERT/UPDATE, no DELETE or DDL. PUBLIC, anon, authenticated and service_role get no access. There are no token rewrites or default/schema privilege changes.
5. Obtain separate authorization for that exact DDL transaction. The maintenance operator must acquire `pg_advisory_xact_lock(350035, 1)`, use 5s lock and 30s statement timeouts, and run `migration_preflight(connection, 'public')` under `SET LOCAL ROLE job_agent_runtime` in the same transaction before DDL. Restore the approved maintenance role before running the reviewed statements. Abort on partial installation, checksum mismatch, drift, excessive permissions, wrong target or unavailable backup. Do not rely on `IF NOT EXISTS` as a preflight. The existing renderer includes BEGIN/COMMIT; when embedding its statements inside an operator-owned transaction, remove only that outer transaction pair, preserving the reviewed body and lock/timeouts.
6. Before committing, repeat the preflight under the runtime role and require `status == 'installed'`. Verify both tables, owner, forced RLS, policies, exact columns/constraints/indexes and effective grants against `backend/app/integrations/gmail/schema_manifest.json`. Roll back the transaction on any mismatch. After commit, verify again through a fresh restricted-runtime connection and preserve the receipt outside Git. Catalog agreement is evidence of current state, not a historical migration ledger.
7. The rollback is for an empty installation only. It requires an explicitly approved maintenance identity, locks the two tables and preference store, refuses any accounts/OAuth states/Gmail evidence, and uses DROP RESTRICT. Once populated, use a reviewed forward repair or the verified restoration procedure; do not delete evidence or use CASCADE to force rollback.
8. Separately approve runtime activation. Each mailbox then needs its own browser-bound PKCE OAuth consent and identity verification. Start with metadata scope, one curated custom job-alert label, optional sender allowlist, seven-day lookback, fourteen-day retention and at most one page/25 selected IDs. Metadata scope cannot use Gmail `q`. Body parsing requires a documented purpose, separate scope consent and the applicable restricted-scope verification/security-assessment review or exemption. Never interpret the legacy compose connection as read consent.
9. Verify account attribution, cursor/retry behavior, account isolation and zero mailbox mutations before enabling a second account. Job leads and email signals remain unverified until factual owner review. No send, compose, forward, reply, mark-read, archive, modify or delete operation belongs to this workflow.

Local readiness verification uses only a disposable PostgreSQL 17 URL:

```sh
export PROFILE_TEST_DATABASE_URL='postgresql://postgres:profile_test_only@127.0.0.1:55436/candidate_profile_test' # pragma: allowlist secret -- fictional disposable fixture
backend/venv/bin/python backend/scripts/verify_phase3_integrations_postgres.py
```

The verifier creates unique fictional databases, exercises both `job_agent` and `public`, migration replay, failed-DDL rollback, schema drift, RLS/grant boundaries, empty/populated rollback and durable per-account transactions. It deliberately refuses a nonlocal target. Do not use `--write-manifest` during ordinary verification.

## Target-specific credential and age setup — 2026-10-29

The owner confirmed that neither a target administrator service nor an approved
age recipient exists, and directed this task to **stop before backup or DDL**.
The earlier conditional migration approval is retained; prerequisites are unmet.
These instructions do not authorize stopping live writers, deployment, OAuth or
mailbox reads.

Preserve existing entries and prepare a new section in ~/.pg_service.conf:

    [automated_apply_admin_luvdmwnlwaqgvfwlmlom]
    host=db.luvdmwnlwaqgvfwlmlom.supabase.co
    port=5432
    dbname=postgres
    user=postgres
    sslmode=verify-full
    sslrootcert=/ABSOLUTE/OWNER_VERIFIED/SUPABASE_CA_FILE

The owner obtains credentials from exactly this project's Supabase database
settings. Add the matching host/port/database/user password entry to ~/.pgpass
with a local editor, never chat, shell arguments or Git. Avoid wildcards; set
both files to 0600. Do not copy, rename, test or substitute the administrator
service for another project. If the direct host is unreachable, stop for an
owner-reviewed target-specific session-pooler identity rather than changing it.

Install age only through the owner's approved package method. The owner creates
a dedicated key with age-keygen -o /PRIVATE/OUTSIDE_GIT/age-identity.txt, protecting
its directory with 0700 and identity with 0600, or uses their approved macOS
Keychain storage/recovery procedure. Never expose the private identity in
arguments, logs, reports or Git. Record and approve the public recipient
separately, test encryption/decryption with fictional probe bytes, and confirm
where the recoverable private key is stored. No recipient was generated here.

After connection/key setup and separately established writer coordination, the
proposed backup method is PostgreSQL 17 pg_dump --format=custom, streaming
directly through age into a private encrypted artifact. Select the exact service
with PGSERVICE and preserve verified TLS. The wrapper must check **both** exit
codes, including failed pg_dump feeding successful encryption, use umask 077,
avoid plaintext temporary dumps, and retain archive checksum/inventory plus
separate roles/grants/configuration/application-key recovery material. A complete
dump is required; a schema-only export or selected-table copy is insufficient.
Do not run it until the owner establishes the prerequisites.

Independently decrypt through a pipe into pg_restore --exit-on-error against a
new disposable PostgreSQL 17 database, with the protected role inventory and no
online credentials. Compare schema, ownership, ACLs, every application table's
row counts, representative content digests and application readiness with the
pinned pre-export catalog. Test recovery of the encryption/application keys as
well as the dump. Preserve an actual private restore receipt and recovery
procedure; an archive listing alone is insufficient. Abort before live DDL on
any identity, writer, checksum, role/grant, catalog, completeness or recovery
mismatch.

The rendered public forward SQL SHA-256 remains
e61d2e23fb27991715e2689cda14273d11abf4aac04e71babaf8ef4f5c434ebd.
Only the reviewed two-table migration is in scope. After an authorized execution,
independently recheck both tables, forced RLS, owners, policies/effective grants,
and old-data counts/digests using fresh restricted-runtime and maintenance
read-only connections. Runtime replacement, OAuth and mailbox reads still need
their separate authorizations.
