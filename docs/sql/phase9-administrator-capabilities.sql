-- Target jyzjgoniuwexvipbbpwa only. Read-only deployment prerequisites.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '2s';
SET LOCAL search_path = pg_catalog;
SELECT current_database() AS database_name, current_user AS role_name,
       current_setting('transaction_read_only') AS read_only,
       pg_get_userbyid(d.datdba) AS database_owner,
       d.datacl AS database_acl,
       has_database_privilege(current_user, d.oid, 'CREATE') AS can_create_schema,
       has_database_privilege(current_user, d.oid, 'CONNECT') AS can_connect,
       has_language_privilege(current_user, 'plpgsql', 'USAGE') AS can_use_plpgsql,
       to_regprocedure('pg_catalog.gen_random_uuid()')::text AS builtin_uuid,
       current_setting('createrole_self_grant', true) AS creator_self_grant,
       EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='job_agent') AS schema_exists,
       EXISTS(SELECT 1 FROM pg_roles WHERE rolname IN
           ('job_agent_owner','job_agent_runtime')) AS proposed_role_name_conflict,
       (SELECT rolvaliduntil FROM pg_roles WHERE rolname='cli_login_postgres') AS cli_login_valid_until
FROM pg_database d WHERE d.datname=current_database();
ROLLBACK;
