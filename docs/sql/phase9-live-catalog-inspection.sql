-- Target jyzjgoniuwexvipbbpwa ONLY. Catalog metadata; no application rows.
-- Authenticated Management API route; no CLI linked-query login-role preflight.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '2s';
SET LOCAL search_path = pg_catalog;
SELECT 'assessment_00' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT current_database() AS database_name, current_user AS effective_role,
       session_user AS login_role, version() AS postgresql_version,
       inet_server_addr() AS server_address, inet_server_port() AS server_port) q
UNION ALL
SELECT 'assessment_01' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT ssl, version, cipher, bits FROM pg_stat_ssl WHERE pid = pg_backend_pid()) q
UNION ALL
SELECT 'assessment_02' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT name, setting FROM pg_settings
WHERE name IN ('max_connections', 'superuser_reserved_connections',
               'reserved_connections', 'ssl', 'server_version_num')) q
UNION ALL
SELECT 'assessment_03' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT pg_database_size(current_database()) AS database_bytes) q
UNION ALL
SELECT 'assessment_04' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT datname = current_database() AS this_database, backend_type, state,
       count(*) AS connections
FROM pg_stat_activity GROUP BY 1, 2, 3 ORDER BY 1, 2, 3) q
UNION ALL
SELECT 'assessment_05' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT n.nspname, pg_get_userbyid(n.nspowner) AS owner, n.nspacl
FROM pg_namespace n
WHERE n.nspname <> 'information_schema' AND n.nspname !~ '^pg_'
ORDER BY 1) q
UNION ALL
SELECT 'assessment_06' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT n.nspname, c.relname, c.relkind, pg_get_userbyid(c.relowner) AS owner,
       c.relrowsecurity, c.relforcerowsecurity, c.relacl
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname <> 'information_schema' AND n.nspname !~ '^pg_'
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') ORDER BY 1, 2) q
UNION ALL
SELECT 'assessment_07' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT extname, extversion, extnamespace::regnamespace AS schema_name
FROM pg_extension ORDER BY 1) q
UNION ALL
SELECT 'assessment_08' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT evtname, evtevent, evtenabled, evtfoid::regprocedure AS handler, evttags
FROM pg_event_trigger ORDER BY 1) q
UNION ALL
SELECT 'assessment_09' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolcanlogin,
       rolreplication, rolbypassrls, rolconnlimit
FROM pg_roles ORDER BY rolname) q
UNION ALL
SELECT 'assessment_10' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT granted.rolname AS granted_role, member.rolname AS member_role,
       m.admin_option
FROM pg_auth_members m JOIN pg_roles granted ON granted.oid = m.roleid
JOIN pg_roles member ON member.oid = m.member ORDER BY 1, 2) q
UNION ALL
SELECT 'assessment_11' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT pg_get_userbyid(d.defaclrole) AS creator,
       CASE WHEN d.defaclnamespace = 0 THEN '(global)'
            ELSE d.defaclnamespace::regnamespace::text END AS schema_name,
       d.defaclobjtype, d.defaclacl FROM pg_default_acl d ORDER BY 1, 2, 3) q
UNION ALL
SELECT 'assessment_12' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT r.rolname, n.nspname,
       has_schema_privilege(r.oid, n.oid, 'USAGE') AS effective_usage,
       has_schema_privilege(r.oid, n.oid, 'CREATE') AS effective_create
FROM pg_roles r CROSS JOIN pg_namespace n
WHERE r.rolname IN ('anon', 'authenticated', 'service_role', 'job_agent_runtime')
  AND n.nspname <> 'information_schema' AND n.nspname !~ '^pg_'
ORDER BY 1, 2) q
UNION ALL
SELECT 'assessment_13' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT r.rolname, n.nspname, c.relname,
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
ORDER BY 1, 2, 3) q
UNION ALL
SELECT 'assessment_14' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT r.rolname, n.nspname, c.relname,
       has_sequence_privilege(r.oid, c.oid, 'USAGE,SELECT,UPDATE') AS any_sequence_access
FROM pg_roles r CROSS JOIN pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE r.rolname IN ('anon', 'authenticated', 'service_role', 'job_agent_runtime')
  AND c.relkind = 'S' AND n.nspname !~ '^pg_' ORDER BY 1, 2, 3) q
UNION ALL
SELECT 'assessment_15' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT r.rolname, n.nspname, p.proname, pg_get_function_identity_arguments(p.oid),
       p.prosecdef AS security_definer, has_function_privilege(r.oid, p.oid, 'EXECUTE') AS can_execute
FROM pg_roles r CROSS JOIN pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE r.rolname IN ('anon', 'authenticated', 'service_role', 'job_agent_runtime')
  AND n.nspname <> 'information_schema' AND n.nspname !~ '^pg_'
ORDER BY 1, 2, 3, 4) q
UNION ALL
SELECT 'assessment_16' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
FROM pg_policies WHERE schemaname = 'job_agent' ORDER BY 2, 3) q
UNION ALL
SELECT 'assessment_17' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT p.proname, pg_get_function_identity_arguments(p.oid),
       p.prosecdef, p.proconfig, p.proacl, pg_get_functiondef(p.oid)
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'job_agent' AND p.prokind IN ('f', 'p') ORDER BY 1, 2) q
UNION ALL
SELECT 'assessment_18' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod) AS type,
       a.attnotnull, pg_get_expr(d.adbin, d.adrelid) AS default_expression
FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
WHERE n.nspname = 'job_agent' AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum) q
UNION ALL
SELECT 'assessment_19' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT c.conrelid::regclass AS table_name, c.conname,
       pg_get_constraintdef(c.oid), c.convalidated,
       CASE WHEN c.confrelid <> 0 THEN c.confrelid::regclass END AS referenced_table
FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
WHERE n.nspname = 'job_agent' ORDER BY 1, 2) q
UNION ALL
SELECT 'assessment_20' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'job_agent' ORDER BY 1) q
UNION ALL
SELECT 'assessment_21' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT c.relname, t.tgname, t.tgenabled, pg_get_triggerdef(t.oid)
FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'job_agent' AND NOT t.tgisinternal ORDER BY 1, 2) q
UNION ALL
SELECT 'assessment_22' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT pg_describe_object(d.classid, d.objid, d.objsubid) AS dependent_object
FROM pg_depend d JOIN pg_namespace n ON d.refclassid = 'pg_namespace'::regclass
  AND d.refobjid = n.oid WHERE n.nspname = 'job_agent' ORDER BY 1) q
UNION ALL
SELECT 'assessment_23' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT current_setting('pgrst.db_schemas', true) AS session_data_api_schemas) q
UNION ALL
SELECT 'assessment_24' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT COALESCE(r.rolname, '(all roles)') AS role_name,
       COALESCE(b.datname, '(all databases)') AS database_name, setting
FROM pg_db_role_setting s LEFT JOIN pg_roles r ON r.oid = s.setrole
LEFT JOIN pg_database b ON b.oid = s.setdatabase
CROSS JOIN LATERAL unnest(s.setconfig) AS setting
WHERE setting LIKE 'pgrst.db_schemas=%' ORDER BY 1, 2) q
UNION ALL
SELECT 'schema_presence' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='job_agent') AS job_agent_exists) q
UNION ALL
SELECT 'catalog_statistics' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT schemaname,relname,n_live_tup,n_dead_tup FROM pg_stat_user_tables ORDER BY 1,2) q
UNION ALL
SELECT 'cross_schema_foreign_keys' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT conrelid::regclass::text AS dependent_table, confrelid::regclass::text AS referenced_table,conname FROM pg_constraint WHERE contype='f' AND (connamespace=(SELECT oid FROM pg_namespace WHERE nspname='job_agent') OR confrelid IN (SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='job_agent'))) q
UNION ALL
SELECT 'function_security' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid) AS arguments,pg_get_userbyid(p.proowner) AS owner,p.prosecdef,p.proconfig,p.proacl FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname <> 'information_schema' AND n.nspname !~ '^pg_' AND p.prokind IN ('f','p') ORDER BY 1,2,3) q
UNION ALL
SELECT 'job_agent_views' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT c.relname,c.relkind,c.reloptions,pg_get_viewdef(c.oid,true) AS definition FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='job_agent' AND c.relkind IN ('v','m')) q
UNION ALL
SELECT 'job_agent_types' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT t.typname,t.typtype FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='job_agent' ORDER BY 1) q
UNION ALL
SELECT 'nonplatform_public_acl' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT n.nspname,c.relname,a.privilege_type FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a WHERE a.grantee=0 AND n.nspname NOT IN ('information_schema','pg_catalog') AND c.relkind IN ('r','p','v','m','f','S') ORDER BY 1,2,3) q
UNION ALL
SELECT 'catalog_tables' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT c.relname AS key, c.relrowsecurity::text AS value
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='job_agent' AND c.relkind='r' ORDER BY 1) q
UNION ALL
SELECT 'catalog_columns' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT c.relname||'.'||a.attname AS key,
        format_type(a.atttypid,a.atttypmod)||'|'||a.attnotnull::text||'|'||
        coalesce(pg_get_expr(d.adbin,d.adrelid),'') AS value
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
        WHERE n.nspname='job_agent' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped ORDER BY 1) q
UNION ALL
SELECT 'catalog_constraints' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT r.relname||'.'||c.conname AS key,
        pg_get_constraintdef(c.oid)||'|'||c.convalidated::text AS value
        FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid
        JOIN pg_namespace n ON n.oid=r.relnamespace WHERE n.nspname='job_agent' ORDER BY 1) q
UNION ALL
SELECT 'catalog_indexes' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT indexname AS key, indexdef AS value FROM pg_indexes
        WHERE schemaname='job_agent' ORDER BY 1) q
UNION ALL
SELECT 'catalog_triggers' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT c.relname||'.'||t.tgname AS key,
        pg_get_triggerdef(t.oid)||'|'||t.tgenabled::text AS value
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='job_agent' AND NOT t.tgisinternal ORDER BY 1) q
UNION ALL
SELECT 'catalog_functions' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT p.proname||'('||pg_get_function_identity_arguments(p.oid)||')' AS key,
        pg_get_functiondef(p.oid) AS value FROM pg_proc p
        JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='job_agent' ORDER BY 1) q
UNION ALL
SELECT 'catalog_policies' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT tablename||'.'||policyname AS key,
        cmd||'|'||roles::text||'|'||coalesce(qual,'')||'|'||coalesce(with_check,'') AS value
        FROM pg_policies WHERE schemaname='job_agent' ORDER BY 1) q
UNION ALL
SELECT 'catalog_service_grants' AS section, COALESCE(jsonb_agg(to_jsonb(q)), '[]'::jsonb) AS evidence FROM (SELECT c.relname||'.'||a.privilege_type AS key, 'granted' AS value
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
        JOIN pg_roles r ON r.oid=a.grantee
        WHERE n.nspname='job_agent' AND c.relkind='r' AND r.rolname='service_role' ORDER BY 1) q;
ROLLBACK;
