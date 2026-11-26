-- Python v2 core tables (Phase 1). Additive and idempotent: no existing table,
-- row, constraint or grant is altered or dropped. Safe to run more than once.
--
-- Ownership/ACL contract matches backend/app/operations/runtime_security.py:
--   owner job_agent_owner, RLS enabled + forced, policy job_agent_backend for
--   job_agent_runtime, runtime privileges SELECT/INSERT/UPDATE (append-only
--   tables SELECT/INSERT; semantic_cache also DELETE for dashboard curation),
--   no PUBLIC/anon/authenticated/service_role access.
--
-- candidate_profiles.preferences: ck_candidate_preferences only constrains the
-- keys it names, so target_roles, keywords_required, keywords_excluded,
-- tech_stack, remote_policy, min_ctc and company_blacklist are already
-- accepted. The pinned constraint is intentionally left unchanged.
--
-- The application audit table is named application_state_events because
-- public.application_events already exists (packet history, append-only).

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

-- BEGIN pgvector
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
-- END pgvector

CREATE TABLE IF NOT EXISTS public.portal_rules (
    platform TEXT PRIMARY KEY CHECK (platform ~ '^[a-z][a-z0-9_]{1,39}$'),
    enabled BOOLEAN NOT NULL DEFAULT false,
    auto_apply_enabled BOOLEAN NOT NULL DEFAULT false,
    max_applies_per_day INT NOT NULL DEFAULT 50 CHECK (max_applies_per_day BETWEEN 0 AND 500),
    max_applies_per_hour INT NOT NULL DEFAULT 10 CHECK (max_applies_per_hour BETWEEN 0 AND 100),
    max_job_age_days INT NOT NULL DEFAULT 7 CHECK (max_job_age_days BETWEEN 0 AND 365),
    max_applicants INT NOT NULL DEFAULT 300 CHECK (max_applicants >= 0),
    unknown_applicants_policy TEXT NOT NULL DEFAULT 'allow_lower_bound'
        CHECK (unknown_applicants_policy IN ('allow_lower_bound','allow','skip','needs_review')),
    min_delay_sec INT NOT NULL DEFAULT 45 CHECK (min_delay_sec >= 0),
    max_delay_sec INT NOT NULL DEFAULT 150 CHECK (max_delay_sec >= 0),
    active_hours_start TIME DEFAULT '08:00',
    active_hours_end TIME DEFAULT '23:30',
    timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    auth_status TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (auth_status IN ('OK','AUTH_REQUIRED','UNKNOWN')),
    auth_checked_at TIMESTAMPTZ,
    portal_limit_hit_at TIMESTAMPTZ,
    -- Phase 6A: live-editable quota fallback volume (dashboard /autopilot).
    quota_fallback_daily_cap INT NOT NULL DEFAULT 10 CHECK (quota_fallback_daily_cap BETWEEN 0 AND 100),
    quota_drafts_per_cycle INT NOT NULL DEFAULT 5 CHECK (quota_drafts_per_cycle BETWEEN 0 AND 50),
    -- Phase 6A: temporary owner pause ("pause Internshala for 3 hours"); NULL = not paused.
    paused_until TIMESTAMPTZ,
    revision INT NOT NULL DEFAULT 1 CHECK (revision >= 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_portal_rules_delay_order CHECK (max_delay_sec >= min_delay_sec)
);
-- Phase 6A columns are also added to a portal_rules table created by an earlier draft of 004.
ALTER TABLE public.portal_rules ADD COLUMN IF NOT EXISTS quota_fallback_daily_cap INT NOT NULL DEFAULT 10
    CHECK (quota_fallback_daily_cap BETWEEN 0 AND 100);
ALTER TABLE public.portal_rules ADD COLUMN IF NOT EXISTS quota_drafts_per_cycle INT NOT NULL DEFAULT 5
    CHECK (quota_drafts_per_cycle BETWEEN 0 AND 50);
ALTER TABLE public.portal_rules ADD COLUMN IF NOT EXISTS paused_until TIMESTAMPTZ;

-- Phase 5: the 10-portal roster. Only naukri has a live adapter today; the other
-- nine are seeded disabled so the dashboard can manage them before Phase 6 wires them.
INSERT INTO public.portal_rules (platform, enabled) VALUES
    ('naukri', true),
    ('instahyre', false),
    ('internshala', false),
    ('himalayas', false),
    ('wellfound', false),
    ('work_at_a_startup', false),
    ('we_work_remotely', false),
    ('hiringcafe', false),
    ('greenhouse', false),
    ('lever', false)
ON CONFLICT (platform) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES public.jobs(id) ON DELETE SET NULL,
    platform TEXT NOT NULL,
    external_job_id TEXT NOT NULL CHECK (length(external_job_id) BETWEEN 1 AND 200),
    company_name TEXT,
    role_title TEXT,
    job_url TEXT,
    dedup_key TEXT,
    state TEXT NOT NULL CHECK (state IN (
        'DISCOVERED','FILTERED_OUT','SCORED','APPLYING','WAITING_FOR_USER','APPLIED',
        'QUOTA_HIT_PENDING','DRAFTED_AND_QUEUED','SUBMISSION_UNKNOWN','FAILED')),
    reason TEXT,
    attempts INT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    retry_after TIMESTAMPTZ,
    draft_created_at TIMESTAMPTZ,
    applied_at TIMESTAMPTZ,
    receipt JSONB,
    version INT NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_applications_platform_external UNIQUE (platform, external_job_id)
);
CREATE INDEX IF NOT EXISTS ix_applications_state_retry ON public.applications (state, retry_after);
CREATE INDEX IF NOT EXISTS ix_applications_dedup_key ON public.applications (dedup_key);

CREATE TABLE IF NOT EXISTS public.application_state_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID NOT NULL REFERENCES public.applications(id),
    from_state TEXT,
    to_state TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (length(event_type) BETWEEN 1 AND 80),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_application_state_events_application
    ON public.application_state_events (application_id, created_at);

CREATE TABLE IF NOT EXISTS public.hitl_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID REFERENCES public.applications(id),
    platform TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('CAPTCHA','OTP','AUTH','QUESTION','ERROR')),
    prompt_text TEXT NOT NULL,
    context JSONB NOT NULL DEFAULT '{}'::jsonb,
    telegram_msg_id BIGINT,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','ANSWERED','EXPIRED','CANCELLED')),
    answer_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    -- Phase 4: which channel resolved it, and when the worker consumed the answer.
    resolved_via TEXT CHECK (resolved_via IS NULL OR resolved_via IN ('telegram','dashboard','mcp','worker')),
    consumed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_hitl_requests_status ON public.hitl_requests (status, created_at);
CREATE INDEX IF NOT EXISTS ix_hitl_requests_telegram_msg
    ON public.hitl_requests (telegram_msg_id) WHERE telegram_msg_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_hitl_requests_application ON public.hitl_requests (application_id, status);

-- BEGIN pgvector
CREATE TABLE IF NOT EXISTS public.semantic_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind TEXT NOT NULL,
    question_text TEXT NOT NULL,
    normalized_question TEXT NOT NULL,
    embedding extensions.vector(384),
    answer_text TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('user','llm','profile')),
    hits INT NOT NULL DEFAULT 0 CHECK (hits >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_semantic_cache_kind_question UNIQUE (kind, normalized_question)
);
CREATE INDEX IF NOT EXISTS ix_semantic_cache_embedding_hnsw
    ON public.semantic_cache USING hnsw (embedding extensions.vector_cosine_ops);
-- END pgvector

CREATE TABLE IF NOT EXISTS public.llm_provider_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    window_type TEXT NOT NULL CHECK (window_type IN ('minute','day')),
    window_start TIMESTAMPTZ NOT NULL,
    requests INT NOT NULL DEFAULT 0 CHECK (requests >= 0),
    input_tokens INT NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens INT NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    circuit_open_until TIMESTAMPTZ,
    last_error TEXT,
    CONSTRAINT uq_llm_provider_usage_window UNIQUE (provider, model, window_type, window_start)
);

-- Phase 5: recruiter-email domain cache. NO_EMAIL_FOUND rows are a negative cache
-- (shorter TTL) so dead domains are not re-queried every day.
CREATE TABLE IF NOT EXISTS public.enrichment_cache (
    company_domain TEXT PRIMARY KEY CHECK (length(company_domain) BETWEEN 3 AND 253),
    role_family TEXT,
    status TEXT NOT NULL DEFAULT 'FOUND' CHECK (status IN ('FOUND','NO_EMAIL_FOUND')),
    emails JSONB NOT NULL DEFAULT '[]'::jsonb,
    source TEXT,
    expires_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Daily free-tier credit ledger (period_key = YYYY-MM-DD in Asia/Kolkata). `used` is
-- reserved atomically BEFORE every external call; cooldown_until parks a provider
-- (plan-restricted 403/402, 429) without burning retries.
CREATE TABLE IF NOT EXISTS public.enrichment_credits (
    provider TEXT NOT NULL,
    period_key TEXT NOT NULL,
    used INT NOT NULL DEFAULT 0 CHECK (used >= 0),
    limit_cap INT NOT NULL CHECK (limit_cap >= 0),
    cooldown_until TIMESTAMPTZ,
    last_error TEXT CHECK (last_error IS NULL OR length(last_error) <= 200),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, period_key)
);

-- One Gmail draft per application, ever (UNIQUE application_id). A PENDING row is
-- reserved before IMAP/Mail.app is called, so a crash or a dashboard/worker race can
-- never produce a second draft; an ambiguous outcome stays PENDING (never retried).
CREATE TABLE IF NOT EXISTS public.email_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID UNIQUE REFERENCES public.applications(id),
    platform TEXT,
    recipient_email TEXT,
    subject TEXT,
    body_preview TEXT CHECK (body_preview IS NULL OR length(body_preview) <= 600),
    channel TEXT CHECK (channel IS NULL OR channel IN ('imap','mail_app')),
    status TEXT NOT NULL DEFAULT 'CREATED' CHECK (status IN ('PENDING','CREATED','FAILED')),
    composer TEXT CHECK (composer IS NULL OR composer IN ('llm','template')),
    enrichment_source TEXT,
    external_draft_id TEXT,
    last_error TEXT CHECK (last_error IS NULL OR length(last_error) <= 200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_email_drafts_created_channel CHECK (status <> 'CREATED' OR channel IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_email_drafts_created ON public.email_drafts (created_at);

-- Persisted desired worker state (Phase 2). A restarted worker resumes RUNNING
-- when that was the last owner command, so service restarts never pause the queue.
CREATE TABLE IF NOT EXISTS public.worker_control (
    singleton_key TEXT PRIMARY KEY DEFAULT 'primary' CHECK (singleton_key = 'primary'),
    desired_state TEXT NOT NULL DEFAULT 'STOPPED'
        CHECK (desired_state IN ('RUNNING','PAUSED','STOPPED')),
    dry_run BOOLEAN NOT NULL DEFAULT true,
    run_once_requested_at TIMESTAMPTZ,
    observed_state TEXT NOT NULL DEFAULT 'OFFLINE'
        CHECK (observed_state IN ('OFFLINE','IDLE','RUNNING','PAUSED','STOPPED','SLEEPING')),
    heartbeat_at TIMESTAMPTZ,
    current_platform TEXT,
    last_cycle_at TIMESTAMPTZ,
    last_error TEXT,
    revision INT NOT NULL DEFAULT 1 CHECK (revision >= 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO public.worker_control (singleton_key) VALUES ('primary')
ON CONFLICT (singleton_key) DO NOTHING;

-- Telegram HITL long-polling state (Phase 4). last_update_id persists the getUpdates
-- offset so a restarted worker never reprocesses an old owner command. Never stores
-- the bot token or message bodies.
CREATE TABLE IF NOT EXISTS public.telegram_v2_state (
    singleton_key TEXT PRIMARY KEY DEFAULT 'primary' CHECK (singleton_key = 'primary'),
    last_update_id BIGINT CHECK (last_update_id IS NULL OR last_update_id >= 0),
    polling_state TEXT NOT NULL DEFAULT 'stopped'
        CHECK (polling_state IN ('unconfigured','starting','polling','conflict','error','stopped')),
    last_poll_at TIMESTAMPTZ,
    last_error TEXT CHECK (last_error IS NULL OR length(last_error) <= 500),
    conflict_detected_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO public.telegram_v2_state (singleton_key) VALUES ('primary')
ON CONFLICT (singleton_key) DO NOTHING;
-- Phase 6A: the nightly Telegram digest is sent at most once per local date (restart-safe).
ALTER TABLE public.telegram_v2_state ADD COLUMN IF NOT EXISTS last_digest_on DATE;

-- Phase 6A: read-only mail watcher results (recruiter replies, interview alerts, job-alert
-- ingestion). Deduplicated by message_key (Message-ID or provider id) so a restart never
-- re-alerts. Never stores OTP codes, full bodies or credentials; snippet is bounded.
CREATE TABLE IF NOT EXISTS public.mail_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_key TEXT NOT NULL CHECK (length(message_key) BETWEEN 1 AND 300),
    kind TEXT NOT NULL CHECK (kind IN ('RECRUITER_REPLY','INTERVIEW','JOB_ALERT')),
    source TEXT NOT NULL CHECK (source IN ('imap','gmail_api','mail_app')),
    platform TEXT,
    company_name TEXT CHECK (company_name IS NULL OR length(company_name) <= 200),
    sender TEXT CHECK (sender IS NULL OR length(sender) <= 200),
    subject TEXT CHECK (subject IS NULL OR length(subject) <= 300),
    snippet TEXT CHECK (snippet IS NULL OR length(snippet) <= 500),
    application_id UUID REFERENCES public.applications(id),
    received_at TIMESTAMPTZ,
    alerted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_mail_events_message_key UNIQUE (message_key)
);
CREATE INDEX IF NOT EXISTS ix_mail_events_created ON public.mail_events (created_at);

-- Ownership, RLS and runtime grants. Role-guarded so a disposable database
-- without the Supabase roles can still validate the DDL.
DO $acl$
DECLARE
    table_name TEXT;
    client_role TEXT;
    append_only CONSTANT TEXT[] := ARRAY['application_state_events'];
    deletable CONSTANT TEXT[] := ARRAY['semantic_cache'];
    v2_tables CONSTANT TEXT[] := ARRAY['portal_rules','applications','application_state_events',
        'hitl_requests','semantic_cache','llm_provider_usage','enrichment_cache',
        'enrichment_credits','email_drafts','worker_control','telegram_v2_state','mail_events'];
BEGIN
    -- Supabase: ALTER ... OWNER TO needs the new owner to hold CREATE on the schema. Grant it only
    -- for the ownership transfer and revoke it again below (same pattern as runtime/001).
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'job_agent_owner') THEN
        GRANT CREATE ON SCHEMA public TO job_agent_owner;
    END IF;
    FOREACH table_name IN ARRAY v2_tables LOOP
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
                -- Owner curates cached answers from the dashboard (DELETE /semantic-cache/{id}).
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
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'job_agent_runtime')
       AND EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'extensions') THEN
        -- Type/operator lookup for extensions.vector only; no table access.
        GRANT USAGE ON SCHEMA extensions TO job_agent_runtime;
    END IF;
END
$acl$;

COMMIT;
