-- Python v2 Phase 9: early-bird priority queue, persisted portal circuit breakers,
-- conditional-GET watcher state, audited Telegram agent (tool audit log + short
-- conversation memory) and portal profile-sync history.
--
-- Requires followup 004. Additive and idempotent: no existing table, row,
-- constraint or grant is altered or dropped. Safe to run more than once.
-- Ownership/ACL contract identical to 004 (owner job_agent_owner, RLS enabled +
-- forced, policy job_agent_backend for job_agent_runtime, no PUBLIC/anon/
-- authenticated/service_role access). Never stores secrets, OTPs or full mail bodies.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

-- Priority queue: P0 early-bird .. P3 backlog, plus the real posting time so the
-- worker can apply newest-first. Defaults keep every existing row valid (P2, unknown age).
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS priority SMALLINT NOT NULL DEFAULT 2
    CHECK (priority BETWEEN 0 AND 3);
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ;
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS posted_precision TEXT
    CHECK (posted_precision IS NULL OR posted_precision IN ('hour','day','unknown'));
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS priority_reason TEXT
    CHECK (priority_reason IS NULL OR length(priority_reason) <= 200);
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS discovered_via TEXT
    CHECK (discovered_via IS NULL OR discovered_via ~ '^[a-z][a-z0-9_:.-]{0,59}$');
CREATE INDEX IF NOT EXISTS ix_applications_priority_queue
    ON public.applications (state, priority, posted_at DESC NULLS LAST);

-- Persisted per-portal circuit breaker (survives worker restarts) and fresh-sweep clock.
ALTER TABLE public.portal_rules ADD COLUMN IF NOT EXISTS circuit_failures INT NOT NULL DEFAULT 0
    CHECK (circuit_failures >= 0);
ALTER TABLE public.portal_rules ADD COLUMN IF NOT EXISTS circuit_level INT NOT NULL DEFAULT 0
    CHECK (circuit_level BETWEEN 0 AND 10);
ALTER TABLE public.portal_rules ADD COLUMN IF NOT EXISTS circuit_open_until TIMESTAMPTZ;
ALTER TABLE public.portal_rules ADD COLUMN IF NOT EXISTS circuit_reason TEXT
    CHECK (circuit_reason IS NULL OR length(circuit_reason) <= 300);
ALTER TABLE public.portal_rules ADD COLUMN IF NOT EXISTS last_fresh_sweep_at TIMESTAMPTZ;

-- Fast-poll watcher state: conditional GET validators, change baseline, budget and
-- per-source breaker. One row per source key, e.g. 'greenhouse:stripe', 'wwr:rss:all'.
CREATE TABLE IF NOT EXISTS public.watcher_state (
    source TEXT PRIMARY KEY CHECK (source ~ '^[a-z][a-z0-9_]{1,39}(:[A-Za-z0-9_.:/-]{1,160})?$'),
    etag TEXT CHECK (etag IS NULL OR length(etag) <= 300),
    last_modified TEXT CHECK (last_modified IS NULL OR length(last_modified) <= 100),
    body_hash TEXT CHECK (body_hash IS NULL OR body_hash ~ '^[0-9a-f]{64}$'),
    seen_ids JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(seen_ids) = 'array'),
    baseline_at TIMESTAMPTZ,
    last_poll_at TIMESTAMPTZ,
    next_poll_at TIMESTAMPTZ,
    last_status INT,
    failures INT NOT NULL DEFAULT 0 CHECK (failures >= 0),
    open_until TIMESTAMPTZ,
    last_error TEXT CHECK (last_error IS NULL OR length(last_error) <= 500),
    budget_day DATE,
    budget_used INT NOT NULL DEFAULT 0 CHECK (budget_used >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Append-only audit of every agent tool call that writes (and refusals/confirmations).
-- args/before/after are sanitized summaries (no secrets, no OTPs, PII scrubbed).
CREATE TABLE IF NOT EXISTS public.agent_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL CHECK (source IN ('telegram','api','mcp','cli','worker')),
    tool_name TEXT NOT NULL CHECK (tool_name ~ '^[a-z][a-z0-9_]{1,59}$'),
    args JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(args) = 'object'),
    before_summary JSONB,
    after_summary JSONB,
    outcome TEXT NOT NULL CHECK (outcome IN ('ok','refused','error','needs_confirmation','cancelled')),
    error TEXT CHECK (error IS NULL OR length(error) <= 500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_agent_audit_log_created ON public.agent_audit_log (created_at DESC);

-- Sliding-window conversation memory for the Telegram/API agent. chat_key is a
-- non-reversible key ('telegram:<sha256 prefix>'), never the raw chat id. HITL
-- answers and OTPs are never written here.
CREATE TABLE IF NOT EXISTS public.agent_conversation_turns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_key TEXT NOT NULL CHECK (chat_key ~ '^[a-z]{2,12}:[0-9a-f]{8,64}$'),
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 4000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_agent_conversation_turns_chat
    ON public.agent_conversation_turns (chat_key, created_at DESC);

-- Portal profile-sync runs (dry-run and live). fields holds per-field status and
-- SHA-256 references, never raw profile values.
CREATE TABLE IF NOT EXISTS public.profile_sync_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform TEXT NOT NULL CHECK (platform ~ '^[a-z][a-z0-9_]{1,39}$'),
    trigger TEXT NOT NULL CHECK (trigger IN ('schedule','telegram','dashboard','cli','profile_change','mcp')),
    dry_run BOOLEAN NOT NULL DEFAULT true,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running','ok','partial','failed','skipped','auth_required')),
    fields JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(fields) = 'object'),
    error TEXT CHECK (error IS NULL OR length(error) <= 500),
    receipt JSONB,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_profile_sync_runs_platform ON public.profile_sync_runs (platform, started_at DESC);

DO $acl$
DECLARE
    table_name TEXT;
    client_role TEXT;
    append_only CONSTANT TEXT[] := ARRAY['agent_audit_log'];
    deletable CONSTANT TEXT[] := ARRAY['agent_conversation_turns'];
    phase9_tables CONSTANT TEXT[] := ARRAY['watcher_state','agent_audit_log',
        'agent_conversation_turns','profile_sync_runs'];
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'job_agent_owner') THEN
        GRANT CREATE ON SCHEMA public TO job_agent_owner;
    END IF;
    FOREACH table_name IN ARRAY phase9_tables LOOP
        IF to_regclass('public.' || table_name) IS NULL THEN
            CONTINUE;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'job_agent_owner') THEN
            EXECUTE format('ALTER TABLE public.%I OWNER TO job_agent_owner', table_name);
        END IF;
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC', table_name);
        FOREACH client_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
                EXECUTE format('REVOKE ALL ON public.%I FROM %I', table_name, client_role);
            END IF;
        END LOOP;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'job_agent_runtime') THEN
            EXECUTE format('REVOKE ALL ON public.%I FROM job_agent_runtime', table_name);
            IF table_name = ANY (append_only) THEN
                EXECUTE format('GRANT SELECT, INSERT ON public.%I TO job_agent_runtime', table_name);
            ELSIF table_name = ANY (deletable) THEN
                -- Sliding window: old turns are pruned and /forget clears the chat.
                EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO job_agent_runtime', table_name);
            ELSE
                EXECUTE format('GRANT SELECT, INSERT, UPDATE ON public.%I TO job_agent_runtime', table_name);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_policies
                           WHERE schemaname = 'public' AND tablename = table_name
                             AND policyname = 'job_agent_backend') THEN
                EXECUTE format('CREATE POLICY job_agent_backend ON public.%I FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true)', table_name);
            END IF;
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'job_agent_owner') THEN
        REVOKE CREATE ON SCHEMA public FROM job_agent_owner;
    END IF;
END
$acl$;

COMMIT;
