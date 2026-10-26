# Reviewed fresh-project migration proposal

Target project: `luvdmwnlwaqgvfwlmlom`. Schema: `public`. No remote DDL has been executed.

SQL: `supabase/fresh_public/001_phase1_public.sql`. SHA-256: `2887a98812a797c3ef9d10f37fe5f14959778d802e126d0170776059ccee6a9e`.
Catalog SHA-256: `3a2a361d6736f88e62d5379c9d21b0047f27cec3cfc821670dd4536c1cf0dcf5`.

Historical migrations 001–012 and their existing manifest/checksums remain unchanged. This separate bundle translates schema references and adds five Phase 1 tables. It is not an upgrade/replay path for a populated project. The public schema already exists; no job_agent schema is created.

## Preconditions and impact

1. Official OAuth/management identity and exact target project verified in the isolated CLI account. Only the Phase 1 checkout was linked. CLI reports ACTIVE_HEALTHY, ap-northeast-1, PostgreSQL 17.11. Existing default account/profile is preserved.
2. Existing database credentials were entered only in the hidden owner Terminal prompt. No credential was rotated or replaced. Actual read-only PostgreSQL inventory succeeded at 2026-10-25T11:44:41.410143Z, with certificate-chain and hostname verification using the official Supabase production CA. Session pooler: aws-0-ap-northeast-1.pooler.supabase.com:5432. Management OAuth and PostgreSQL authentication were verified separately.
3. The live inventory has no public tables, application roles, job_agent schema or application migration history. Auth/Storage/Extensions/Vault managed objects exist. The public schema contains the postgres-owned `rls_auto_enable()` SECURITY DEFINER event-trigger function and `ensure_rls` event trigger. Public defaults currently grant client access to new postgres/supabase_admin objects. Private inventory includes schemas, tables and ACLs, roles/memberships, policies, extensions, event triggers and default grants. No user row data was read.
4. Owner must explicitly approve this exact bundle after live preconditions and disposable verification. No automatic remote apply, reset or destructive SQL.
5. One transaction rejects existing public user objects, job_agent namespace or app role collisions; creates NOLOGIN owner/runtime roles; grants only postgres membership for migration ownership; preserves Supabase schema ownership. The only allowed pre-existing public function is the exact inventoried `rls_auto_enable()` definition (SHA-256 `b21d88816c445d14cef5032c3cd4abaebc1db2001fcb3435022ab6b496182ca4`). Its body, owner and event trigger are preserved. EXECUTE is revoked from PUBLIC/anon/authenticated/service_role, addressing the two live security-advisor findings. Runtime never receives EXECUTE on it. No Auth, Storage, Vault or system-schema objects are altered.
6. Removes PUBLIC/anon/authenticated/service_role schema access; removes their app-object privileges and relevant postgres/public default grants. This affects public schema access in this dedicated project only and must be reviewed against installed extensions before approval. New object functions are explicitly revoked from clients. The new owner role has global PUBLIC function-default execution revoked; postgres global defaults outside public are left untouched.
7. App tables/functions become job_agent_owner owned; every table has ENABLE and FORCE RLS plus a backend-only policy for job_agent_runtime. Runtime is NOINHERIT, NOBYPASSRLS, cannot create schema/database objects, and cannot read other user schemas. It remains NOLOGIN until separate reviewed private password provisioning.
8. Runtime readiness checks exact catalog, SQL/source/catalog hashes, ownership, RLS, policies, excess privileges, effective public/client grants and verified TLS. Table presence is not a claim that historical migrations ran.
9. Remote harmless persistence record/cleanup and API restart verification remain pending; no test row has been created remotely. Disposable lifecycle records contain fictional data only.

The revised bundle passed on actual disposable PostgreSQL 17 with the exact inventoried function/event trigger and Supabase-style default grants. All 47 application tables, forced RLS and runtime permissions verified. Five forbidden runtime operations and twelve injected security faults were rejected, including client/runtime grants on the managed function, changed definition, disabled trigger and extra trigger. An unreviewed pre-existing function still blocks installation; repeat application is rejected atomically. The expected application catalog and all historical migration checksums remain unchanged.

After approval of the bundle, activation also needs a **first credential for the newly created restricted runtime role**. This initializes a new role; it does not rotate or change the existing postgres password or any existing key. The proposed additional statement is `ALTER ROLE job_agent_runtime LOGIN PASSWORD <initial-private-random-secret>`, executed only after confirming that the new role is still NOLOGIN. The secret will be generated privately, URI-escaped and saved in the private backend configuration. No admin credential will be used by FastAPI, Telegram or the native host. This provisioning is remote DDL and is included in the approval request, not performed automatically.

## Exact application tables and runtime privileges

| Object in public | Runtime privileges |
|---|---|
| agent_operations | INSERT, SELECT |
| agent_policies | INSERT, SELECT, UPDATE |
| agent_policy_events | INSERT, SELECT |
| agent_telegram_deliveries | INSERT, SELECT, UPDATE |
| agent_telegram_state | INSERT, SELECT, UPDATE |
| api_keys_pool | INSERT, SELECT, UPDATE |
| application_answer_drafts | INSERT, SELECT, UPDATE |
| application_events | INSERT, SELECT |
| application_packet_fields | INSERT, SELECT, UPDATE |
| application_packets | INSERT, SELECT, UPDATE |
| application_submission_evidence | INSERT, SELECT |
| automation_executions | INSERT, SELECT, UPDATE |
| automation_matches | INSERT, SELECT, UPDATE |
| automation_schedule | INSERT, SELECT, UPDATE |
| candidate_evidence | INSERT, SELECT, UPDATE |
| candidate_profiles | INSERT, SELECT, UPDATE |
| candidate_resources | INSERT, SELECT, UPDATE |
| companies | INSERT, SELECT, UPDATE |
| company_source_observations | INSERT, SELECT |
| connected_accounts | INSERT, SELECT, UPDATE |
| contact_enrichment_runs | INSERT, SELECT, UPDATE |
| contact_evidence | INSERT, SELECT, UPDATE |
| contact_identities | DELETE, INSERT, SELECT, UPDATE |
| contact_provider_lookups | INSERT, SELECT, UPDATE |
| contacts | INSERT, SELECT, UPDATE |
| discovered_company_people | INSERT, SELECT, UPDATE |
| discovery_budget_reservations | INSERT, SELECT, UPDATE |
| discovery_monthly_budgets | INSERT, SELECT, UPDATE |
| discovery_runs | INSERT, SELECT, UPDATE |
| drive_resume_versions | INSERT, SELECT |
| job_source_observations | INSERT, SELECT, UPDATE |
| jobs | INSERT, SELECT, UPDATE |
| llm_monthly_usage | INSERT, SELECT, UPDATE |
| notification_deliveries | INSERT, SELECT, UPDATE |
| oauth_states | INSERT, SELECT, UPDATE |
| outreach_logs | INSERT, SELECT, UPDATE |
| outreach_send_attempts | INSERT, SELECT, UPDATE |
| outreach_send_confirmations | INSERT, SELECT, UPDATE |
| owner_notifications | INSERT, SELECT, UPDATE |
| owner_preferences | INSERT, SELECT, UPDATE |
| private_resumes | INSERT, SELECT, UPDATE |
| provider_access_windows | INSERT, SELECT, UPDATE |
| provider_connection_checks | INSERT, SELECT, UPDATE |
| provider_usage_logs | INSERT, SELECT |
| resume_drive_sources | INSERT, SELECT, UPDATE |
| resume_profile_reviews | INSERT, SELECT, UPDATE |
| startup_shortlist_entries | INSERT, SELECT |

The ten historical trigger functions receive runtime EXECUTE only, with unchanged bodies except schema qualification. Triggers/checks/indexes/foreign keys are recorded in catalog.json. Audit events/operations remain append-only through runtime ACLs. Private resumes and OAuth tokens retain existing encrypted storage.

## Rollback and recovery

Any bundle failure rolls the transaction back. After commit, do not drop tables or reset the database. Preserve a reviewed recovery artifact and repair through an additive reviewed change. There is no automated destructive rollback. Keep migration/admin credentials out of the routine browser, host and worker.
