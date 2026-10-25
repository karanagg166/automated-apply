# Exact migration comparison before final owner approval

Verified 2026-10-25. No remote DDL has been executed.

| Check | Result |
|---|---|
| Previously reviewed bundle at ce88367 | `6cfaf217fb10a9467e193aa7d12529b311a1f65afcf971f1a554039789ce5644` |
| Current exact bundle | `2887a98812a797c3ef9d10f37fe5f14959778d802e126d0170776059ccee6a9e` |
| Target | Only `luvdmwnlwaqgvfwlmlom`; official CLI account verified and Phase 1 checkout linked |
| Live read-only SQL inventory | Passed at `2026-10-25T11:44:41.410143Z`, PostgreSQL 17.11, database postgres |
| TLS | Official Supabase production CA plus exact session-pooler hostname verification; TLS 1.3 |
| Existing public application tables / application roles / migration history | 0 / 0 / 0 |
| Historical migrations 001–012 | Files and SHA-256 entries unchanged |
| Expected application catalog | Unchanged: `3a2a361d6736f88e62d5379c9d21b0047f27cec3cfc821670dd4536c1cf0dcf5` |
| Application table list | Same 47 tables as the previous review |
| Forced RLS / backend policies / runtime table grant statements | 47 / 47 / 47; verified in actual PostgreSQL catalog |

## Entire SQL difference

Only the opening fresh-project precondition and a following managed-function ACL block changed. Every byte from `CREATE ROLE job_agent_owner` through the final COMMIT is identical to the previously reviewed SQL.

1. The precondition now permits precisely the existing postgres-owned `public.rls_auto_enable()` with no arguments and function-definition SHA-256 `b21d88816c445d14cef5032c3cd4abaebc1db2001fcb3435022ab6b496182ca4`. All other pre-existing non-extension public functions, relations, application roles and job_agent namespace still cause the transaction to fail before creating application objects.
2. A conditional block revokes EXECUTE on that preserved function from PUBLIC, anon, authenticated and service_role. It does not replace its body, change its owner, drop it or alter the `ensure_rls` event trigger. This closes the two live security-advisor findings. PostgreSQL invokes event triggers without granting application clients direct function access.
3. The manifest records the new bundle checksum and the separate reviewed managed-function definition file. The application catalog, table list and historical checksums are unchanged.

The existing bundle contains `DROP TRIGGER IF EXISTS company_snapshot_guard ON public.company_source_observations`, retained byte-for-byte from the previous review. It recreates an application trigger on an application table created earlier in the same transaction. The fresh-project precondition forbids that table from existing beforehand. It cannot remove a pre-existing managed trigger or unrelated table. No DROP TABLE, DROP SCHEMA, TRUNCATE, DELETE of existing data, db reset or schema reset is present.

## Executed acceptance checks

The exact new bundle was applied only to an owned disposable PostgreSQL 17 instance containing the inventoried Supabase function, its event trigger and Supabase-style postgres default grants. The application catalog, indexes, constraints, trigger/function bodies, policies, ownership and restricted runtime permissions matched the unchanged expected catalog. All 47 application tables had both ENABLE and FORCE RLS. The runtime could not execute the managed function.

Five forbidden runtime operations were denied: table creation, access to Auth data, audit deletion, policy-event rewriting and disabling RLS. Twelve security faults were rejected: anonymous grants, disabled RLS, privileged runtime, broadened policy, extra DELETE, unsafe defaults, cross-schema access, managed-function grants to clients/runtime, managed-function definition drift, disabled managed trigger and an extra managed trigger. An unreviewed pre-existing function and a second bundle application were rejected. All injected changes were rolled back only in the disposable database.

The bundle leaves existing Auth, Storage, Vault, Extensions, system schemas, roles and managed event triggers intact. It keeps public schema ownership with Supabase. Public schema USAGE/default grants are intentionally tightened for this empty dedicated application project; new application tables/functions are owned by the private NOLOGIN owner. The runtime is non-superuser, NOINHERIT, NOBYPASSRLS, has no owner membership and receives only the reviewed per-table operations.

The 1,467-test backend regression passed with disposable PostgreSQL and no skips before this final managed-function verification; the exact managed fixture then passed the catalog/permission/fault suite above. Frontend: 40 unit tests, production build, type/format checks and all eight browser journeys passed. Extension: twelve event tests and actual isolated Chromium native messaging/FastAPI/PostgreSQL/restart persistence passed. Simulated browser events and real owner-browser verification remain separately classified.

## Approval boundary

Final owner approval is still required for this exact bundle and the separate initial `job_agent_runtime` login credential. Existing credentials are retained. After approval, execution must recheck the project, checksum and live preconditions, execute this bundle once, initialize the previously NOLOGIN runtime, verify TLS and effective runtime privileges, test harmless persistence/cleanup, switch genuine services only to the verified restricted online connection, restart and run security advisors. A failure or uncertain outcome stops automatic re-application. No actual job application, email, Gmail draft, paid provider call or Phase 2 work is authorized by this DDL approval.
