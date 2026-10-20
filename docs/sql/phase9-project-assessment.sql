-- REVIEW COPY ONLY. No remote execution is authorized by this file.
-- Intended project: jyzjgoniuwexvipbbpwa. Verify dashboard/account and exact
-- Connect-panel endpoint independently BEFORE connecting. SQL alone cannot
-- establish a Supabase project reference, account, organization, or ownership.
-- Requires separate owner approval for catalog inspection. No application rows,
-- passwords, OAuth values, query texts, or unrelated function bodies are read.
-- Run using a protected libpq service with sslmode=verify-full and ON_ERROR_STOP.
BEGIN TRANSACTION READ ONLY;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '2s';
SET LOCAL search_path = pg_catalog;

SELECT current_database() AS database_name, current_user AS effective_role,
       session_user AS login_role, version() AS postgresql_version,
       inet_server_addr() AS server_address, inet_server_port() AS server_port;
-- With a session pooler this is the pooler-to-Postgres TLS leg. Independently
-- record certificate AND hostname verification on the client-to-pooler leg.
SELECT ssl, version, cipher, bits FROM pg_stat_ssl WHERE pid = pg_backend_pid();
SELECT name, setting FROM pg_settings
WHERE name IN ('max_connections', 'superuser_reserved_connections',
               'reserved_connections', 'ssl', 'server_version_num');
SELECT pg_database_size(current_database()) AS database_bytes;
-- Aggregates only: no other application's query text or client identifiers.
SELECT datname = current_database() AS this_database, backend_type, state,
       count(*) AS connections
FROM pg_stat_activity GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

SELECT n.nspname, pg_get_userbyid(n.nspowner) AS owner, n.nspacl
FROM pg_namespace n
WHERE n.nspname <> 'information_schema' AND n.nspname !~ '^pg_'
ORDER BY 1;
SELECT n.nspname, c.relname, c.relkind, pg_get_userbyid(c.relowner) AS owner,
       c.relrowsecurity, c.relforcerowsecurity, c.relacl
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname <> 'information_schema' AND n.nspname !~ '^pg_'
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') ORDER BY 1, 2;
SELECT extname, extversion, extnamespace::regnamespace AS schema_name
FROM pg_extension ORDER BY 1;
-- Enabled event triggers may perform cross-schema work during otherwise scoped DDL.
SELECT evtname, evtevent, evtenabled, evtfoid::regprocedure AS handler, evttags
FROM pg_event_trigger ORDER BY 1;

SELECT rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolcanlogin,
       rolreplication, rolbypassrls, rolconnlimit
FROM pg_roles ORDER BY rolname;
SELECT granted.rolname AS granted_role, member.rolname AS member_role,
       m.admin_option
FROM pg_auth_members m JOIN pg_roles granted ON granted.oid = m.roleid
JOIN pg_roles member ON member.oid = m.member ORDER BY 1, 2;
SELECT pg_get_userbyid(d.defaclrole) AS creator,
       CASE WHEN d.defaclnamespace = 0 THEN '(global)'
            ELSE d.defaclnamespace::regnamespace::text END AS schema_name,
       d.defaclobjtype, d.defaclacl FROM pg_default_acl d ORDER BY 1, 2, 3;

-- This role name is proposed, not evidence that it exists or is available.
SELECT r.rolname, n.nspname,
       has_schema_privilege(r.oid, n.oid, 'USAGE') AS effective_usage,
       has_schema_privilege(r.oid, n.oid, 'CREATE') AS effective_create
FROM pg_roles r CROSS JOIN pg_namespace n
WHERE r.rolname IN ('anon', 'authenticated', 'service_role', 'job_agent_runtime')
  AND n.nspname <> 'information_schema' AND n.nspname !~ '^pg_'
ORDER BY 1, 2;
-- has_* includes inherited and PUBLIC privileges. Check columns separately;
-- table-level SELECT=false does not exclude column-only grants.
SELECT r.rolname, n.nspname, c.relname,
       has_table_privilege(r.oid, c.oid, 'SELECT') AS can_select,
       has_any_column_privilege(r.oid, c.oid, 'SELECT') AS can_select_columns,
       has_table_privilege(r.oid, c.oid, 'INSERT') AS can_insert,
       has_any_column_privilege(r.oid, c.oid, 'INSERT') AS can_insert_columns,
       has_table_privilege(r.oid, c.oid, 'UPDATE') AS can_update,
       has_any_column_privilege(r.oid, c.oid, 'UPDATE') AS can_update_columns,
       has_table_privilege(r.oid, c.oid, 'DELETE') AS can_delete,
       has_table_privilege(r.oid, c.oid, 'TRUNCATE') AS can_truncate,
       has_table_privilege(r.oid, c.oid, 'REFERENCES') AS can_reference,
       has_table_privilege(r.oid, c.oid, 'TRIGGER') AS can_trigger
FROM pg_roles r CROSS JOIN pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE r.rolname IN ('anon', 'authenticated', 'service_role', 'job_agent_runtime')
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND n.nspname <> 'information_schema' AND n.nspname !~ '^pg_'
ORDER BY 1, 2, 3;
SELECT r.rolname, n.nspname, c.relname,
       has_sequence_privilege(r.oid, c.oid, 'USAGE,SELECT,UPDATE') AS any_sequence_access
FROM pg_roles r CROSS JOIN pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE r.rolname IN ('anon', 'authenticated', 'service_role', 'job_agent_runtime')
  AND c.relkind = 'S' AND n.nspname !~ '^pg_' ORDER BY 1, 2, 3;
SELECT r.rolname, n.nspname, p.proname, pg_get_function_identity_arguments(p.oid),
       p.prosecdef AS security_definer, has_function_privilege(r.oid, p.oid, 'EXECUTE') AS can_execute
FROM pg_roles r CROSS JOIN pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE r.rolname IN ('anon', 'authenticated', 'service_role', 'job_agent_runtime')
  AND n.nspname <> 'information_schema' AND n.nspname !~ '^pg_'
ORDER BY 1, 2, 3, 4;

SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
FROM pg_policies WHERE schemaname = 'job_agent' ORDER BY 2, 3;
SELECT p.proname, pg_get_function_identity_arguments(p.oid),
       p.prosecdef, p.proconfig, p.proacl, pg_get_functiondef(p.oid)
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'job_agent' AND p.prokind IN ('f', 'p') ORDER BY 1, 2;
SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod) AS type,
       a.attnotnull, pg_get_expr(d.adbin, d.adrelid) AS default_expression
FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
WHERE n.nspname = 'job_agent' AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum;
SELECT c.conrelid::regclass AS table_name, c.conname,
       pg_get_constraintdef(c.oid), c.convalidated,
       CASE WHEN c.confrelid <> 0 THEN c.confrelid::regclass END AS referenced_table
FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
WHERE n.nspname = 'job_agent' ORDER BY 1, 2;
SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'job_agent' ORDER BY 1;
SELECT c.relname, t.tgname, t.tgenabled, pg_get_triggerdef(t.oid)
FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'job_agent' AND NOT t.tgisinternal ORDER BY 1, 2;
-- Includes non-table schema conflicts; an empty table list alone is insufficient.
SELECT pg_describe_object(d.classid, d.objid, d.objsubid) AS dependent_object
FROM pg_depend d JOIN pg_namespace n ON d.refclassid = 'pg_namespace'::regclass
  AND d.refobjid = n.oid WHERE n.nspname = 'job_agent' ORDER BY 1;

-- A database setting is evidence, not the complete deployed Data API config.
-- Also verify the dashboard exposed-schema list and any REST/GraphQL wrappers.
SELECT current_setting('pgrst.db_schemas', true) AS session_data_api_schemas;
SELECT COALESCE(r.rolname, '(all roles)') AS role_name,
       COALESCE(b.datname, '(all databases)') AS database_name, setting
FROM pg_db_role_setting s LEFT JOIN pg_roles r ON r.oid = s.setrole
LEFT JOIN pg_database b ON b.oid = s.setdatabase
CROSS JOIN LATERAL unnest(s.setconfig) AS setting
WHERE setting LIKE 'pgrst.db_schemas=%' ORDER BY 1, 2;
ROLLBACK;
