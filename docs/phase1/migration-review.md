# Reviewed fresh-project migration proposal

Target project: `luvdmwnlwaqgvfwlmlom`. Schema: `public`. No remote DDL has been executed.

SQL: `supabase/fresh_public/001_phase1_public.sql`. SHA-256: `6cfaf217fb10a9467e193aa7d12529b311a1f65afcf971f1a554039789ce5644`.
Catalog SHA-256: `3a2a361d6736f88e62d5379c9d21b0047f27cec3cfc821670dd4536c1cf0dcf5`.

Historical migrations 001–012 and their existing manifest/checksums remain unchanged. This separate bundle translates schema references and adds five Phase 1 tables. It is not an upgrade/replay path for a populated project. The public schema already exists; no job_agent schema is created.

## Preconditions and impact

1. Official OAuth/management identity and exact target project verified; owning account identified privately. MCP read-only access is verified, but CLI management account does not yet list this project.
2. Rotate exposed secrets; privately provision separate admin and restricted runtime credentials. TLS verified direct/session-pooler connection remains pending.
3. Inventory user/system schemas, extensions, table/column ACLs, roles/memberships, policies, default grants, existing migration history and Data API configuration. MCP currently reports no public tables and no migrations; complete role/grant/managed-schema inventory is pending direct SQL access.
4. Owner must explicitly approve this exact bundle after live preconditions and disposable verification. No automatic remote apply, reset or destructive SQL.
5. One transaction rejects existing public user objects, job_agent namespace or app role collisions; creates NOLOGIN owner/runtime roles; grants only postgres membership for migration ownership; preserves Supabase schema ownership. No Auth, Storage or system-schema objects are altered.
6. Removes PUBLIC/anon/authenticated/service_role schema access; removes their app-object privileges and relevant postgres/public default grants. This affects public schema access in this dedicated project only and must be reviewed against installed extensions before approval. New object functions are explicitly revoked from clients. The new owner role has global PUBLIC function-default execution revoked; postgres global defaults outside public are left untouched.
7. App tables/functions become job_agent_owner owned; every table has ENABLE and FORCE RLS plus a backend-only policy for job_agent_runtime. Runtime is NOINHERIT, NOBYPASSRLS, cannot create schema/database objects, and cannot read other user schemas. It remains NOLOGIN until separate reviewed private password provisioning.
8. Runtime readiness checks exact catalog, SQL/source/catalog hashes, ownership, RLS, policies, excess privileges, effective public/client grants and verified TLS. Table presence is not a claim that historical migrations ran.
9. Remote harmless persistence record/cleanup and API restart verification remain pending; no test row has been created remotely. Disposable lifecycle records contain fictional data only.

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
