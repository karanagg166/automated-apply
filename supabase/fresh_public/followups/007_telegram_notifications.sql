-- Python v2 followup 007: zero-spam Telegram notifications.
--   * telegram_notification_ledger: persistent dedup/cooldown ledger (one row per dedup key) with
--     a suppressed counter and the live alert card (chat/message id) for edit-in-place.
--   * telegram_digest_queue: P2 (routine) events and deferred P1 (quiet hours / mute / hourly
--     budget overflow) waiting for the next scheduled digest. Bounded one-line texts, no PII bodies.
--   * telegram_v2_state.muted_until (/mute survives restarts) + last_digest_slot (twice-daily digest).
--   * hitl_requests.telegram_chat_id + telegram_card_closed_at: a request resolved anywhere
--     (dashboard, MCP, expiry, Telegram) gets its card edited in place exactly once.
--
-- Requires followups 004 + 005. Additive and idempotent: nothing is altered or dropped.
-- Ownership/ACL contract identical to 005. Never stores tokens, OTPs or message bodies.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE TABLE IF NOT EXISTS public.telegram_notification_ledger (
    dedup_key TEXT PRIMARY KEY CHECK (dedup_key ~ '^[a-z0-9_.:-]{3,64}$'),
    topic TEXT NOT NULL CHECK (topic ~ '^[a-z][a-z0-9_.]{2,59}$'),
    priority SMALLINT NOT NULL CHECK (priority BETWEEN 0 AND 3),
    last_event_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_sent_at TIMESTAMPTZ,
    suppressed_count INT NOT NULL DEFAULT 0 CHECK (suppressed_count >= 0),
    chat_id BIGINT,
    message_id BIGINT,
    resolved_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_telegram_notification_ledger_open
    ON public.telegram_notification_ledger (topic, last_sent_at DESC) WHERE resolved_at IS NULL;

CREATE TABLE IF NOT EXISTS public.telegram_digest_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic TEXT NOT NULL CHECK (topic ~ '^[a-z][a-z0-9_.]{2,59}$'),
    priority SMALLINT NOT NULL CHECK (priority BETWEEN 0 AND 3),
    dedup_key TEXT CHECK (dedup_key IS NULL OR dedup_key ~ '^[a-z0-9_.:-]{3,64}$'),
    text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 600),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_telegram_digest_queue_pending
    ON public.telegram_digest_queue (created_at) WHERE delivered_at IS NULL;

ALTER TABLE public.telegram_v2_state ADD COLUMN IF NOT EXISTS muted_until TIMESTAMPTZ;
ALTER TABLE public.telegram_v2_state ADD COLUMN IF NOT EXISTS last_digest_slot TEXT
    CHECK (last_digest_slot IS NULL OR last_digest_slot ~ '^\d{4}-\d{2}-\d{2}T\d{2}$');

ALTER TABLE public.hitl_requests ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT;
ALTER TABLE public.hitl_requests ADD COLUMN IF NOT EXISTS telegram_card_closed_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS ix_hitl_requests_card_sync
    ON public.hitl_requests (resolved_at)
    WHERE status <> 'OPEN' AND telegram_msg_id IS NOT NULL AND telegram_card_closed_at IS NULL;

DO $acl$
DECLARE
    table_name TEXT;
    client_role TEXT;
    new_tables CONSTANT TEXT[] := ARRAY['telegram_notification_ledger','telegram_digest_queue'];
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'job_agent_owner') THEN
        GRANT CREATE ON SCHEMA public TO job_agent_owner;
    END IF;
    FOREACH table_name IN ARRAY new_tables LOOP
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
            -- Delivered digest rows are pruned; the ledger is pruned after 30 days.
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO job_agent_runtime', table_name);
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
