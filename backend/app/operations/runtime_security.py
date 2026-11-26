"""Explicit single-owner backend contract; never creates roles, policies or grants."""

import copy

RUNTIME_ROLE = "job_agent_runtime"
OWNER_ROLE = "job_agent_owner"
POLICY = "job_agent_backend"
APPEND_ONLY = frozenset({
    "application_events", "application_submission_evidence",
    "company_source_observations", "drive_resume_versions",
    "provider_usage_logs", "startup_shortlist_entries", "agent_policy_events", "agent_operations",
    "rust_agent_events", "rust_agent_control_events",
    "application_state_events",
    "agent_audit_log",  # Python v2 Phase 9 (followup 005)
})


def runtime_privileges(tables):
    privileges = {name: {"SELECT", "INSERT"} for name in tables}
    for name in privileges:
        if name not in APPEND_ONLY:
            privileges[name].add("UPDATE")
    # Existing privacy/suppression workflows replace contact identity mappings.
    privileges["contact_identities"].add("DELETE")
    # The dashboard deletes wrong/stale semantic-cache answers (Python v2, migration 004).
    if "semantic_cache" in privileges:
        privileges["semantic_cache"].add("DELETE")
    # Phase 9: the agent's sliding-window memory prunes old turns and /forget clears a chat.
    if "agent_conversation_turns" in privileges:
        privileges["agent_conversation_turns"].add("DELETE")
    return privileges


def restricted_manifest(manifest):
    """Keep historical checksums/object definitions; require the precise ACL overlay."""
    result = copy.deepcopy(manifest)
    tables = result["catalog"]["tables"]
    result["catalog"]["tables"] = dict.fromkeys(tables, "true")
    result["catalog"]["service_grants"] = {}
    result["catalog"]["policies"] = {
        name + "." + POLICY: f"ALL|{{{RUNTIME_ROLE}}}|true|true" for name in tables
    }
    return result


async def verify_restricted_runtime(connection, tables, schema="job_agent", *, preserved_function_oids=()):
    if schema not in {"public", "job_agent"}:
        raise RuntimeError("invalid_runtime_schema")
    if preserved_function_oids and (schema != "public" or len(preserved_function_oids) != 1
                                   or any(type(oid) is not int or oid < 1 for oid in preserved_function_oids)):
        raise RuntimeError("invalid_preserved_function_inventory")
    if schema == "public":
        connection = PublicCatalogConnection(connection)

    """Catalog reads only. Reject excess authority as well as missing access.

    A permissive policy is safe here only for the one trusted backend principal.
    This is a single-owner application, not a tenant isolation policy.
    """
    role = await connection.fetchrow("""
        SELECT current_user AS name, rolsuper, rolcreatedb, rolcreaterole,
               rolreplication, rolbypassrls, rolinherit,
               has_database_privilege(current_user,current_database(),'CREATE') AS database_create,
               EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid) AS memberships
        FROM pg_roles r WHERE rolname=current_user
    """)
    if (role["name"] != RUNTIME_ROLE or any(role[k] for k in (
            "rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication",
            "rolbypassrls", "rolinherit", "memberships", "database_create"))):
        raise RuntimeError("database_runtime_role_authority_incompatible")
    schema = await connection.fetchrow("""
        SELECT pg_get_userbyid(nspowner) AS owner,
               has_schema_privilege(current_user,oid,'USAGE') AS usage,
               has_schema_privilege(current_user,oid,'CREATE') AS create
        FROM pg_namespace WHERE nspname='job_agent'
    """)
    if not schema or schema["owner"] not in ({OWNER_ROLE, "pg_database_owner", "postgres"} if isinstance(connection, PublicCatalogConnection) else {OWNER_ROLE}) or not schema["usage"] or schema["create"]:
        raise RuntimeError("database_runtime_schema_permissions_incompatible")
    rows = await connection.fetch("""
        SELECT c.relname, pg_get_userbyid(c.relowner) AS owner,
               c.relrowsecurity, c.relforcerowsecurity,
               ARRAY(SELECT p FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE',
                   'TRUNCATE','REFERENCES','TRIGGER'] ||
                   CASE WHEN current_setting('server_version_num')::int >= 170000
                       THEN ARRAY['MAINTAIN'] ELSE ARRAY[]::text[] END) p
                   WHERE has_table_privilege(current_user,c.oid,p)) AS privileges,
               EXISTS(SELECT 1 FROM pg_attribute a WHERE a.attrelid=c.oid
                   AND a.attnum>0 AND NOT a.attisdropped AND a.attacl IS NOT NULL) AS column_acl
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='job_agent' AND c.relkind IN ('r','p')
    """)
    expected = runtime_privileges(tables)
    if {r["relname"] for r in rows} != set(tables):
        raise RuntimeError("database_runtime_table_inventory_incompatible")
    for row in rows:
        if (row["owner"] != OWNER_ROLE or not row["relrowsecurity"]
                or not row["relforcerowsecurity"] or row["column_acl"]
                or set(row["privileges"]) != expected[row["relname"]]):
            raise RuntimeError("database_runtime_table_permissions_incompatible")
    # Schema and object ACLs must not leave a second shared/client entry point.
    unsafe = await connection.fetchval("""
        SELECT EXISTS(
            SELECT 1 FROM pg_namespace n,
                LATERAL aclexplode(coalesce(n.nspacl,acldefault('n',n.nspowner))) a
            WHERE n.nspname='job_agent' AND a.grantee NOT IN
                (SELECT oid FROM pg_roles WHERE rolname IN ('job_agent_owner','job_agent_runtime'))
            UNION ALL
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace,
                LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
            WHERE n.nspname='job_agent' AND c.relkind IN ('r','p','v','m','f','S')
                AND (c.relkind<>'r' OR a.grantee NOT IN
                (SELECT oid FROM pg_roles WHERE rolname IN ('job_agent_owner','job_agent_runtime'))
                OR a.is_grantable)
            UNION ALL
            SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace,
                LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
            WHERE n.nspname='job_agent' AND p.oid <> ALL($1::oid[]) AND (p.prosecdef OR
                pg_get_userbyid(p.proowner)<>'job_agent_owner' OR a.grantee NOT IN
                (SELECT oid FROM pg_roles WHERE rolname IN ('job_agent_owner','job_agent_runtime'))
                OR a.is_grantable)
        )
    """, list(preserved_function_oids))
    if unsafe:
        raise RuntimeError("database_runtime_shared_grants_incompatible")
    authority = await connection.fetchval("""
        SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='job_agent_owner'
            AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
                 OR rolreplication OR rolbypassrls))
        OR EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid
            JOIN pg_roles member_role ON member_role.oid=m.member
            WHERE r.rolname IN ('job_agent_runtime','job_agent_owner')
                AND member_role.rolname<>'postgres')
    """)
    if authority:
        raise RuntimeError("database_runtime_role_authority_incompatible")
    # PUBLIC access outside this schema cannot be removed by REVOKE from runtime.
    # Refuse effective row access to other apps, including column-only grants.
    cross_schema = await connection.fetchval("""
        SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname NOT IN ('job_agent','pg_catalog','information_schema')
              AND n.nspname !~ '^pg_toast' AND c.relkind IN ('r','p','v','m','f')
              AND NOT (n.nspname='extensions' AND c.relname IN
                  ('pg_stat_statements','pg_stat_statements_info') AND c.relkind='v')
              AND has_schema_privilege(current_user,n.oid,'USAGE')
              AND (has_table_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
                   OR has_any_column_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE')))
    """)
    if cross_schema:
        raise RuntimeError("database_runtime_cross_schema_access_incompatible")
    functions = await connection.fetchval("""
        SELECT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='job_agent'
                AND p.oid <> ALL($1::oid[])
                AND NOT has_function_privilege(current_user,p.oid,'EXECUTE'))
        OR EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname NOT IN ('job_agent','pg_catalog','information_schema')
                AND p.prosecdef AND has_schema_privilege(current_user,n.oid,'USAGE')
                AND has_function_privilege(current_user,p.oid,'EXECUTE'))
    """, list(preserved_function_oids))
    if functions:
        raise RuntimeError("database_runtime_function_access_incompatible")


class PublicCatalogConnection:
    """Reuse exact restricted checks with public as the application namespace.

    Schema ownership stays with Supabase; table/function ownership stays private.
    Only schema-level ACLs may include PostgreSQL's managed schema owner.
    """
    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, method):
        async def call(sql, *args):
            sql = sql.replace("'job_agent'", "'public'")
            sql = sql.replace("WHERE n.nspname='public' AND a.grantee NOT IN",
                "WHERE n.nspname='public' AND a.grantee NOT IN (SELECT oid FROM pg_roles WHERE rolname IN ('postgres','pg_database_owner')) AND a.grantee NOT IN")
            return await getattr(self.connection, method)(sql, *args)
        return call
