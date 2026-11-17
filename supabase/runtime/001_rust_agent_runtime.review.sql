-- Target: approved project luvdmwnlwaqgvfwlmlom, public schema only.
-- Deploy the matching backend catalog recognizer BEFORE applying this package.
-- Review backup/rollback inventory and run through the owner database connection.
-- This does not enable a worker, modify application history or grant submissions.
BEGIN;
SET LOCAL search_path = public, pg_catalog;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '60s';
DO $preflight$
DECLARE
    legacy_state text;
BEGIN
    IF current_user <> 'postgres' THEN
        RAISE EXCEPTION 'explicit_owner_migration_connection_required';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='job_agent_owner' AND NOT rolcanlogin)
       OR NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='job_agent_runtime'
                     AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolbypassrls)
    THEN RAISE EXCEPTION 'restricted_application_roles_required'; END IF;
    IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
              WHERE n.nspname='public' AND c.relname IN (
                  'rust_agent_runs','rust_agent_events','rust_agent_control',
                  'rust_agent_control_events','rust_telegram_runtime','rust_telegram_outbox'))
    THEN RAISE EXCEPTION 'rust_runtime_schema_already_or_partially_installed'; END IF;
    PERFORM value FROM public.owner_preferences
      WHERE key='application_queue_policy' AND value->>'state'='STOPPED' FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'stopped_application_queue_required'; END IF;
    SELECT value->>'state' INTO legacy_state FROM public.owner_preferences
      WHERE key='naukri_automation' FOR UPDATE;
    IF FOUND AND legacy_state IS DISTINCT FROM 'STOPPED' THEN
        RAISE EXCEPTION 'stopped_legacy_preparation_required';
    END IF;
END $preflight$;

-- Source: rust/agent-runtime/sql/001_runtime.sql
-- Apply explicitly to an owner-approved target only. The Rust process never auto-migrates.
-- This namespace is new: existing application/queue/receipt tables remain untouched.
CREATE TABLE rust_agent_runs (
    id uuid PRIMARY KEY,
    request_key uuid NOT NULL UNIQUE,
    owner text NOT NULL DEFAULT 'primary' CHECK (owner = 'primary'),
    run jsonb NOT NULL CHECK (jsonb_typeof(run) = 'object'),
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    lease_token uuid,
    lease_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((lease_token IS NULL) = (lease_until IS NULL))
);
CREATE UNIQUE INDEX rust_agent_one_active_lease ON rust_agent_runs ((true)) WHERE lease_token IS NOT NULL;
CREATE INDEX rust_agent_runnable ON rust_agent_runs (created_at)
WHERE run->>'state' IN ('ready','model_running','tool_pending','tool_running');
CREATE TABLE rust_agent_events (
    run_id uuid NOT NULL REFERENCES rust_agent_runs(id),
    revision bigint NOT NULL,
    role text NOT NULL,
    state text NOT NULL,
    model_calls integer NOT NULL,
    tool_calls integer NOT NULL,
    reserved_tokens integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (run_id,revision)
);
-- Fail closed for Supabase/PostgREST clients. Backend role grants/policies require an
-- explicit target-specific deployment review; table owners/service roles may bypass RLS.
ALTER TABLE rust_agent_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE rust_agent_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON rust_agent_runs,rust_agent_events FROM PUBLIC;
DO $block$
DECLARE client_role text;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
            EXECUTE format('REVOKE ALL ON rust_agent_runs,rust_agent_events FROM %I',client_role);
        END IF;
    END LOOP;
END
$block$;


-- Source: rust/agent-runtime/sql/002_control.sql
-- Explicit additive migration. No existing application policy, quota or history is modified.
CREATE TABLE rust_agent_control (
    key text PRIMARY KEY CHECK (key='primary'),
    mode text NOT NULL CHECK (mode IN ('STOPPED','PAUSED','RUNNING')),
    revision bigint NOT NULL DEFAULT 1 CHECK (revision>0),
    heartbeat_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO rust_agent_control(key,mode)VALUES('primary','STOPPED');
CREATE TABLE rust_agent_control_events (
    revision bigint PRIMARY KEY CHECK (revision>0),
    mode text NOT NULL CHECK (mode IN ('STOPPED','PAUSED','RUNNING')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO rust_agent_control_events(revision,mode)VALUES(1,'STOPPED');
ALTER TABLE rust_agent_events ADD COLUMN decision_calls integer NOT NULL DEFAULT 0;
ALTER TABLE rust_agent_runs ADD COLUMN question_checked_at timestamptz;
CREATE INDEX rust_agent_question_scan ON rust_agent_runs(question_checked_at NULLS FIRST,created_at,id)
WHERE run->>'state'='waiting_owner';
ALTER TABLE rust_agent_control ENABLE ROW LEVEL SECURITY;
ALTER TABLE rust_agent_control_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON rust_agent_control FROM PUBLIC;
REVOKE ALL ON rust_agent_control_events FROM PUBLIC;
DO $block$
DECLARE client_role text;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
            EXECUTE format('REVOKE ALL ON rust_agent_control FROM %I',client_role);
            EXECUTE format('REVOKE ALL ON rust_agent_control_events FROM %I',client_role);
        END IF;
    END LOOP;
END
$block$;


-- Source: rust/agent-runtime/sql/003_telegram.sql
-- Additive Rust metadata only. Existing Telegram offsets, bot pin and deliveries are retained.
-- Requires the existing agent_telegram_state / agent_telegram_deliveries tables.
CREATE TABLE rust_telegram_runtime (
    key text PRIMARY KEY CHECK(key='primary'),
    binding text NOT NULL CHECK(binding ~ '^[0-9a-f]{64}$'),
    next_request_at timestamptz NOT NULL DEFAULT '-infinity',
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE rust_telegram_outbox (
    id uuid PRIMARY KEY,
    update_id bigint UNIQUE REFERENCES agent_telegram_deliveries(update_id),
    binding text NOT NULL CHECK(binding ~ '^[0-9a-f]{64}$'),
    reply text NOT NULL CHECK(length(reply) BETWEEN 1 AND 3500),
    state text NOT NULL CHECK(state IN('pending','sending','sent')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    attempted_at timestamptz,
    receipt_message_id bigint CHECK(receipt_message_id>0)
);
CREATE INDEX rust_telegram_pending ON rust_telegram_outbox(created_at,id)WHERE state='pending';
ALTER TABLE rust_telegram_runtime ENABLE ROW LEVEL SECURITY;
ALTER TABLE rust_telegram_outbox ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON rust_telegram_runtime,rust_telegram_outbox FROM PUBLIC;
DO $block$
DECLARE client_role text;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon','authenticated']LOOP
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role)THEN
            EXECUTE format('REVOKE ALL ON rust_telegram_runtime,rust_telegram_outbox FROM %I',client_role);
        END IF;
    END LOOP;
END
$block$;


-- Source: rust/agent-runtime/sql/004_graph.sql
-- Additive observable graph checkpoints; no policy, quota, history or provider grants change.
ALTER TABLE rust_agent_events ADD COLUMN graph_node text NOT NULL DEFAULT 'planning';
ALTER TABLE rust_agent_events ADD COLUMN graph_iteration integer NOT NULL DEFAULT 0;
ALTER TABLE rust_agent_events ADD COLUMN approval_required boolean NOT NULL DEFAULT false;


-- Source: rust/agent-runtime/sql/005_backend_access.sql
-- Reviewed backend-only ACL overlay. No schema/database/role authority is added.
DO $access$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'rust_agent_runs','rust_agent_events','rust_agent_control',
        'rust_agent_control_events','rust_telegram_runtime','rust_telegram_outbox'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I OWNER TO job_agent_owner',table_name);
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',table_name);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',table_name);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated,service_role,job_agent_runtime',table_name);
        EXECUTE format('CREATE POLICY job_agent_backend ON public.%I FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true)',table_name);
        IF table_name IN ('rust_agent_events','rust_agent_control_events') THEN
            EXECUTE format('GRANT SELECT,INSERT ON public.%I TO job_agent_runtime',table_name);
        ELSE
            EXECUTE format('GRANT SELECT,INSERT,UPDATE ON public.%I TO job_agent_runtime',table_name);
        END IF;
    END LOOP;
END $access$;

COMMIT;
